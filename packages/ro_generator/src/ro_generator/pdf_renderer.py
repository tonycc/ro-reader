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
