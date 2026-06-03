const BASE = "http://127.0.0.1:54321";

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const opts: RequestInit = {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  };
  const resp = await fetch(BASE + path, opts);
  if (!resp.ok) throw new Error((await resp.json().catch(() => ({ detail: resp.statusText }))).detail ?? resp.statusText);
  return resp.json() as Promise<T>;
}

export interface PoListItem {
  po_no: string
  status: "ready" | "partial" | "blocked"
  sellers: string[]
  line_count: number
  monthly_months: string[]
  blocking_count: number
}

export interface SessionData { ok: boolean; po_list: PoListItem[]; errors?: unknown[] }
export interface DataView { po_no: string; headers: string[]; rows: Record<string, unknown>[] }

export interface DryRunRequest {
  base_file: string; po_no: string; seller: string
  buyer?: string | null; invoice_month?: string | null
  invoice_no?: string | null; document?: string
}

export interface DryRunResult {
  status: string; summary: Record<string, unknown>; files: string[]
  output_file: string | null; errors: unknown[]; warnings: unknown[]
  missing_inputs: string[]; source_index: SourceIndexEntry[]
}

export interface SourceIndexEntry {
  doc_cell: string
  source: { sheet: string; row: number | null; field: string; is_computed: boolean }
}

export interface EditRequest { base_file: string; sheet: string; row: number; field: string; value: unknown }

export const api = {
  health: (): Promise<{ status: string }> => request("GET", "/health"),
  openSession: (base_file: string): Promise<SessionData> => request("POST", "/session/open", { base_file }),
  getDataView: (base_file: string, po_no: string): Promise<DataView> =>
    request("GET", `/po/${po_no}?base_file=${encodeURIComponent(base_file)}`),
  dryRun: (req: DryRunRequest): Promise<DryRunResult> =>
    request("POST", `/po/${req.po_no}/dry-run`, req),
  editField: (po_no: string, req: Omit<EditRequest, "po_no">): Promise<{ ok: boolean; message: string }> =>
    request("POST", `/po/${po_no}/edit`, req),
  exportDocuments: (req: DryRunRequest): Promise<DryRunResult> => request("POST", "/export", req),
};
