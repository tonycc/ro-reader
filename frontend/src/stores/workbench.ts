import { defineStore } from "pinia";
import { ref, computed } from "vue";
import type {
  PoListItem,
  DryRunResult,
  SourceIndexEntry,
  PreviewPayload,
  PreviewSourceEntry,
  PreviewDocumentResult,
  PoIssuesResponse,
  PreviewResponse,
} from "./api";
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
  const previewDocuments = ref<PreviewDocumentResult[]>([]);
  const previewDocType = ref("INVOICE");
  const previewLoading = ref(false);
  const sourceIndex = ref<SourceIndexEntry[]>([]);
  const previewSourceEntries = ref<PreviewSourceEntry[]>([]);

  const exporting = ref(false);
  const lastExportFile = ref("");

  const blockingErrors = ref<unknown[]>([]);
  const warnings = ref<unknown[]>([]);
  const poIssues = ref<PoIssuesResponse | null>(null);
  const issuesLoading = ref(false);
  const issuesError = ref("");

  const previewError = ref("");
  const exportError = ref("");

  const poEntry = computed(() => poList.value.find((p) => p.po_no === selectedPo.value));
  const poStatus = computed(() => poEntry.value?.status ?? "");
  const invoiceOptions = computed(() => invoiceOptionsForSeller(selectedSeller.value));

  async function openSession(file: string) {
    loading.value = true; error.value = "";
    selectedPo.value = ""; preview.value = null;
    previewData.value = null; previewDocuments.value = [];
    blockingErrors.value = []; warnings.value = []; sourceIndex.value = [];
    poIssues.value = null; issuesError.value = "";
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
    previewData.value = null; previewDocuments.value = [];
    poIssues.value = null; issuesError.value = "";
    if (!baseFile.value) return;
    const data = await api.getDataView(baseFile.value, po_no);
    dataRows.value = data.rows; dataHeaders.value = data.headers;
    const po = poList.value.find((p) => p.po_no === po_no);
    if (po?.sellers.length) selectedSeller.value = po.sellers[0];
    syncSelectedInvoiceForSeller();
    await refreshPoIssues();
    await refreshPreview();
  }

  async function refreshPoIssues() {
    if (!baseFile.value || !selectedPo.value) return;
    issuesLoading.value = true;
    issuesError.value = "";
    try {
      poIssues.value = await api.getPoIssues(baseFile.value, selectedPo.value);
    } catch (e) {
      issuesError.value = e instanceof ApiError ? e.message : `读取阻断原因失败：${e}`;
      poIssues.value = null;
    } finally { issuesLoading.value = false; }
  }

  async function refreshPreview(docType?: string) {
    if (!baseFile.value || !selectedPo.value || !selectedSeller.value) return;
    const dt = docType || previewDocType.value || "INVOICE";
    const requestSeller = selectedSeller.value;
    previewLoading.value = true;
    previewError.value = "";
    previewData.value = null;
    previewDocuments.value = [];
    previewSourceEntries.value = [];
    blockingErrors.value = [];
    warnings.value = [];
    try {
      previewDocType.value = dt;
      const docs = isInvoicePlDocument(dt) ? ["INVOICE", "PL"] : [dt];
      const results = await Promise.all(docs.map(async (document) => {
        try {
          const result = await api.preview({
            base_file: baseFile.value, po_no: selectedPo.value,
            seller: requestSeller, invoice_no: selectedInvoiceNo.value, document,
          });
          return toPreviewDocument(document, result, requestSeller);
        } catch (e) {
          return toFailedPreviewDocument(document, requestSeller, e);
        }
      }));
      previewDocuments.value = results;
      previewData.value = results.find((doc) => doc.preview)?.preview ?? null;
      previewSourceEntries.value = results.flatMap((doc) => doc.preview?.source_entries ?? []);
      blockingErrors.value = results.flatMap((doc) => doc.errors);
      warnings.value = results.flatMap((doc) => doc.warnings);
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

  type ExportGroup = { seller: string; documents: string[] };

  async function doExport(documents?: string[]) {
    if (!baseFile.value || !selectedPo.value || !selectedSeller.value) return;
    exporting.value = true;
    exportError.value = "";
    try {
      const exportDocuments = documents?.length
        ? documents
        : [isInvoicePlDocument(previewDocType.value) ? "INVOICE_PL" : previewDocType.value];
      return await exportOneGroup({
        seller: selectedSeller.value,
        documents: exportDocuments,
      });
    } catch (e) {
      exportError.value = e instanceof ApiError ? e.message : `导出失败：${e}`;
    } finally { exporting.value = false; }
  }

  async function doExportGroups(groups: ExportGroup[]) {
    if (!baseFile.value || !selectedPo.value || !groups.length) return;
    exporting.value = true;
    exportError.value = "";
    lastExportFile.value = "";
    try {
      const result = await api.exportDocumentGroups({
        base_file: baseFile.value,
        po_no: selectedPo.value,
        groups: groups.map((group) => ({
          seller: group.seller,
          documents: group.documents,
          invoice_no: invoiceNoForSeller(group.seller),
        })),
      });
      if (result.status !== "success") {
        exportError.value = formatExportFailure(result);
        lastExportFile.value = "";
        return result;
      }
      lastExportFile.value = result.output_file ?? "";
      triggerDownload(result, "export.zip");
      return result;
    } catch (e) {
      exportError.value = e instanceof ApiError ? e.message : `导出失败：${e}`;
    } finally { exporting.value = false; }
  }

  async function exportOneGroup(group: ExportGroup) {
    const exportDocuments = group.documents;
    if (!exportDocuments.length) return;
    try {
      const payload = {
        base_file: baseFile.value, po_no: selectedPo.value,
        seller: group.seller, invoice_no: invoiceNoForSeller(group.seller),
        document: exportDocuments[0], documents: exportDocuments,
      };
      const result = await api.exportDocuments(payload);
      if (result.status !== "success") {
        exportError.value = formatExportFailure(result);
        lastExportFile.value = "";
        return result;
      }
      lastExportFile.value = result.output_file ?? "";
      triggerDownload(result, "export.xlsx");
      return result;
    } catch (e) {
      exportError.value = e instanceof ApiError ? e.message : `导出失败：${e}`;
    }
  }

  function triggerDownload(result: DryRunResult, fallbackName: string) {
    if (!result.output_file) return;
    const downloadUrl = `/api/download?path=${encodeURIComponent(result.output_file)}&session_id=${getSessionId()}`;
    const a = document.createElement("a");
    a.href = downloadUrl;
    a.download = result.output_file.split(/[\\/]/).pop() || result.files[0] || fallbackName;
    a.click();
  }

  function selectSeller(seller: string) {
    selectedSeller.value = seller;
    syncSelectedInvoiceForSeller();
    return refreshPreview();
  }
  function selectInvoice(inv: string | null) { selectedInvoiceNo.value = inv; return refreshPreview(); }

  function isInvoicePlDocument(document: string): boolean {
    return document === "INVOICE" || document === "PL";
  }

  function formatExportFailure(result: DryRunResult): string {
    const messages = result.errors.map(formatIssueMessage).filter(Boolean);
    if (messages.length) return `导出失败：${messages.join("；")}`;
    if (result.missing_inputs.length) {
      return `导出失败：缺少 ${result.missing_inputs.join(", ")}`;
    }
    return `导出失败：${result.status}`;
  }

  function formatIssueMessage(issue: unknown): string {
    if (!issue || typeof issue !== "object") return "";
    const record = issue as Record<string, unknown>;
    const code = typeof record.code === "string" ? record.code : "";
    const message = typeof record.message === "string" ? record.message : "";
    if (code && message) return `${code}: ${message}`;
    return message || code;
  }

  function documentLabel(document: string): string {
    if (document === "INVOICE") return "Invoice";
    if (document === "PL") return "PL";
    return document;
  }

  function invoiceOptionsForSeller(seller: string): string[] {
    const po = poEntry.value;
    if (!po) return [];
    const sellerOptions = po.invoice_options_by_seller?.[seller] ?? [];
    if (seller === "SK" || seller === "YM") return sellerOptions;
    return sellerOptions.length ? sellerOptions : po.invoice_nos;
  }

  function syncSelectedInvoiceForSeller() {
    const options = invoiceOptionsForSeller(selectedSeller.value);
    if (selectedInvoiceNo.value && options.includes(selectedInvoiceNo.value)) return;
    selectedInvoiceNo.value = options[0] ?? null;
  }

  function invoiceNoForSeller(seller: string): string | null {
    const options = invoiceOptionsForSeller(seller);
    if (seller === selectedSeller.value && selectedInvoiceNo.value && options.includes(selectedInvoiceNo.value)) {
      return selectedInvoiceNo.value;
    }
    return options[0] ?? null;
  }

  function toPreviewDocument(document: string, result: PreviewResponse, seller: string): PreviewDocumentResult {
    const softPreviewIssues = result.errors.filter(isSoftPreviewIssue).map(asPreviewWarning);
    const errors = result.errors.filter((issue) => !isSoftPreviewIssue(issue));
    const title = result.preview?.title || documentLabel(document);
    return {
      id: `${seller}-${document}`,
      seller,
      document,
      label: `${seller} · ${title}`,
      preview: result.preview,
      errors,
      warnings: [...result.warnings, ...softPreviewIssues],
    };
  }

  function toFailedPreviewDocument(document: string, seller: string, error: unknown): PreviewDocumentResult {
    const message = error instanceof ApiError ? error.message : `预览失败：${error}`;
    return {
      id: `${seller}-${document}`,
      seller,
      document,
      label: `${seller} · ${documentLabel(document)}`,
      preview: null,
      errors: [{ kind: "blocking_error", code: "PREVIEW_REQUEST_FAILED", message }],
      warnings: [],
    };
  }

  function isSoftPreviewIssue(issue: unknown): boolean {
    return getIssueCode(issue) === "NO_LINES_FOR_SELLER";
  }

  function getIssueCode(issue: unknown): string {
    if (!issue || typeof issue !== "object") return "";
    const code = (issue as Record<string, unknown>).code;
    return typeof code === "string" ? code : "";
  }

  function asPreviewWarning(issue: unknown): unknown {
    if (!issue || typeof issue !== "object") return issue;
    return {
      ...(issue as Record<string, unknown>),
      kind: "warning",
      severity: "low",
    };
  }

  return {
    baseFile, poList, loading, error,
    selectedPo, dataRows, dataHeaders,
    selectedSeller, selectedInvoiceNo,
    invoiceOptions,
    preview, previewData, previewDocuments, previewDocType, previewLoading, sourceIndex, previewSourceEntries,
    exporting, lastExportFile,
    blockingErrors, warnings,
    poIssues, issuesLoading, issuesError,
    previewError, exportError,
    poEntry, poStatus,
    openSession, selectPo, refreshPreview, editCell, doExport, doExportGroups,
    selectSeller, selectInvoice, refreshPoIssues,
  };
});
