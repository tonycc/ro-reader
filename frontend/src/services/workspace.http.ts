import {
  type CustomerWorkspace,
  type ProfileSummary,
  type WorkspaceActivationResult,
  type WorkspaceBootstrap,
  type WorkspaceInput,
  type WorkspaceService,
  WorkspaceServiceError,
  type WorkspaceValidationResult,
} from "./workspace";

interface ErrorDetail {
  code?: unknown;
  message?: unknown;
}

/** Real HTTP adapter for the FastAPI workspace contract. */
export class HttpWorkspaceService implements WorkspaceService {
  private readonly basePath: string;

  constructor(basePath = "/api") {
    this.basePath = basePath;
  }

  async listProfiles(): Promise<ProfileSummary[]> {
    const payload = await this.request<{ profiles: ProfileSummary[] }>("GET", "/profiles");
    return payload.profiles;
  }

  async listWorkspaces(): Promise<CustomerWorkspace[]> {
    const payload = await this.request<{ workspaces: CustomerWorkspace[] }>("GET", "/workspaces");
    return payload.workspaces;
  }

  createWorkspace(input: WorkspaceInput): Promise<CustomerWorkspace> {
    return this.request<CustomerWorkspace>("POST", "/workspaces", input);
  }

  updateWorkspace(id: string, input: WorkspaceInput): Promise<CustomerWorkspace> {
    return this.request<CustomerWorkspace>("PATCH", `/workspaces/${encodeURIComponent(id)}`, input);
  }

  async deleteWorkspace(id: string): Promise<void> {
    await this.request<{ status: string }>("DELETE", `/workspaces/${encodeURIComponent(id)}`);
  }

  validateWorkspaceInput(input: WorkspaceInput): Promise<WorkspaceValidationResult> {
    return this.request<WorkspaceValidationResult>("POST", "/workspaces/validate", input);
  }

  validateWorkspace(id: string): Promise<CustomerWorkspace> {
    return this.request<CustomerWorkspace>(
      "POST",
      `/workspaces/${encodeURIComponent(id)}/validate`,
    );
  }

  activateWorkspace(id: string): Promise<WorkspaceActivationResult> {
    return this.request<WorkspaceActivationResult>(
      "POST",
      `/workspaces/${encodeURIComponent(id)}/activate`,
    );
  }

  bootstrap(): Promise<WorkspaceBootstrap> {
    return this.request<WorkspaceBootstrap>("GET", "/bootstrap");
  }

  private async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const response = await fetch(`${this.basePath}${path}`, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });

    const payload = await response.json().catch(() => null) as unknown;
    if (!response.ok) {
      throw this.toError(response.status, response.statusText, payload);
    }
    return payload as T;
  }

  private toError(status: number, statusText: string, payload: unknown): WorkspaceServiceError {
    const detail = this.detailFrom(payload);
    const code = typeof detail?.code === "string" ? detail.code : `HTTP_${status}`;
    const message = typeof detail?.message === "string"
      ? detail.message
      : typeof payload === "string" ? payload : statusText || "工作区请求失败";
    return new WorkspaceServiceError(code, message);
  }

  private detailFrom(payload: unknown): ErrorDetail | null {
    if (!payload || typeof payload !== "object") return null;
    const detail = (payload as { detail?: unknown }).detail;
    if (!detail || typeof detail !== "object") return null;
    return detail as ErrorDetail;
  }
}

export function createHttpWorkspaceService(basePath = "/api"): WorkspaceService {
  return new HttpWorkspaceService(basePath);
}
