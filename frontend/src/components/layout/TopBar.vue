<script setup lang="ts">
import { useWorkbench } from "../../stores/workbench";
const wb = useWorkbench();

function handleOpen() {
  const path = prompt("base 文件路径:")?.trim();
  if (path) wb.openSession(path);
}
</script>

<template>
  <header class="topbar">
    <div class="left">
      <span class="file-status" :class="wb.loading ? 'loading' : wb.error ? 'error' : 'ok'">●</span>
      <span class="filename" @click="handleOpen">
        {{ wb.baseFile ? wb.baseFile.split("/").pop() : "点击打开 base 文件…" }}
      </span>
    </div>
    <div class="right">
      <button class="btn-export" :disabled="!wb.selectedPo || wb.exporting" @click="wb.doExport()">
        {{ wb.exporting ? "导出中…" : "导出 ⌘E" }}
      </button>
    </div>
  </header>
</template>

<style scoped>
.topbar { display: flex; align-items: center; justify-content: space-between; height: 48px; padding: 0 var(--space-4); background: var(--surface-default); border-bottom: 1px solid var(--border-default); flex-shrink: 0; }
.left { display: flex; align-items: center; gap: var(--space-2); }
.file-status { font-size: 10px; }
.file-status.ok { color: var(--status-ready-fg); }
.file-status.loading { color: var(--accent-default); animation: pulse 1s infinite; }
.file-status.error { color: var(--status-blocked-fg); }
.filename { cursor: pointer; color: var(--accent-default); font-size: var(--text-md); }
.filename:hover { text-decoration: underline; }
.btn-export { padding: var(--space-1) var(--space-3); background: var(--accent-default); color: var(--fg-on-accent); border: none; border-radius: var(--radius-md); cursor: pointer; font-size: var(--text-sm); }
.btn-export:disabled { opacity: 0.5; cursor: not-allowed; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
</style>
