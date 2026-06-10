const BASE = "/api";

let _sessionId = "";

export function setSessionId(id: string) { _sessionId = id; }
export function getSessionId(): string { return _sessionId; }

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
    throw new Error(errBody.detail ?? resp.statusText);
  }
  return resp.json() as Promise<T>;
}

export interface PoListItem {
  po_no: string
  status: "ready" | "partial" | "blocked"
  sellers: string[]
  line_count: number
  invoice_nos: string[]
  blocking_count: number
}

export interface DryRunRequest {
  base_file: string; po_no: string; seller: string
  buyer?: string | null
  invoice_no?: string | null; document?: string
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

export interface SourceIndexEntry {
  doc_cell: string
  source: { sheet: string; row: number | null; field: string; is_computed: boolean }
}

export interface EditRequest { base_file: string; sheet: string; row: number; field: string; value: unknown }

export interface OpenSessionResponse {
  ok: boolean
  session_id?: string
  po_list: PoListItem[]
  errors?: unknown[]
}

export const api = {
  openSession: (base_file: string): Promise<OpenSessionResponse> =>
    request("POST", "/session/open", { base_file }),
  getDataView: (base_file: string, po_no: string): Promise<{ po_no: string; headers: string[]; rows: Record<string, unknown>[] }> =>
    request("GET", `/po/${po_no}?base_file=${encodeURIComponent(base_file)}`),
  dryRun: (req: DryRunRequest): Promise<DryRunResult> =>
    request("POST", `/po/${req.po_no}/dry-run`, req),
  preview: (req: DryRunRequest): Promise<PreviewResponse> =>
    request("POST", `/po/${req.po_no}/preview`, req),
  editField: (po_no: string, req: Omit<EditRequest, "po_no">): Promise<{ ok: boolean; message: string }> =>
    request("POST", `/po/${po_no}/edit`, req),
  exportDocuments: (req: DryRunRequest): Promise<DryRunResult> => request("POST", "/export", req),
};
