<script setup lang="ts">
import { useWorkbench } from "../../stores/workbench";
const wb = useWorkbench();
</script>

<template>
  <footer class="statusbar">
    <span class="status-dot" :class="wb.poStatus">●</span>
    <span v-if="wb.poStatus">{{ wb.poStatus }} </span>
    <span v-if="wb.selectedPo">PO {{ wb.selectedPo }} </span>
    <span v-if="wb.selectedSeller">{{ wb.selectedSeller }} </span>
    <span v-if="wb.selectedMonth">/ {{ wb.selectedMonth }}</span>
    <span v-if="wb.warnings.length" class="warn-count"> · {{ wb.warnings.length }} 项待补全</span>
    <span v-if="wb.blockingErrors.length" class="err-count"> · {{ wb.blockingErrors.length }} 阻断</span>
    <span v-if="wb.lastExportFile" class="exported"> · 已导出: {{ wb.lastExportFile.split('/').pop() }}</span>
  </footer>
</template>

<style scoped>
.statusbar { display: flex; align-items: center; height: 28px; padding: 0 var(--space-4); background: var(--surface-sunken); border-top: 1px solid var(--border-default); font-size: var(--text-xs); color: var(--fg-muted); gap: var(--space-1); flex-shrink: 0; }
.status-dot { font-size: 8px; }
.status-dot.ready { color: var(--status-ready-fg); }
.status-dot.partial { color: var(--status-partial-fg); }
.status-dot.blocked { color: var(--status-blocked-fg); }
.err-count { color: var(--status-blocked-fg); }
.warn-count { color: var(--status-partial-fg); }
.exported { color: var(--fg-subtle); }
</style>
