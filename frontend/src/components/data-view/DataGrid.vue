<script setup lang="ts">
import { ref, computed } from "vue";
import { useWorkbench } from "../../stores/workbench";
const wb = useWorkbench();

const editingCell = ref<{ row: number; field: string } | null>(null);
const editValue = ref<string>("");

function startEdit(row: number, field: string, current: unknown) {
  editingCell.value = { row, field };
  editValue.value = String(current ?? "") as string;
}

async function commitEdit() {
  if (!editingCell.value) return;
  const { row, field } = editingCell.value;
  const raw = editValue.value;
  // eslint-disable-next-line
  let val: any = raw;
  const num = Number(val);
  if (!isNaN(num) && String(val).trim() !== "") val = num;
  await wb.editCell(field, row, val);
  editingCell.value = null;
}

function cancelEdit() { editingCell.value = null; }

const visibleHeaders = computed(() => {
  return wb.dataHeaders.filter(h => h && !String(h).startsWith("__"));
});
</script>

<template>
  <div class="data-grid">
    <div v-if="!wb.selectedPo" class="placeholder">选择一个 PO 以查看数据视图</div>
    <div v-else class="grid-wrap">
      <div class="po-header">
        <span style="font-family: var(--font-mono); font-size: var(--text-md);">{{ wb.selectedPo }}</span>
        <span v-if="wb.poEntry" class="meta">
          {{ wb.poEntry.line_count }} 行 · {{ wb.dataRows.length }} 条数据
        </span>
      </div>
      <table>
        <thead>
          <tr>
            <th class="row-num">#</th>
            <th v-for="h in visibleHeaders" :key="h">{{ h }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in wb.dataRows" :key="(row.__row_number__ as number)">
            <td class="row-num">{{ row.__row_number__ }}</td>
            <td
              v-for="h in visibleHeaders"
              :key="h"
              :class="{ editing: editingCell?.row === row.__row_number__ && editingCell?.field === h }"
              @dblclick="startEdit(Number(row.__row_number__), h, row[h])"
            >
              <template v-if="editingCell?.row === row.__row_number__ && editingCell?.field === h">
                <input
                  v-model="editValue"
                  @keydown.enter="commitEdit"
                  @keydown.escape="cancelEdit"
                  @blur="commitEdit"
                  class="edit-input"
                  autofocus
                />
              </template>
              <template v-else>
                {{ row[h] }}
              </template>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.data-grid { flex: 1; overflow: auto; background: var(--surface-default); }
.placeholder { padding: var(--space-8); text-align: center; color: var(--fg-subtle); }
.grid-wrap { min-height: 100%; }
.po-header { padding: var(--space-2) var(--space-4); border-bottom: 1px solid var(--border-default); display: flex; gap: var(--space-3); align-items: center; }
.meta { font-size: var(--text-xs); color: var(--fg-muted); }
table { width: 100%; border-collapse: collapse; font-size: var(--text-sm); }
thead { position: sticky; top: 0; z-index: 1; }
th { background: var(--surface-sunken); padding: var(--space-1) var(--space-2); text-align: left; font-weight: 600; border-bottom: 2px solid var(--border-strong); white-space: nowrap; }
td { padding: var(--space-1) var(--space-2); border-bottom: 1px solid var(--border-default); max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
td.editing { padding: 0; }
.row-num { width: 40px; font-family: var(--font-mono); font-size: var(--text-xs); color: var(--fg-subtle); text-align: right; }
.edit-input { width: 100%; padding: var(--space-1); border: 2px solid var(--accent-default); border-radius: var(--radius-sm); font-family: inherit; font-size: inherit; }
tr:hover td { background: var(--surface-sunken); }
</style>
