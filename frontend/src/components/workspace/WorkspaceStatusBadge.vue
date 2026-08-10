<script setup lang="ts">
import { workspaceStatusLabel, type WorkspaceStatus } from "../../services/workspace";

const props = withDefaults(defineProps<{
  status: WorkspaceStatus;
  compact?: boolean;
}>(), {
  compact: false,
});
</script>

<template>
  <span class="status-badge" :class="[props.status, { compact: props.compact }]">
    <span class="status-dot" aria-hidden="true" />
    {{ workspaceStatusLabel(props.status) }}
  </span>
</template>

<style scoped>
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 24px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}
.status-badge.compact { min-height: 20px; padding: 0 7px; font-size: 11px; }
.status-dot { width: 7px; height: 7px; border-radius: 999px; background: currentColor; }
.ready { color: var(--green); background: var(--green-weak); }
.unchecked { color: var(--muted); background: var(--panel-soft); }
.file_missing, .permission_denied, .profile_not_found, .schema_mismatch {
  color: var(--red);
  background: var(--red-weak);
}
</style>
