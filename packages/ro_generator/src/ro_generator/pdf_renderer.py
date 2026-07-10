"""PDF 渲染器：把 DocumentPreview（预览页同源数据）渲染为 PDF。

设计边界：
- 只消费 build_preview() 产出的 DocumentPreview，不做业务计算、不重算金额。
- 一份或多份 preview 渲染为单个 PDF；多份之间用分页符分隔（发票组 bundle）。
- 版面对齐预览页：标题 / 头信息（top+info 左右分栏）/ 明细表 / 合计 / 备注。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as _xml_escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ro_generator.document_preview import DocumentPreview


@dataclass(frozen=True)
class PdfRenderResult:
    """PDF 渲染输出。"""

    output_path: Path


_WIDE_COLUMN_THRESHOLD = 6


def render_pdf(previews: list[DocumentPreview], output_path: str | Path) -> PdfRenderResult:
    """把一份或多份 preview 渲染为单个 PDF。多份 = 多节（分页）。"""
    if not previews:
        raise ValueError("render_pdf 至少需要一份 preview")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    max_cols = max(len(p.column_labels) for p in previews)
    pagesize = landscape(A4) if max_cols > _WIDE_COLUMN_THRESHOLD else A4

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=pagesize,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
    )
    styles = getSampleStyleSheet()
    story: list[Any] = []
    for i, preview in enumerate(previews):
        if i > 0:
            story.append(PageBreak())
        story.extend(_section_flowables(preview, styles))
    doc.build(story)

    return PdfRenderResult(output_path=output_path.resolve())


def _section_flowables(preview: DocumentPreview, styles: Any) -> list[Any]:
    flow: list[Any] = []

    # 标题
    flow.append(Paragraph(_xml_escape(preview.title or preview.document_type), styles["Title"]))
    flow.append(Spacer(1, 4 * mm))

    # 头信息区（top + info），左右分栏
    header_rows: list[list[Any]] = []
    for section in ("top", "info"):
        left = _region_lines(preview, section, "left")
        right = _region_lines(preview, section, "right")
        center = _region_lines(preview, section, "center")
        left_all = left + center
        if not left_all and not right:
            continue
        header_rows.append(
            [
                Paragraph("<br/>".join(_xml_escape(x) for x in left_all), styles["Normal"]),
                Paragraph("<br/>".join(_xml_escape(x) for x in right), styles["Normal"]),
            ]
        )
    if header_rows:
        htable = Table(header_rows, colWidths=["55%", "45%"])
        htable.setStyle(
            TableStyle(
                [
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        flow.append(htable)
    flow.append(Spacer(1, 6 * mm))

    # 明细表
    if preview.column_labels:
        header = [col.get("label", col.get("key", "")) for col in preview.column_labels]
        keys = [col.get("key", "") for col in preview.column_labels]
        rows: list[list[str]] = [header]
        for line in preview.lines:
            rows.append([str(line.get(key, "")) for key in keys])
        table = Table(rows, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        flow.append(table)
        flow.append(Spacer(1, 4 * mm))

    # 合计
    for total in _totals_lines(preview):
        flow.append(Paragraph(total, styles["Normal"]))

    # 备注
    if preview.notes:
        flow.append(Spacer(1, 4 * mm))
        for note in preview.notes:
            flow.append(Paragraph(_xml_escape(str(note)), styles["Normal"]))

    return flow


def _totals_lines(preview: DocumentPreview) -> list[str]:
    labels = preview.totals.get("_labels")
    if not isinstance(labels, dict):
        return []
    lines: list[str] = []
    for key, label in labels.items():
        value = preview.totals.get(key)
        if value is None:
            continue
        lines.append(f"<b>{_xml_escape(str(label))}:</b> {_xml_escape(str(value))}")
    return lines


_FIELD_LABELS = {
    "po_no": "PO NO.",
    "invoice_no": "INVOICE NO.",
    "pi_no": "PI NO.",
    "ship_to": "SHIP TO",
    "buyer": "BUYER",
}


def _region_lines(preview: DocumentPreview, section: str, position: str) -> list[str]:
    layout = preview.layout if isinstance(preview.layout, dict) else {}
    sec = layout.get(section, {})
    if not isinstance(sec, dict):
        return []
    fields = sec.get(position, [])
    if not isinstance(fields, list):
        return []
    out: list[str] = []
    for field in fields:
        if isinstance(field, str):
            out.extend(_field_lines(preview, field))
    return out


def _field_lines(preview: DocumentPreview, field: str) -> list[str]:
    if field == "title":
        return []  # 标题已单独渲染
    if field == "seller_info":
        return [str(x) for x in preview.seller_info]
    if field == "to_label":
        return [preview.to_label] if preview.to_label else []
    if field == "terms":
        return [f"{k}: {v}" for k, v in preview.terms.items()]
    if field == "seller":
        return [preview.seller] if preview.seller else []
    # 其余字段：优先 resolved_values，其次直接属性
    resolved = (
        preview.resolved_values.get(field) if isinstance(preview.resolved_values, dict) else None
    )
    value = resolved if resolved else getattr(preview, field, None)
    if not value:
        return []
    label = _FIELD_LABELS.get(field)
    return [f"{label}: {value}" if label else str(value)]
