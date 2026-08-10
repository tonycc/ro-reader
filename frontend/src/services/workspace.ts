import type { InvoiceListItem, PoListItem } from "../stores/api";

export type WorkspaceStatus =
  | "unchecked"
  | "ready"
  | "file_missing"
  | "permission_denied"
  | "profile_not_found"
  | "schema_mismatch";

export interface ProfileSummary {
  id: string;
  display_name: string;
  version: string;
  available: boolean;
  description?: string;
}

export interface CustomerWorkspace {
  id: string;
  display_name: string;
  profile_id: string;
  profile_name: string;
  base_file: string;
  base_file_name: string;
  status: WorkspaceStatus;
  status_message?: string;
  created_at: string;
  updated_at: string;
  last_opened_at?: string | null;
}

export interface WorkspaceInput {
  display_name: string;
  profile_id: string;
  base_file: string;
}

export interface WorkspaceValidationResult {
  status: WorkspaceStatus;
  message: string;
  base_file_name: string;
}

export interface WorkspaceActivationResult {
  workspace: CustomerWorkspace;
  session_id: string;
  po_list: PoListItem[];
  invoices: InvoiceListItem[];
}

export interface WorkspaceBootstrap {
  profiles: ProfileSummary[];
  workspaces: CustomerWorkspace[];
  workspace?: CustomerWorkspace;
  current_workspace_id: string | null;
  session_id: string | null;
  po_list?: PoListItem[];
  invoices?: InvoiceListItem[];
  needs_setup: boolean;
  activation_error?: WorkspaceServiceErrorPayload | null;
}

export interface WorkspaceServiceErrorPayload {
  code: string;
  message: string;
}

export class WorkspaceServiceError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "WorkspaceServiceError";
    this.code = code;
  }
}

export interface WorkspaceService {
  listProfiles(): Promise<ProfileSummary[]>;
  listWorkspaces(): Promise<CustomerWorkspace[]>;
  createWorkspace(input: WorkspaceInput): Promise<CustomerWorkspace>;
  updateWorkspace(id: string, input: WorkspaceInput): Promise<CustomerWorkspace>;
  deleteWorkspace(id: string): Promise<void>;
  validateWorkspaceInput(input: WorkspaceInput): Promise<WorkspaceValidationResult>;
  validateWorkspace(id: string): Promise<CustomerWorkspace>;
  activateWorkspace(id: string): Promise<WorkspaceActivationResult>;
  bootstrap(): Promise<WorkspaceBootstrap>;
}

export function baseFileName(path: string): string {
  const normalized = path.replace(/\\/g, "/").replace(/\/+$/, "");
  return normalized.split("/").pop() || path;
}

export function profileName(profiles: ProfileSummary[], profileId: string): string {
  return profiles.find((profile) => profile.id === profileId)?.display_name ?? profileId;
}

export function workspaceStatusLabel(status: WorkspaceStatus): string {
  const labels: Record<WorkspaceStatus, string> = {
    unchecked: "未检测",
    ready: "可用",
    file_missing: "文件不存在",
    permission_denied: "无权限",
    profile_not_found: "Profile 不存在",
    schema_mismatch: "格式不匹配",
  };
  return labels[status];
}
