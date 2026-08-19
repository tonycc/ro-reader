import {
  baseFileName,
  type CustomerWorkspace,
  type ProfileSummary,
  type WorkspaceActivationResult,
  type WorkspaceBootstrap,
  type WorkspaceInput,
  type WorkspaceService,
  WorkspaceServiceError,
  type WorkspaceStatus,
  type WorkspaceValidationResult,
} from "./workspace";

const DEMO_PROFILES: ProfileSummary[] = [
  {
    id: "ro",
    display_name: "Rather Outdoors",
    version: "ro_v1",
    available: true,
    description: "当前已支持的 RO 单据流程",
  },
  {
    id: "pf",
    display_name: "PF",
    version: "pf_v1",
    available: true,
    description: "PF 单据流程（含 MOQ 与整箱提醒）",
  },
];

const INITIAL_WORKSPACES: CustomerWorkspace[] = [
  makeWorkspace("ro-2026", {
    display_name: "RO 2026",
    profile_id: "ro",
    base_file: "/data/ro/RO DATA BASE.xlsx",
  }, "ready", "本地 base 文件已通过检测"),
  makeWorkspace("ro-test", {
    display_name: "RO 测试",
    profile_id: "ro",
    base_file: "/data/ro/missing-test-base.xlsx",
  }, "file_missing", "示例：文件已被移动，请重新选择 base 文件"),
];

let idSeed = 1;
let sessionSeed = 1;

function now(): string {
  return new Date().toISOString();
}

function makeWorkspace(
  id: string,
  input: WorkspaceInput,
  status: WorkspaceStatus = "unchecked",
  statusMessage?: string,
): CustomerWorkspace {
  const timestamp = now();
  return {
    id,
    display_name: input.display_name,
    profile_id: input.profile_id,
    profile_name: profileNameFromDemoProfiles(input.profile_id),
    base_file: input.base_file,
    base_file_name: baseFileName(input.base_file),
    status,
    status_message: statusMessage,
    created_at: timestamp,
    updated_at: timestamp,
    last_opened_at: null,
  };
}

function profileNameFromDemoProfiles(profileId: string): string {
  return DEMO_PROFILES.find((profile) => profile.id === profileId)?.display_name ?? profileId;
}

function cloneWorkspace(workspace: CustomerWorkspace): CustomerWorkspace {
  return { ...workspace };
}

function cloneList(workspaces: CustomerWorkspace[]): CustomerWorkspace[] {
  return workspaces.map(cloneWorkspace);
}

function wait(ms = 180): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function statusFor(input: WorkspaceInput): { status: WorkspaceStatus; message?: string } {
  if (!DEMO_PROFILES.some((profile) => profile.id === input.profile_id && profile.available)) {
    return { status: "profile_not_found", message: "该 Profile 仅用于交互演示，尚未提供业务规则" };
  }
  const path = input.base_file.toLowerCase();
  if (!path.trim() || path.includes("missing") || path.includes("not-found")) {
    return { status: "file_missing", message: "找不到 base 文件，请检查路径" };
  }
  if (path.includes("schema-error")) {
    return { status: "schema_mismatch", message: "文件缺少 DATA BASE 或 PO record Sheet" };
  }
  return { status: "ready", message: "本地 base 文件已通过检测" };
}

export class MockWorkspaceService implements WorkspaceService {
  private readonly profiles = DEMO_PROFILES.map((profile) => ({ ...profile }));
  private workspaces = cloneList(INITIAL_WORKSPACES);
  private currentWorkspaceId: string | null = "ro-2026";

  async listProfiles(): Promise<ProfileSummary[]> {
    await wait();
    return this.profiles.map((profile) => ({ ...profile }));
  }

  async listWorkspaces(): Promise<CustomerWorkspace[]> {
    await wait();
    return cloneList(this.workspaces);
  }

  async createWorkspace(input: WorkspaceInput): Promise<CustomerWorkspace> {
    await wait();
    this.assertInput(input);
    const workspace = makeWorkspace(`workspace-${idSeed++}`, input);
    this.workspaces.push(workspace);
    return cloneWorkspace(workspace);
  }

  async updateWorkspace(id: string, input: WorkspaceInput): Promise<CustomerWorkspace> {
    await wait();
    this.assertInput(input);
    const index = this.workspaces.findIndex((workspace) => workspace.id === id);
    if (index < 0) throw new WorkspaceServiceError("WORKSPACE_NOT_FOUND", "工作区不存在");
    const previous = this.workspaces[index];
    const updated: CustomerWorkspace = {
      ...previous,
      ...input,
      profile_name: profileNameFromDemoProfiles(input.profile_id),
      base_file_name: baseFileName(input.base_file),
      status: "unchecked",
      status_message: "配置已修改，请重新检测并激活",
      updated_at: now(),
    };
    this.workspaces[index] = updated;
    return cloneWorkspace(updated);
  }

  async deleteWorkspace(id: string): Promise<void> {
    await wait();
    if (id === this.currentWorkspaceId) {
      throw new WorkspaceServiceError("WORKSPACE_CURRENT_DELETE_FORBIDDEN", "当前工作区不能直接删除，请先切换到其他工作区");
    }
    const index = this.workspaces.findIndex((workspace) => workspace.id === id);
    if (index < 0) throw new WorkspaceServiceError("WORKSPACE_NOT_FOUND", "工作区不存在");
    this.workspaces.splice(index, 1);
  }

  async validateWorkspaceInput(input: WorkspaceInput): Promise<WorkspaceValidationResult> {
    await wait(260);
    this.assertInput(input);
    const result = statusFor(input);
    return {
      ...result,
      message: result.message ?? "本地 base 文件已通过检测",
      base_file_name: baseFileName(input.base_file),
    };
  }

  async validateWorkspace(id: string): Promise<CustomerWorkspace> {
    await wait(260);
    const index = this.indexOf(id);
    const workspace = this.workspaces[index];
    const result = statusFor(workspace);
    const updated: CustomerWorkspace = {
      ...workspace,
      ...result,
      updated_at: now(),
    };
    this.workspaces[index] = updated;
    return cloneWorkspace(updated);
  }

  async activateWorkspace(id: string): Promise<WorkspaceActivationResult> {
    await wait(360);
    const index = this.indexOf(id);
    const workspace = this.workspaces[index];
    const result = statusFor(workspace);
    if (result.status !== "ready") {
      const updated = { ...workspace, ...result, updated_at: now() };
      this.workspaces[index] = updated;
      this.currentWorkspaceId = id;
      throw new WorkspaceServiceError(result.status.toUpperCase(), result.message ?? "工作区无法激活");
    }
    const opened = {
      ...workspace,
      ...result,
      last_opened_at: now(),
      updated_at: now(),
    };
    this.workspaces[index] = opened;
    this.currentWorkspaceId = id;
    return {
      workspace: cloneWorkspace(opened),
      session_id: `mock-session-${sessionSeed++}`,
      po_list: [],
      invoices: [],
    };
  }

  async bootstrap(): Promise<WorkspaceBootstrap> {
    await wait(240);
    return {
      profiles: await this.listProfiles(),
      workspaces: await this.listWorkspaces(),
      current_workspace_id: this.currentWorkspaceId,
      session_id: this.currentWorkspaceId ? "mock-session-0" : null,
      needs_setup: this.workspaces.length === 0,
      activation_error: null,
    };
  }

  private indexOf(id: string): number {
    const index = this.workspaces.findIndex((workspace) => workspace.id === id);
    if (index < 0) throw new WorkspaceServiceError("WORKSPACE_NOT_FOUND", "工作区不存在");
    return index;
  }

  private assertInput(input: WorkspaceInput): void {
    if (!input.display_name.trim()) {
      throw new WorkspaceServiceError("WORKSPACE_NAME_REQUIRED", "请输入工作区名称");
    }
    if (!input.profile_id) {
      throw new WorkspaceServiceError("PROFILE_REQUIRED", "请选择 Profile");
    }
    if (!input.base_file.trim()) {
      throw new WorkspaceServiceError("WORKSPACE_FILE_REQUIRED", "请输入 base 文件路径");
    }
  }
}

export function createMockWorkspaceService(): WorkspaceService {
  return new MockWorkspaceService();
}
