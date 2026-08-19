<script setup lang="ts">
import { computed } from "vue";
import { useWorkspace } from "../../stores/workspace";

const emit = defineEmits<{
  close: [];
}>();

const workspace = useWorkspace();
const message = computed(() => workspace.activationError?.message ?? "");
</script>

<template>
  <Teleport to="body">
    <div
      v-if="workspace.activationError"
      class="activation-overlay"
      data-testid="workspace-activation-error"
      @click.self="emit('close')"
    >
      <section class="activation-dialog" role="dialog" aria-modal="true" aria-labelledby="activation-error-title">
        <h2 id="activation-error-title" class="activation-title">无法打开工作区</h2>
        <p class="activation-message" data-testid="workspace-switch-error">{{ message }}</p>
        <div class="activation-actions">
          <button type="button" class="btn-secondary" @click="emit('close')">关闭</button>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.activation-overlay {
  position: fixed;
  inset: 0;
  z-index: 1300;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgba(16, 24, 40, 0.45);
}
.activation-dialog {
  width: min(480px, 100%);
  padding: 22px 22px 18px;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: var(--panel);
  box-shadow: 0 18px 48px rgba(16, 24, 40, 0.24);
}
.activation-title {
  margin: 0 0 10px;
  font-size: 16px;
  font-weight: 700;
}
.activation-message {
  margin: 0;
  color: var(--red);
  font-size: 13px;
  line-height: 1.55;
}
.activation-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 18px;
}
.btn-secondary {
  height: 32px;
  padding: 0 14px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
  color: var(--muted);
  font: inherit;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}
</style>
