<script setup lang="ts">
import { useWorkbench } from "../../stores/workbench";
const wb = useWorkbench();
</script>

<template>
  <div class="month-selector">
    <span class="label">月份:</span>
    <template v-if="wb.poEntry?.monthly_months?.length">
      <button
        v-for="m in wb.poEntry!.monthly_months"
        :key="m"
        class="month-btn"
        :class="{ active: wb.selectedMonth === m }"
        @click="wb.selectMonth(wb.selectedMonth === m ? null : m)"
      >
        {{ m }}
      </button>
      <span v-if="wb.selectedMonth" class="clear" @click="wb.selectMonth(null)">清除</span>
    </template>
    <span v-else class="hint">无月度出货数据</span>
  </div>
</template>

<style scoped>
.month-selector { display: flex; align-items: center; gap: var(--space-2); }
.label { color: var(--fg-muted); font-size: var(--text-xs); white-space: nowrap; }
.month-btn { padding: var(--space-1) var(--space-3); border: 1px solid var(--border-default); border-radius: var(--radius-md); background: var(--surface-default); cursor: pointer; font-size: var(--text-xs); font-family: var(--font-mono); color: var(--fg-muted); }
.month-btn.active { background: var(--accent-subtle); border-color: var(--accent-default); color: var(--accent-default); font-weight: 600; }
.month-btn:hover { border-color: var(--accent-default); }
.clear { cursor: pointer; font-size: var(--text-xs); color: var(--accent-default); }
.hint { font-size: var(--text-xs); color: var(--fg-subtle); }
</style>
