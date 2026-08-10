import { computed, ref, shallowRef } from "vue";
import { defineStore } from "pinia";
import {
  type CustomerWorkspace,
  type ProfileSummary,
  type WorkspaceActivationResult,
  type WorkspaceBootstrap,
  type WorkspaceInput,
  type WorkspaceService,
  WorkspaceServiceError,
  type WorkspaceStatus,
} from "../services/workspace";

export const useWorkspace = defineStore("workspace", () => {
  const service = shallowRef<WorkspaceService | null>(null);
  const profiles = ref<ProfileSummary[]>([]);
  const workspaces = ref<CustomerWorkspace[]>([]);
  const currentWorkspaceId = ref<string | null>(null);
  const sessionId = ref("");
  const loading = ref(false);
  const switching = ref(false);
  const saving = ref(false);
  const error = ref("");
  const initialized = ref(false);
  // 当前工作区配置修改后，旧 session 仍可继续使用，但必须重新激活。
  const needsActivation = ref(false);
  const lastActivation = shallowRef<WorkspaceActivationResult | null>(null);

  const currentWorkspace = computed(() =>
    workspaces.value.find((workspace) => workspace.id === currentWorkspaceId.value) ?? null,
  );
  const availableProfiles = computed(() => profiles.value.filter((profile) => profile.available));
  const canSwitch = computed(() => !switching.value && !saving.value);

  function configure(nextService: WorkspaceService) {
    if (service.value === nextService) return;
    service.value = nextService;
    initialized.value = false;
    error.value = "";
    needsActivation.value = false;
  }

  function requireService(): WorkspaceService {
    if (!service.value) throw new WorkspaceServiceError("WORKSPACE_SERVICE_UNAVAILABLE", "工作区服务尚未初始化");
    return service.value;
  }

  function applyBootstrap(data: WorkspaceBootstrap) {
    profiles.value = data.profiles;
    workspaces.value = data.workspaces;
    currentWorkspaceId.value = data.current_workspace_id;
    sessionId.value = data.session_id ?? "";
    needsActivation.value = Boolean(data.current_workspace_id && !data.session_id);
    if (data.workspace && data.session_id && data.po_list && data.invoices) {
      lastActivation.value = {
        workspace: data.workspace,
        session_id: data.session_id,
        po_list: data.po_list,
        invoices: data.invoices,
      };
      needsActivation.value = false;
    } else {
      lastActivation.value = null;
      if (data.activation_error) needsActivation.value = Boolean(data.current_workspace_id);
    }
  }

  async function bootstrap() {
    loading.value = true;
    error.value = "";
    try {
      const data = await requireService().bootstrap();
      applyBootstrap(data);
      initialized.value = true;
      return data;
    } catch (cause) {
      error.value = messageFor(cause);
      throw cause;
    } finally {
      loading.value = false;
    }
  }

  async function createWorkspace(input: WorkspaceInput) {
    saving.value = true;
    error.value = "";
    try {
      const workspace = await requireService().createWorkspace(input);
      workspaces.value = [...workspaces.value, workspace];
      return workspace;
    } catch (cause) {
      error.value = messageFor(cause);
      throw cause;
    } finally {
      saving.value = false;
    }
  }

  async function updateWorkspace(id: string, input: WorkspaceInput) {
    saving.value = true;
    error.value = "";
    try {
      const updated = await requireService().updateWorkspace(id, input);
      replaceWorkspace(updated);
      if (id === currentWorkspaceId.value) needsActivation.value = true;
      return updated;
    } catch (cause) {
      error.value = messageFor(cause);
      throw cause;
    } finally {
      saving.value = false;
    }
  }

  async function deleteWorkspace(id: string) {
    saving.value = true;
    error.value = "";
    try {
      await requireService().deleteWorkspace(id);
      workspaces.value = workspaces.value.filter((workspace) => workspace.id !== id);
    } catch (cause) {
      error.value = messageFor(cause);
      throw cause;
    } finally {
      saving.value = false;
    }
  }

  async function validateWorkspace(id: string) {
    saving.value = true;
    error.value = "";
    try {
      const validated = await requireService().validateWorkspace(id);
      replaceWorkspace(validated);
      return validated;
    } catch (cause) {
      error.value = messageFor(cause);
      throw cause;
    } finally {
      saving.value = false;
    }
  }

  async function validateWorkspaceInput(input: WorkspaceInput) {
    saving.value = true;
    error.value = "";
    try {
      return await requireService().validateWorkspaceInput(input);
    } catch (cause) {
      error.value = messageFor(cause);
      throw cause;
    } finally {
      saving.value = false;
    }
  }

  async function activateWorkspace(id: string): Promise<WorkspaceActivationResult> {
    if (!canSwitch.value) throw new WorkspaceServiceError("WORKSPACE_BUSY", "当前工作区仍在处理中");
    switching.value = true;
    error.value = "";
    try {
      const result = await requireService().activateWorkspace(id);
      replaceWorkspace(result.workspace);
      currentWorkspaceId.value = result.workspace.id;
      sessionId.value = result.session_id;
      needsActivation.value = false;
      lastActivation.value = result;
      return result;
    } catch (cause) {
      error.value = messageFor(cause);
      throw cause;
    } finally {
      switching.value = false;
    }
  }

  function replaceWorkspace(updated: CustomerWorkspace) {
    workspaces.value = workspaces.value.map((workspace) =>
      workspace.id === updated.id ? updated : workspace,
    );
  }

  function messageFor(cause: unknown): string {
    return cause instanceof Error ? cause.message : String(cause);
  }

  function profileDisplayName(profileId: string): string {
    return profiles.value.find((profile) => profile.id === profileId)?.display_name ?? profileId;
  }

  function clearLastActivation() {
    lastActivation.value = null;
  }

  function statusLabel(status: WorkspaceStatus): string {
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

  return {
    profiles,
    availableProfiles,
    workspaces,
    currentWorkspaceId,
    currentWorkspace,
    sessionId,
    loading,
    switching,
    saving,
    canSwitch,
    error,
    initialized,
    needsActivation,
    lastActivation,
    configure,
    bootstrap,
    createWorkspace,
    updateWorkspace,
    deleteWorkspace,
    validateWorkspaceInput,
    validateWorkspace,
    activateWorkspace,
    clearLastActivation,
    profileDisplayName,
    statusLabel,
  };
});
