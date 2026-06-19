const BASE = "/api";

let _sessionId = "";

export function setSessionId(id: string) { _sessionId = id; }
export function getSessionId(): string { return _sessionId; }

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
  if (_sessionId) headers["X-Session-Id"] = _sessionId;

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
}

export interface DryRunRequest {
  base_file: string; po_no: string; seller: string
  invoice_no?: string | null; document?: string; documents?: string[]
}

export interface BatchExportGroup {
  seller: string
  documents: string[]
  invoice_no?: string | null
}

export interface BatchExportRequest {
  base_file: string
  po_no: string
  groups: BatchExportGroup[]
}

export interface DryRunResult {
  status: string; summary: Record<string, unknown>; files: string[]
  output_file: string | null; errors: unknown[]; warnings: unknown[]
  missing_inputs: string[]; source_index: SourceIndexEntry[]
}

export interface PreviewColumnLabel { key: string; label: string }

export interface PreviewLayout {
  top: { left: string[]; center: string[]; right: string[] }
  info: { left: string[]; right: string[] }
}

export interface PreviewLine {
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
  column_labels: PreviewColumnLabel[]
  lines: PreviewLine[]
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
  errors: unknown[]; warnings: unknown[]
  missing_inputs: string[]
  options: Record<string, string[]>
}

export interface PreviewDocumentResult {
  id: string
  seller: string
  document: string
  label: string
  preview: PreviewPayload | null
  errors: unknown[]
  warnings: unknown[]
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
  errors?: unknown[]
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
