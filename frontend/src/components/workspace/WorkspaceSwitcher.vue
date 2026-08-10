<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useWorkspace } from "../../stores/workspace";
import WorkspaceStatusBadge from "./WorkspaceStatusBadge.vue";

const emit = defineEmits<{
  manage: [];
}>();

const workspace = useWorkspace();
const open = ref(false);
const root = ref<HTMLElement | null>(null);
const currentLabel = computed(() => workspace.currentWorkspace?.display_name ?? "未配置工作区");

function toggle() {
  if (workspace.switching) return;
  open.value = !open.value;
}

async function choose(id: string) {
  open.value = false;
  if (id === workspace.currentWorkspaceId) return;
  try {
    await workspace.activateWorkspace(id);
  } catch {
    // The store preserves the previous current workspace and exposes the error below.
  }
}

function onDocumentClick(event: MouseEvent) {
  if (root.value && !root.value.contains(event.target as Node)) open.value = false;
}

onMounted(() => document.addEventListener("click", onDocumentClick));
onUnmounted(() => document.removeEventListener("click", onDocumentClick));
</script>

<template>
  <div ref="root" class="workspace-switcher" data-testid="workspace-switcher">
    <button
      type="button"
      class="switcher-trigger"
      data-testid="workspace-switcher-trigger"
      :aria-expanded="open"
      :disabled="workspace.switching"
      @click="toggle"
    >
      <span class="switcher-copy">
        <strong>{{ currentLabel }}</strong>
        <span v-if="workspace.currentWorkspace" class="switcher-meta">
          {{ workspace.currentWorkspace.profile_name }} · {{ workspace.currentWorkspace.base_file_name }}
        </span>
        <span v-else class="switcher-meta">请选择一个工作区</span>
        <span v-if="workspace.needsActivation" class="switcher-pending">配置已变更 · 请重新激活</span>
      </span>
      <span class="switcher-arrow" :class="{ open }" aria-hidden="true">▾</span>
    </button>

      <div v-if="open" class="switcher-menu" role="listbox" aria-label="工作区列表">
      <div class="menu-heading">切换工作区</div>
      <button
        v-for="item in workspace.workspaces"
        :key="item.id"
        type="button"
        role="option"
        class="workspace-option"
        :class="{ current: item.id === workspace.currentWorkspaceId }"
        :data-testid="`workspace-option-${item.id}`"
        :aria-selected="item.id === workspace.currentWorkspaceId"
        :disabled="workspace.switching"
        @click="choose(item.id)"
      >
        <span class="option-check">{{ item.id === workspace.currentWorkspaceId ? "✓" : "" }}</span>
        <span class="option-copy">
          <strong>{{ item.display_name }}</strong>
          <span>{{ item.profile_name }} · {{ item.base_file_name }}</span>
        </span>
        <WorkspaceStatusBadge :status="item.status" compact />
      </button>
      <p v-if="workspace.error" class="switch-error" data-testid="workspace-switch-error">
        {{ workspace.error }}
      </p>
      <div class="menu-footer">
        <button type="button" class="manage-button" @click="emit('manage'); open = false">
          <span aria-hidden="true">＋</span> 管理工作区
        </button>
      </div>
    </div>
    <p v-if="workspace.error && !open" class="switch-error switch-error-outside" data-testid="workspace-switch-error">
      {{ workspace.error }}
    </p>
  </div>
</template>

<style scoped>
.workspace-switcher { position: relative; width: min(100%, 440px); min-width: 0; max-width: 440px; }
.switcher-trigger {
  display: flex; align-items: center; justify-content: space-between; gap: 14px;
  width: 100%; min-height: 38px; padding: 5px 10px 5px 12px;
  border: 1px solid var(--line); border-radius: 9px;
  color: var(--text); background: var(--panel-soft); text-align: left;
  font: inherit; cursor: pointer;
}
.switcher-trigger:hover { border-color: var(--blue); background: var(--blue-weak); }
.switcher-trigger:disabled { opacity: 0.65; cursor: wait; }
.switcher-copy { min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.switcher-copy strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.switcher-meta { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--muted); font-size: 11px; }
.switcher-pending { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #a16207; font-size: 10px; font-weight: 700; }
.switcher-arrow { color: var(--muted); font-size: 15px; transition: transform 120ms ease; }
.switcher-arrow.open { transform: rotate(180deg); }
.switcher-menu {
  position: absolute; z-index: 30; top: calc(100% + 7px); left: 0; right: 0;
  max-height: min(430px, calc(100vh - 72px)); overflow-y: auto;
  padding: 7px; border: 1px solid var(--line); border-radius: 11px;
  background: var(--panel); box-shadow: 0 16px 38px rgba(21, 32, 51, 0.16);
}
.menu-heading { padding: 6px 9px 7px; color: var(--muted); font-size: 11px; font-weight: 700; }
.workspace-option {
  display: flex; align-items: center; gap: 7px; width: 100%; min-height: 48px;
  padding: 7px 8px; border: 0; border-radius: 8px; background: transparent;
  color: var(--text); text-align: left; font: inherit; cursor: pointer;
}
.workspace-option:hover { background: var(--panel-soft); }
.workspace-option.current { background: var(--blue-weak); }
.workspace-option:disabled { opacity: 0.65; cursor: wait; }
.workspace-option > .status-badge { flex: 0 0 auto; }
.option-check { width: 14px; color: var(--blue); font-weight: 800; }
.option-copy { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 2px; }
.option-copy strong, .option-copy span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.option-copy strong { font-size: 12px; }
.option-copy span { color: var(--muted); font-size: 11px; }
.switch-error { margin: 6px 8px 4px; padding: 7px 8px; border-radius: 7px; color: var(--red); background: var(--red-weak); font-size: 11px; line-height: 1.45; }
.switch-error-outside {
  margin: 5px 0 0;
}
.menu-footer { margin-top: 5px; padding-top: 6px; border-top: 1px solid var(--line); }
.manage-button { width: 100%; padding: 7px 8px; border: 0; border-radius: 7px; background: transparent; color: var(--blue); text-align: left; font: inherit; font-size: 12px; font-weight: 700; cursor: pointer; }
.manage-button:hover { background: var(--blue-weak); }
@media (max-width: 900px) {
  .workspace-switcher { width: 100%; max-width: none; }
}
</style>
