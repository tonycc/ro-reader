# PDF 导出功能实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在单据预览页新增"导出 PDF"按钮，把当前预览的单据（含 SK/YM 发票组 bundle）渲染为 PDF 一键下载。

**Architecture:** 核心包 `ro_generator` 新增 `pdf_renderer.py`，消费 `build_preview()` 产出的 `DocumentPreview` 渲染 PDF（纸面 = 预览页）。格式分派复用 `DocumentRequest.output_format`（扩展出 `"pdf"`），全部发生在核心包内；API/前端仅透传 `output_format`，不含格式判断。复用现有 `/api/download` 下载通道。

**Tech Stack:** Python 3.11 / reportlab（纯 Python，PyInstaller 友好）/ pypdf（测试期文本抽取）/ FastAPI / Vue 3 + TypeScript / Playwright。

**Spec:** `docs/superpowers/specs/2026-07-09-pdf-export-design.md`

---

## 文件结构

**新增：**
- `packages/ro_generator/src/ro_generator/pdf_renderer.py` — PDF 渲染器，`render_pdf(previews, output_path) -> PdfRenderResult`
- `packages/ro_generator/tests/test_pdf_renderer.py` — 渲染器单元测试

**修改（核心包）：**
- `packages/ro_generator/pyproject.toml` — 新增 `reportlab>=4.0`
- `pyproject.toml`（root）— dev 组新增 `pypdf>=4.0`；mypy 增加 `reportlab.*` override
- `packages/ro_generator/src/ro_generator/models.py:187` — `output_format` 扩展 `"pdf"`
- `packages/ro_generator/src/ro_generator/packager.py` — 3 个文件名构造函数增加 `extension` 参数
- `packages/ro_generator/src/ro_generator/generator.py` — `_generate_one` / `_generate_invoice_pl_bundle` / `export_invoice_group_from_snapshot` 增加 pdf 分派
- `packages/ro_generator/tests/test_generator.py` — pdf 分派测试
- `packages/ro_generator/tests/test_packager.py` — extension 参数测试

**修改（API）：**
- `packages/ro_workbench_api/src/ro_workbench_api/app.py` — 请求模型加 `output_format`、端点透传、下载 media type 加 pdf
- `packages/ro_workbench_api/tests/test_app.py` — pdf 导出与下载测试

**修改（前端）：**
- `frontend/src/stores/api.ts` — `DryRunRequest` 加 `output_format`；`exportInvoiceGroup` 加 `output_format` 参数
- `frontend/src/stores/workbench.ts` — `doExport`/`exportOneGroup` 加 `outputFormat` 形参；新增 `doExportPdf()`
- `frontend/src/components/preview/PreviewScreen.vue` — 新增"导出 PDF"按钮
- `frontend/e2e/workbench.spec.ts` — 新增 PDF 下载 E2E 场景

---

## Task 1: reportlab 依赖 + pdf_renderer 骨架（标题 + 明细表 + 合计 + 备注）

**Files:**
- Modify: `packages/ro_generator/pyproject.toml:6-9`
- Modify: `pyproject.toml:19-30`（root dev 组）+ `pyproject.toml:74-78`（mypy override）
- Create: `packages/ro_generator/src/ro_generator/pdf_renderer.py`
- Test: `packages/ro_generator/tests/test_pdf_renderer.py`

- [ ] **Step 1: 加依赖**

编辑 `packages/ro_generator/pyproject.toml`，`dependencies` 改为：

```toml
dependencies = [
    "openpyxl>=3.1.5",
    "PyYAML>=6.0",
    "reportlab>=4.0",
]
```

编辑 root `pyproject.toml`，`[dependency-groups] dev` 列表末尾（`"xlrd<2",` 之后）加一行：

```toml
    "pypdf>=4.0",
```

在 root `pyproject.toml` 的 mypy overrides 区（`[[tool.mypy.overrides]]` 之后）追加一个新块：

```toml
[[tool.mypy.overrides]]
module = ["reportlab.*"]
ignore_missing_imports = true
```

- [ ] **Step 2: 安装依赖**

Run: `uv sync --all-packages`
Expected: 成功，安装 reportlab 与 pypdf。

- [ ] **Step 3: 写失败测试**

创建 `packages/ro_generator/tests/test_pdf_renderer.py`：

```python
"""pdf_renderer 单元测试。"""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader
from ro_generator.document_preview import DocumentPreview
from ro_generator.pdf_renderer import PdfRenderResult, render_pdf


def _sample_preview(**overrides) -> DocumentPreview:
    base = dict(
        document_type="INVOICE",
        title="COMMERCIAL INVOICE",
        seller="GS PTE",
        buyer="EMAX PTE",
        po_no="4500030844",
        invoice_no="INV-001",
        column_labels=[
            {"key": "description", "label": "DESCRIPTION"},
            {"key": "quantity", "label": "QTY"},
            {"key": "unit_price", "label": "UNIT PRICE"},
        ],
        lines=[
            {"description": "CB2500.B2", "quantity": "100", "unit_price": "$28.00", "_index": 0},
        ],
        totals={
            "total_quantity": "100 PCS",
            "total_amount": "$2,800.00",
            "_labels": {"total_quantity": "TOTAL QTY", "total_amount": "TOTAL AMOUNT"},
        },
        notes=["PACKED IN 5 CTNS"],
    )
    base.update(overrides)
    return DocumentPreview(**base)


def _text(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_render_pdf_creates_file(tmp_path):
    out = tmp_path / "doc.pdf"
    result = render_pdf([_sample_preview()], out)
    assert isinstance(result, PdfRenderResult)
    assert result.output_path == out.resolve()
    assert out.exists()
    assert out.read_bytes()[:4] == b"%PDF"


def test_render_pdf_contains_title_columns_totals_notes(tmp_path):
    out = tmp_path / "doc.pdf"
    render_pdf([_sample_preview()], out)
    text = _text(out)
    assert "COMMERCIAL INVOICE" in text
    assert "DESCRIPTION" in text
    assert "CB2500.B2" in text
    assert "$2,800.00" in text
    assert "PACKED IN 5 CTNS" in text
```

- [ ] **Step 4: 运行测试确认失败**

Run: `uv run pytest packages/ro_generator/tests/test_pdf_renderer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ro_generator.pdf_renderer'`

- [ ] **Step 5: 写最小实现**

创建 `packages/ro_generator/src/ro_generator/pdf_renderer.py`：

```python
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
    flow.append(Paragraph(preview.title or preview.document_type, styles["Title"]))
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
            flow.append(Paragraph(str(note), styles["Normal"]))

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
        lines.append(f"<b>{label}:</b> {value}")
    return lines
```

- [ ] **Step 6: 运行测试确认通过**

Run: `uv run pytest packages/ro_generator/tests/test_pdf_renderer.py -v`
Expected: PASS（2 passed）

- [ ] **Step 7: Commit**

```bash
git add packages/ro_generator/pyproject.toml pyproject.toml uv.lock \
  packages/ro_generator/src/ro_generator/pdf_renderer.py \
  packages/ro_generator/tests/test_pdf_renderer.py
git commit -m "feat(generator): add pdf_renderer with title/table/totals/notes"
```

---

## Task 2: pdf_renderer 头信息区（top/info 左右分栏）

**Files:**
- Modify: `packages/ro_generator/src/ro_generator/pdf_renderer.py`
- Test: `packages/ro_generator/tests/test_pdf_renderer.py`

- [ ] **Step 1: 写失败测试**

在 `test_pdf_renderer.py` 末尾追加：

```python
def test_render_pdf_contains_header_layout_fields(tmp_path):
    preview = _sample_preview(
        seller_info=["GS PTE LTD", "1 Marina Blvd"],
        ship_to="EMAX WAREHOUSE",
        layout={
            "top": {"left": ["seller_info"], "center": [], "right": ["title", "seller", "po_no"]},
            "info": {"left": ["ship_to"], "right": ["invoice_no"]},
        },
        resolved_values={"po_no": "4500030844", "invoice_no": "INV-001"},
    )
    out = tmp_path / "doc.pdf"
    render_pdf([preview], out)
    text = _text(out)
    assert "GS PTE LTD" in text
    assert "1 Marina Blvd" in text
    assert "EMAX WAREHOUSE" in text
    assert "4500030844" in text
    assert "INV-001" in text
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest packages/ro_generator/tests/test_pdf_renderer.py::test_render_pdf_contains_header_layout_fields -v`
Expected: FAIL — `GS PTE LTD` / `EMAX WAREHOUSE` 不在文本中（头信息区未渲染）

- [ ] **Step 3: 实现头信息区**

在 `pdf_renderer.py` 中，`_section_flowables` 的"标题"之后、"明细表"之前，插入头信息区渲染。将标题段之后的 `flow.append(Spacer(1, 6 * mm))` 替换为下面这段（新增 header 表格）：

```python
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
                Paragraph("<br/>".join(left_all), styles["Normal"]),
                Paragraph("<br/>".join(right), styles["Normal"]),
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
```

并在文件底部（`_totals_lines` 之后）新增两个 helper：

```python
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
    resolved = preview.resolved_values.get(field) if isinstance(preview.resolved_values, dict) else None
    value = resolved if resolved else getattr(preview, field, None)
    if not value:
        return []
    label = _FIELD_LABELS.get(field)
    return [f"{label}: {value}" if label else str(value)]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest packages/ro_generator/tests/test_pdf_renderer.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add packages/ro_generator/src/ro_generator/pdf_renderer.py packages/ro_generator/tests/test_pdf_renderer.py
git commit -m "feat(generator): render header layout region in pdf_renderer"
```

---

## Task 3: pdf_renderer 多份 preview 分页（发票组 bundle）

**Files:**
- Test: `packages/ro_generator/tests/test_pdf_renderer.py`（分页逻辑已在 Task 1 的 `render_pdf` 里实现，此任务补测试验证）

- [ ] **Step 1: 写测试**

在 `test_pdf_renderer.py` 末尾追加：

```python
def test_render_pdf_multi_preview_paginates(tmp_path):
    inv = _sample_preview(title="COMMERCIAL INVOICE")
    pl = _sample_preview(
        document_type="PL",
        title="PACKING LIST",
        totals={"total_quantity": "100 PCS", "_labels": {"total_quantity": "TOTAL QTY"}},
        notes=["PACKED IN 5 CTNS"],
    )
    out = tmp_path / "bundle.pdf"
    render_pdf([inv, pl], out)
    reader = PdfReader(str(out))
    assert len(reader.pages) == 2
    all_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "COMMERCIAL INVOICE" in all_text
    assert "PACKING LIST" in all_text
```

- [ ] **Step 2: 运行测试确认通过**

Run: `uv run pytest packages/ro_generator/tests/test_pdf_renderer.py::test_render_pdf_multi_preview_paginates -v`
Expected: PASS（`render_pdf` 已在多份间插入 `PageBreak`）

> 若失败（页数 ≠ 2），检查 `render_pdf` 循环里 `if i > 0: story.append(PageBreak())` 是否存在。

- [ ] **Step 3: Commit**

```bash
git add packages/ro_generator/tests/test_pdf_renderer.py
git commit -m "test(generator): verify pdf_renderer paginates multiple previews"
```

---

## Task 4: packager 文件名构造函数支持 extension 参数

**Files:**
- Modify: `packages/ro_generator/src/ro_generator/packager.py:32-45`（`build_document_filename`）、`:48-59`（`build_invoice_pl_filename`）、`:62-80`（`build_invoice_group_document_filename`）
- Test: `packages/ro_generator/tests/test_packager.py`

- [ ] **Step 1: 写失败测试**

在 `packages/ro_generator/tests/test_packager.py` 末尾追加：

```python
def test_filenames_accept_pdf_extension():
    from ro_generator.packager import (
        build_document_filename,
        build_invoice_group_document_filename,
        build_invoice_pl_filename,
    )

    assert build_document_filename(
        seller="GS PTE", document_type="INVOICE", po_no="4500030844",
        invoice_no="INV-001", extension="pdf",
    ) == "GS_PTE-GS-INVOICE-4500030844-INV-001.pdf"

    assert build_invoice_pl_filename(
        seller="GS PTE", po_no="4500030844", invoice_no="INV-001", extension="pdf",
    ).endswith(".pdf")

    assert build_invoice_group_document_filename(
        seller="SK", document_type="CI_PL", invoice_no="INV-001", extension="pdf",
    ).endswith(".pdf")

    # 默认仍为 xlsx
    assert build_document_filename(
        seller="GS PTE", document_type="PI", po_no="4500030844",
    ).endswith(".xlsx")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest packages/ro_generator/tests/test_packager.py::test_filenames_accept_pdf_extension -v`
Expected: FAIL — `build_document_filename() got an unexpected keyword argument 'extension'`

- [ ] **Step 3: 实现 extension 参数**

编辑 `packages/ro_generator/src/ro_generator/packager.py`。

`build_document_filename`（改签名与末行）：

```python
def build_document_filename(
    *,
    seller: str,
    document_type: DocumentType,
    po_no: str,
    invoice_no: str | None = None,
    extension: str = "xlsx",
) -> str:
    seller_token = _sanitize(seller)
    po_token = _sanitize(po_no)
    version = "RO" if document_type in ("CI", "RO_PL") else "GS"
    base = f"{seller_token}-{version}-{document_type}-{po_token}"
    if document_type in ("INVOICE", "PL", "CI", "RO_PL") and invoice_no:
        base = f"{base}-{_sanitize(invoice_no)}"
    return f"{base}.{extension}"
```

`build_invoice_pl_filename`：

```python
def build_invoice_pl_filename(
    *,
    seller: str,
    po_no: str,
    invoice_no: str | None = None,
    extension: str = "xlsx",
) -> str:
    seller_token = _sanitize(seller)
    po_token = _sanitize(po_no)
    base = f"{seller_token}-GS-INVOICE&PL-{po_token}"
    if invoice_no:
        base = f"{base}-{_sanitize(invoice_no)}"
    return f"{base}.{extension}"
```

`build_invoice_group_document_filename`（改签名与末行）：

```python
def build_invoice_group_document_filename(
    *,
    seller: str,
    document_type: Literal["INVOICE", "PL", "INVOICE_PL", "CI", "RO_PL", "CI_PL"],
    invoice_no: str,
    extension: str = "xlsx",
) -> str:
    if document_type == "INVOICE_PL":
        document_token = "INVOICE&PL"
        version = "GS"
    elif document_type == "CI_PL":
        document_token = "CI&PL"
        version = "RO"
    elif document_type in ("CI", "RO_PL"):
        document_token = document_type
        version = "RO"
    else:
        document_token = document_type
        version = "GS"
    return f"{_sanitize(seller)}-{version}-{document_token}-{_sanitize(invoice_no)}.{extension}"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest packages/ro_generator/tests/test_packager.py -v`
Expected: PASS（含既有测试全绿）

- [ ] **Step 5: Commit**

```bash
git add packages/ro_generator/src/ro_generator/packager.py packages/ro_generator/tests/test_packager.py
git commit -m "feat(generator): add extension param to filename builders"
```

---

## Task 5: DocumentRequest.output_format 扩展 pdf

**Files:**
- Modify: `packages/ro_generator/src/ro_generator/models.py:187`

- [ ] **Step 1: 修改字段类型**

编辑 `packages/ro_generator/src/ro_generator/models.py:187`：

```python
    output_format: Literal["xlsx", "zip", "pdf"] = "xlsx"
```

- [ ] **Step 2: 验证类型检查通过**

Run: `uv run mypy packages/ro_generator/src/ro_generator/models.py`
Expected: Success（no issues）

- [ ] **Step 3: Commit**

```bash
git add packages/ro_generator/src/ro_generator/models.py
git commit -m "feat(generator): allow output_format='pdf' on DocumentRequest"
```

---

## Task 6: generate() 单文档路径 pdf 分派（_generate_one）

**Files:**
- Modify: `packages/ro_generator/src/ro_generator/generator.py:874-924`（`_generate_one`）
- Test: `packages/ro_generator/tests/test_generator.py`

- [ ] **Step 1: 写失败测试**

在 `packages/ro_generator/tests/test_generator.py` 的 `TestSuccessPath` 类中追加：

```python
    def test_pdf_output_single_document(self, tmp_path):
        path = make_base_file(
            tmp_path, data_base_rows=[COMBO_PRODUCT], po_record_rows=[basic_po_row()]
        )
        request = DocumentRequest(
            base_file=str(path),
            po_no="4500030844",
            documents=("INVOICE",),
            seller="GS PTE",
            invoice_no="INV-001",
            output_format="pdf",
            output_dir=str(tmp_path / "out"),
        )
        result = generate(request)
        assert result.status == "success", result.errors
        assert result.output_file is not None
        assert result.output_file.endswith(".pdf")
        assert Path(result.output_file).exists()
        assert Path(result.output_file).read_bytes()[:4] == b"%PDF"
        # pdf 分支不产生 .xlsx
        assert not list(Path(tmp_path / "out").glob("*.xlsx"))
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest packages/ro_generator/tests/test_generator.py::TestSuccessPath::test_pdf_output_single_document -v`
Expected: FAIL — `output_file` 以 `.xlsx` 结尾（pdf 分派未实现）

- [ ] **Step 3: 实现 pdf 分派**

编辑 `packages/ro_generator/src/ro_generator/generator.py` 的 `_generate_one`。将现有的 filename/render 段（约 897-924 行）替换为：

```python
    is_pdf = request.output_format == "pdf"
    filename = build_document_filename(
        seller=seller,
        document_type=doc_type,
        po_no=po_no,
        invoice_no=invoice_no,
        extension="pdf" if is_pdf else "xlsx",
    )
    output_path = resolve_output_path(
        request.output_dir,
        filename,
        on_conflict=request.on_conflict,
    )

    if is_pdf:
        from ro_generator.document_preview import build_preview
        from ro_generator.pdf_renderer import render_pdf

        preview = build_preview(build)
        pdf_result = render_pdf([preview], output_path)
        return GenerationResult(
            status="success",
            files=(filename,),
            output_file=str(pdf_result.output_path),
            warnings=doc_warnings,
        )

    render_result = render_document(build.model, build.mapping, output_path)

    return GenerationResult(
        status="success",
        files=(filename,),
        output_file=str(render_result.output_path),
        warnings=doc_warnings,
        source_index=render_result.source_index,
        summary={
            "table_start_row": build.mapping.lines.start_row,
            "table_label_row": build.mapping.lines.start_row - 1,
            "style": {
                "bold": list(build.mapping.style.bold),
                "underline": list(build.mapping.style.underline),
            },
        },
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest packages/ro_generator/tests/test_generator.py::TestSuccessPath::test_pdf_output_single_document -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/ro_generator/src/ro_generator/generator.py packages/ro_generator/tests/test_generator.py
git commit -m "feat(generator): dispatch pdf in _generate_one single-doc path"
```

---

## Task 7: generate() 发票+装箱 bundle 路径 pdf 分派（_generate_invoice_pl_bundle）

**Files:**
- Modify: `packages/ro_generator/src/ro_generator/generator.py:947-1003`（`_generate_invoice_pl_bundle`）
- Test: `packages/ro_generator/tests/test_generator.py`

- [ ] **Step 1: 写失败测试**

在 `test_generator.py` 的 `TestSuccessPath` 类中追加（SK 主体 CI+RO_PL 合并为单份 pdf）：

```python
    def test_pdf_output_invoice_pl_bundle(self, tmp_path):
        path = make_base_file(
            tmp_path, data_base_rows=[COMBO_PRODUCT], po_record_rows=[basic_po_row()]
        )
        request = DocumentRequest(
            base_file=str(path),
            po_no="4500030844",
            documents=("INVOICE", "PL"),
            seller="GS PTE",
            invoice_no="INV-001",
            output_format="pdf",
            output_dir=str(tmp_path / "out"),
        )
        result = generate(request)
        assert result.status == "success", result.errors
        assert result.output_file is not None
        assert result.output_file.endswith(".pdf")
        assert Path(result.output_file).read_bytes()[:4] == b"%PDF"
        assert not list(Path(tmp_path / "out").glob("*.xlsx"))
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest packages/ro_generator/tests/test_generator.py::TestSuccessPath::test_pdf_output_invoice_pl_bundle -v`
Expected: FAIL — bundle 仍输出 `.xlsx`

- [ ] **Step 3: 实现 bundle pdf 分派**

编辑 `_generate_invoice_pl_bundle`。将现有 filename/render/return 段（约 976-1003 行）替换为：

```python
    is_pdf = request.output_format == "pdf"
    filename = build_invoice_pl_filename(
        seller=seller,
        po_no=po_no,
        invoice_no=invoice_no,
        extension="pdf" if is_pdf else "xlsx",
    )
    output_path = resolve_output_path(
        request.output_dir,
        filename,
        on_conflict=request.on_conflict,
    )

    if is_pdf:
        from ro_generator.document_preview import build_preview
        from ro_generator.pdf_renderer import render_pdf

        previews = [build_preview(build) for build in builds]
        pdf_result = render_pdf(previews, output_path)
        return GenerationResult(
            status="success",
            files=(filename,),
            output_file=str(pdf_result.output_path),
            warnings=tuple(warnings),
            summary={"combined_documents": combined_documents},
        )

    bundle_items = tuple(
        (build.model, build.mapping)
        for build in builds
        if build.model is not None and build.mapping is not None
    )
    render_result = render_document_bundle(bundle_items, output_path)

    return GenerationResult(
        status="success",
        files=(filename,),
        output_file=str(render_result.output_path),
        warnings=tuple(warnings),
        source_index=render_result.source_index,
        summary={
            "combined_documents": combined_documents,
            "sheets": [build.mapping.sheet for build in builds if build.mapping is not None],
        },
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest packages/ro_generator/tests/test_generator.py::TestSuccessPath::test_pdf_output_invoice_pl_bundle -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/ro_generator/src/ro_generator/generator.py packages/ro_generator/tests/test_generator.py
git commit -m "feat(generator): dispatch pdf in invoice+pl bundle path"
```

---

## Task 8: 发票组导出路径 pdf 分派（export_invoice_group_from_snapshot）

**Files:**
- Modify: `packages/ro_generator/src/ro_generator/generator.py:420-524`（`export_invoice_group_from_snapshot`）
- Test: `packages/ro_generator/tests/test_generator.py`

- [ ] **Step 1: 写失败测试**

在 `test_generator.py` 的 `TestSuccessPath` 类中追加（快照构造照抄 `test_workbook_snapshot.py::TestInvoiceSummary::test_invoice_summary_groups_rows_across_pos` 中已验证可产生一个发票组的写法；seller 从快照动态取，避免硬编码主体）：

```python
    def test_invoice_group_export_pdf(self, tmp_path):
        path = make_base_file(
            tmp_path,
            data_base_rows=[COMBO_PRODUCT],
            po_record_rows=[
                basic_po_row(**{"PO NO.": "PO-1", "INV#": "INV-001"}),
                basic_po_row(
                    **{
                        "PO NO.": "PO-2",
                        "ITEM LINE#": "20",
                        "INV#": "INV-001",
                        "SK/YM INVOICE NO.": None,
                    }
                ),
            ],
            customer_po_rows=[
                {"Purchasing Document": "PO-1", "Material": "21-44640", "Order Quantity": 100},
                {"Purchasing Document": "PO-2", "Material": "21-44640", "Order Quantity": 100},
            ],
        )
        snap = build_workbook_snapshot(path)
        assert snap.invoice_summary, "需要至少一个发票组"
        summary = snap.invoice_summary[0]
        seller = next(iter(summary.seller_invoice_numbers))
        result = export_invoice_group_from_snapshot(
            snap,
            summary.invoice_group_key,
            seller=seller,
            documents=("INVOICE", "PL"),
            output_dir=str(tmp_path / "out"),
            output_format="pdf",
        )
        assert result.status == "success", result.errors
        assert result.output_file is not None
        assert result.output_file.endswith(".pdf")
        assert Path(result.output_file).read_bytes()[:4] == b"%PDF"
```

> `build_workbook_snapshot` 与 `basic_po_row` / `COMBO_PRODUCT` / `make_base_file` 均为 `test_generator.py` 已导入/已定义的符号，无需新增 import。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest packages/ro_generator/tests/test_generator.py::TestSuccessPath::test_invoice_group_export_pdf -v`
Expected: FAIL — `export_invoice_group_from_snapshot() got an unexpected keyword argument 'output_format'`

- [ ] **Step 3: 实现 output_format 参数 + pdf 分派**

编辑 `export_invoice_group_from_snapshot`。

改签名（420-427 行）加 `output_format`：

```python
def export_invoice_group_from_snapshot(
    snapshot: WorkbookSnapshot,
    invoice_group_key: str,
    *,
    seller: str,
    documents: tuple[str, ...],
    output_dir: str,
    output_format: Literal["xlsx", "pdf"] = "xlsx",
) -> GenerationResult:
```

替换渲染段（493-524 行）：

```python
    is_pdf = output_format == "pdf"
    ext = "pdf" if is_pdf else "xlsx"
    rendered_paths: list[Path] = []
    filenames: list[str] = []
    if is_pdf:
        from ro_generator.document_preview import build_preview
        from ro_generator.pdf_renderer import render_pdf

    if set(normalized_documents) in ({"INVOICE", "PL"}, {"CI", "RO_PL"}):
        combined_label: Literal["INVOICE_PL", "CI_PL"] = (
            "CI_PL" if set(normalized_documents) == {"CI", "RO_PL"} else "INVOICE_PL"
        )
        filename = build_invoice_group_document_filename(
            seller=seller,
            document_type=combined_label,
            invoice_no=invoice_no,
            extension=ext,
        )
        output_path = resolve_output_path(output_root, filename)
        if is_pdf:
            previews = [build_preview(build) for build in builds]
            rendered = render_pdf(previews, output_path)
            rendered_paths.append(Path(rendered.output_path))
        else:
            bundle_items = tuple(
                (build.model, build.mapping)
                for build in builds
                if build.model is not None and build.mapping is not None
            )
            rendered_xlsx = render_document_bundle(bundle_items, output_path)
            rendered_paths.append(Path(rendered_xlsx.output_path))
        filenames.append(filename)
    else:
        for document, build in zip(normalized_documents, builds, strict=True):
            filename = build_invoice_group_document_filename(
                seller=seller,
                document_type=cast(Literal["INVOICE", "PL", "CI", "RO_PL"], document),
                invoice_no=invoice_no,
                extension=ext,
            )
            output_path = resolve_output_path(output_root, filename)
            assert build.model is not None and build.mapping is not None
            if is_pdf:
                rendered = render_pdf([build_preview(build)], output_path)
            else:
                rendered = render_document(build.model, build.mapping, output_path)
            rendered_paths.append(Path(rendered.output_path))
            filenames.append(filename)
```

> 注意：多份非合并（如仅 `("INVOICE","PL")` 之外的组合）在 pdf 下仍是每份一个 pdf，最终若 >1 会走既有 `package_zip` 分支打成 zip。预览页单据组只会传合并对（INVOICE+PL / CI+RO_PL）或单份，故正常路径产出单个 pdf。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest packages/ro_generator/tests/test_generator.py::TestSuccessPath::test_invoice_group_export_pdf -v`
Expected: PASS

- [ ] **Step 5: 全量核心包测试 + lint**

Run: `uv run pytest packages/ro_generator -q && uv run ruff check packages/ro_generator && uv run mypy packages/ro_generator/src`
Expected: 全绿

- [ ] **Step 6: Commit**

```bash
git add packages/ro_generator/src/ro_generator/generator.py packages/ro_generator/tests/test_generator.py
git commit -m "feat(generator): dispatch pdf in invoice-group export path"
```

---

## Task 9: API 层透传 output_format + 下载 media type

**Files:**
- Modify: `packages/ro_workbench_api/src/ro_workbench_api/app.py`（`DryRunRequest`、`InvoiceExportRequest`、`_build_document_request`、`export_documents`、`export_invoice_group`、`download_file`）
- Test: `packages/ro_workbench_api/tests/test_app.py`

- [ ] **Step 1: 写失败测试**

在 `packages/ro_workbench_api/tests/test_app.py` 追加（照抄文件内 `test_export_uses_xlsx_output_format` 的模式：module 级 `client`、`FIXTURE`、`_response_json`、`monkeypatch`。关键点：`fake_generate` 把假 PDF 写进 `request.output_dir`——即 session 临时目录，这样 `/api/download` 的路径校验才会放行）：

```python
def test_po_export_pdf_passthrough_and_download(
    monkeypatch: MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_generate(request: DocumentRequest) -> GenerationResult:
        captured["output_format"] = request.output_format
        output = Path(request.output_dir) / "GS-RO-INVOICE-4500099999-INV-001.pdf"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"%PDF-1.4 fake")
        return GenerationResult(
            status="success",
            files=(output.name,),
            output_file=str(output),
        )

    monkeypatch.setattr("ro_workbench_api.app.generate", fake_generate)
    sid = _response_json(client.post("/api/session/open", json={"base_file": str(FIXTURE)}))[
        "session_id"
    ]

    resp = client.post(
        "/api/po/4500099999/export",
        json={
            "base_file": str(FIXTURE),
            "po_no": "4500099999",
            "seller": "GS PTE",
            "invoice_no": "INV-001",
            "documents": ["INVOICE"],
            "output_format": "pdf",
        },
        headers={"X-Session-Id": sid},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert captured["output_format"] == "pdf"
    assert body["output_file"].endswith(".pdf")

    dl = client.get(
        "/api/download",
        params={"path": body["output_file"]},
        headers={"X-Session-Id": sid},
    )
    assert dl.status_code == 200
    assert dl.headers["content-type"] == "application/pdf"
```

> `MonkeyPatch` / `Any` / `Path` / `DocumentRequest` / `GenerationResult` / `_response_json` / `client` / `FIXTURE` 均为 `test_app.py` 已有导入或定义，无需新增。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest packages/ro_workbench_api/tests/test_app.py::test_po_export_pdf_passthrough_and_download -v`
Expected: FAIL — `output_format` 字段不被接受（Pydantic 忽略后 captured 为 "xlsx"）或 download content-type 非 pdf

- [ ] **Step 3: 实现请求模型 + 透传 + media type**

编辑 `packages/ro_workbench_api/src/ro_workbench_api/app.py`：

(a) `DryRunRequest`（194-200 行）末尾加字段：

```python
    output_format: Literal["xlsx", "pdf"] = "xlsx"
```

(b) `InvoiceExportRequest`（208-210 行）末尾加字段：

```python
    output_format: Literal["xlsx", "pdf"] = "xlsx"
```

(c) `_build_document_request`（374-390 行）：形参类型放宽并透传：

```python
def _build_document_request(
    *,
    req: DryRunRequest,
    po_no: str,
    output_dir: str,
    documents: tuple[DocumentType, ...],
    output_format: Literal["xlsx", "zip", "pdf"] = "xlsx",
) -> DocumentRequest:
    return DocumentRequest(
        base_file=req.base_file,
        po_no=po_no,
        documents=documents,
        seller=req.seller,
        invoice_no=req.invoice_no,
        output_format=output_format,
        output_dir=output_dir,
    )
```

(d) `export_documents` 端点（729-735 行）：把硬编码 `output_format="xlsx"` 改为透传：

```python
    request = _build_document_request(
        req=req,
        po_no=po_no,
        documents=documents,
        output_dir=session.temp_dir,
        output_format=req.output_format,
    )
```

(e) `export_invoice_group` 端点（529-535 行）：透传 `output_format`：

```python
    result = export_invoice_group_from_snapshot(
        snapshot,
        invoice_group_key,
        seller=req.seller,
        documents=tuple(req.documents),
        output_dir=session.temp_dir,
        output_format=req.output_format,
    )
```

(f) `download_file` 的 media type（805-809 行）改为：

```python
    suffix = p.suffix.lower()
    if suffix == ".zip":
        media_type = "application/zip"
    elif suffix == ".pdf":
        media_type = "application/pdf"
    else:
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest packages/ro_workbench_api/tests/test_app.py::test_po_export_pdf_and_download -v`
Expected: PASS

- [ ] **Step 5: 全量 API 测试 + lint**

Run: `uv run pytest packages/ro_workbench_api -q && uv run ruff check packages/ro_workbench_api && uv run mypy packages/ro_workbench_api/src`
Expected: 全绿

- [ ] **Step 6: Commit**

```bash
git add packages/ro_workbench_api/src/ro_workbench_api/app.py packages/ro_workbench_api/tests/test_app.py
git commit -m "feat(api): pass through output_format=pdf and serve pdf downloads"
```

---

## Task 10: 前端 API 与 store 支持 output_format

**Files:**
- Modify: `frontend/src/stores/api.ts:96-99`（`DryRunRequest`）、`:251-256`（`exportInvoiceGroup`）
- Modify: `frontend/src/stores/workbench.ts:197-234`（`doExport`）、`:290-311`（`exportOneGroup`），并新增 `doExportPdf` 与导出

- [ ] **Step 1: 扩展 api.ts 类型与调用**

编辑 `frontend/src/stores/api.ts`。

`DryRunRequest` 接口（96-99 行）加字段：

```ts
export interface DryRunRequest {
  base_file: string; po_no: string; seller: string
  invoice_no?: string | null; document?: string; documents?: string[]
  output_format?: "xlsx" | "pdf"
}
```

`exportInvoiceGroup`（251-256 行）加参数并透传：

```ts
  exportInvoiceGroup: (
    invoice_group_key: string,
    seller: string,
    documents: Array<"INVOICE" | "PL" | "CI" | "RO_PL">,
    output_format: "xlsx" | "pdf" = "xlsx",
  ): Promise<DryRunResult> =>
    request("POST", `/invoice/${encodeURIComponent(invoice_group_key)}/export`, { seller, documents, output_format }),
```

- [ ] **Step 2: 扩展 workbench.ts**

编辑 `frontend/src/stores/workbench.ts`。

(a) `doExport` 签名（197 行）加参数：

```ts
  async function doExport(documents?: string[], outputFormat: "xlsx" | "pdf" = "xlsx") {
```

(b) invoice 分支的 `api.exportInvoiceGroup(...)` 调用（213-217 行）传入格式：

```ts
        const result = await api.exportInvoiceGroup(
          selectedInvoiceGroup.value,
          selectedSeller.value,
          invoiceDocuments,
          outputFormat,
        );
```

(c) po 分支的 `exportOneGroup(...)` 调用（227-230 行）传入格式：

```ts
      return await exportOneGroup({
        seller: selectedSeller.value,
        documents: exportDocuments,
      }, outputFormat);
```

(d) `exportOneGroup` 签名与 payload（290-299 行）加格式：

```ts
  async function exportOneGroup(group: ExportGroup, outputFormat: "xlsx" | "pdf" = "xlsx") {
    const exportDocuments = group.documents;
    if (!exportDocuments.length) return;
    try {
      const payload = {
        base_file: baseFile.value, po_no: selectedPo.value,
        seller: group.seller, invoice_no: invoiceNoForSeller(group.seller),
        document: exportDocuments[0], documents: exportDocuments,
        output_format: outputFormat,
      };
```

(e) 在 `doExport` 定义之后新增：

```ts
  async function doExportPdf() {
    return doExport(undefined, "pdf");
  }
```

(f) 在 store 的 `return { ... }` 里，`doExport` 旁边导出 `doExportPdf`。

- [ ] **Step 3: 类型检查**

Run: `cd frontend && pnpm run build`
Expected: vue-tsc 通过，无类型错误。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/stores/api.ts frontend/src/stores/workbench.ts
git commit -m "feat(frontend): thread output_format=pdf through export store actions"
```

---

## Task 11: 预览页新增"导出 PDF"按钮

**Files:**
- Modify: `frontend/src/components/preview/PreviewScreen.vue:72-74`（新增方法）、`:269-276`（新增按钮）

- [ ] **Step 1: 新增方法**

编辑 `frontend/src/components/preview/PreviewScreen.vue`，在 `exportCurrentDocument`（72-74 行）之后新增：

```ts
async function exportCurrentDocumentPdf() {
  await wb.doExportPdf();
}
```

- [ ] **Step 2: 新增按钮**

在现有导出按钮（269-276 行）之后、"查看字段来源"按钮之前，插入：

```vue
          <button
            class="ghost-btn export-btn"
            :disabled="!hasData || wb.exporting || wb.previewLoading"
            @click="exportCurrentDocumentPdf"
            v-if="hasData"
          >
            导出 PDF
          </button>
```

- [ ] **Step 3: 类型检查 + 构建**

Run: `cd frontend && pnpm run build`
Expected: 通过。

- [ ] **Step 4: 手动验证（golden path）**

Run（两个终端）：
```bash
uv run uvicorn ro_workbench_api.app:app --reload --host 127.0.0.1 --port 54321
cd frontend && pnpm run dev
```
在浏览器打开工作台 → 打开 base 文件 → 选 PO `4500030844` → 单据预览 tab → 点"导出 PDF" → 确认下载的 `.pdf` 打开正常、标题/明细/合计/备注齐全、版面与预览页一致。再切到 SK/YM 发票组作用域重复一次，确认 bundle（两节）正常。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/preview/PreviewScreen.vue
git commit -m "feat(frontend): add Export PDF button to preview screen"
```

---

## Task 12: E2E 场景 — 预览页导出 PDF

**Files:**
- Modify: `frontend/e2e/workbench.spec.ts`

- [ ] **Step 1: 看现有导出 E2E 写法**

Run: `grep -n "导出\|export\|download\|waitForEvent" frontend/e2e/workbench.spec.ts`
读懂现有 xlsx 导出场景如何触发下载、如何断言（Playwright `page.waitForEvent('download')`）。

- [ ] **Step 2: 新增 PDF 下载场景**

仿照现有导出场景，在 `workbench.spec.ts` 增加一个测试：进入单据预览 → 点击"导出 PDF" → 捕获 download → 断言文件名以 `.pdf` 结尾。示例（按文件内既有 helper/选择器对齐）：

```ts
test("preview screen exports PDF", async ({ page }) => {
  // <复用现有：打开 base 文件、选 PO、进入单据预览 tab 的步骤>
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "导出 PDF" }).click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/\.pdf$/);
});
```

- [ ] **Step 3: 运行 E2E**

Run: `cd frontend && pnpm run test:e2e`
Expected: 含新场景全绿。

- [ ] **Step 4: Commit**

```bash
git add frontend/e2e/workbench.spec.ts
git commit -m "test(frontend): e2e for preview PDF export"
```

---

## Task 13: 全量回归 + 收尾

- [ ] **Step 1: 后端全量测试 + lint**

Run: `uv run pytest packages/ -q && uv run ruff check . && uv run ruff format --check . && uv run mypy packages`
Expected: 全绿。若 `ruff format --check` 报本计划新增/修改文件未格式化，运行 `uv run ruff format <file>` 后重跑并纳入相应 commit。

- [ ] **Step 2: 前端构建 + E2E**

Run: `cd frontend && pnpm run build && pnpm run test:e2e`
Expected: 全绿。

- [ ] **Step 3: 确认无残留**

Run: `git status`
Expected: 干净（仅 `.gitignore` 已忽略的 `tests/fixtures/synthetic_base.xlsx` 可存在）。
