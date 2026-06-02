<script setup lang="ts">
import { ref, computed } from "vue";
import { useWorkbench } from "../../stores/workbench";
const wb = useWorkbench();
const search = ref("");
const filterStatus = ref("");

const filtered = computed(() => {
  let list = wb.poList;
  if (search.value) {
    const q = search.value.toLowerCase();
    list = list.filter((p) => p.po_no.toLowerCase().includes(q));
  }
  if (filterStatus.value) {
    list = list.filter((p) => p.status === filterStatus.value);
  }
  return list;
});
</script>

<template>
  <div class="po-list">
    <div class="filters">
      <input v-model="search" class="search-input" placeholder="搜索 PO / SAP / INV#" />
      <select v-model="filterStatus" class="status-filter">
        <option value="">全部</option>
        <option value="ready">就绪</option>
        <option value="partial">部分</option>
        <option value="blocked">阻断</option>
        <option value="done">已导出</option>
      </select>
    </div>
    <ul class="list">
      <li
        v-for="po in filtered"
        :key="po.po_no"
        class="po-item"
        :class="{ selected: wb.selectedPo === po.po_no, [po.status]: true }"
        @click="wb.selectPo(po.po_no)"
      >
        <span class="status-dot" :class="po.status">{{ po.status === 'ready' ? '●' : po.status === 'partial' ? '◐' : po.status === 'blocked' ? '●' : '○' }}</span>
        <span class="po-no" style="font-family: var(--font-mono);">{{ po.po_no }}</span>
        <span class="po-meta">{{ po.chain_segments.map(s => s.seller.split('/')[0]).join('·') }} · {{ po.line_count }} 行</span>
      </li>
      <li v-if="!filtered.length && !wb.loading" class="empty">没有匹配的 PO</li>
      <li v-if="wb.loading" class="empty">解析 PO record...</li>
    </ul>
    <div class="count">{{ filtered.length }} / {{ wb.poList.length }}</div>
  </div>
</template>

<style scoped>
.po-list { display: flex; flex-direction: column; height: 100%; }
.filters { padding: var(--space-2); display: flex; gap: var(--space-1); border-bottom: 1px solid var(--border-default); }
.search-input { flex: 1; padding: var(--space-1) var(--space-2); border: 1px solid var(--border-default); border-radius: var(--radius-sm); font-size: var(--text-xs); }
.status-filter { padding: var(--space-1); border: 1px solid var(--border-default); border-radius: var(--radius-sm); font-size: var(--text-xs); background: var(--surface-default); }
.list { flex: 1; overflow-y: auto; margin: 0; padding: 0; list-style: none; }
.po-item { padding: var(--space-2) var(--space-3); cursor: pointer; border-bottom: 1px solid var(--border-default); }
.po-item:hover { background: var(--surface-sunken); }
.po-item.selected { background: var(--accent-subtle); border-left: 2px solid var(--accent-default); }
.po-meta { display: block; font-size: var(--text-xs); color: var(--fg-muted); }
.status-dot { font-size: 10px; margin-right: 4px; }
.status-dot.ready { color: var(--status-ready-fg); }
.status-dot.partial { color: var(--status-partial-fg); }
.status-dot.blocked { color: var(--status-blocked-fg); }
.status-dot.done { color: var(--status-done-fg); }
.empty { padding: var(--space-4); text-align: center; color: var(--fg-subtle); }
.count { padding: var(--space-1) var(--space-3); font-size: var(--text-xs); color: var(--fg-subtle); border-top: 1px solid var(--border-default); }
</style>
