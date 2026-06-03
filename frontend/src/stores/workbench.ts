import { defineStore } from "pinia";
import { ref, computed } from "vue";
import type { PoListItem, DryRunResult, SourceIndexEntry } from "./api";
import { api } from "./api";

export const useWorkbench = defineStore("workbench", () => {
  // Base session
  const baseFile = ref("");
  const poList = ref<PoListItem[]>([]);
  const loading = ref(false);
  const error = ref("");

  // Selected PO
  const selectedPo = ref("");
  const dataRows = ref<Record<string, unknown>[]>([]);
  const dataHeaders = ref<string[]>([]);

  // Chain & month
  const selectedSegment = ref<{ seller: string; buyer: string } | null>(null);
  const selectedMonth = ref<string | null>(null);

  // Preview
  const preview = ref<DryRunResult | null>(null);
  const previewDocType = ref("INVOICE");
  const sourceIndex = ref<SourceIndexEntry[]>([]);

  // Export
  const exporting = ref(false);
  const lastExportFile = ref("");

  // Errors & warnings
  const blockingErrors = ref<unknown[]>([]);
  const warnings = ref<unknown[]>([]);

  // Computed
  const poEntry = computed(() => poList.value.find((p) => p.po_no === selectedPo.value));
  const poStatus = computed(() => poEntry.value?.status ?? "");

  // Actions
  async function openSession(file: string) {
    loading.value = true;
    error.value = "";
    // Reset all transient state
    selectedPo.value = "";
    preview.value = null;
    blockingErrors.value = [];
    warnings.value = [];
    sourceIndex.value = [];
    try {
      baseFile.value = file;
      const data = await api.openSession(file);
      if (!data.ok) throw new Error(data.errors?.[0] ? String((data.errors[0] as Record<string, unknown>).message) : "session failed");
      poList.value = data.po_list;
    } catch (e) {
      error.value = String(e);
    } finally {
      loading.value = false;
    }
  }

  async function selectPo(po_no: string) {
    console.log("[selectPo] START", { po_no, prevBlockingErrors: blockingErrors.value.length });
    selectedPo.value = po_no;
    preview.value = null;
    blockingErrors.value = [];
    warnings.value = [];
    sourceIndex.value = [];
    console.log("[selectPo] cleared state, blockingErrors now:", blockingErrors.value.length);
    if (!baseFile.value) { console.log("[selectPo] no baseFile, returning"); return; }
    const data = await api.getDataView(baseFile.value, po_no);
    dataRows.value = data.rows;
    dataHeaders.value = data.headers;
    const po = poList.value.find((p) => p.po_no === po_no);
    console.log("[selectPo] po found:", { status: po?.status, segments: po?.chain_segments?.length });
    if (po?.chain_segments.length) {
      selectedSegment.value = po.chain_segments[0];
      console.log("[selectPo] segment set:", selectedSegment.value);
    }
    console.log("[selectPo] calling refreshPreview, blockingErrors before:", blockingErrors.value.length);
    await refreshPreview();
    console.log("[selectPo] DONE, blockingErrors:", blockingErrors.value.length, "errors:", JSON.stringify(blockingErrors.value.slice(0, 3)));
  }

  async function refreshPreview(docType?: string) {
    if (!baseFile.value || !selectedPo.value || !selectedSegment.value) {
      console.log("[refreshPreview] SKIP - missing:", { base: !!baseFile.value, po: !!selectedPo.value, seg: !!selectedSegment.value });
      return;
    }
    const dt = docType || previewDocType.value || "INVOICE";
    console.log("[refreshPreview] START", { po: selectedPo.value, segment: selectedSegment.value, doc: dt, month: selectedMonth.value });
    try {
      const result = await api.dryRun({
        base_file: baseFile.value,
        po_no: selectedPo.value,
        seller: selectedSegment.value.seller,
        buyer: selectedSegment.value.buyer,
        invoice_month: selectedMonth.value,
        document: dt,
      });
      console.log("[refreshPreview] GOT result", {
        status: result.status,
        errors: result.errors?.length,
        warnings: result.warnings?.length,
        missing_inputs: result.missing_inputs,
        files: result.files,
      });
      if (result.errors?.length) {
        console.log("[refreshPreview] ERROR DETAILS:", JSON.stringify(result.errors.slice(0, 5)));
      }
      preview.value = result;
      previewDocType.value = dt;
      sourceIndex.value = result.source_index ?? [];
      warnings.value = result.warnings;
      blockingErrors.value = result.errors;
      console.log("[refreshPreview] DONE, blockingErrors set to:", blockingErrors.value.length);
    } catch (e) {
      console.error("[refreshPreview] FAILED:", e);
    }
  }

  async function editCell(field: string, row: number, value: unknown) {
    await api.editField(selectedPo.value, {
      base_file: baseFile.value,
      sheet: "PO record",
      row,
      field,
      value,
    });
    await selectPo(selectedPo.value);
    await refreshPreview();
  }

  async function doExport() {
    if (!baseFile.value || !selectedPo.value || !selectedSegment.value) return;
    exporting.value = true;
    try {
      const result = await api.exportDocuments({
        base_file: baseFile.value,
        po_no: selectedPo.value,
        seller: selectedSegment.value.seller,
        buyer: selectedSegment.value.buyer,
        invoice_month: selectedMonth.value,
      });
      lastExportFile.value = result.output_file ?? "";
      return result;
    } finally {
      exporting.value = false;
    }
  }

  function selectSegment(seg: { seller: string; buyer: string }) {
    selectedSegment.value = seg;
    refreshPreview();
  }

  function selectMonth(month: string | null) {
    selectedMonth.value = month;
    refreshPreview();
  }

  return {
    baseFile, poList, loading, error,
    selectedPo, dataRows, dataHeaders,
    selectedSegment, selectedMonth,
    preview, previewDocType, sourceIndex,
    exporting, lastExportFile,
    blockingErrors, warnings,
    poEntry, poStatus,
    openSession, selectPo, refreshPreview, editCell, doExport,
    selectSegment, selectMonth,
  };
});
