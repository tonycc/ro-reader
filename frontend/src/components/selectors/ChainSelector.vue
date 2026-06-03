<script setup lang="ts">
import { useWorkbench } from "../../stores/workbench";
const wb = useWorkbench();
</script>

<template>
  <div class="seller-selector">
    <span class="label">主体:</span>
    <button
      v-for="s in wb.poEntry?.sellers ?? []"
      :key="s"
      class="seller-btn"
      :class="{ active: wb.selectedSeller === s }"
      @click="wb.selectSeller(s)"
    >
      {{ s }}
    </button>
    <span v-if="!wb.poEntry?.sellers?.length" class="hint">无可用主体</span>
  </div>
</template>

<style scoped>
.seller-selector { display: flex; align-items: center; gap: var(--space-2); }
.label { color: var(--fg-muted); font-size: var(--text-xs); white-space: nowrap; }
.seller-btn { padding: var(--space-1) var(--space-3); border: 1px solid var(--border-default); border-radius: var(--radius-md); background: var(--surface-default); cursor: pointer; font-size: var(--text-xs); color: var(--fg-muted); }
.seller-btn.active { background: var(--accent-subtle); border-color: var(--accent-default); color: var(--accent-default); font-weight: 600; }
.seller-btn:hover { border-color: var(--accent-default); }
.hint { color: var(--fg-subtle); font-size: var(--text-xs); }
</style>
