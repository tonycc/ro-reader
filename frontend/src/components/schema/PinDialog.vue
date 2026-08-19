<script setup lang="ts">
import { ref, watch, nextTick } from "vue";

/**
 * 修复 PIN 输入弹窗（生产版）。
 * 进入修复向导前弹出，校验通过才允许修改列对应关系。
 * 软管控：仅约束界面内的保存操作，不对抗本机文件访问。
 */

const props = defineProps<{
  open: boolean;
  errorMessage: string;
}>();

const emit = defineEmits<{
  (e: "confirm", pin: string): void;
  (e: "cancel"): void;
}>();

const pin = ref("");
const inputRef = ref<HTMLInputElement | null>(null);

watch(
  () => props.open,
  async (open) => {
    if (open) {
      pin.value = "";
      await nextTick();
      inputRef.value?.focus();
    }
  },
);

function submit() {
  if (!pin.value.trim()) return;
  emit("confirm", pin.value.trim());
}
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="pin-overlay" @click.self="emit('cancel')">
      <div class="pin-dialog" role="dialog" aria-modal="true" aria-labelledby="pin-title">
        <h3 id="pin-title" class="pin-title">输入校验码</h3>
        <p class="pin-sub">修改列对应关系需要系统校验码</p>

        <input
          ref="inputRef"
          v-model="pin"
          type="password"
          class="pin-input"
          placeholder="请输入校验码"
          autocomplete="off"
          @keydown.enter="submit"
        />
        <p v-if="errorMessage" class="pin-error">{{ errorMessage }}</p>

        <div class="pin-actions">
          <button class="btn-cancel" type="button" @click="emit('cancel')">取消</button>
          <button
            class="btn-confirm"
            type="button"
            :disabled="!pin.trim()"
            @click="submit"
          >
            确认
          </button>
        </div>

        <p class="pin-note">校验码由系统内置，仅授权人员可修改列对应关系</p>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.pin-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1400;
}
.pin-dialog {
  width: 320px;
  background: var(--panel);
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 20px 50px rgba(15, 23, 42, 0.25);
}
.pin-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
}
.pin-sub {
  margin: 4px 0 14px;
  color: var(--muted);
  font-size: 12px;
}
.pin-input {
  width: 100%;
  height: 36px;
  padding: 0 12px;
  border: 1px solid var(--line-strong);
  border-radius: 8px;
  font-size: 14px;
  box-sizing: border-box;
  background: var(--panel);
  color: var(--text);
}
.pin-input:focus {
  outline: none;
  border-color: var(--blue);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15);
}
.pin-error {
  margin: 8px 0 0;
  color: var(--red);
  font-size: 12px;
}
.pin-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}
.btn-cancel {
  height: 32px;
  padding: 0 14px;
  border: 1px solid var(--line-strong);
  border-radius: 8px;
  background: var(--panel);
  color: var(--muted);
  font-size: 13px;
  cursor: pointer;
}
.btn-confirm {
  height: 32px;
  padding: 0 14px;
  border: none;
  border-radius: 8px;
  background: var(--blue);
  color: white;
  font-size: 13px;
  cursor: pointer;
}
.btn-confirm:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.pin-note {
  margin: 14px 0 0;
  padding-top: 12px;
  border-top: 1px solid var(--line);
  color: var(--subtle);
  font-size: 11px;
  text-align: center;
}
</style>
