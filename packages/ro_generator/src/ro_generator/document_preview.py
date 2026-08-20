"""预览序列化：将 DocumentModel + 模板固定内容转为前端可消费的 JSON。

不包含新的领域模型。不依赖 renderer 阶段的 SourceIndex。
不包含 HTTP 逻辑。

preview_content 由 template_mapping.load_template_mapping() 加载时解析，
build_preview() 直接通过 mapping.preview_content 读取，不再重复打开 YAML。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, cast

from ro_generator.document_model import DocumentLine, DocumentModel
from ro_generator.generator import BuildDocumentResult
from ro_generator.header_rules import (
    HEADER_MANUAL_KEYS,
    build_header_resolved_values,
    is_system_generated_header_field,
    resolve_header_field_spec,
)
from ro_generator.line_rules import (
    line_display_value,
    resolve_line_field_spec,
    uses_po_record_row,
)
from ro_generator.profiles.runtime import current_schema
from ro_generator.totals_rules import (
    build_preview_totals,
    total_spec_for_mapping_key,
)

# —————————————————————————————————————
# 预览数据结构
# —————————————————————————————————————


@dataclass
class PreviewSourceEntry:
    preview_field: str
    label: str
    source_type: str  # base_field | computed | template_content | system_generated | manual_input
    sheet: str | None = None
    row: int | None = None
    field: str | None = None
    value: str = ""
    rule: str = ""


@dataclass
class DocumentPreview:
    document_type: str
    title: str
    seller: str
    buyer: str
    po_no: str
    pi_no: str | None = None
    invoice_no: str | None = None
    ship_to: str | None = None
    seller_info: list[str] = field(default_factory=list)
    to_label: str = ""
    terms: dict[str, str] = field(default_factory=dict)
    header_labels: dict[str, str] = field(default_factory=dict)
    column_labels: list[dict[str, str]] = field(default_factory=list)
    column_header_rows: list[list[dict[str, object]]] = field(default_factory=list)
    lines: list[dict[str, object]] = field(default_factory=list)
    cost_breakdown_column_labels: list[dict[str, str]] = field(default_factory=list)
    cost_breakdown: list[dict[str, object]] = field(default_factory=list)
    totals: dict[str, object] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    source_entries: list[dict[str, object]] = field(default_factory=list)
    layout: dict[str, object] = field(default_factory=dict)
    resolved_values: dict[str, str] = field(default_factory=dict)
    errors: list[dict[str, object]] = field(default_factory=list)
    warnings: list[dict[str, object]] = field(default_factory=list)
    missing_inputs: list[str] = field(default_factory=list)


# —————————————————————————————————————
# 列标签默认值
# —————————————————————————————————————

_COLUMN_LABEL_DEFAULTS: dict[str, str] = {
    "po_no": "PO NO.",
    "item_number": "Item Number",
    "item_line_no": "Item Line",
    "sap": "SAP Number",
    "description": "Description",
    "gs_model": "GS Model",
    "unit_price": "Unit Price",
    "quantity": "Qty",
    "unit_label": "Unit",
    "amount": "Amount",
    "net_weight": "N/W (KGS)",
    "gross_weight": "G/W (KGS)",
    "cbm": "CBM",
    "carton_count": "CTNS",
    "carton_from": "Fr",
    "carton_to": "To",
    "confirmed_ex_factory_date": "EX-FACTORY DATE",
}

_DOC_TITLE_DEFAULTS: dict[str, str] = {
    "PI": "PROFORMA INVOICE",
    "PO": "PURCHASE ORDER",
    "INVOICE": "COMMERCIAL INVOICE",
    "PL": "PACKING LIST",
    "CI": "COMMERCIAL INVOICE",
    "RO_PL": "PACKING LIST",
}

_DEFAULT_LAYOUT: dict[str, Any] = {
    "top": {
        "left": ["seller_info", "to_label"],
        "center": [],
        "right": ["title", "seller", "buyer", "po_no"],
    },
    "info": {
        "left": ["ship_to"],
        "right": ["invoice_no", "pi_no", "terms"],
    },
}

# —————————————————————————————————————
# 主入口
# —————————————————————————————————————


def build_preview(build: BuildDocumentResult) -> DocumentPreview:
    """从 BuildDocumentResult 构建预览数据。"""
    model = build.model
    mapping = build.mapping
    if model is None or mapping is None:
        return _error_preview(build)

    doc_type = model.document_type

    # 从 mapping 对象读取 preview_content（YAML 加载时已解析，不再重复读文件）
    preview_config: dict[str, Any] = mapping.preview_content
    preview_static_values = mapping.preview_static_values

    title_values = preview_static_values.get("title", ())
    title = (
        title_values[0]
        if title_values
        else str(preview_config.get("title", _DOC_TITLE_DEFAULTS.get(doc_type, doc_type)))
    )
    seller_info_values = preview_static_values.get("seller_info", ())
    seller_info = (
        list(seller_info_values)
        if seller_info_values
        else list(preview_config.get("seller_info", []))
    )

    # 列标签（同时返回列键顺序，供 _build_lines 使用）
    column_labels, line_columns = _build_column_labels(mapping)

    # 明细行（含 row_fixed 固定列值）
    lines = _build_lines(
        model,
        line_columns,
        mapping.lines.row_fixed,
        mapping.preview_column_letters,
    )
    cost_breakdown_column_labels, cost_breakdown = _build_cost_breakdown_preview(
        model,
        preview_config,
    )
    unit_label = mapping.lines.unit_label or "PCS"

    # 合计
    totals = build_preview_totals(model, unit_label=unit_label)
    _merge_custom_mapping_totals(totals, mapping, model)
    totals["_footer_items"] = _build_footer_total_items(mapping, totals)

    # 布局：YAML 配置覆盖默认值
    layout = _merge_layout(preview_config.get("layout"))

    # 备注：模板固定文本 + 插值
    notes = _build_notes(preview_config, model)

    # layout 中所有引用的字段名
    all_layout_fields: set[str] = set()
    for section in ("top", "info"):
        sec = layout.get(section, {})
        if isinstance(sec, dict):
            for pos_fields in sec.values():
                if isinstance(pos_fields, list):
                    for f in pos_fields:
                        if isinstance(f, str):
                            all_layout_fields.add(f)

    resolved_values = build_header_resolved_values(
        model,
        header_keys=mapping.header.keys(),
        header_fixed=mapping.header_fixed,
        field_names=all_layout_fields,
    )

    # 字段来源（从 layout + column_labels 推导，与预览展示一致）
    source_entries = _build_source_entries(
        model,
        preview_config,
        column_labels,
        layout,
        totals,
        mapping,
        resolved_values,
    )

    # 拆解消息
    errors: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []
    for m in build.messages:
        entry = {
            "code": m.code,
            "message": m.message,
            "severity": getattr(m, "severity", None),
        }
        if m.kind == "blocking_error":
            errors.append(entry)
        else:
            warnings.append(entry)

    return DocumentPreview(
        document_type=doc_type,
        title=title,
        seller=model.seller,
        buyer=model.buyer,
        po_no=model.po_no,
        pi_no=model.pi_no,
        invoice_no=model.invoice_no,
        ship_to=model.ship_to,
        seller_info=seller_info,
        to_label=preview_config.get("to_label", ""),
        terms=_build_terms(preview_config, resolved_values),
        header_labels=dict(mapping.preview_header_labels),
        column_labels=column_labels,
        column_header_rows=[list(row) for row in mapping.preview_header_rows],
        lines=lines,
        cost_breakdown_column_labels=cost_breakdown_column_labels,
        cost_breakdown=cost_breakdown,
        totals=totals,
        notes=notes,
        source_entries=source_entries,
        layout=layout,
        resolved_values=resolved_values,
        errors=errors,
        warnings=warnings,
    )


# —————————————————————————————————————
# 内部函数
# —————————————————————————————————————


def _merge_layout(config_layout: object) -> dict[str, object]:
    """Deep-merge YAML layout config into defaults."""
    import copy

    merged = copy.deepcopy(_DEFAULT_LAYOUT)
    if not isinstance(config_layout, dict):
        return cast(dict[str, object], merged)
    for section in ("top", "info"):
        if section in config_layout:
            cfg_section = config_layout[section]
            if isinstance(cfg_section, dict):
                for position in cfg_section:
                    if position in merged[section] and isinstance(cfg_section[position], list):
                        merged[section][position] = list(cfg_section[position])
    return cast(dict[str, object], merged)


def _merge_custom_mapping_totals(
    totals: dict[str, object],
    mapping: object,
    model: DocumentModel,
) -> None:
    extra_items: list[dict[str, object]] = []
    mapping_totals = getattr(mapping, "totals", {})
    if not isinstance(mapping_totals, dict):
        return

    for key, total_cell in mapping_totals.items():
        if not isinstance(key, str):
            continue
        mode = getattr(total_cell, "value_mode", "model_total")
        if mode == "model_total":
            continue

        value = _custom_total_value(total_cell, model)
        if value is None:
            continue

        item: dict[str, object] = {
            "key": key,
            "label": _format_total_label(key),
            "value": value,
            "source_type": "template_content" if mode == "fixed" else "system_generated",
            "rule": ("mapping.totals 固定值" if mode == "fixed" else "系统生成当前日期"),
        }
        if mode == "model_date":
            schema = current_schema()
            item.update(
                {
                    "source_type": "base_field",
                    "sheet": schema.sheet("客户PO").name,
                    "field": schema.field("客户PO", "document_date"),
                    "rule": 'new PO template A列 "PO Creation Date"',
                }
            )
        totals[key] = value
        extra_items.append(item)

    if extra_items:
        totals["_extra_items"] = extra_items


def _build_footer_total_items(
    mapping: object | None,
    totals: dict[str, object],
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    mapping_totals = getattr(mapping, "totals", {})
    if not isinstance(mapping_totals, dict):
        return items

    for key, total_cell in mapping_totals.items():
        if not isinstance(key, str):
            continue
        mode = getattr(total_cell, "value_mode", "model_total")
        if mode == "model_total":
            spec = total_spec_for_mapping_key(key)
            if spec is None:
                continue
            raw_value = totals.get(spec.preview_key)
            if raw_value in (None, ""):
                continue
            items.append(
                {
                    "key": key,
                    "label": spec.label,
                    "value": _format_footer_total_value(spec.preview_key, raw_value, totals),
                }
            )
            continue

        raw_value = totals.get(key)
        if raw_value in (None, ""):
            continue
        items.append(
            {
                "key": key,
                "label": _format_total_label(key),
                "value": str(raw_value),
            }
        )

    return items


def _format_footer_total_value(
    preview_key: str,
    raw_value: object,
    totals: dict[str, object],
) -> str:
    text = str(raw_value)
    if preview_key == "total_quantity":
        unit_label = totals.get("unit_label")
        if isinstance(unit_label, str) and unit_label:
            return f"{text} {unit_label}"
        return text
    if preview_key == "total_amount":
        currency = totals.get("currency")
        if text.startswith("$"):
            return text
        if isinstance(currency, str) and currency:
            return f"{currency} {text}"
        return text
    if preview_key == "total_cbm":
        return f"{text} CBM"
    return text


def _custom_total_value(total_cell: object, model: DocumentModel) -> str | None:
    mode = getattr(total_cell, "value_mode", "model_total")
    if mode == "fixed":
        value = getattr(total_cell, "value", None)
        return value if isinstance(value, str) else None
    if mode == "current_date":
        return date.today().strftime("%Y-%m-%d")
    if mode == "model_date":
        return model.document_date.strftime("%Y-%m-%d") if model.document_date is not None else None
    return None


def _format_total_label(key: str) -> str:
    if not key:
        return key
    return key.replace("_", " ").replace(".", " ").title()


def _build_column_labels(
    mapping: object,
) -> tuple[list[dict[str, str]], list[str]]:
    """构建列标签列表，每项 {key, label}。同时返回列键顺序。

    YAML 中 preview_content.column_labels 的键顺序决定展示列及顺序；标签文字由
    TemplateMapping 在加载时从实际 Excel 表头解析，避免预览与导出形成两个事实源。
    """
    resolved = getattr(mapping, "preview_column_labels", ())
    if isinstance(resolved, tuple) and resolved:
        resolved_labels = [
            {"key": key, "label": label}
            for key, label in resolved
            if isinstance(key, str) and isinstance(label, str)
        ]
        return resolved_labels, [item["key"] for item in resolved_labels]

    preview_config = getattr(mapping, "preview_content", {})
    if not isinstance(preview_config, dict):
        preview_config = {}
    config_labels = preview_config.get("column_labels", {})
    if not isinstance(config_labels, dict) or not config_labels:
        import logging

        logging.getLogger("ro_generator").error(
            "preview_content.column_labels 未配置，预览将不展示列。请在模板 YAML 中添加 column_labels。"
        )
        return [], []

    columns = list(config_labels.keys())
    configured_labels: list[dict[str, str]] = []
    for key in columns:
        raw_label = config_labels.get(key)
        label = raw_label if isinstance(raw_label, str) else _COLUMN_LABEL_DEFAULTS.get(key, key)
        configured_labels.append({"key": key, "label": str(label)})
    return configured_labels, columns


def _build_lines(
    model: DocumentModel,
    columns: list[str],
    row_fixed: dict[str, str] | None = None,
    preview_column_letters: dict[str, str] | None = None,
) -> list[dict[str, object]]:
    """将 DocumentLine 列表转为前端可消费的 dict 列表。

    column_labels 中的键有两类：
    - 命名键（如 po_no、description）→ 从 OrderLine 属性取值
    - 列字母键（如 A）→ 从 row_fixed 取固定值
    """
    rf = row_fixed or {}
    column_letters = preview_column_letters or {}
    result: list[dict[str, object]] = []
    for i, dl in enumerate(model.lines):
        row: dict[str, object] = {}
        for col in columns:
            template_column = column_letters.get(col, col)
            if template_column in rf:
                row[col] = rf[template_column]
            else:
                val = getattr(dl, col, None)
                if isinstance(val, Decimal):
                    spec = resolve_line_field_spec(
                        col,
                        document_type=model.document_type,
                        seller=model.seller,
                        category=dl.category,
                    )
                    row[col] = line_display_value(val, spec)
                elif val is not None:
                    row[col] = val
                else:
                    row[col] = ""
        row["_index"] = i
        row["_source_row"] = dl.source_row
        result.append(row)
    return result


def _build_cost_breakdown_preview(
    model: DocumentModel,
    preview_config: dict[str, Any],
) -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    """构建 Combo 成本拆分的预览列和行。"""

    section = preview_config.get("cost_breakdown", {})
    if not isinstance(section, dict) or not model.cost_breakdown:
        return [], []
    raw_labels = section.get("column_labels", {})
    if not isinstance(raw_labels, dict):
        raw_labels = {}
    default_labels = {
        "po_no": "PO Number",
        "item_line_no": "PO item Line Number",
        "item_number": "Item Number",
        "description": "Description",
        "unit_price": "USD unit price breakdown",
    }
    labels = [
        {"key": key, "label": str(raw_labels.get(key, default))}
        for key, default in default_labels.items()
    ]
    rows: list[dict[str, object]] = []
    for index, line in enumerate(model.cost_breakdown):
        rows.append(
            {
                "po_no": line.po_no,
                "item_line_no": line.item_line_no,
                "item_number": line.item_number,
                "description": line.description,
                "unit_price": f"${line.unit_price.quantize(Decimal('0.01')):,.2f}",
                "_index": index,
                "_source_row": line.source_row,
                "component": line.component,
            }
        )
    return labels, rows


def _build_cost_breakdown_source_entries(
    model: DocumentModel,
) -> list[dict[str, object]]:
    """为成本拆分行提供与主明细相同的来源提示。"""

    if not model.cost_breakdown:
        return []
    schema = current_schema()
    entries: list[dict[str, object]] = []
    identity_fields = {
        "po_no": schema.field("PO record", "po_no"),
        "item_line_no": schema.field("PO record", "item_line"),
        "item_number": schema.field("PO record", "sap"),
    }
    for index, line in enumerate(model.cost_breakdown):
        for key, source_field in identity_fields.items():
            value = getattr(line, key)
            entries.append(
                {
                    "preview_field": f"cost_breakdown[{index}].{key}",
                    "label": f"Cost breakdown {key} (Row {index + 1})",
                    "source_type": "base_field",
                    "sheet": schema.sheet("PO record").name,
                    "row": line.source_row,
                    "field": source_field,
                    "value": str(value),
                    "rule": f'PO RECORD 的 "{source_field}" 列，按 INV# 筛选',
                }
            )
        entries.append(
            {
                "preview_field": f"cost_breakdown[{index}].description",
                "label": f"Cost breakdown Description (Row {index + 1})",
                "source_type": "computed",
                "sheet": schema.sheet("PO record").name,
                "row": line.source_row,
                "field": schema.field("PO record", "description"),
                "value": line.description,
                "rule": f'PO RECORD 的 "{schema.field("PO record", "description")}" 列 + {line.component} 组件标识',
            }
        )
        entries.append(
            {
                "preview_field": f"cost_breakdown[{index}].unit_price",
                "label": f"Cost breakdown Unit Price (Row {index + 1})",
                "source_type": "base_field",
                "sheet": schema.sheet("DATA BASE").name,
                "row": None,
                "field": line.source_field,
                "value": f"${line.unit_price.quantize(Decimal('0.01')):,.2f}",
                "rule": f'DATA BASE 的 "{line.source_field}" 列',
            }
        )
    return entries


def _build_notes(preview_config: dict[str, Any], model: DocumentModel) -> list[str]:
    """构建备注。支持 {total_carton_count} 等模板变量插值。"""
    raw_notes = preview_config.get("notes", [])
    if not isinstance(raw_notes, list):
        raw_notes = []

    interpolations: dict[str, str] = {}
    if model.total_carton_count is not None:
        interpolations["total_carton_count"] = str(model.total_carton_count)

    result: list[str] = []
    for note in raw_notes:
        if not isinstance(note, str):
            continue
        text = note
        for key, val in interpolations.items():
            text = text.replace(f"{{{key}}}", val)
        result.append(text)
    return result


def _build_terms(
    preview_config: dict[str, Any],
    resolved_values: dict[str, str],
) -> dict[str, str]:
    """构建预览条款。

    新结构分为两类：
    - terms_fields: 复用 header / layout 已解析出的字段值
    - static_terms: 仅预览存在的固定文案
    """
    result: dict[str, str] = {}

    raw_fields = preview_config.get("terms_fields", [])
    if isinstance(raw_fields, list):
        for field_name in raw_fields:
            if not isinstance(field_name, str):
                continue
            value = resolved_values.get(field_name)
            if value:
                result[field_name] = value

    raw_static_terms = preview_config.get("static_terms", {})
    if isinstance(raw_static_terms, dict):
        for key, value in raw_static_terms.items():
            if isinstance(key, str) and isinstance(value, str) and value:
                result[key] = value

    return result


def _build_source_entries(
    model: DocumentModel,
    preview_config: dict[str, Any],
    column_labels: list[dict[str, str]],
    layout: dict[str, object],
    totals: dict[str, object],
    mapping: Any = None,
    resolved_values: dict[str, str] | None = None,
) -> list[dict[str, object]]:
    """从 layout + column_labels 构建字段来源记录，与预览展示完全一致。"""
    src_overrides = _parse_source_overrides(preview_config)
    entries: list[dict[str, object]] = []
    entries.extend(
        _build_header_source_entries(model, layout, mapping, resolved_values, src_overrides)
    )
    entries.extend(_build_line_source_entries(model, column_labels, mapping, src_overrides))
    entries.extend(_build_cost_breakdown_source_entries(model))
    entries.extend(_build_totals_source_entries(totals, mapping))
    return entries


def _parse_source_overrides(preview_config: dict[str, Any]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    raw = preview_config.get("source_overrides", {})
    if isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(k, str) and isinstance(v, dict):
                result[k] = {ik: str(iv) for ik, iv in v.items() if isinstance(iv, str)}
    return result


def _build_header_source_entries(
    model: DocumentModel,
    layout: dict[str, object],
    mapping: Any,
    resolved_values: dict[str, str] | None,
    src_overrides: dict[str, dict[str, str]],
) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    seen: set[str] = set()
    for section in ("top", "info"):
        sec = layout.get(section, {})
        if not isinstance(sec, dict):
            continue
        for position in ("left", "center", "right"):
            field_names = sec.get(position, [])
            if not isinstance(field_names, list):
                continue
            for field_name in field_names:
                if not isinstance(field_name, str) or field_name in seen:
                    continue
                seen.add(field_name)

                spec = resolve_header_field_spec(
                    field_name, seller=model.seller, document_type=model.document_type
                )
                label = spec.label if spec is not None else field_name
                header_fixed = mapping.header_fixed if mapping is not None else {}
                if field_name in header_fixed:
                    source_type, sheet, field = ("template_content", None, None)
                    rule = "YAML header_fixed 固定值"
                elif is_system_generated_header_field(
                    field_name,
                    seller=model.seller,
                    document_type=model.document_type,
                ):
                    source_type, sheet, field = ("system_generated", None, None)
                    rule = "预览时自动填入程序运行当天日期"
                elif field_name in HEADER_MANUAL_KEYS or (
                    spec is not None and spec.source_type == "manual_input"
                ):
                    source_type, sheet, field = ("manual_input", None, None)
                    rule = (
                        spec.rule
                        if spec is not None and spec.rule
                        else "业务字段，需由业务人员在工作台中录入，工具不自动生成"
                    )
                else:
                    if spec is None:
                        source_type, sheet, field = ("template_content", None, None)
                        rule = "模板固定文本"
                    else:
                        source_type = spec.source_type
                        sheet = spec.source_sheet
                        field = spec.source_field
                        rule = spec.rule
                override = src_overrides.get(field_name, {})
                if override.get("sheet"):
                    sheet = override["sheet"]
                if override.get("field"):
                    field = override["field"]
                if override.get("rule"):
                    rule = override["rule"]

                value = ""
                static_values = getattr(mapping, "preview_static_values", {})
                if isinstance(static_values, dict) and field_name in static_values:
                    raw_static = static_values[field_name]
                    if isinstance(raw_static, tuple):
                        value = "\n".join(str(item) for item in raw_static)
                model_attr = spec.model_attr if spec is not None else None
                if model_attr and not value:
                    val = getattr(model, model_attr, None)
                    if val is not None:
                        value = str(val)
                if resolved_values is not None and field_name in resolved_values:
                    value = resolved_values[field_name]

                entries.append(
                    {
                        "preview_field": field_name,
                        "label": label,
                        "source_type": source_type,
                        "sheet": sheet,
                        "row": None,
                        "field": field,
                        "value": value,
                        "rule": rule,
                    }
                )
    return entries


def _build_line_source_entries(
    model: DocumentModel,
    column_labels: list[dict[str, str]],
    mapping: Any,
    src_overrides: dict[str, dict[str, str]],
) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for i, dl in enumerate(model.lines):
        for col_def in column_labels:
            key = col_def.get("key", "")
            if not isinstance(key, str) or not key:
                continue
            label = str(col_def.get("label", key))
            override = src_overrides.get(key, {})

            fixed_value, fixed_column = _preview_fixed_value(mapping, key)
            line_spec = None
            val: object = None
            source_type = "template_content"
            sheet: str | None = None
            field: str | None = None
            rule = ""
            if fixed_value is not None:
                val = fixed_value
                if not val:
                    continue
                source_type = "template_content"
                sheet = None
                field = fixed_column
                rule = f"每行固定值：{val}"
            else:
                line_spec = resolve_line_field_spec(
                    key,
                    document_type=model.document_type,
                    seller=model.seller,
                    category=dl.category,
                )
                source_type = line_spec.source_type
                sheet = line_spec.source_sheet
                field = line_spec.source_field or key
                rule = line_spec.rule
                if override.get("sheet"):
                    sheet = override["sheet"]
                if override.get("field"):
                    field = override["field"]
                if override.get("rule"):
                    rule = override["rule"]
                val = getattr(dl, key, None)

                # PF Invoice/PL 的实际出货列由 INV# 中的 YYMM 决定；预览来源
                # 必须展示真实的 2601–2612 列，不能继续显示通用 SHIP QTY。
                if key == "quantity" and dl.quantity_source_field:
                    field = dl.quantity_source_field
                    rule = f'PO RECORD 的 INV# 对应月度出货列 "{field}"'
                sheet, field, rule = _apply_packing_weight_source(dl, key, sheet, field, rule)

            if val is None or val == "":
                continue
            display_value = str(val)
            if line_spec is not None and isinstance(val, Decimal):
                display_value = str(line_display_value(val, line_spec))

            entries.append(
                {
                    "preview_field": f"line[{i}].{key}",
                    "label": f"{label} (Row {i + 1})",
                    "source_type": source_type,
                    "sheet": sheet,
                    "row": _line_source_row(dl, sheet, line_spec),
                    "field": field,
                    "value": display_value,
                    "rule": rule,
                }
            )
    return entries


def _line_source_row(
    line: DocumentLine,
    sheet: str | None,
    line_spec: Any,
) -> int | None:
    if sheet == current_schema().sheet("PO record").name:
        return line.source_row
    if line_spec and uses_po_record_row(line_spec):
        return line.source_row
    return None


def _apply_packing_weight_source(
    line: DocumentLine,
    key: str,
    sheet: str | None,
    field: str | None,
    rule: str,
) -> tuple[str | None, str | None, str]:
    if key == "net_weight" and line.net_weight_source_field:
        return (
            line.net_weight_source_sheet,
            line.net_weight_source_field,
            line.net_weight_source_rule or rule,
        )
    if key == "gross_weight" and line.gross_weight_source_field:
        return (
            line.gross_weight_source_sheet,
            line.gross_weight_source_field,
            line.gross_weight_source_rule or rule,
        )
    return sheet, field, rule


def _preview_fixed_value(mapping: Any, key: str) -> tuple[str | None, str]:
    if mapping is None or not hasattr(mapping, "lines"):
        return None, key
    preview_columns = getattr(mapping, "preview_column_letters", {})
    column = preview_columns.get(key, key) if isinstance(preview_columns, dict) else key
    row_fixed = mapping.lines.row_fixed or {}
    value = row_fixed.get(column)
    return value if isinstance(value, str) else None, column


def _build_totals_source_entries(
    totals: dict[str, object],
    mapping: Any,
) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []

    mapping_totals = getattr(mapping, "totals", {}) if mapping is not None else {}
    if isinstance(mapping_totals, dict):
        for key, total_cell in mapping_totals.items():
            if not isinstance(key, str):
                continue
            mode = getattr(total_cell, "value_mode", "model_total")
            if mode == "model_total":
                total_spec = total_spec_for_mapping_key(key)
                if total_spec is None:
                    continue
                raw_value = totals.get(total_spec.preview_key)
                if raw_value in (None, ""):
                    continue
                entries.append(
                    {
                        "preview_field": f"totals.{key}",
                        "label": total_spec.label,
                        "source_type": "computed",
                        "sheet": None,
                        "row": None,
                        "field": None,
                        "value": _format_footer_total_value(
                            total_spec.preview_key, raw_value, totals
                        ),
                        "rule": total_spec.rule,
                    }
                )

    extra_items = totals.get("_extra_items", [])
    if isinstance(extra_items, list):
        for item in extra_items:
            if not isinstance(item, dict):
                continue
            extra_key = item.get("key")
            extra_value = item.get("value")
            if (
                not isinstance(extra_key, str)
                or not isinstance(extra_value, str)
                or not extra_value
            ):
                continue
            extra_label = item.get("label")
            extra_source_type = item.get("source_type")
            extra_sheet = item.get("sheet")
            extra_field = item.get("field")
            extra_rule = item.get("rule")
            entries.append(
                {
                    "preview_field": f"totals.{extra_key}",
                    "label": (
                        str(extra_label)
                        if isinstance(extra_label, str)
                        else _format_total_label(extra_key)
                    ),
                    "source_type": (
                        str(extra_source_type)
                        if isinstance(extra_source_type, str)
                        else "system_generated"
                    ),
                    "sheet": extra_sheet if isinstance(extra_sheet, str) else None,
                    "row": None,
                    "field": extra_field if isinstance(extra_field, str) else None,
                    "value": extra_value,
                    "rule": str(extra_rule) if isinstance(extra_rule, str) else "",
                }
            )

    return entries


def _error_preview(build: BuildDocumentResult) -> DocumentPreview:
    errors: list[dict[str, object]] = []
    for m in build.messages:
        if m.kind == "blocking_error":
            errors.append(
                {
                    "code": m.code,
                    "message": m.message,
                    "severity": getattr(m, "severity", None),
                }
            )
    return DocumentPreview(
        document_type="",
        title="",
        seller="",
        buyer="",
        po_no="",
        errors=errors,
    )


__all__ = [
    "DocumentPreview",
    "PreviewSourceEntry",
    "build_preview",
]
