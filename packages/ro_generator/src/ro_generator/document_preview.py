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
from typing import Any

from ro_generator.document_model import DocumentModel
from ro_generator.generator import BuildDocumentResult
from ro_generator.header_rules import (
    HEADER_DATE_KEYS,
    HEADER_MANUAL_KEYS,
    build_header_resolved_values,
    resolve_header_field_spec,
)
from ro_generator.line_rules import (
    line_display_value,
    resolve_line_field_spec,
    uses_po_record_row,
)
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
    column_labels: list[dict[str, str]] = field(default_factory=list)
    lines: list[dict[str, object]] = field(default_factory=list)
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
    "confirmed_ex_factory_date": "EX-FACTORY DATE",
}

_DOC_TITLE_DEFAULTS: dict[str, str] = {
    "PI": "PROFORMA INVOICE",
    "PO": "PURCHASE ORDER",
    "INVOICE": "COMMERCIAL INVOICE",
    "PL": "PACKING LIST",
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
    if model is None:
        return _error_preview(build)

    doc_type = model.document_type

    # 从 mapping 对象读取 preview_content（YAML 加载时已解析，不再重复读文件）
    preview_config: dict[str, Any] = mapping.preview_content if mapping is not None else {}

    # 列标签（同时返回列键顺序，供 _build_lines 使用）
    column_labels, line_columns = _build_column_labels(preview_config)

    # 明细行（含 row_fixed 固定列值）
    lines = _build_lines(model, line_columns, mapping.lines.row_fixed)
    unit_label = mapping.lines.unit_label or "PCS"

    # 合计
    totals = build_preview_totals(model, unit_label=unit_label)
    if mapping is not None:
        _merge_custom_mapping_totals(totals, mapping)
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
        title=preview_config.get("title", _DOC_TITLE_DEFAULTS.get(doc_type, doc_type)),
        seller=model.seller,
        buyer=model.buyer,
        po_no=model.po_no,
        pi_no=model.pi_no,
        invoice_no=model.invoice_no,
        ship_to=model.ship_to,
        seller_info=list(preview_config.get("seller_info", [])),
        to_label=preview_config.get("to_label", ""),
        terms=_build_terms(preview_config, resolved_values),
        column_labels=column_labels,
        lines=lines,
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
        return merged  # type: ignore[return-type]
    for section in ("top", "info"):
        if section in config_layout:
            cfg_section = config_layout[section]
            if isinstance(cfg_section, dict):
                for position in cfg_section:
                    if position in merged[section] and isinstance(cfg_section[position], list):
                        merged[section][position] = list(cfg_section[position])
    return merged  # type: ignore[return-type]


def _merge_custom_mapping_totals(
    totals: dict[str, object],
    mapping: object,
) -> None:
    extra_items: list[dict[str, str]] = []
    mapping_totals = getattr(mapping, "totals", {})
    if not isinstance(mapping_totals, dict):
        return

    for key, total_cell in mapping_totals.items():
        if not isinstance(key, str):
            continue
        mode = getattr(total_cell, "value_mode", "model_total")
        if mode == "model_total":
            continue

        value = _custom_total_value(total_cell)
        if value is None:
            continue

        item = {
            "key": key,
            "label": _format_total_label(key),
            "value": value,
            "source_type": "template_content" if mode == "fixed" else "system_generated",
            "rule": (
                "mapping.totals 固定值"
                if mode == "fixed"
                else "系统生成当前日期"
            ),
        }
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
            items.append({
                "key": key,
                "label": spec.label,
                "value": _format_footer_total_value(spec.preview_key, raw_value, totals),
            })
            continue

        raw_value = totals.get(key)
        if raw_value in (None, ""):
            continue
        items.append({
            "key": key,
            "label": _format_total_label(key),
            "value": str(raw_value),
        })

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
        if isinstance(currency, str) and currency:
            return f"{currency} {text}"
        return text
    if preview_key == "total_cbm":
        return f"{text} CBM"
    return text


def _custom_total_value(total_cell: object) -> str | None:
    mode = getattr(total_cell, "value_mode", "model_total")
    if mode == "fixed":
        value = getattr(total_cell, "value", None)
        return value if isinstance(value, str) else None
    if mode == "current_date":
        return date.today().strftime("%Y-%m-%d")
    return None


def _format_total_label(key: str) -> str:
    if not key:
        return key
    return key.replace("_", " ").replace(".", " ").title()


def _build_column_labels(
    preview_config: dict[str, Any],
) -> tuple[list[dict[str, str]], list[str]]:
    """构建列标签列表，每项 {key, label}。同时返回列键顺序。

    YAML 中 preview_content.column_labels 的键顺序决定了预览中展示哪些列及顺序。
    若未配置则返回空列表并记录错误。
    """
    config_labels = preview_config.get("column_labels", {})
    if not isinstance(config_labels, dict) or not config_labels:
        import logging
        logging.getLogger("ro_generator").error(
            "preview_content.column_labels 未配置，预览将不展示列。请在模板 YAML 中添加 column_labels。"
        )
        return [], []

    columns = list(config_labels.keys())
    result: list[dict[str, str]] = []
    for key in columns:
        raw_label = config_labels.get(key)
        if isinstance(raw_label, str):
            label = raw_label
        else:
            label = _COLUMN_LABEL_DEFAULTS.get(key, key)
        result.append({"key": key, "label": str(label)})
    return result, columns


def _build_lines(
    model: DocumentModel,
    columns: list[str],
    row_fixed: dict[str, str] | None = None,
) -> list[dict[str, object]]:
    """将 DocumentLine 列表转为前端可消费的 dict 列表。

    column_labels 中的键有两类：
    - 命名键（如 po_no、description）→ 从 OrderLine 属性取值
    - 列字母键（如 A）→ 从 row_fixed 取固定值
    """
    rf = row_fixed or {}
    result: list[dict[str, object]] = []
    for i, dl in enumerate(model.lines):
        row: dict[str, object] = {}
        for col in columns:
            if col in rf:
                row[col] = rf[col]
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
    preview_config: dict[str, Any], resolved_values: dict[str, str],
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
    entries: list[dict[str, object]] = []
    src_overrides: dict[str, dict[str, str]] = {}
    raw_overrides = preview_config.get("source_overrides", {})
    if isinstance(raw_overrides, dict):
        for k, v in raw_overrides.items():
            if isinstance(k, str) and isinstance(v, dict):
                src_overrides[k] = {ik: str(iv) for ik, iv in v.items() if isinstance(iv, str)}

    # 1. Header 字段：遍历 layout 中所有区域引用的 field 名
    seen_header: set[str] = set()
    for section in ("top", "info"):
        sec = layout.get(section, {})
        if not isinstance(sec, dict):
            continue
        for position in ("left", "center", "right"):
            field_names = sec.get(position, [])
            if not isinstance(field_names, list):
                continue
            for field_name in field_names:
                if not isinstance(field_name, str) or field_name in seen_header:
                    continue
                seen_header.add(field_name)

                spec = resolve_header_field_spec(
                    field_name, seller=model.seller, document_type=model.document_type
                )
                label = spec.label if spec is not None else field_name
                if field_name in HEADER_DATE_KEYS:
                    source_type, sheet, field = ("system_generated", None, None)
                    rule = "预览时自动填入程序运行当天日期"
                elif field_name in HEADER_MANUAL_KEYS:
                    source_type, sheet, field = ("manual_input", None, None)
                    rule = "业务字段，需由业务人员在工作台中录入，工具不自动生成"
                else:
                    if spec is None:
                        source_type, sheet, field = ("template_content", None, None)
                        rule = "模板固定文本"
                    else:
                        source_type = spec.source_type
                        sheet = spec.source_sheet
                        field = spec.source_field
                        rule = spec.rule
                # YAML source_overrides 覆盖默认来源信息
                override = src_overrides.get(field_name, {})
                if override.get("sheet"):
                    sheet = override["sheet"]
                if override.get("field"):
                    field = override["field"]
                if override.get("rule"):
                    rule = override["rule"]

                value = ""
                model_attr = spec.model_attr if spec is not None else None
                if model_attr:
                    val = getattr(model, model_attr, None)
                    if val is not None:
                        value = str(val)
                if resolved_values is not None and field_name in resolved_values:
                    value = resolved_values[field_name]

                entries.append({
                    "preview_field": field_name,
                    "label": label,
                    "source_type": source_type,
                    "sheet": sheet,
                    "row": None,
                    "field": field,
                    "value": value,
                    "rule": rule,
                })

    # 2. 明细行字段：遍历 column_labels（与预览表格列头一致）
    for i, dl in enumerate(model.lines):
        for col_def in column_labels:
            key = col_def.get("key", "")
            if not isinstance(key, str) or not key:
                continue
            # label 直接来自 YAML column_labels，保证与预览表头一致
            label = str(col_def.get("label", key))
            override = src_overrides.get(key, {})

            # row_fixed 列（键为列字母，如 "A"）从映射取值
            row_fixed: dict[str, str] = {}
            if mapping is not None and hasattr(mapping, 'lines'):
                row_fixed = mapping.lines.row_fixed or {}
            line_spec = None
            if key in row_fixed:
                val = row_fixed[key]
                if not val:
                    continue
                source_type = "template_content"
                sheet = None
                field = key
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

            if val is None or val == "":
                continue
            display_value = str(val)
            if line_spec is not None and isinstance(val, Decimal):
                display_value = str(line_display_value(val, line_spec))

            entries.append({
                "preview_field": f"line[{i}].{key}",
                "label": f"{label} (Row {i + 1})",
                "source_type": source_type,
                "sheet": sheet,
                "row": dl.source_row if line_spec and uses_po_record_row(line_spec) and sheet == "PO record" else None,
                "field": field,
                "value": display_value,
                "rule": rule,
            })

    # 3. 合计字段（严格跟随 mapping.totals，保证与预览 footer 一致）
    mapping_totals = getattr(mapping, "totals", {}) if mapping is not None else {}
    if isinstance(mapping_totals, dict):
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
                entries.append({
                    "preview_field": f"totals.{key}",
                    "label": spec.label,
                    "source_type": "computed",
                    "sheet": None,
                    "row": None,
                    "field": None,
                    "value": _format_footer_total_value(spec.preview_key, raw_value, totals),
                    "rule": spec.rule,
                })

    extra_items = totals.get("_extra_items", [])
    if isinstance(extra_items, list):
        for item in extra_items:
            if not isinstance(item, dict):
                continue
            key = item.get("key")
            value = item.get("value")
            if not isinstance(key, str) or not isinstance(value, str) or not value:
                continue
            label = item.get("label")
            source_type = item.get("source_type")
            rule = item.get("rule")
            entries.append({
                "preview_field": f"totals.{key}",
                "label": str(label) if isinstance(label, str) else _format_total_label(key),
                "source_type": (
                    str(source_type)
                    if isinstance(source_type, str)
                    else "system_generated"
                ),
                "sheet": None,
                "row": None,
                "field": None,
                "value": value,
                "rule": str(rule) if isinstance(rule, str) else "",
            })

    return entries


def _error_preview(build: BuildDocumentResult) -> DocumentPreview:
    errors: list[dict[str, object]] = []
    for m in build.messages:
        if m.kind == "blocking_error":
            errors.append({
                "code": m.code,
                "message": m.message,
                "severity": getattr(m, "severity", None),
            })
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
