<script setup lang="ts">
import { ref, watch } from "vue";
import { useWorkbench } from "../../stores/workbench";
import { read, utils } from "xlsx";

const wb = useWorkbench();
const previewTab = ref<"INVOICE" | "PI" | "PO" | "PL">("INVOICE");
const htmlContent = ref("");
const hoveredCell = ref("");
const hoverSource = ref<string>("");
const zoom = ref(100);

const tabs: { key: typeof previewTab.value; label: string }[] = [
  { key: "PI", label: "PI" },
  { key: "PO", label: "PO" },
  { key: "INVOICE", label: "Invoice" },
  { key: "PL", label: "PL" },
];

function switchTab(key: typeof previewTab.value) {
  previewTab.value = key;
  wb.refreshPreview(key);
}

/** 把 SheetJS worksheet 转成自定义 HTML table */
function buildTableHtml(ws: Record<string, unknown>): string {
  const range = utils.decode_range((ws["!ref"] as string) || "A1");
  const merges = (ws["!merges"] || []) as { s: { r: number; c: number }; e: { r: number; c: number } }[];

  // 标记哪些单元格是合并区域的"被吞掉"的格子
  const mergedHidden = new Set<string>();
  for (const m of merges) {
    for (let r = m.s.r; r <= m.e.r; r++) {
      for (let c = m.s.c; c <= m.e.c; c++) {
        if (r !== m.s.r || c !== m.s.c) {
          mergedHidden.add(`${r},${c}`);
        }
      }
    }
  }

  // 收集非空行
  const nonBlankRows = new Set<number>();
  for (let r = range.s.r; r <= range.e.r; r++) {
    for (let c = range.s.c; c <= range.e.c; c++) {
      const cell = ws[utils.encode_cell({ r, c })] as { v?: unknown } | undefined;
      if (cell && cell.v != null && cell.v !== "") { nonBlankRows.add(r); break; }
    }
  }

  let html = '<table class="preview-table">';
  let rowIdx = 0;
  for (let r = range.s.r; r <= range.e.r; r++) {
    if (!nonBlankRows.has(r)) continue;
    // 第一个非空行 = 字段标签行
    const isLabel = rowIdx === 0;
    rowIdx++;
    html += `<tr class="${isLabel ? "label-row" : ""}">`;
    for (let c = range.s.c; c <= range.e.c; c++) {
      const key = `${r},${c}`;
      if (mergedHidden.has(key)) continue;

      const cell = ws[utils.encode_cell({ r, c })] as { v?: unknown; t?: string } | undefined;
      const value = cell?.v != null ? String(cell.v) : "";

      // 合并单元格的 span
      const merge = merges.find((m) => m.s.r === r && m.s.c === c);
      const rowspan = merge ? merge.e.r - merge.s.r + 1 : 1;
      const colspan = merge ? merge.e.c - merge.s.c + 1 : 1;

      const cellId = `cell-${utils.encode_cell({ r, c })}`;

      // 数值类型 → 右对齐 + mono 字体
      const isNum = cell?.t === "n" || (!isNaN(Number(value)) && value !== "");
      // 字段标签行（header 区域，未有溯源数据的行）→ 加粗
      const cls = isNum ? "num" : "";

      let attrs = `id="${cellId}" class="${cls}"`;
      if (colspan > 1) attrs += ` colspan="${colspan}"`;
      if (rowspan > 1) attrs += ` rowspan="${rowspan}"`;

      html += `<td ${attrs}>${value}</td>`;
    }
    html += "</tr>";
  }
  html += "</table>";
  return html;
}

function onCellHover(e: MouseEvent) {
  const el = e.target as HTMLElement;
  const id = el.id || "";
  hoveredCell.value = id;
  if (id && wb.sourceIndex.length) {
    const cellRef = id.replace("cell-", "");
    const entry = wb.sourceIndex.find((s) => s.doc_cell === cellRef);
    if (entry) {
      hoverSource.value = `${entry.source.sheet} · ${entry.source.field}` + (entry.source.row ? ` row ${entry.source.row}` : "");
      return;
    }
  }
  hoverSource.value = "";
}

watch(
  () => wb.preview,
  async (result) => {
    if (!result?.output_file) {
      if (result?.status === "needs_input") {
        htmlContent.value = `<p class="preview-msg warn">请选择 ${result.missing_inputs?.join("、") || "..."}</p>`;
      } else if (result?.status === "error") {
        const err = (result.errors?.[0] as any) || {};
        const code = err.code || "...";
        if (code === "MAPPING_NOT_FOUND" && (wb.selectedSeller?.includes("SK") || wb.selectedSeller?.includes("YM"))) {
          htmlContent.value = `<p class="preview-msg warn">${wb.selectedSeller || "该主体"}不提供 PO 模板<br>请切换到 GS PTE 或 EMAX PTE</p>`;
        } else {
          htmlContent.value = `<p class="preview-msg err">生成失败：${code}<br>${err.message || ""}</p>`;
        }
      } else {
        htmlContent.value = "";
      }
      return;
    }
    try {
      const resp = await fetch(`http://127.0.0.1:54321/download?path=${encodeURIComponent(result.output_file)}`);
      if (!resp.ok) { htmlContent.value = `<p>下载失败 HTTP ${resp.status}</p>`; return; }
      const buf = await resp.arrayBuffer();
      const workbook = read(new Uint8Array(buf), { type: "array", cellStyles: true });
      const ws = workbook.Sheets[workbook.SheetNames[0]];
      if (!ws) { htmlContent.value = "<p>无法读取 sheet</p>"; return; }
      htmlContent.value = buildTableHtml(ws as Record<string, unknown>);
    } catch (e) {
      htmlContent.value = `<p>加载预览失败: ${String(e).substring(0, 80)}</p>`;
    }
  },
  { immediate: true }
);
</script>

<template>
  <div class="preview-pane">
    <div class="preview-toolbar">
      <div class="seller-group">
        <span class="label">主体:</span>
        <button v-for="s in wb.poEntry?.sellers ?? []" :key="s" class="sel-btn"
          :class="{ active: wb.selectedSeller === s }" @click="wb.selectSeller(s)">{{ s }}</button>
        <span v-if="!wb.selectedPo" class="hint">选择 PO</span>
      </div>
      <div class="month-group">
        <span class="label">月份:</span>
        <template v-if="wb.poEntry?.monthly_months?.length">
          <button v-for="m in wb.poEntry!.monthly_months" :key="m" class="sel-btn mono"
            :class="{ active: wb.selectedMonth === m }" @click="wb.selectMonth(wb.selectedMonth === m ? null : m)">{{ m }}</button>
          <span v-if="wb.selectedMonth" class="clear" @click="wb.selectMonth(null)">清除</span>
        </template>
        <span v-else class="hint">无月度数据</span>
      </div>
    </div>

    <div class="tab-bar">
      <button v-for="tab in tabs" :key="tab.key" class="tab-btn"
        :class="{ active: previewTab === tab.key }" @click="switchTab(tab.key)">{{ tab.label }}</button>
      <span class="zoom-control">
        <button class="zoom-btn" @click="zoom = Math.max(50, zoom - 10)" :disabled="zoom <= 50">−</button>
        <span class="zoom-label">{{ zoom }}%</span>
        <button class="zoom-btn" @click="zoom = Math.min(150, zoom + 10)" :disabled="zoom >= 150">+</button>
      </span>
    </div>

    <div class="preview-body" @mouseover="onCellHover">
      <div v-if="!wb.selectedPo" class="placeholder">选择 PO 后自动预览</div>
      <div v-else-if="!htmlContent" class="placeholder">加载预览中…</div>
      <div v-else class="html-preview"
        :style="{ transform: `scale(${zoom / 100})`, transformOrigin: 'top left' }"
        v-html="htmlContent"></div>
    </div>
    <div v-if="hoverSource" class="tooltip">{{ hoverSource }} · {{ hoveredCell }}</div>
  </div>
</template>

<style scoped>
.preview-pane { display: flex; flex-direction: column; height: 100%; }

/* toolbar */
.preview-toolbar { padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--border-default); background: var(--surface-sunken); display: flex; align-items: center; gap: var(--space-4); }
.seller-group, .month-group { display: flex; align-items: center; gap: var(--space-1); }
.label { color: var(--fg-muted); font-size: var(--text-xs); white-space: nowrap; width: 32px; flex-shrink: 0; }
.sel-btn { padding: 2px var(--space-2); border: 1px solid var(--border-default); border-radius: var(--radius-md); background: var(--surface-default); cursor: pointer; font-size: var(--text-xs); color: var(--fg-muted); }
.sel-btn.active { background: var(--accent-subtle); border-color: var(--accent-default); color: var(--accent-default); font-weight: 600; }
.sel-btn:hover { border-color: var(--accent-default); }
.sel-btn.mono { font-family: var(--font-mono); }
.clear { cursor: pointer; font-size: var(--text-xs); color: var(--accent-default); }
.hint { font-size: var(--text-xs); color: var(--fg-subtle); }

/* tabs */
.tab-bar { display: flex; align-items: center; border-bottom: 1px solid var(--border-default); padding: 0 var(--space-2); gap: var(--space-1); }
.tab-btn { padding: var(--space-2) var(--space-3); border: none; border-bottom: 2px solid transparent; background: none; cursor: pointer; font-size: var(--text-sm); color: var(--fg-muted); }
.tab-btn.active { border-bottom-color: var(--accent-default); color: var(--accent-default); font-weight: 600; }
.tab-btn:hover { color: var(--fg-default); }

.zoom-control { margin-left: auto; display: flex; align-items: center; gap: 2px; padding-right: var(--space-2); }
.zoom-btn { width: 22px; height: 22px; border: 1px solid var(--border-default); border-radius: var(--radius-sm); background: var(--surface-default); cursor: pointer; font-size: 13px; line-height: 1; color: var(--fg-muted); display: flex; align-items: center; justify-content: center; }
.zoom-btn:disabled { opacity: 0.3; cursor: not-allowed; }
.zoom-label { font-size: var(--text-xs); color: var(--fg-muted); width: 36px; text-align: center; font-family: var(--font-mono); }

/* content */
.preview-body { flex: 1; overflow: auto; padding: var(--space-2); }
.html-preview { display: inline-block; min-width: 100%; }

/* custom table */
.html-preview :deep(.preview-table) {
  border-collapse: collapse; width: max-content; min-width: 100%;
  font-size: var(--text-sm); font-family: var(--font-sans);
  background: var(--surface-default);
}
.html-preview :deep(.preview-table td) {
  padding: 5px 10px; border-bottom: 1px solid var(--border-default);
  vertical-align: middle; white-space: nowrap; min-width: 60px;
}
.html-preview :deep(.preview-table .num) {
  text-align: right; font-family: var(--font-mono);
}
.html-preview :deep(.preview-table .label-row td) {
  font-weight: 600; color: var(--fg-default); font-size: var(--text-xs);
  text-transform: uppercase; letter-spacing: 0.02em;
  border-bottom: 2px solid var(--border-strong); background: var(--surface-sunken);
}
.html-preview :deep(.preview-table .label-row td:empty) {
  background: transparent;
}
.html-preview :deep(.preview-table tr:hover td) { background: var(--surface-sunken); }
.html-preview :deep(.preview-table .label-row:hover td) { background: var(--surface-sunken); }

.preview-msg { padding: var(--space-3); margin: 0; }
.preview-msg.warn { color: var(--status-partial-fg); }
.preview-msg.err { color: var(--status-blocked-fg); }
.placeholder { padding: var(--space-8); text-align: center; color: var(--fg-subtle); }

.tooltip { position: fixed; bottom: 32px; right: 16px; padding: var(--space-1) var(--space-2); background: var(--fg-default); color: var(--fg-on-accent); font-size: var(--text-xs); border-radius: var(--radius-sm); max-width: 320px; z-index: 100; }
</style>
