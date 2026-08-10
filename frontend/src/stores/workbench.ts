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
  ValidationIssue,
  BatchExportGroup,
  ExportFileFormat,
  InvoiceListItem,
  InvoiceInspectionResponse,
  PreviewScope,
} from "./api";
import { api, setSessionId, getSessionId, ApiError } from "./api";
import type { WorkspaceActivationResult } from "../services/workspace";

export const useWorkbench = defineStore("workbench", () => {
  const baseFile = ref("");
  // 当前 session 绑定的 Customer Profile。旧的 openSession 兼容入口固定使用 RO；
  // 工作区激活入口会把实际 Profile 一并带入，供 Profile 特有的页面交互使用。
  const profileId = ref("ro");
  const poList = ref<PoListItem[]>([]);
  const loading = ref(false);
  const error = ref("");

  const selectedPo = ref("");
  const previewScope = ref<PreviewScope>("po");
  const invoiceList = ref<InvoiceListItem[]>([]);
  const selectedInvoiceGroup = ref("");
  const invoiceInspection = ref<InvoiceInspectionResponse | null>(null);
  const invoiceInspectionLoading = ref(false);
  const invoiceInspectionError = ref("");
  const dataRows = ref<Record<string, unknown>[]>([]);
  const dataHeaders = ref<string[]>([]);

  // Selected seller (one of: SK/YM, GS PTE, EMAX PTE)
  const selectedSeller = ref("");
  const selectedPoSeller = ref("");
  const selectedInvoiceSeller = ref("");
  const selectedInvoiceNo = ref<string | null>(null);

  const preview = ref<DryRunResult | null>(null);
  const previewData = ref<PreviewPayload | null>(null);
  const previewDocuments = ref<PreviewDocumentResult[]>([]);
  const previewDocType = ref("PI");
  const previewLoading = ref(false);
  let previewRequestSerial = 0;
  const sourceIndex = ref<SourceIndexEntry[]>([]);
  const previewSourceEntries = ref<PreviewSourceEntry[]>([]);

  const exporting = ref(false);
  const lastExportFile = ref("");

  const blockingErrors = ref<ValidationIssue[]>([]);
  const warnings = ref<ValidationIssue[]>([]);
  const poIssues = ref<PoIssuesResponse | null>(null);
  const issuesLoading = ref(false);
  const issuesError = ref("");

  const previewError = ref("");
  const exportError = ref("");
  // 未检测到 LibreOffice 时置真，由全局弹窗引导用户下载安装（PDF 导出专用）。
  const libreOfficeMissing = ref(false);

  const poEntry = computed(() => poList.value.find((p) => p.po_no === selectedPo.value));
  const invoiceEntry = computed(() =>
    invoiceList.value.find((item) => item.invoice_group_key === selectedInvoiceGroup.value),
  );
  const poStatus = computed(() => poEntry.value?.status ?? "");
  const invoiceStatus = computed(() => invoiceEntry.value?.status ?? "");
  const invoiceOptions = computed(() => invoiceOptionsForSeller(selectedSeller.value));

  function clearSessionState() {
    previewRequestSerial += 1;
    profileId.value = "ro";
    selectedPo.value = "";
    selectedInvoiceGroup.value = "";
    invoiceInspection.value = null;
    invoiceInspectionLoading.value = false;
    invoiceInspectionError.value = "";
    dataRows.value = [];
    dataHeaders.value = [];
    selectedSeller.value = "";
    selectedPoSeller.value = "";
    selectedInvoiceSeller.value = "";
    selectedInvoiceNo.value = null;
    preview.value = null;
    previewData.value = null;
    previewDocuments.value = [];
    previewLoading.value = false;
    sourceIndex.value = [];
    previewSourceEntries.value = [];
    blockingErrors.value = [];
    warnings.value = [];
    poIssues.value = null;
    issuesLoading.value = false;
    issuesError.value = "";
    previewError.value = "";
    exportError.value = "";
    lastExportFile.value = "";
  }

  function applySessionData(
    file: string,
    sessionId: string,
    nextPoList: PoListItem[],
    nextInvoiceList: InvoiceListItem[],
    nextProfileId = "ro",
  ) {
    baseFile.value = file;
    profileId.value = nextProfileId;
    setSessionId(sessionId);
    poList.value = nextPoList;
    invoiceList.value = nextInvoiceList;
    const defaultInvoice = nextInvoiceList.find((item) => item.status !== "blocked") ?? nextInvoiceList[0];
    selectedInvoiceGroup.value = defaultInvoice?.invoice_group_key ?? "";
    selectedInvoiceSeller.value = defaultInvoice?.sellers[0] ?? "";
  }

  async function openSession(file: string) {
    loading.value = true; error.value = "";
    clearSessionState();
    poList.value = [];
    invoiceList.value = [];
    try {
      baseFile.value = file;
      const data = await api.openSession(file);
      if (!data.ok) throw new Error(data.errors?.[0]?.message ?? "session failed");
      if (!data.session_id) throw new Error("session 响应缺少 session_id");
      setSessionId(data.session_id);
      const invoiceData = await api.getInvoices();
      applySessionData(file, data.session_id, data.po_list, invoiceData.invoices);
    } catch (e) { error.value = String(e); }
    finally { loading.value = false; }
  }

  function adoptWorkspaceSession(activation: WorkspaceActivationResult) {
    loading.value = true;
    error.value = "";
    clearSessionState();
    poList.value = [];
    invoiceList.value = [];
    applySessionData(
      activation.workspace.base_file,
      activation.session_id,
      activation.po_list,
      activation.invoices,
      activation.workspace.profile_id,
    );
    loading.value = false;
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
    if (po?.sellers.length) {
      selectedPoSeller.value = po.sellers[0];
      if (previewScope.value === "po") selectedSeller.value = selectedPoSeller.value;
    }
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

  async function refreshInvoiceInspection() {
    const invoiceGroupKey = selectedInvoiceGroup.value;
    if (!invoiceGroupKey) return;
    invoiceInspectionLoading.value = true;
    invoiceInspectionError.value = "";
    try {
      const result = await api.getInvoiceInspection(invoiceGroupKey);
      if (selectedInvoiceGroup.value === invoiceGroupKey) invoiceInspection.value = result;
    } catch (e) {
      if (selectedInvoiceGroup.value !== invoiceGroupKey) return;
      invoiceInspection.value = null;
      invoiceInspectionError.value = e instanceof ApiError ? e.message : String(e);
    } finally {
      if (selectedInvoiceGroup.value === invoiceGroupKey) invoiceInspectionLoading.value = false;
    }
  }

  async function refreshPreview(docType?: string) {
    if (!baseFile.value || !selectedSeller.value) return;
    if (previewScope.value === "po" && !selectedPo.value) return;
    if (previewScope.value === "invoice" && !selectedInvoiceGroup.value) return;
    const requestedDocument = docType || previewDocType.value;
    const dt = previewScope.value === "invoice"
      ? (isInvoicePlDocument(requestedDocument) ? requestedDocument : "INVOICE_PL")
      : (["PI", "PO"].includes(requestedDocument) ? requestedDocument : "PI");
    const requestSeller = selectedSeller.value;
    const requestSerial = ++previewRequestSerial;
    previewLoading.value = true;
    previewError.value = "";
    previewData.value = null;
    previewDocuments.value = [];
    previewSourceEntries.value = [];
    blockingErrors.value = [];
    warnings.value = [];
    try {
      previewDocType.value = dt;
      const docs = dt === "INVOICE_PL" ? ["INVOICE", "PL"]
                : dt === "CI_PL" ? ["CI", "RO_PL"]
                : [dt];
      const results = await Promise.all(docs.map(async (document) => {
        try {
          const result = previewScope.value === "invoice"
            ? await api.previewInvoiceGroup(
                selectedInvoiceGroup.value,
                requestSeller,
                document as "INVOICE" | "PL" | "CI" | "RO_PL",
              )
            : await api.preview({
                base_file: baseFile.value, po_no: selectedPo.value,
                seller: requestSeller, invoice_no: selectedInvoiceNo.value, document,
              });
          return toPreviewDocument(document, result, requestSeller);
        } catch (e) {
          return toFailedPreviewDocument(document, requestSeller, e);
        }
      }));
      if (requestSerial !== previewRequestSerial) return;
      previewDocuments.value = results;
      previewData.value = results.find((doc) => doc.preview)?.preview ?? null;
      previewSourceEntries.value = results.flatMap((doc) => doc.preview?.source_entries ?? []);
      blockingErrors.value = results.flatMap((doc) => doc.errors);
      warnings.value = results.flatMap((doc) => doc.warnings);
    } catch (e) {
      if (requestSerial !== previewRequestSerial) return;
      previewError.value = e instanceof ApiError ? e.message : `预览失败：${e}`;
    } finally {
      if (requestSerial === previewRequestSerial) previewLoading.value = false;
    }
  }

  async function editCell(field: string, row: number, value: unknown) {
    const result = await api.editField(selectedPo.value, {
      base_file: baseFile.value, sheet: "PO record", row, field, value,
    });
    if (!result.ok) {
      throw new Error(result.message || "字段编辑失败");
    }
    await selectPo(selectedPo.value);
    await refreshPreview();
  }

  type ExportGroup = { seller: string; documents: string[] };

  async function doExport(documents?: string[], outputFormat: "xlsx" | "pdf" = "xlsx") {
    if (!baseFile.value || !selectedSeller.value) return;
    if (previewScope.value === "po" && !selectedPo.value) return;
    if (previewScope.value === "invoice" && !selectedInvoiceGroup.value) return;
    exporting.value = true;
    exportError.value = "";
    try {
      if (previewScope.value === "invoice") {
        const defaultInvoiceDocs = previewDocType.value === "CI_PL"
          ? ["CI", "RO_PL"]
          : previewDocType.value === "CI" ? ["CI"]
          : previewDocType.value === "RO_PL" ? ["RO_PL"]
          : previewDocType.value === "INVOICE" || previewDocType.value === "PL"
            ? [previewDocType.value]
          : ["INVOICE", "PL"];
        const invoiceDocuments = (documents?.length ? documents : defaultInvoiceDocs)
          .filter((document): document is "INVOICE" | "PL" | "CI" | "RO_PL" =>
            document === "INVOICE" || document === "PL" || document === "CI" || document === "RO_PL");
        const result = await api.exportInvoiceGroup(
          selectedInvoiceGroup.value,
          selectedSeller.value,
          invoiceDocuments,
          outputFormat,
        );
        if (result.status !== "success") {
          exportError.value = formatExportFailure(result);
          return result;
        }
        lastExportFile.value = result.output_file ?? "";
        triggerDownload(result, "invoice-export.zip");
        return result;
      }
      const exportDocuments = documents?.length ? documents : [previewDocType.value];
      return await exportOneGroup({
        seller: selectedSeller.value,
        documents: exportDocuments,
      }, outputFormat);
    } catch (e) {
      exportError.value = e instanceof ApiError ? e.message : `导出失败：${e}`;
    } finally { exporting.value = false; }
  }

  async function doExportPdf() {
    return doExport(undefined, "pdf");
  }

  async function doExportGroups(groups: BatchExportGroup[], formats: ExportFileFormat[] = ["xlsx"]) {
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
          invoice_no: group.invoice_no ?? null,
        })),
        output_formats: formats,
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

  async function doExportInvoiceGroups(groups: BatchExportGroup[], formats: ExportFileFormat[] = ["xlsx"]) {
    if (!selectedInvoiceGroup.value || !groups.length) return;
    exporting.value = true;
    exportError.value = "";
    lastExportFile.value = "";
    try {
      const result = await api.exportInvoiceDocumentGroups(
        selectedInvoiceGroup.value,
        groups.map((group) => ({
          seller: group.seller,
          documents: group.documents,
        })),
        formats,
      );
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

  async function exportOneGroup(group: ExportGroup, outputFormat: "xlsx" | "pdf" = "xlsx") {
    const exportDocuments = group.documents;
    if (!exportDocuments.length) return;
    try {
      const payload = {
        base_file: baseFile.value, po_no: selectedPo.value,
        seller: group.seller, invoice_no: invoiceNoForSeller(group.seller),
        document: exportDocuments[0], documents: exportDocuments,
        output_format: outputFormat,
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
    if (previewScope.value === "invoice") selectedInvoiceSeller.value = seller;
    else selectedPoSeller.value = seller;
    if (previewScope.value === "po") syncSelectedInvoiceForSeller();
    return refreshPreview();
  }
  function selectInvoice(inv: string | null) { selectedInvoiceNo.value = inv; return refreshPreview(); }

  function isInvoicePlDocument(document: string): boolean {
    return document === "INVOICE" || document === "PL" || document === "INVOICE_PL"
        || document === "CI" || document === "RO_PL" || document === "CI_PL";
  }

  async function selectPreviewScope(scope: PreviewScope) {
    previewScope.value = scope;
    if (scope === "invoice") {
      const entry = invoiceEntry.value;
      selectedSeller.value = selectedInvoiceSeller.value || entry?.sellers[0] || "";
      const isSinglePfDocument = profileId.value === "pf"
        && (previewDocType.value === "INVOICE" || previewDocType.value === "PL");
      previewDocType.value = isSinglePfDocument
        ? previewDocType.value
        : profileId.value === "pf" ? "INVOICE" : "INVOICE_PL";
    } else {
      selectedSeller.value = selectedPoSeller.value || poEntry.value?.sellers[0] || "";
      previewDocType.value = ["PI", "PO"].includes(previewDocType.value) ? previewDocType.value : "PI";
      syncSelectedInvoiceForSeller();
    }
    await refreshPreview();
  }

  async function selectInvoiceGroup(invoiceGroupKey: string) {
    const groupChanged = selectedInvoiceGroup.value !== invoiceGroupKey;
    selectedInvoiceGroup.value = invoiceGroupKey;
    if (groupChanged) {
      invoiceInspection.value = null;
      invoiceInspectionError.value = "";
    }
    const entry = invoiceEntry.value;
    selectedInvoiceSeller.value = entry?.sellers[0] ?? "";
    if (previewScope.value === "invoice") selectedSeller.value = selectedInvoiceSeller.value;
    await refreshPreview();
  }

  function dismissLibreOfficePrompt() {
    libreOfficeMissing.value = false;
  }

  function formatExportFailure(result: DryRunResult): string {
    // 未装 LibreOffice：改用弹窗引导下载，不显示行内错误（所有导出路径都经此函数）。
    if (result.errors.some((issue) => issue.code === "PDF_CONVERTER_UNAVAILABLE")) {
      libreOfficeMissing.value = true;
      return "";
    }
    const messages = result.errors.map(formatIssueMessage).filter(Boolean);
    if (messages.length) return `导出失败：${messages.join("；")}`;
    if (result.missing_inputs.length) {
      return `导出失败：缺少 ${result.missing_inputs.join(", ")}`;
    }
    return `导出失败：${result.status}`;
  }

  function formatIssueMessage(issue: ValidationIssue): string {
    if (issue.code && issue.message) return `${issue.code}: ${issue.message}`;
    return issue.message || issue.code;
  }

  function documentLabel(document: string): string {
    if (document === "INVOICE") return "Invoice";
    if (document === "PL") return "PL";
    if (document === "CI") return "CI";
    if (document === "RO_PL") return "RO PL";
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
      errors: [{ kind: "blocking_error", code: "PREVIEW_REQUEST_FAILED", message, sheet: null, row: null, field: null }],
      warnings: [],
    };
  }

  function isSoftPreviewIssue(issue: ValidationIssue): boolean {
    return issue.code === "NO_LINES_FOR_SELLER";
  }

  function asPreviewWarning(issue: ValidationIssue): ValidationIssue {
    return { ...issue, kind: "warning", severity: "low" };
  }

  return {
    baseFile, profileId, poList, invoiceList, loading, error,
    selectedPo, selectedInvoiceGroup, previewScope, dataRows, dataHeaders,
    invoiceInspection, invoiceInspectionLoading, invoiceInspectionError,
    selectedSeller, selectedInvoiceNo,
    invoiceOptions,
    preview, previewData, previewDocuments, previewDocType, previewLoading, sourceIndex, previewSourceEntries,
    exporting, lastExportFile,
    blockingErrors, warnings,
    poIssues, issuesLoading, issuesError,
    previewError, exportError, libreOfficeMissing,
    poEntry, poStatus, invoiceEntry, invoiceStatus,
    openSession, adoptWorkspaceSession, selectPo, refreshPreview, editCell, doExport, doExportPdf, doExportGroups, doExportInvoiceGroups,
    selectSeller, selectInvoice, selectPreviewScope, selectInvoiceGroup,
    refreshPoIssues, refreshInvoiceInspection, dismissLibreOfficePrompt,
  };
});
