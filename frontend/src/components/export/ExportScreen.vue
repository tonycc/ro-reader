<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useWorkbench } from "../../stores/workbench";

const wb = useWorkbench();

const docLabels: Record<string, string> = {
  PI: "形式发票（PI）",
  PO: "采购订单（PO）",
  INVOICE_PL: "商业发票 / 装箱单（Invoice / PL）",
};

const docOrder = ["PI", "PO", "INVOICE_PL"];

interface ExportDocEntry {
  id: string
  seller: string
  document: string
  documents: string[]
  label: string
  disabled: boolean
}

const selectedDocs = ref<Set<string>>(new Set());
const selectedInvoices = ref<Record<string, string | null>>({});
const selectedInvoiceDocuments = ref<Set<"INVOICE" | "PL">>(new Set(["INVOICE", "PL"]));

const exportGroups = computed(() => (
  (wb.poEntry?.sellers ?? []).map((seller) => ({
    seller,
    entries: docOrder
      .filter((document) => document !== "PO" || (seller !== "SK" && seller !== "YM"))
      .map((document) => buildExportEntry(seller, document)),
  }))
));

const selectedExportDocs = computed(() => (
  exportGroups.value
      .map((group) => ({
      seller: group.seller,
      documents: group.entries
        .filter((entry) => selectedDocs.value.has(entry.id))
        .flatMap((entry) => entry.documents),
      invoice_no: group.entries.some((entry) => (
        selectedDocs.value.has(entry.id) && entry.document === "INVOICE_PL"
      ))
        ? selectedInvoiceForSeller(group.seller)
        : null,
    }))
    .filter((group) => group.documents.length > 0)
));

const selectedDocCount = computed(() => (
  exportGroups.value.flatMap((group) => group.entries)
    .filter((entry) => selectedDocs.value.has(entry.id))
    .length
));

watch(exportGroups, (groups) => {
  selectedDocs.value = new Set(groups.flatMap((group) => (
    group.entries.filter((entry) => !entry.disabled).map((entry) => entry.id)
  )));
  selectedInvoices.value = Object.fromEntries(groups.map((group) => [
    group.seller,
    invoiceOptionsForSeller(group.seller)[0] ?? null,
  ]));
}, { immediate: true });

function toggleDoc(id: string) {
  const entry = exportGroups.value.flatMap((group) => group.entries).find((item) => item.id === id);
  if (entry?.disabled) return;
  const next = new Set(selectedDocs.value);
  if (next.has(id)) next.delete(id); else next.add(id);
  selectedDocs.value = next;
}

async function handleExport() {
  await wb.doExportGroups(selectedExportDocs.value);
}

async function handleInvoiceGroupExport() {
  await wb.doExport(Array.from(selectedInvoiceDocuments.value));
}

function toggleInvoiceDocument(document: "INVOICE" | "PL") {
  const next = new Set(selectedInvoiceDocuments.value);
  if (next.has(document)) next.delete(document); else next.add(document);
  selectedInvoiceDocuments.value = next;
}

function invoiceGroupFilename(document: "INVOICE" | "PL"): string {
  const invoiceNo = wb.invoiceEntry?.seller_invoice_numbers[wb.selectedSeller]
    ?? wb.invoiceEntry?.display_invoice_no
    ?? "INVOICE";
  return `${safeToken(wb.selectedSeller)}-RO-${document}-${safeToken(invoiceNo)}.xlsx`;
}

function buildExportEntry(seller: string, document: string): ExportDocEntry {
  return {
    id: `${safeToken(seller)}-${document}`,
    seller,
    document,
    documents: document === "INVOICE_PL" ? ["INVOICE", "PL"] : [document],
    label: docLabels[document],
    disabled: !exportableDocumentsForSeller(seller).includes(document),
  };
}

function buildFilename(seller: string, document: string): string {
  const documentToken = document === "INVOICE_PL" ? "INVOICE&PL" : document;
  const base = `${safeToken(seller)}-RO-${documentToken}-${safeToken(wb.selectedPo)}`;
  if (document === "INVOICE_PL" && selectedInvoiceForSeller(seller)) {
    return `${base}-${safeToken(selectedInvoiceForSeller(seller) ?? "")}.xlsx`;
  }
  return `${base}.xlsx`;
}

function invoiceOptionsForSeller(seller: string): string[] {
  const po = wb.poEntry;
  if (!po) return [];
  const options = po.invoice_options_by_seller?.[seller] ?? [];
  return options.length ? options : po.invoice_nos;
}

function selectedInvoiceForSeller(seller: string): string | null {
  return selectedInvoices.value[seller] ?? invoiceOptionsForSeller(seller)[0] ?? null;
}

function selectExportInvoice(seller: string, event: Event) {
  const value = (event.target as HTMLSelectElement).value || null;
  selectedInvoices.value = { ...selectedInvoices.value, [seller]: value };
}

function canExportInvoicePl(seller: string): boolean {
  return exportableDocumentsForSeller(seller).includes("INVOICE_PL");
}

function exportableDocumentsForSeller(seller: string): string[] {
  return wb.poEntry?.exportable_documents_by_seller?.[seller] ?? [];
}

function safeToken(value: string): string {
  return value.trim().replace(/[\\/:*?"<>|\s]+/g, "_");
}
</script>

<template>
  <div class="export-screen">
    <div v-if="wb.previewScope === 'invoice' && !wb.selectedInvoiceGroup" class="placeholder">选择左侧 Invoice 开始导出</div>
    <div v-else-if="wb.previewScope === 'invoice'" class="export-grid">
      <div class="export-card">
        <h3>{{ wb.invoiceEntry?.display_invoice_no }} · 导出内容确认</h3>
        <section class="seller-section">
          <h4>{{ wb.selectedSeller }}</h4>
          <div
            v-for="document in (['INVOICE', 'PL'] as const)"
            :key="document"
            class="check-line"
            :data-testid="`invoice-export-${document}`"
          >
            <div>
              <b>{{ invoiceGroupFilename(document) }}</b><br>
              <span class="fname">{{ document === 'INVOICE' ? '商业发票' : '装箱单' }}</span>
            </div>
            <span
              class="checkbox"
              :class="{ on: selectedInvoiceDocuments.has(document) }"
              @click="toggleInvoiceDocument(document)"
            >{{ selectedInvoiceDocuments.has(document) ? '✓' : '' }}</span>
          </div>
        </section>
      </div>
      <div class="export-card">
        <h3>输出设置</h3>
        <div class="field" style="margin-bottom: 10px"><label>文件格式</label><div class="value">ZIP 包</div></div>
        <div class="field" style="margin-bottom: 14px"><label>覆盖 PO</label><div class="value">{{ wb.invoiceEntry?.po_count ?? 0 }} 个</div></div>
        <button class="primary-btn" :disabled="!selectedInvoiceDocuments.size || wb.exporting" @click="handleInvoiceGroupExport">
          {{ wb.exporting ? '导出中…' : '确认导出' }}
        </button>
        <div v-if="wb.exportError" class="export-err">{{ wb.exportError }}</div>
      </div>
    </div>
    <div v-else-if="!wb.selectedPo" class="placeholder">选择左侧 PO 开始导出</div>
    <div v-else class="export-grid">
      <div class="export-card">
        <h3>导出内容确认</h3>
        <section v-for="group in exportGroups" :key="group.seller" class="seller-section">
          <h4>{{ group.seller }}</h4>
          <label v-if="canExportInvoicePl(group.seller)" class="invoice-field">
            <span>发票号</span>
            <select
              :data-testid="`export-invoice-${safeToken(group.seller)}`"
              :value="selectedInvoiceForSeller(group.seller) ?? ''"
              @change="selectExportInvoice(group.seller, $event)"
            >
              <option v-for="invoiceNo in invoiceOptionsForSeller(group.seller)" :key="invoiceNo" :value="invoiceNo">
                {{ invoiceNo }}
              </option>
            </select>
          </label>
          <div
            v-for="entry in group.entries"
            :key="entry.id"
            class="check-line"
            :class="{ disabled: entry.disabled }"
            :data-testid="`export-doc-${entry.id}`"
          >
            <div>
              <b>{{ buildFilename(entry.seller, entry.document) }}</b><br>
              <span class="fname">{{ entry.label }}</span>
            </div>
            <span
              class="checkbox"
              :class="{ on: selectedDocs.has(entry.id), disabled: entry.disabled }"
              @click="toggleDoc(entry.id)"
            >
              {{ selectedDocs.has(entry.id) ? '✓' : '' }}
            </span>
          </div>
        </section>
      </div>

      <div class="export-card">
        <h3>输出设置</h3>
        <div class="field" style="margin-bottom: 10px">
          <label>文件格式</label>
          <div class="value">ZIP 包</div>
        </div>
        <div class="field" style="margin-bottom: 14px">
          <label>已选单据</label>
          <div class="value">{{ selectedDocCount }} 份</div>
        </div>
        <button class="primary-btn" :disabled="!selectedDocCount || wb.exporting" @click="handleExport">
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
.export-card { border: 1px solid var(--line); border-radius: 8px; background: white; padding: 16px; }
.export-card h3 { margin: 0 0 14px; font-size: 14px; }
.seller-section { padding: 12px 0; border-top: 1px solid var(--line); }
.seller-section:first-of-type { border-top: 0; padding-top: 0; }
.seller-section h4 { margin: 0 0 8px; font-size: 12px; color: var(--muted); font-weight: 900; }
.invoice-field { display: flex; align-items: center; gap: 8px; margin: 0 0 8px; color: var(--muted); font-size: 12px; font-weight: 700; }
.invoice-field select { min-width: 0; max-width: 260px; height: 30px; border: 1px solid var(--line); border-radius: 6px; background: white; color: var(--text); font: inherit; }
.check-line { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 0; border-bottom: 1px solid var(--line); }
.check-line:last-child { border-bottom: 0; }
.check-line.disabled { opacity: 0.45; }
.check-line b { font-size: 13px; font-family: var(--mono); }
.fname { color: var(--muted); font-size: 12px; }
.checkbox {
  width: 20px; height: 20px; border-radius: 6px;
  display: grid; place-items: center;
  border: 2px solid var(--line);
  color: white; font-weight: 900; font-size: 12px;
  cursor: pointer; flex-shrink: 0;
}
.checkbox.on { background: var(--blue); border-color: var(--blue); }
.checkbox.disabled { cursor: not-allowed; background: #f2f4f7; border-color: var(--line); color: transparent; }
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
