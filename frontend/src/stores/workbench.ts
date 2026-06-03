import { defineStore } from "pinia";
import { ref, computed } from "vue";
import type { PoListItem, DryRunResult, SourceIndexEntry } from "./api";
import { api } from "./api";

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
  const selectedMonth = ref<string | null>(null);

  const preview = ref<DryRunResult | null>(null);
  const previewDocType = ref("INVOICE");
  const sourceIndex = ref<SourceIndexEntry[]>([]);

  const exporting = ref(false);
  const lastExportFile = ref("");

  const blockingErrors = ref<unknown[]>([]);
  const warnings = ref<unknown[]>([]);

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
    if (po?.monthly_months.length) selectedMonth.value = po.monthly_months[0];
    await refreshPreview();
  }

  async function refreshPreview(docType?: string) {
    if (!baseFile.value || !selectedPo.value || !selectedSeller.value) return;
    const dt = docType || previewDocType.value || "INVOICE";
    try {
      const result = await api.dryRun({
        base_file: baseFile.value, po_no: selectedPo.value,
        seller: selectedSeller.value, invoice_month: selectedMonth.value, document: dt,
      });
      preview.value = result; previewDocType.value = dt;
      sourceIndex.value = result.source_index ?? [];
      warnings.value = result.warnings; blockingErrors.value = result.errors;
    } catch (e) { console.error("dry-run failed", e); }
  }

  async function editCell(field: string, row: number, value: unknown) {
    await api.editField(selectedPo.value, {
      base_file: baseFile.value, sheet: "PO record", row, field, value,
    });
    await selectPo(selectedPo.value);
    await refreshPreview();
  }

  async function doExport() {
    console.log("[doExport] called", { base: !!baseFile.value, po: selectedPo.value, seller: selectedSeller.value, month: selectedMonth.value, doc: previewDocType.value });
    if (!baseFile.value || !selectedPo.value || !selectedSeller.value) {
      console.log("[doExport] EARLY RETURN - missing required");
      return;
    }
    exporting.value = true;
    try {
      const result = await api.exportDocuments({
        base_file: baseFile.value, po_no: selectedPo.value,
        seller: selectedSeller.value, invoice_month: selectedMonth.value,
        document: previewDocType.value,
      });
      console.log("[doExport] result:", { status: result.status, output: result.output_file, files: result.files, errors: result.errors?.length });
      lastExportFile.value = result.output_file ?? "";
      return result;
    } catch (e) {
      console.error("[doExport] FAILED:", e);
    } finally { exporting.value = false; }
  }

  function selectSeller(seller: string) { selectedSeller.value = seller; refreshPreview(); }
  function selectMonth(month: string | null) { selectedMonth.value = month; refreshPreview(); }

  return {
    baseFile, poList, loading, error,
    selectedPo, dataRows, dataHeaders,
    selectedSeller, selectedMonth,
    preview, previewDocType, sourceIndex,
    exporting, lastExportFile,
    blockingErrors, warnings,
    poEntry, poStatus,
    openSession, selectPo, refreshPreview, editCell, doExport,
    selectSeller, selectMonth,
  };
});
