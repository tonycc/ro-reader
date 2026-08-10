<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { workspaceStatusLabel, type CustomerWorkspace, type ProfileSummary, type WorkspaceInput, type WorkspaceValidationResult } from "../../services/workspace";

const props = defineProps<{
  workspace: CustomerWorkspace | null;
  profiles: ProfileSummary[];
  busy?: boolean;
  validating?: boolean;
  validation?: WorkspaceValidationResult | null;
}>();

const emit = defineEmits<{
  save: [input: WorkspaceInput];
  validate: [input: WorkspaceInput];
  changed: [];
  cancel: [];
}>();

const draft = reactive<WorkspaceInput>({
  display_name: "",
  profile_id: "ro",
  base_file: "",
});
const hasDraft = computed(() => Boolean(draft.profile_id && draft.base_file.trim()));
const pathCheckRequested = ref(false);

function syncDraft(workspace: CustomerWorkspace | null) {
  draft.display_name = workspace?.display_name ?? "";
  draft.profile_id = workspace?.profile_id ?? props.profiles.find((profile) => profile.available)?.id ?? "";
  draft.base_file = workspace?.base_file ?? "";
}

watch(() => props.workspace, syncDraft, { immediate: true });
watch(() => [draft.display_name, draft.profile_id, draft.base_file], () => {
  if (pathCheckRequested.value) pathCheckRequested.value = false;
  emit("changed");
});

function currentInput(): WorkspaceInput {
  return {
    display_name: draft.display_name.trim(),
    profile_id: draft.profile_id,
    base_file: draft.base_file.trim(),
  };
}

function validatePath() {
  if (!hasDraft.value) return;
  pathCheckRequested.value = true;
  emit("validate", currentInput());
}

function submit() {
  if (!draft.display_name.trim() || !draft.profile_id || !draft.base_file.trim()) return;
  emit("save", {
    display_name: draft.display_name.trim(),
    profile_id: draft.profile_id,
    base_file: draft.base_file.trim(),
  });
}
</script>

<template>
  <form class="workspace-form" @submit.prevent="submit">
    <div class="form-head">
      <div>
        <h3 id="workspace-form-title">{{ props.workspace ? "编辑工作区" : "新增工作区" }}</h3>
        <p>工作区保存客户 Profile 与本机 base 文件的组合。</p>
      </div>
      <button type="button" class="icon-button" aria-label="关闭表单" @click="emit('cancel')">✕</button>
    </div>

    <label class="form-field">
      <span>工作区名称</span>
      <input v-model="draft.display_name" autofocus placeholder="例如：RO 2026" />
    </label>

    <label class="form-field">
      <span>Customer Profile</span>
      <select v-model="draft.profile_id">
        <option v-for="profile in props.profiles" :key="profile.id" :value="profile.id" :disabled="!profile.available">
          {{ profile.display_name }}{{ profile.available ? "" : "（尚未接入）" }}
        </option>
      </select>
      <small v-if="props.profiles.find((profile) => profile.id === draft.profile_id)?.description">
        {{ props.profiles.find((profile) => profile.id === draft.profile_id)?.description }}
      </small>
    </label>

    <div class="form-field">
      <div class="field-heading">
        <label for="workspace-base-file">Base 文件路径</label>
        <button
          type="button"
          class="check-path-button"
          data-testid="workspace-path-check"
          :disabled="props.busy || props.validating || !hasDraft"
          @click="validatePath"
        >
          {{ props.validating ? "检测中…" : "检测路径" }}
        </button>
      </div>
      <input id="workspace-base-file" v-model="draft.base_file" placeholder="输入本机 .xlsx 文件的完整路径" />
      <small>检测会读取 Profile 对应的 schema；检测结果不会自动保存配置。</small>
      <div
        v-if="props.validating || (props.validation && pathCheckRequested)"
        class="path-check-result"
        :class="props.validating ? 'checking' : props.validation?.status"
        data-testid="workspace-path-status"
        role="status"
        aria-live="polite"
      >
        <template v-if="props.validating">正在检查文件路径…</template>
        <template v-else-if="props.validation">
          <strong>{{ workspaceStatusLabel(props.validation.status) }}</strong>
          <span> · {{ props.validation.message }}</span>
        </template>
      </div>
    </div>

    <div class="form-actions">
      <button type="button" class="secondary-button" :disabled="props.busy" @click="emit('cancel')">取消</button>
      <button type="submit" class="primary-button" :disabled="props.busy || !draft.display_name.trim() || !draft.profile_id || !draft.base_file.trim()">
        {{ props.validating ? "检测中…" : props.busy ? "保存中…" : "保存工作区" }}
      </button>
    </div>
  </form>
</template>

<style scoped>
.workspace-form { padding: 24px 26px; background: var(--panel); }
.form-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; margin-bottom: 17px; }
.form-head h3 { margin: 0 0 4px; font-size: 15px; }
.form-head p { margin: 0; color: var(--muted); font-size: 12px; line-height: 1.45; }
.icon-button { width: 28px; height: 28px; border: 0; border-radius: 6px; background: transparent; color: var(--muted); cursor: pointer; }
.icon-button:hover { background: var(--red-weak); color: var(--red); }
.form-field { display: flex; flex-direction: column; gap: 6px; margin-bottom: 14px; }
.field-heading { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.field-heading > label { font-size: 12px; font-weight: 700; }
.check-path-button { height: 27px; padding: 0 9px; border: 1px solid var(--blue); border-radius: 6px; background: var(--blue-weak); color: var(--blue); font: inherit; font-size: 11px; font-weight: 700; cursor: pointer; }
.check-path-button:hover:not(:disabled) { background: #dce7ff; }
.form-field input, .form-field select { width: 100%; height: 36px; box-sizing: border-box; padding: 0 10px; border: 1px solid var(--line); border-radius: 7px; background: var(--panel); color: var(--text); font: inherit; font-size: 12px; }
.form-field input:focus, .form-field select:focus { outline: 0; border-color: var(--blue); box-shadow: 0 0 0 2px var(--blue-weak); }
.form-field small { color: var(--muted); font-size: 11px; line-height: 1.4; }
.path-check-result { padding: 7px 9px; border-radius: 7px; font-size: 11px; line-height: 1.4; }
.path-check-result.checking, .path-check-result.unchecked { color: var(--muted); background: var(--panel-soft); }
.path-check-result.ready { color: var(--green); background: var(--green-weak); }
.path-check-result.file_missing, .path-check-result.permission_denied, .path-check-result.profile_not_found, .path-check-result.schema_mismatch { color: var(--red); background: var(--red-weak); }
.form-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 20px; }
.secondary-button, .primary-button { height: 34px; padding: 0 13px; border-radius: 7px; font: inherit; font-size: 12px; font-weight: 700; cursor: pointer; }
.secondary-button { border: 1px solid var(--line); background: var(--panel); color: var(--text); }
.primary-button { border: 1px solid var(--blue); background: var(--blue); color: white; }
button:disabled { opacity: 0.55; cursor: not-allowed; }
</style>
