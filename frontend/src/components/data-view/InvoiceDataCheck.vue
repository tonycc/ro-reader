<script setup lang="ts">
import { watch } from "vue";
import { useWorkbench } from "../../stores/workbench";
import IssueSummaryBar from "./IssueSummaryBar.vue";

const wb = useWorkbench();

watch(
  () => wb.selectedInvoiceGroup,
  () => wb.refreshInvoiceInspection(),
  { immediate: true },
);
</script>

<template>
  <div class="check-screen">
    <div v-if="!wb.selectedInvoiceGroup" class="placeholder">选择左侧 Invoice 开始数据检查</div>
    <div v-else-if="wb.invoiceInspectionLoading && !wb.invoiceInspection" class="placeholder">正在读取 Invoice 检查结果…</div>
    <div v-else-if="wb.invoiceInspectionError && !wb.invoiceInspection" class="placeholder error">{{ wb.invoiceInspectionError }}</div>
    <template v-else-if="wb.invoiceInspection">
      <IssueSummaryBar
        :object-label="wb.invoiceInspection.display_invoice_no"
        :meta-label="`${wb.invoiceInspection.line_count} 行 · ${wb.invoiceInspection.po_nos.length} 个 PO · Invoice 基础检查`"
        :blocking-errors="wb.invoiceInspection.blocking_errors"
        :warnings="wb.invoiceInspection.warnings"
        :loading="wb.invoiceInspectionLoading"
        :error="wb.invoiceInspectionError"
      />
      <div v-if="!wb.invoiceInspection.rows.length" class="placeholder">该票据组没有可检查的出货行</div>
      <div v-else class="panel">
        <div class="table-shell">
          <table class="data-table" data-testid="invoice-inspection-table">
            <thead>
              <tr>
                <th>源行</th><th>PO NO.</th><th>SAP</th><th>品名</th><th>Category</th>
                <th>SHIP QTY</th><th>INV#</th><th>FACTORY DOC NO.</th><th>可用主体</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in wb.invoiceInspection.rows" :key="row.source_row">
                <td class="mono row-num">{{ row.source_row }}</td>
                <td class="mono">{{ row.po_no }}</td>
                <td class="mono">{{ row.sap }}</td>
                <td>{{ row.description }}</td>
                <td>{{ row.category ?? '' }}</td>
                <td class="mono">{{ row.ship_qty }}</td>
                <td class="mono">{{ row.invoice_no ?? '' }}</td>
                <td class="mono">{{ row.factory_document_no ?? '' }}</td>
                <td>{{ row.sellers.join(', ') }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.check-screen { padding: 14px 20px 22px; display: flex; flex-direction: column; min-height: 0; }
.placeholder { padding: var(--space-8); text-align: center; color: var(--subtle); }
.placeholder.error { color: var(--red); }
.panel { border: 1px solid var(--line); border-radius: 8px; background: var(--panel); overflow: hidden; flex: 1; min-height: 0; }
.table-shell { max-height: calc(100vh - 180px); overflow: auto; }
.data-table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: 12px; }
th, td { border-bottom: 1px solid var(--line); padding: 9px 10px; text-align: left; white-space: nowrap; }
th { position: sticky; top: 0; z-index: 1; background: #f7f9fc; color: var(--muted); font-weight: 800; border-bottom-color: var(--line-strong); }
.mono { font-family: var(--mono); }
.row-num { width: 48px; color: var(--subtle); text-align: right; }
tr:hover td { background: #f8fbff; }
</style>
