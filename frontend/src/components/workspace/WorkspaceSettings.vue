<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useWorkspace } from "../../stores/workspace";
import type { CustomerWorkspace, WorkspaceInput, WorkspaceValidationResult } from "../../services/workspace";
import WorkspaceForm from "./WorkspaceForm.vue";
import WorkspaceStatusBadge from "./WorkspaceStatusBadge.vue";

const props = defineProps<{
  open: boolean;
}>();

const emit = defineEmits<{
  close: [];
}>();

const workspace = useWorkspace();
const editingWorkspace = ref<CustomerWorkspace | null>(null);
const formVisible = ref(false);
const operationMessage = ref("");
const operationKind = ref<"success" | "error" | "">("");
const pathChecking = ref(false);
const pathCheckResult = ref<WorkspaceValidationResult | null>(null);
const profileById = computed(() => new Map(workspace.profiles.map((profile) => [profile.id, profile.display_name])));

watch(() => props.open, (open) => {
  if (open) {
    formVisible.value = false;
    editingWorkspace.value = null;
    operationMessage.value = "";
    operationKind.value = "";
    pathChecking.value = false;
    pathCheckResult.value = null;
  }
});

function openCreate() {
  editingWorkspace.value = null;
  formVisible.value = true;
  clearPathCheck();
  clearOperation();
}

function openEdit(item: CustomerWorkspace) {
  editingWorkspace.value = item;
  formVisible.value = true;
  clearPathCheck();
  clearOperation();
}

function closeForm() {
  formVisible.value = false;
  editingWorkspace.value = null;
  clearPathCheck();
}

async function save(input: WorkspaceInput) {
  clearOperation();
  try {
    if (editingWorkspace.value) {
      await workspace.updateWorkspace(editingWorkspace.value.id, input);
      showOperation("success", "配置已保存，请重新检测并激活");
    } else {
      await workspace.createWorkspace(input);
      showOperation("success", "工作区已创建，请检测后设为当前");
    }
    closeForm();
  } catch (cause) {
    showOperation("error", cause instanceof Error ? cause.message : String(cause));
  }
}

async function validateInput(input: WorkspaceInput) {
  clearOperation();
  pathChecking.value = true;
  pathCheckResult.value = null;
  try {
    pathCheckResult.value = await workspace.validateWorkspaceInput(input);
  } catch (cause) {
    showOperation("error", cause instanceof Error ? cause.message : String(cause));
  } finally {
    pathChecking.value = false;
  }
}

async function validate(item: CustomerWorkspace) {
  clearOperation();
  try {
    const result = await workspace.validateWorkspace(item.id);
    showOperation(result.status === "ready" ? "success" : "error", result.status_message ?? workspace.statusLabel(result.status));
  } catch (cause) {
    showOperation("error", cause instanceof Error ? cause.message : String(cause));
  }
}

async function activate(item: CustomerWorkspace) {
  clearOperation();
  try {
    await workspace.activateWorkspace(item.id);
    showOperation("success", `已切换到「${item.display_name}」`);
  } catch (cause) {
    showOperation("error", cause instanceof Error ? cause.message : String(cause));
  }
}

async function remove(item: CustomerWorkspace) {
  if (item.id === workspace.currentWorkspaceId) return;
  if (!window.confirm(`确定删除工作区「${item.display_name}」吗？只会删除配置，不会删除 base 文件。`)) return;
  clearOperation();
  try {
    await workspace.deleteWorkspace(item.id);
    showOperation("success", "工作区配置已删除");
  } catch (cause) {
    showOperation("error", cause instanceof Error ? cause.message : String(cause));
  }
}

function showOperation(kind: "success" | "error", message: string) {
  operationKind.value = kind;
  operationMessage.value = message;
}

function clearOperation() {
  operationKind.value = "";
  operationMessage.value = "";
  workspace.error = "";
}

function clearPathCheck() {
  pathChecking.value = false;
  pathCheckResult.value = null;
}
</script>

<template>
  <Teleport to="body">
    <div v-if="props.open" class="settings-overlay" data-testid="workspace-settings" @click.self="emit('close')">
      <section class="settings-panel" role="dialog" aria-modal="true" aria-labelledby="workspace-settings-title">
        <header class="settings-header">
          <div>
            <p class="eyebrow">WORKSPACE CONFIGURATION</p>
            <h2 id="workspace-settings-title">工作区设置</h2>
            <p class="settings-intro">每个工作区绑定一个 Customer Profile 和一个本机 base 文件。</p>
          </div>
          <button type="button" class="close-button" aria-label="关闭工作区设置" @click="emit('close')">✕</button>
        </header>

        <div class="settings-content">
          <div v-if="operationMessage" class="operation-message" :class="operationKind" data-testid="workspace-operation-message">
            {{ operationMessage }}
          </div>
          <div v-if="workspace.error && !operationMessage" class="operation-message error">
            {{ workspace.error }}
          </div>

          <div class="toolbar-row">
            <div>
              <strong>已配置工作区</strong>
              <span>{{ workspace.workspaces.length }} 个</span>
            </div>
            <button type="button" class="primary-button" :disabled="workspace.saving || workspace.switching" @click="openCreate">
              ＋ 新增工作区
            </button>
          </div>

          <div v-if="workspace.loading" class="empty-state">正在读取工作区…</div>
          <div v-else-if="!workspace.workspaces.length" class="empty-state">
            还没有工作区。新增后即可在顶部栏快速切换。
          </div>
          <div v-else class="workspace-list">
            <article
              v-for="item in workspace.workspaces"
              :key="item.id"
              class="workspace-card"
              :class="{ current: item.id === workspace.currentWorkspaceId }"
              :data-testid="`workspace-card-${item.id}`"
            >
              <div class="card-main">
                <div class="card-title-row">
                  <strong>{{ item.display_name }}</strong>
                  <span v-if="item.id === workspace.currentWorkspaceId" class="current-label">当前</span>
                  <span
                    v-if="item.id === workspace.currentWorkspaceId && workspace.needsActivation"
                    class="pending-label"
                  >待重新激活</span>
                  <WorkspaceStatusBadge :status="item.status" compact />
                </div>
                <div class="card-meta">{{ profileById.get(item.profile_id) ?? item.profile_id }} · {{ item.base_file_name }}</div>
                <div class="card-path" :title="item.base_file">{{ item.base_file }}</div>
                <p v-if="item.status_message" class="card-message" :class="{ danger: item.status !== 'ready' }">{{ item.status_message }}</p>
              </div>
              <div class="card-actions">
                <button type="button" class="text-button" :disabled="workspace.saving || workspace.switching" @click="validate(item)">检测</button>
                <button
                  type="button"
                  class="text-button primary-text"
                  :disabled="workspace.saving || workspace.switching || (item.id === workspace.currentWorkspaceId && !workspace.needsActivation)"
                  @click="activate(item)"
                >
                  {{ item.id === workspace.currentWorkspaceId && workspace.needsActivation ? '重新激活' : '设为当前' }}
                </button>
                <button type="button" class="text-button" :disabled="workspace.saving || workspace.switching" @click="openEdit(item)">编辑</button>
                <button type="button" class="text-button danger-text" :disabled="workspace.saving || workspace.switching || item.id === workspace.currentWorkspaceId" @click="remove(item)">删除</button>
              </div>
            </article>
          </div>

        </div>

        <footer v-if="!formVisible" class="settings-footer">
          <span>配置只影响工作区，不会删除 base 文件。</span>
          <button type="button" class="secondary-button" data-testid="close-workspace-settings" @click="emit('close')">关闭设置</button>
        </footer>
      </section>

      <div v-if="formVisible" class="form-overlay" @click.self="closeForm">
        <section class="form-dialog" data-testid="workspace-form-dialog" role="dialog" aria-modal="true" aria-labelledby="workspace-form-title">
          <WorkspaceForm
            :workspace="editingWorkspace"
            :profiles="workspace.profiles"
            :busy="workspace.saving"
            :validating="pathChecking"
            :validation="pathCheckResult"
            @save="save"
            @validate="validateInput"
            @changed="clearPathCheck"
            @cancel="closeForm"
          />
        </section>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.settings-overlay { position: fixed; inset: 0; z-index: 1100; display: grid; place-items: center; padding: 28px; background: rgba(21, 32, 51, 0.36); }
.settings-panel { width: min(760px, 100%); max-height: min(820px, 90vh); display: flex; flex-direction: column; overflow: hidden; border: 1px solid var(--line); border-radius: 16px; background: var(--panel); box-shadow: 0 24px 70px rgba(21, 32, 51, 0.22); }
.form-overlay { position: fixed; inset: 0; z-index: 1200; display: grid; place-items: center; padding: 20px; background: rgba(21, 32, 51, 0.28); }
.form-dialog { width: min(520px, 100%); max-height: min(680px, 90vh); overflow: auto; border: 1px solid var(--line); border-radius: 14px; background: var(--panel); box-shadow: 0 24px 70px rgba(21, 32, 51, 0.24); }
.settings-header { display: flex; justify-content: space-between; gap: 18px; padding: 24px 26px 18px; border-bottom: 1px solid var(--line); }
.eyebrow { margin: 0 0 5px; color: var(--blue); font-size: 10px; font-weight: 800; letter-spacing: .1em; }
.settings-header h2 { margin: 0 0 6px; font-size: 20px; }
.settings-intro { margin: 0; color: var(--muted); font-size: 12px; }
.close-button { width: 30px; height: 30px; border: 0; border-radius: 7px; background: transparent; color: var(--muted); cursor: pointer; }
.close-button:hover { background: var(--red-weak); color: var(--red); }
.settings-content { overflow: auto; min-height: 0; padding: 20px 26px; }
.operation-message { margin-bottom: 14px; padding: 9px 11px; border-radius: 8px; font-size: 12px; line-height: 1.45; }
.operation-message.success { color: var(--green); background: var(--green-weak); }
.operation-message.error { color: var(--red); background: var(--red-weak); }
.toolbar-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.toolbar-row > div { display: flex; align-items: baseline; gap: 8px; }
.toolbar-row > div span { color: var(--muted); font-size: 12px; }
.workspace-list { display: grid; gap: 9px; }
.workspace-card { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; padding: 14px; border: 1px solid var(--line); border-radius: 10px; background: var(--panel); }
.workspace-card.current { border-color: #9ab9ff; background: #fbfdff; box-shadow: inset 3px 0 var(--blue); }
.card-main { min-width: 0; flex: 1; }
.card-title-row { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; margin-bottom: 5px; }
.card-title-row strong { font-size: 13px; }
.current-label { padding: 2px 6px; border-radius: 999px; color: var(--blue); background: var(--blue-weak); font-size: 10px; font-weight: 800; }
.pending-label { padding: 2px 6px; border-radius: 999px; color: #a16207; background: #fef3c7; font-size: 10px; font-weight: 800; }
.card-meta, .card-path, .card-message { font-size: 11px; }
.card-meta { color: var(--muted); }
.card-path { overflow: hidden; margin-top: 5px; color: var(--subtle); text-overflow: ellipsis; white-space: nowrap; }
.card-message { margin: 7px 0 0; color: var(--green); }
.card-message.danger { color: var(--red); }
.card-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 3px; max-width: 190px; }
.text-button { padding: 5px 6px; border: 0; border-radius: 5px; background: transparent; color: var(--muted); font: inherit; font-size: 11px; cursor: pointer; }
.text-button:hover:not(:disabled) { background: var(--panel-soft); color: var(--text); }
.primary-text { color: var(--blue); font-weight: 700; }
.danger-text { color: var(--red); }
.text-button:disabled { opacity: .45; cursor: not-allowed; }
.empty-state { padding: 32px 12px; color: var(--muted); text-align: center; font-size: 12px; }
.settings-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 26px; border-top: 1px solid var(--line); background: var(--panel-soft); color: var(--muted); font-size: 11px; }
.primary-button, .secondary-button { height: 34px; padding: 0 13px; border-radius: 7px; font: inherit; font-size: 12px; font-weight: 700; cursor: pointer; }
.primary-button { border: 1px solid var(--blue); background: var(--blue); color: white; }
.secondary-button { border: 1px solid var(--line); background: var(--panel); color: var(--text); }
button:disabled { opacity: .55; cursor: not-allowed; }
@media (max-width: 700px) {
  .settings-overlay { padding: 10px; }
  .settings-header, .settings-content, .settings-footer { padding-left: 16px; padding-right: 16px; }
  .form-overlay { padding: 10px; }
  .workspace-card { flex-direction: column; }
  .card-actions { justify-content: flex-start; max-width: none; }
  .settings-footer { align-items: flex-end; flex-direction: column; }
}
</style>
