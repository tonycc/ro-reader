<script setup lang="ts">
import { ref, computed } from "vue";
import { useWorkbench } from "../../stores/workbench";

const wb = useWorkbench();
const editingCell = ref<{ row: number; field: string } | null>(null);
const editValue = ref("");

const visibleHeaders = computed(() => wb.dataHeaders.filter((h) => h && !String(h).startsWith("__")));
const requiredFields = new Set(["SAP Number", "FINALQTY", "PO NO.", "INV#"]);

function isMissing(row: Record<string, unknown>, field: string): boolean {
  const v = row[field];
  return v === null || v === undefined || v === "";
}
function startEdit(row: number, field: string, current: unknown) {
  editingCell.value = { row, field };
  editValue.value = String(current ?? "");
}
async function commitEdit() {
  if (!editingCell.value) return;
  const { row, field } = editingCell.value;
  let val: unknown = editValue.value;
  const num = Number(val);
  if (!isNaN(num) && String(val).trim() !== "") val = num;
  await wb.editCell(field, row, val);
  editingCell.value = null;
}
function cancelEdit() { editingCell.value = null; }
</script>

<template>
  <div class="check-screen">
    <div v-if="!wb.selectedPo" class="placeholder">选择左侧 PO 开始数据检查</div>
    <template v-else>
      <!-- 问题摘要 -->
      <div class="issue-bar">
        <span class="issue-badge ready" v-if="wb.blockingErrors.length === 0 && wb.warnings.length === 0">✓ 数据完整</span>
        <span class="issue-badge blocked" v-if="wb.blockingErrors.length">{{ wb.blockingErrors.length }} 项阻断</span>
        <span class="issue-badge fix" v-if="wb.warnings.length">{{ wb.warnings.length }} 项警告</span>
        <span class="issue-meta">{{ wb.dataRows.length }} 行 · {{ wb.selectedSeller || '未选链段' }}</span>
        <span class="issue-meta" v-if="wb.selectedInvoiceNo">INV# {{ wb.selectedInvoiceNo }}</span>
      </div>

      <!-- 数据表格 -->
      <div class="panel">
        <div class="table-shell">
          <table class="data-table">
            <thead>
              <tr>
                <th class="mono">#</th>
                <th v-for="h in visibleHeaders" :key="h">{{ h }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in wb.dataRows" :key="(row.__row_number__ as number)">
                <td class="mono row-num">{{ row.__row_number__ }}</td>
                <td
                  v-for="h in visibleHeaders" :key="h"
                  :class="{
                    missing: requiredFields.has(h) && isMissing(row as Record<string, unknown>, h),
                    editing: editingCell?.row === row.__row_number__ && editingCell?.field === h,
                  }"
                  @dblclick="startEdit(Number(row.__row_number__), h, row[h])"
                >
                  <template v-if="editingCell?.row === row.__row_number__ && editingCell?.field === h">
                    <input v-model="editValue" data-testid="cell-edit-input" @keydown.enter="commitEdit" @keydown.escape="cancelEdit" @blur="commitEdit" class="edit-input" autofocus />
                  </template>
                  <template v-else>{{ row[h] }}</template>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.check-screen { padding: 14px 20px 22px; display: flex; flex-direction: column; min-height: 0; }
.placeholder { padding: var(--space-8); text-align: center; color: var(--subtle); }

/* 问题摘要条 */
.issue-bar {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 14px; margin-bottom: 12px;
  border: 1px solid var(--line); border-radius: 10px;
  background: white; flex-wrap: wrap;
}
.issue-badge {
  display: inline-flex; align-items: center; gap: 4px;
  height: 22px; padding: 0 8px; border-radius: 999px; font-size: 12px;
}
.ready { color: var(--green); background: var(--green-weak); }
.blocked { color: var(--red); background: var(--red-weak); }
.fix { color: var(--amber); background: var(--amber-weak); }
.issue-meta { color: var(--muted); font-size: 12px; }

/* 表格 */
.panel { border: 1px solid var(--line); border-radius: 12px; background: var(--panel); overflow: hidden; flex: 1; min-height: 0; }
.table-shell { max-height: calc(100vh - 180px); overflow: auto; }
.data-table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: 12px; }
th, td { border-bottom: 1px solid var(--line); padding: 9px 10px; text-align: left; white-space: nowrap; }
th { position: sticky; top: 0; z-index: 1; background: #f7f9fc; color: var(--muted); font-weight: 800; border-bottom-color: var(--line-strong); }
.mono { font-family: var(--mono); }
.row-num { width: 40px; color: var(--subtle); text-align: right; }
td.missing { border: 2px solid #f2c17d; background: #fffaf0; }
td.editing { padding: 0; }
.edit-input { width: 100%; padding: var(--space-1); border: 2px solid var(--blue); border-radius: var(--radius-sm); font: inherit; }
tr:hover td { background: #f8fbff; }
</style>
