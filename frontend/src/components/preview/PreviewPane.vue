<script setup lang="ts">
import { ref, watch } from "vue";
import { useWorkbench } from "../../stores/workbench";
import { read, utils } from "xlsx";

const wb = useWorkbench();
const previewTab = ref<"INVOICE" | "PI" | "PO" | "PL">("INVOICE");
const zoom = ref(100);

interface CellData { value: string; colspan: number; rowspan: number; cellRef: string; isNum: boolean }
interface RowData { cells: CellData[]; rowNum: number; isLabel?: boolean }
const headerRows = ref<RowData[]>([]);
const dataRows = ref<RowData[]>([]);
const styleBold = ref<string[]>([]);
const styleUnderline = ref<string[]>([]);
const tableStartRow = ref(99);
const statusMsg = ref("");
const hoveredCell = ref("");
const hoverSource = ref<string>("");

const tabs = [
  { key: "PI" as const, label: "PI" },
  { key: "PO" as const, label: "PO" },
  { key: "INVOICE" as const, label: "Invoice" },
  { key: "PL" as const, label: "PL" },
];

function switchTab(key: typeof previewTab.value) { previewTab.value = key; wb.refreshPreview(key); }

function parseSheet(ws: Record<string, unknown>): RowData[] {
  const range = utils.decode_range((ws["!ref"] as string) || "A1");
  const merges = (ws["!merges"] || []) as { s: { r: number; c: number }; e: { r: number; c: number } }[];

  const mergedHidden = new Set<string>();
  for (const m of merges) {
    for (let r = m.s.r; r <= m.e.r; r++)
      for (let c = m.s.c; c <= m.e.c; c++)
        if (r !== m.s.r || c !== m.s.c) mergedHidden.add(`${r},${c}`);
  }

  const nonBlankRows = new Set<number>();
  for (let r = range.s.r; r <= range.e.r; r++) {
    for (let c = range.s.c; c <= range.e.c; c++) {
      const cell = ws[utils.encode_cell({ r, c })] as { v?: unknown } | undefined;
      if (cell?.v != null && cell.v !== "") { nonBlankRows.add(r); break; }
    }
  }

  const rows: RowData[] = [];
  for (let r = range.s.r; r <= range.e.r; r++) {
    if (!nonBlankRows.has(r)) continue;
    const cells: CellData[] = [];
    for (let c = range.s.c; c <= range.e.c; c++) {
      if (mergedHidden.has(`${r},${c}`)) continue;
      const cell = ws[utils.encode_cell({ r, c })] as { v?: unknown; t?: string } | undefined;
      const value = cell?.v != null ? String(cell.v) : "";
      const merge = merges.find((m) => m.s.r === r && m.s.c === c);
      const isNum = cell?.t === "n" || (value !== "" && !isNaN(Number(value)));
      cells.push({
        value,
        colspan: merge ? merge.e.c - merge.s.c + 1 : 1,
        rowspan: merge ? merge.e.r - merge.s.r + 1 : 1,
        cellRef: utils.encode_cell({ r, c }),
        isNum,
      });
    }
    rows.push({ cells, rowNum: r + 1 });
  }
  return rows;
}

function onCellEnter(cellRef: string) {
  hoveredCell.value = cellRef;
  const entry = wb.sourceIndex.find((s) => s.doc_cell === cellRef);
  hoverSource.value = entry
    ? `${entry.source.sheet} · ${entry.source.field}` + (entry.source.row ? ` row ${entry.source.row}` : "")
    : "";
}

function onCellLeave() { hoveredCell.value = ""; hoverSource.value = ""; }
function headerCellClass(cellRef: string): string {
  const cls: string[] = [];
  if (styleBold.value.includes(cellRef)) cls.push("bold");
  if (styleUnderline.value.includes(cellRef)) cls.push("underline");
  return cls.join(" ");
}

watch(
  () => wb.preview,
  async (result) => {
    headerRows.value = [];
    dataRows.value = [];
    tableStartRow.value = (result?.summary?.table_start_row as number) || 99;
    styleBold.value = ((result as any)?.style?.bold as string[]) || [];
    styleUnderline.value = ((result as any)?.style?.underline as string[]) || [];
    if (!result?.output_file) {
      if (result?.status === "needs_input") statusMsg.value = `请选择 ${result.missing_inputs?.join("、") || "..."}`;
      else if (result?.status === "error") {
        const err = (result.errors?.[0] as any) || {};
        if (err.code === "MAPPING_NOT_FOUND" && (wb.selectedSeller?.includes("SK") || wb.selectedSeller?.includes("YM")))
          statusMsg.value = `${wb.selectedSeller || "该主体"}不提供 PO 模板`;
        else statusMsg.value = `生成失败：${err.code || "..."}`;
      }
      return;
    }
    statusMsg.value = "";
    try {
      const resp = await fetch(`http://127.0.0.1:54321/download?path=${encodeURIComponent(result.output_file)}`);
      if (!resp.ok) { statusMsg.value = `下载失败 HTTP ${resp.status}`; return; }
      const buf = await resp.arrayBuffer();
      const wb = read(new Uint8Array(buf), { type: "array", cellStyles: true });
      const ws = wb.Sheets[wb.SheetNames[0]];
      if (!ws) { statusMsg.value = "无法读取 sheet"; return; }
      const allRows = parseSheet(ws as Record<string, unknown>);
      const splitAt = (result?.summary?.table_label_row as number) || (result?.summary?.table_start_row as number) || 99;
      headerRows.value = allRows.filter((r) => r.rowNum < splitAt);
      dataRows.value = allRows.filter((r) => r.rowNum >= splitAt);
      // Mark first data row as label
      if (dataRows.value.length) dataRows.value[0] = { ...dataRows.value[0], isLabel: true } as RowData;
    } catch (e) { statusMsg.value = `加载失败: ${String(e).substring(0, 80)}`; }
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
      <button v-for="t in tabs" :key="t.key" class="tab-btn"
        :class="{ active: previewTab === t.key }" @click="switchTab(t.key)">{{ t.label }}</button>
      <span class="zoom-control">
        <button class="zoom-btn" @click="zoom = Math.max(50, zoom - 10)" :disabled="zoom <= 50">−</button>
        <span class="zoom-label">{{ zoom }}%</span>
        <button class="zoom-btn" @click="zoom = Math.min(150, zoom + 10)" :disabled="zoom >= 150">+</button>
      </span>
    </div>

    <div class="preview-body">
      <div v-if="!wb.selectedPo" class="placeholder">选择 PO 后自动预览</div>
      <div v-else-if="statusMsg" class="status-msg" :class="{ err: statusMsg.includes('失败') || statusMsg.includes('不提供') }">{{ statusMsg }}</div>
      <div v-else-if="!headerRows.length && !dataRows.length" class="placeholder">加载预览中…</div>
      <template v-else>
        <!-- 表头区域 -->
        <div class="preview-header" :style="{ transform: `scale(${zoom / 100})`, transformOrigin: 'top left' }">
          <table class="header-table">
            <tr v-for="(row, ri) in headerRows" :key="'h'+ri">
              <td v-for="(cell, ci) in row.cells" :key="ci"
                :class="headerCellClass(cell.cellRef)"
                :colspan="cell.colspan" :rowspan="cell.rowspan"
              >{{ cell.value }}</td>
            </tr>
          </table>
        </div>
        <!-- 表格区域 -->
        <table v-if="dataRows.length" class="preview-table" :style="{ transform: `scale(${zoom / 100})`, transformOrigin: 'top left' }">
          <tr v-for="(row, ri) in dataRows" :key="'d'+ri" :class="{ 'label-row': row.isLabel }">
            <td v-for="(cell, ci) in row.cells" :key="ci"
              :class="{ num: cell.isNum }"
              :colspan="cell.colspan" :rowspan="cell.rowspan"
              @mouseenter="onCellEnter(cell.cellRef)" @mouseleave="onCellLeave"
            >{{ cell.value }}</td>
          </tr>
        </table>
      </template>
    </div>
    <div v-if="hoverSource" class="tooltip">{{ hoverSource }} · {{ hoveredCell }}</div>
  </div>
</template>

<style scoped>
.preview-pane { display: flex; flex-direction: column; height: 100%; }

.preview-toolbar { padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--border-default); background: var(--surface-sunken); display: flex; align-items: center; gap: var(--space-4); }
.seller-group, .month-group { display: flex; align-items: center; gap: var(--space-1); }
.label { color: var(--fg-muted); font-size: var(--text-xs); white-space: nowrap; width: 32px; flex-shrink: 0; }
.sel-btn { padding: 2px var(--space-2); border: 1px solid var(--border-default); border-radius: var(--radius-md); background: var(--surface-default); cursor: pointer; font-size: var(--text-xs); color: var(--fg-muted); }
.sel-btn.active { background: var(--accent-subtle); border-color: var(--accent-default); color: var(--accent-default); font-weight: 600; }
.sel-btn:hover { border-color: var(--accent-default); }
.sel-btn.mono { font-family: var(--font-mono); }
.clear { cursor: pointer; font-size: var(--text-xs); color: var(--accent-default); }
.hint { font-size: var(--text-xs); color: var(--fg-subtle); }

.tab-bar { display: flex; align-items: center; border-bottom: 1px solid var(--border-default); padding: 0 var(--space-2); gap: var(--space-1); }
.tab-btn { padding: var(--space-2) var(--space-3); border: none; border-bottom: 2px solid transparent; background: none; cursor: pointer; font-size: var(--text-sm); color: var(--fg-muted); }
.tab-btn.active { border-bottom-color: var(--accent-default); color: var(--accent-default); font-weight: 600; }
.tab-btn:hover { color: var(--fg-default); }

.zoom-control { margin-left: auto; display: flex; align-items: center; gap: 2px; padding-right: var(--space-2); }
.zoom-btn { width: 22px; height: 22px; border: 1px solid var(--border-default); border-radius: var(--radius-sm); background: var(--surface-default); cursor: pointer; font-size: 13px; line-height: 1; color: var(--fg-muted); display: flex; align-items: center; justify-content: center; }
.zoom-btn:disabled { opacity: 0.3; cursor: not-allowed; }
.zoom-label { font-size: var(--text-xs); color: var(--fg-muted); width: 36px; text-align: center; font-family: var(--font-mono); }

.preview-body { flex: 1; overflow: auto; padding: var(--space-2); }
.status-msg { padding: var(--space-3); color: var(--status-partial-fg); }
.status-msg.err { color: var(--status-blocked-fg); }
.placeholder { padding: var(--space-8); text-align: center; color: var(--fg-subtle); }

.preview-header { margin-bottom: var(--space-3); }
.header-table { border-collapse: collapse; font-size: var(--text-sm); font-family: var(--font-sans); }
.header-table td { padding: 2px 6px; vertical-align: middle; white-space: nowrap; }
.header-table td.bold { font-weight: 600; }
.header-table td.underline { border-bottom: 1.5px solid var(--accent-default); }

.preview-table {
  border-collapse: separate; border-spacing: 0;
  width: max-content; min-width: 100%;
  font-size: var(--text-sm); font-family: var(--font-sans);
  background: var(--surface-default);
  border: 1px solid var(--border-default); border-radius: var(--radius-md);
  overflow: hidden;
}
.preview-table td {
  padding: 6px 12px; vertical-align: middle; white-space: nowrap;
  border-bottom: 1px solid var(--border-default);
  min-width: 50px; max-width: 280px;
  overflow: hidden; text-overflow: ellipsis;
}
.preview-table td.num { text-align: right; font-family: var(--font-mono); font-size: 0.85em; }
.preview-table .label-row td {
  font-weight: 600; color: var(--fg-muted); font-size: var(--text-xs);
  border-bottom: 2px solid var(--border-strong); background: var(--surface-sunken);
  position: sticky; top: 0; z-index: 1;
}
.preview-table .label-row td:empty { background: transparent; }
.preview-table tr:nth-child(even):not(.label-row) td { background: #fafbfc; }
.preview-table tr:hover td { background: var(--accent-subtle) !important; }
.preview-table tr:last-child td { border-bottom: none; }

.tooltip { position: fixed; bottom: 32px; right: 16px; padding: var(--space-1) var(--space-2); background: var(--fg-default); color: var(--fg-on-accent); font-size: var(--text-xs); border-radius: var(--radius-sm); max-width: 320px; z-index: 100; }
</style>
