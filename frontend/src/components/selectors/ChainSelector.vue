<script setup lang="ts">
import { useWorkbench } from "../../stores/workbench";
const wb = useWorkbench();
</script>

<template>
  <div class="chain-selector">
    <span class="label">链段:</span>
    <button
      v-for="seg in wb.poEntry?.chain_segments ?? []"
      :key="seg.seller + seg.buyer"
      class="chain-btn"
      :class="{ active: wb.selectedSegment?.seller === seg.seller && wb.selectedSegment?.buyer === seg.buyer }"
      @click="wb.selectSegment(seg)"
    >
      {{ seg.seller.split('/')[0] }} → {{ seg.buyer.split('/')[0] }}
    </button>
    <span v-if="!wb.poEntry?.chain_segments.length" class="hint">无可用链段</span>
  </div>
</template>

<style scoped>
.chain-selector { display: flex; align-items: center; gap: var(--space-2); }
.label { color: var(--fg-muted); font-size: var(--text-xs); white-space: nowrap; }
.chain-btn { padding: var(--space-1) var(--space-3); border: 1px solid var(--border-default); border-radius: var(--radius-md); background: var(--surface-default); cursor: pointer; font-size: var(--text-xs); color: var(--fg-muted); }
.chain-btn.active { background: var(--accent-subtle); border-color: var(--accent-default); color: var(--accent-default); font-weight: 600; }
.chain-btn:hover { border-color: var(--accent-default); }
.hint { color: var(--fg-subtle); font-size: var(--text-xs); }
</style>
