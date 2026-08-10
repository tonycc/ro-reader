import { ref } from "vue";

const BASE = "/api";

const sessionId = ref("");

export function setSessionId(id: string) { sessionId.value = id; }
export function getSessionId(): string { return sessionId.value; }

export class ApiError extends Error {
  code: string;
  constructor(code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.code = code;
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  if (body) headers["Content-Type"] = "application/json";
  if (sessionId.value) headers["X-Session-Id"] = sessionId.value;

  const opts: RequestInit = {
    method,
    headers: Object.keys(headers).length ? headers : undefined,
    body: body ? JSON.stringify(body) : undefined,
  };
  const resp = await fetch(BASE + path, opts);
  if (!resp.ok) {
    const errBody = await resp.json().catch(() => ({ detail: resp.statusText }));
    const detail = errBody.detail;
    if (typeof detail === "object" && detail !== null && "code" in detail && "message" in detail) {
      throw new ApiError(String(detail.code), String(detail.message));
    }
    throw new ApiError("HTTP_ERROR", typeof detail === "string" ? detail : resp.statusText);
  }
  return resp.json() as Promise<T>;
}

export interface PoListItem {
  po_no: string
  status: "ready" | "partial" | "blocked"
  sellers: string[]
  line_count: number
  invoice_nos: string[]
  invoice_options_by_seller?: Record<string, string[]>
  exportable_documents_by_seller?: Record<string, string[]>
  blocking_count: number
  date: string | null
}

export type PreviewScope = "po" | "invoice"

export interface InvoiceListItem {
  invoice_group_key: string
  display_invoice_no: string
  status: "ready" | "partial" | "blocked" | "done"
  po_nos: string[]
  po_count: number
  sellers: string[]
  seller_invoice_numbers: Record<string, string>
  blocking_count: number
  conflict_count: number
  date: string | null
}

export interface InvoiceListResponse {
  invoices: InvoiceListItem[]
}

export interface InvoiceInspectionRow {
  source_row: number
  po_no: string
  sap: string
  description: string
  category: number | null
  ship_qty: number
  invoice_no: string | null
  factory_document_no: string | null
  sellers: string[]
}

export interface InvoiceInspectionResponse {
  invoice_group_key: string
  display_invoice_no: string
  po_nos: string[]
  line_count: number
  blocking_count: number
  warnings_count: number
  rows: InvoiceInspectionRow[]
  blocking_errors: ValidationIssue[]
  warnings: ValidationIssue[]
}

export interface DryRunRequest {
  base_file: string; po_no: string; seller: string
  invoice_no?: string | null; document?: string; documents?: string[]
  output_format?: "xlsx" | "pdf"
}

export interface BatchExportGroup {
  seller: string
  documents: string[]
  invoice_no?: string | null
}

export type ExportFileFormat = "xlsx" | "pdf"

export interface BatchExportRequest {
  base_file: string
  po_no: string
  groups: BatchExportGroup[]
  output_formats?: ExportFileFormat[]
}

export interface InvoiceBatchExportRequest {
  groups: BatchExportGroup[]
  output_formats?: ExportFileFormat[]
}

export interface DryRunResult {
  status: string; summary: Record<string, unknown>; files: string[]
  output_file: string | null; errors: ValidationIssue[]; warnings: ValidationIssue[]
  missing_inputs: string[]; source_index: SourceIndexEntry[]
}

export interface PreviewColumnLabel { key: string; label: string }
export interface PreviewHeaderCell {
  key?: string
  label: string
  colspan?: number
  rowspan?: number
}

export interface PreviewLayout {
  top: { left: string[]; center: string[]; right: string[] }
  info: { left: string[]; right: string[] }
}

export interface PreviewLine {
  _index: number; _source_row: number | null
  [key: string]: unknown
}

export interface PreviewCostBreakdownLine {
  _index: number; _source_row: number | null
  [key: string]: unknown
}

export interface PreviewTotalExtraItem {
  key: string
  label: string
  value: string
  source_type?: string
  rule?: string
}

export interface PreviewFooterItem {
  key: string
  label: string
  value: string
}

export interface PreviewPayload {
  document_type: string; title: string; seller: string; buyer: string
  po_no: string; pi_no: string | null; invoice_no: string | null
  ship_to: string | null; seller_info: string[]; to_label: string
  terms: Record<string, string>
  header_labels: Record<string, string>
  column_labels: PreviewColumnLabel[]
  column_header_rows?: PreviewHeaderCell[][]
  lines: PreviewLine[]
  cost_breakdown_column_labels?: PreviewColumnLabel[]
  cost_breakdown?: PreviewCostBreakdownLine[]
  totals: Record<string, unknown> & {
    _extra_items?: PreviewTotalExtraItem[]
    _footer_items?: PreviewFooterItem[]
  }
  notes: string[]
  source_entries: PreviewSourceEntry[]
  layout: PreviewLayout
  resolved_values: Record<string, string>
}

export interface PreviewSourceEntry {
  preview_field: string; label: string
  source_type: "base_field" | "computed" | "template_content" | "system_generated" | "manual_input"
  sheet: string | null; row: number | null; field: string | null
  value: string; rule: string
}

export interface PreviewResponse {
  status: string
  preview: PreviewPayload | null
  errors: ValidationIssue[]; warnings: ValidationIssue[]
  missing_inputs: string[]
  options: Record<string, string[]>
}

export interface InvoicePreviewResponse extends PreviewResponse {
  invoice_group_key: string
  display_invoice_no: string
  seller_invoice_no: string | null
  po_nos: string[]
}

export interface PreviewDocumentResult {
  id: string
  seller: string
  document: string
  label: string
  preview: PreviewPayload | null
  errors: ValidationIssue[]
  warnings: ValidationIssue[]
}

export interface SourceIndexEntry {
  doc_cell: string
  source: { sheet: string; row: number | null; field: string; is_computed: boolean }
}

export interface ValidationIssue {
  kind: string
  code: string
  message: string
  sheet: string | null
  row: number | null
  field: string | null
  severity?: "high" | "low" | null
}

export interface PoIssuesResponse {
  po_no: string
  blocking_count: number
  warnings_count: number
  blocking_errors: ValidationIssue[]
  warnings: ValidationIssue[]
}

export interface EditRequest { base_file: string; sheet: string; row: number; field: string; value: unknown }

export interface OpenSessionResponse {
  ok: boolean
  session_id?: string
  po_list: PoListItem[]
  errors?: ValidationIssue[]
}

export interface CheckPathResult {
  ok: boolean
  sheets?: string[]
  size?: number
  error?: string
}

export const api = {
  checkPath: (path: string): Promise<CheckPathResult> =>
    request("POST", "/check-path", { path }),
  openSession: (base_file: string): Promise<OpenSessionResponse> =>
    request("POST", "/session/open", { base_file }),
  getInvoices: (): Promise<InvoiceListResponse> => request("GET", "/invoices"),
  getInvoiceInspection: (invoice_group_key: string): Promise<InvoiceInspectionResponse> =>
    request("GET", `/invoice/${encodeURIComponent(invoice_group_key)}/inspection`),
  previewInvoiceGroup: (
    invoice_group_key: string,
    seller: string,
    document: "INVOICE" | "PL" | "CI" | "RO_PL",
  ): Promise<InvoicePreviewResponse> =>
    request("POST", `/invoice/${encodeURIComponent(invoice_group_key)}/preview`, { seller, document }),
  exportInvoiceGroup: (
    invoice_group_key: string,
    seller: string,
    documents: Array<"INVOICE" | "PL" | "CI" | "RO_PL">,
    output_format: "xlsx" | "pdf" = "xlsx",
  ): Promise<DryRunResult> =>
    request("POST", `/invoice/${encodeURIComponent(invoice_group_key)}/export`, { seller, documents, output_format }),
  exportInvoiceDocumentGroups: (
    invoice_group_key: string,
    groups: BatchExportGroup[],
    output_formats: ExportFileFormat[] = ["xlsx"],
  ): Promise<DryRunResult> =>
    request("POST", `/invoice/${encodeURIComponent(invoice_group_key)}/export-batch`, { groups, output_formats }),
  getDataView: (base_file: string, po_no: string): Promise<{ po_no: string; headers: string[]; rows: Record<string, unknown>[] }> =>
    request("GET", `/po/${po_no}?base_file=${encodeURIComponent(base_file)}`),
  getPoIssues: (base_file: string, po_no: string): Promise<PoIssuesResponse> =>
    request("GET", `/po/${po_no}/issues?base_file=${encodeURIComponent(base_file)}`),
  dryRun: (req: DryRunRequest): Promise<DryRunResult> =>
    request("POST", `/po/${req.po_no}/dry-run`, req),
  preview: (req: DryRunRequest): Promise<PreviewResponse> =>
    request("POST", `/po/${req.po_no}/preview`, req),
  editField: (po_no: string, req: Omit<EditRequest, "po_no">): Promise<{ ok: boolean; message: string }> =>
    request("POST", `/po/${po_no}/edit`, req),
  exportDocuments: (req: DryRunRequest): Promise<DryRunResult> => request("POST", `/po/${req.po_no}/export`, req),
  exportDocumentGroups: (req: BatchExportRequest): Promise<DryRunResult> =>
    request("POST", `/po/${req.po_no}/export-batch`, req),
};
