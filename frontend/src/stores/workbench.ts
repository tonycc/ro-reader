import { defineStore } from "pinia";
import { ref, computed } from "vue";
import type { PoListItem, DryRunResult, SourceIndexEntry, PreviewPayload, PreviewSourceEntry } from "./api";
import { api, setSessionId, getSessionId, ApiError } from "./api";

export const useWorkbench = defineStore("workbench", () => {
  const baseFile = ref("");
  const poList = ref<PoListItem[]>([]);
  const loading = ref(false);
  const error = ref("");

  const selectedPo = ref("");
  const dataRows = ref<Record<string, unknown>[]>([]);
  const dataHeaders = ref<string[]>([]);

  // Selected seller (one of: SK/YM, GS PTE, EMAX PTE)
  const selectedSeller = ref("");
  const selectedInvoiceNo = ref<string | null>(null);

  const preview = ref<DryRunResult | null>(null);
  const previewData = ref<PreviewPayload | null>(null);
  const previewDocType = ref("INVOICE");
  const previewLoading = ref(false);
  const sourceIndex = ref<SourceIndexEntry[]>([]);
  const previewSourceEntries = ref<PreviewSourceEntry[]>([]);

  const exporting = ref(false);
  const lastExportFile = ref("");

  const blockingErrors = ref<unknown[]>([]);
  const warnings = ref<unknown[]>([]);

  const previewError = ref("");
  const exportError = ref("");

  const poEntry = computed(() => poList.value.find((p) => p.po_no === selectedPo.value));
  const poStatus = computed(() => poEntry.value?.status ?? "");

  async function openSession(file: string) {
    loading.value = true; error.value = "";
    selectedPo.value = ""; preview.value = null;
    blockingErrors.value = []; warnings.value = []; sourceIndex.value = [];
    try {
      baseFile.value = file;
      const data = await api.openSession(file);
      if (!data.ok) throw new Error(data.errors?.[0] ? String((data.errors[0] as Record<string, unknown>).message) : "session failed");
      if (data.session_id) setSessionId(data.session_id);
      poList.value = data.po_list;
    } catch (e) { error.value = String(e); }
    finally { loading.value = false; }
  }

  async function selectPo(po_no: string) {
    selectedPo.value = po_no;
    preview.value = null; blockingErrors.value = []; warnings.value = []; sourceIndex.value = [];
    if (!baseFile.value) return;
    const data = await api.getDataView(baseFile.value, po_no);
    dataRows.value = data.rows; dataHeaders.value = data.headers;
    const po = poList.value.find((p) => p.po_no === po_no);
    if (po?.sellers.length) selectedSeller.value = po.sellers[0];
    if (po?.invoice_nos.length) selectedInvoiceNo.value = po.invoice_nos[0];
    await refreshPreview();
  }

  async function refreshPreview(docType?: string) {
    if (!baseFile.value || !selectedPo.value || !selectedSeller.value) return;
    const dt = docType || previewDocType.value || "INVOICE";
    previewLoading.value = true;
    previewError.value = "";
    try {
      const result = await api.preview({
        base_file: baseFile.value, po_no: selectedPo.value,
        seller: selectedSeller.value, invoice_no: selectedInvoiceNo.value, document: dt,
      });
      previewDocType.value = dt;
      previewData.value = result.preview;
      previewSourceEntries.value = result.preview?.source_entries ?? [];
      warnings.value = result.warnings;
      blockingErrors.value = result.errors;
    } catch (e) {
      previewError.value = e instanceof ApiError ? e.message : `预览失败：${e}`;
    } finally { previewLoading.value = false; }
  }

  async function editCell(field: string, row: number, value: unknown) {
    await api.editField(selectedPo.value, {
      base_file: baseFile.value, sheet: "PO record", row, field, value,
    });
    await selectPo(selectedPo.value);
    await refreshPreview();
  }

  async function doExport() {
    if (!baseFile.value || !selectedPo.value || !selectedSeller.value) return;
    exporting.value = true;
    exportError.value = "";
    try {
      const result = await api.exportDocuments({
        base_file: baseFile.value, po_no: selectedPo.value,
        seller: selectedSeller.value, invoice_no: selectedInvoiceNo.value,
        document: previewDocType.value,
      });
      lastExportFile.value = result.output_file ?? "";
      // Trigger browser download
      if (result.output_file) {
        const downloadUrl = `/api/download?path=${encodeURIComponent(result.output_file)}&session_id=${getSessionId()}`;
        const a = document.createElement("a");
        a.href = downloadUrl;
        a.download = result.files[0] || "export.xlsx";
        a.click();
      }
      return result;
    } catch (e) {
      exportError.value = e instanceof ApiError ? e.message : `导出失败：${e}`;
    } finally { exporting.value = false; }
  }

  function selectSeller(seller: string) { selectedSeller.value = seller; refreshPreview(); }
  function selectInvoice(inv: string | null) { selectedInvoiceNo.value = inv; refreshPreview(); }

  return {
    baseFile, poList, loading, error,
    selectedPo, dataRows, dataHeaders,
    selectedSeller, selectedInvoiceNo,
    preview, previewData, previewDocType, previewLoading, sourceIndex, previewSourceEntries,
    exporting, lastExportFile,
    blockingErrors, warnings,
    previewError, exportError,
    poEntry, poStatus,
    openSession, selectPo, refreshPreview, editCell, doExport,
    selectSeller, selectInvoice,
  };
});
