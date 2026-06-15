<script setup lang="ts">
import { ref } from "vue";
import { useWorkbench } from "../../stores/workbench";

const wb = useWorkbench();
const selectedDocs = ref<Set<string>>(new Set(["PI", "PO", "INVOICE", "PL"]));

const docLabels: Record<string, string> = {
  PI: "形式发票（PI）",
  PO: "采购订单（PO）",
  INVOICE: "商业发票（CI）",
  PL: "装箱单（PL）",
};

function toggleDoc(key: string) {
  const next = new Set(selectedDocs.value);
  if (next.has(key)) next.delete(key); else next.add(key);
  selectedDocs.value = next;
}

async function handleExport() {
  await wb.doExport();
}
</script>

<template>
  <div class="export-screen">
    <div v-if="!wb.selectedPo" class="placeholder">选择左侧 PO 开始导出</div>
    <div v-else class="export-grid">
      <div class="export-card">
        <h3>导出内容确认</h3>
        <div class="check-line" v-for="(label, key) in docLabels" :key="key">
          <div>
            <b>{{ label }}</b><br>
            <span class="fname">{{ (wb.selectedSeller || 'SELLER').replace(/[/\s]+/g, '-') }}-RO-{{ key }}-{{ wb.selectedPo }}{{ (key === 'INVOICE' || key === 'PL') && wb.selectedInvoiceNo ? '-' + wb.selectedInvoiceNo : '' }}.xlsx</span>
          </div>
          <span class="checkbox" :class="{ on: selectedDocs.has(key) }" @click="toggleDoc(key)">{{ selectedDocs.has(key) ? '✓' : '' }}</span>
        </div>
      </div>

      <div class="export-card">
        <h3>输出设置</h3>
        <div class="field" style="margin-bottom: 10px">
          <label>文件格式</label>
          <div class="value">ZIP 包</div>
        </div>
        <div class="field" style="margin-bottom: 10px">
          <label>输出文件名</label>
          <div class="value">RO-{{ wb.selectedPo }}{{ wb.selectedInvoiceNo ? '-' + wb.selectedInvoiceNo : '' }}.zip</div>
        </div>
        <div class="field" style="margin-bottom: 14px">
          <label>输出目录</label>
          <div class="value">~/Documents/RO Outputs</div>
        </div>
        <button class="primary-btn" :disabled="!selectedDocs.size || wb.exporting" @click="handleExport">
          {{ wb.exporting ? "导出中…" : "确认导出" }}
        </button>
        <div v-if="wb.exportError" class="export-err">{{ wb.exportError }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.export-screen { padding: 18px 20px 22px; }
.placeholder { padding: var(--space-8); text-align: center; color: var(--subtle); }
.export-grid { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; }
.export-card { border: 1px solid var(--line); border-radius: 12px; background: white; padding: 16px; }
.export-card h3 { margin: 0 0 14px; font-size: 14px; }
.check-line { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 0; border-bottom: 1px solid var(--line); }
.check-line:last-child { border-bottom: 0; }
.check-line b { font-size: 13px; }
.fname { color: var(--muted); font-size: 12px; }
.checkbox {
  width: 20px; height: 20px; border-radius: 6px;
  display: grid; place-items: center;
  border: 2px solid var(--line);
  color: white; font-weight: 900; font-size: 12px;
  cursor: pointer; flex-shrink: 0;
}
.checkbox.on { background: var(--blue); border-color: var(--blue); }
.field { border: 1px solid var(--line); border-radius: 10px; background: var(--panel-soft); padding: 10px; }
.field label { display: block; color: var(--muted); font-size: 12px; margin-bottom: 6px; }
.field .value { color: var(--text); font-family: var(--mono); font-weight: 800; font-size: 13px; }
.primary-btn {
  width: 100%; height: 42px;
  border: 1px solid #1d4ed8; border-radius: 8px;
  color: white; background: var(--blue);
  font-weight: 700; cursor: pointer; font: inherit; font-size: 13px;
}
.primary-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.export-err { margin-top: 8px; padding: 8px 10px; border-radius: 6px; background: #fff5f5; border: 1px solid #fecaca; color: var(--red); font-size: 12px; line-height: 1.5; }
</style>
