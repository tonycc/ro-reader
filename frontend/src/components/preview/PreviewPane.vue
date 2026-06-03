<script setup lang="ts">
import { ref, watch } from "vue";
import { useWorkbench } from "../../stores/workbench";
import { read, utils } from "xlsx";

const wb = useWorkbench();
const previewTab = ref<"INVOICE" | "PI" | "PO" | "PL">("INVOICE");
const htmlContent = ref("");
const hoveredCell = ref("");
const hoverSource = ref<string>("");
const zoom = ref(100); // 50–150

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

function onCellHover(e: MouseEvent) {
  const el = e.target as HTMLElement;
  const id = el.id || "";
  hoveredCell.value = id;
  if (id && wb.sourceIndex.length) {
    const entry = wb.sourceIndex.find((s) => s.doc_cell === id.replace("sjs-", ""));
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
    if (!result?.output_file) { htmlContent.value = ""; return; }
    try {
      const resp = await fetch(`http://127.0.0.1:54321/download?path=${encodeURIComponent(result.output_file)}`);
      const buf = await resp.arrayBuffer();
      const workbook = read(new Uint8Array(buf), { type: "array", cellStyles: true });
      const ws = workbook.Sheets[workbook.SheetNames[0]];
      if (!ws) { htmlContent.value = "<p>无法读取 sheet</p>"; return; }
      htmlContent.value = utils.sheet_to_html(ws, { editable: false });
    } catch {
      htmlContent.value = "<p>加载预览失败</p>";
    }
  },
  { immediate: true }
);
</script>

<template>
  <div class="preview-pane">
    <div class="tab-bar">
      <button
        v-for="tab in tabs" :key="tab.key"
        class="tab-btn" :class="{ active: previewTab === tab.key }"
        @click="switchTab(tab.key)"
      >{{ tab.label }}</button>
      <span class="zoom-control">
        <button class="zoom-btn" @click="zoom = Math.max(50, zoom - 10)" :disabled="zoom <= 50">−</button>
        <span class="zoom-label">{{ zoom }}%</span>
        <button class="zoom-btn" @click="zoom = Math.min(150, zoom + 10)" :disabled="zoom >= 150">+</button>
      </span>
    </div>
    <div class="preview-body" @mouseover="onCellHover">
      <div v-if="!wb.selectedPo" class="placeholder">选择 PO 后自动预览</div>
      <div v-else-if="!htmlContent" class="placeholder">加载预览中…</div>
      <div v-else class="html-preview" :style="{ transform: `scale(${zoom / 100})`, transformOrigin: 'top left' }" v-html="htmlContent"></div>
    </div>
    <div v-if="hoverSource" class="tooltip">{{ hoverSource }} · {{ hoveredCell }}</div>
  </div>
</template>

<style scoped>
.preview-pane { display: flex; flex-direction: column; height: 100%; }

.tab-bar { display: flex; align-items: center; border-bottom: 1px solid var(--border-default); padding: 0 var(--space-2); gap: var(--space-1); }
.tab-btn { padding: var(--space-2) var(--space-3); border: none; border-bottom: 2px solid transparent; background: none; cursor: pointer; font-size: var(--text-sm); color: var(--fg-muted); }
.tab-btn.active { border-bottom-color: var(--accent-default); color: var(--accent-default); font-weight: 600; }
.tab-btn:hover { color: var(--fg-default); }

.zoom-control { margin-left: auto; display: flex; align-items: center; gap: 2px; padding-right: var(--space-2); }
.zoom-btn { width: 22px; height: 22px; border: 1px solid var(--border-default); border-radius: var(--radius-sm); background: var(--surface-default); cursor: pointer; font-size: 13px; line-height: 1; color: var(--fg-muted); display: flex; align-items: center; justify-content: center; }
.zoom-btn:disabled { opacity: 0.3; cursor: not-allowed; }
.zoom-btn:hover:not(:disabled) { border-color: var(--accent-default); color: var(--accent-default); }
.zoom-label { font-size: var(--text-xs); color: var(--fg-muted); width: 36px; text-align: center; font-family: var(--font-mono); }

.preview-body { flex: 1; overflow: auto; padding: var(--space-2); }
.html-preview { display: inline-block; min-width: 100%; }
.html-preview :deep(table) { border-collapse: collapse; font-size: var(--text-xs); }
.html-preview :deep(td) { border: 1px solid var(--border-default); padding: 1px 3px; }
.placeholder { padding: var(--space-8); text-align: center; color: var(--fg-subtle); }

.tooltip { position: fixed; bottom: 32px; right: 16px; padding: var(--space-1) var(--space-2); background: var(--fg-default); color: var(--fg-on-accent); font-size: var(--text-xs); border-radius: var(--radius-sm); max-width: 320px; z-index: 100; }
</style>
