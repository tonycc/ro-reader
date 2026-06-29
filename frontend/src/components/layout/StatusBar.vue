<script setup lang="ts">
import { useWorkbench } from "../../stores/workbench";
import { computed } from "vue";

const wb = useWorkbench();
const currentStatus = computed(() => wb.previewScope === "invoice" ? wb.invoiceStatus : wb.poStatus);
const hasSelection = computed(() => wb.previewScope === "invoice"
  ? Boolean(wb.selectedInvoiceGroup)
  : Boolean(wb.selectedPo));

const statusColor = computed(() => {
  if (!hasSelection.value) return "var(--muted)";
  if (currentStatus.value === "ready") return "var(--green)";
  if (currentStatus.value === "partial") return "var(--amber)";
  return "var(--red)";
});
</script>

<template>
  <footer class="statusbar">
    <span>
      <span class="dot" :style="{ background: statusColor }" />
      {{ hasSelection ? (currentStatus === 'ready' ? '就绪' : currentStatus === 'partial' ? '待补全' : '阻断') : '未选择' }}
      <template v-if="hasSelection"> · {{ wb.blockingErrors.length }} blocking · {{ wb.warnings.length }} warnings</template>
    </span>
    <span v-if="wb.lastExportFile">已导出: {{ wb.lastExportFile.split("/").pop() }}</span>
    <span>Local service :54321</span>
  </footer>
</template>

<style scoped>
.statusbar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 14px;
  border-top: 1px solid var(--line);
  background: #ffffff;
  color: var(--muted);
  font-size: 12px;
}
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 999px; margin-right: 6px; }
</style>
