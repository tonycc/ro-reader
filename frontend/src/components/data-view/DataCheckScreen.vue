<script setup lang="ts">
import { ref, computed } from "vue";
import { useWorkbench } from "../../stores/workbench";
import InvoiceDataCheck from "./InvoiceDataCheck.vue";
import IssueSummaryBar from "./IssueSummaryBar.vue";

const wb = useWorkbench();
const editingCell = ref<{ row: number; field: string } | null>(null);
const editValue = ref("");
const editError = ref("");

const visibleHeaders = computed(() => wb.dataHeaders.filter((h) => h && !String(h).startsWith("__")));
const requiredFields = new Set(["SAP Number", "FINALQTY", "PO NO.", "INV#"]);
const hasReadOnlyProjection = computed(() => wb.dataRows.some((row) => sourceRowNumber(row) === null));

function isMissing(row: Record<string, unknown>, field: string): boolean {
  const v = row[field];
  return v === null || v === undefined || v === "";
}
function sourceRowNumber(row: Record<string, unknown>): number | null {
  const value = Number(row.__row_number__);
  return Number.isInteger(value) && value > 0 ? value : null;
}
function startEdit(row: number, field: string, current: unknown) {
  editingCell.value = { row, field };
  editValue.value = String(current ?? "");
  editError.value = "";
}
function startEditForRow(row: Record<string, unknown>, field: string) {
  const rowNumber = sourceRowNumber(row);
  if (rowNumber === null) return;
  startEdit(rowNumber, field, row[field]);
}
async function commitEdit() {
  if (!editingCell.value) return;
  const { row, field } = editingCell.value;
  let val: unknown = editValue.value;
  const num = Number(val);
  if (!isNaN(num) && String(val).trim() !== "") val = num;
  try {
    await wb.editCell(field, row, val);
    editingCell.value = null;
    editError.value = "";
  } catch (e) {
    editError.value = e instanceof Error ? e.message : String(e);
  }
}
function cancelEdit() {
  editingCell.value = null;
  editError.value = "";
}
</script>

<template>
  <InvoiceDataCheck v-if="wb.previewScope === 'invoice'" />
  <div v-else class="check-screen">
    <div v-if="!wb.selectedPo" class="placeholder">选择左侧 PO 开始数据检查</div>
    <template v-else>
      <IssueSummaryBar
        :object-label="wb.selectedPo"
        :meta-label="`${wb.dataRows.length} 行 · PO 基础检查`"
        :blocking-errors="wb.poIssues?.blocking_errors ?? []"
        :warnings="wb.poIssues?.warnings ?? []"
        :loading="wb.issuesLoading"
        :error="wb.issuesError"
      />

      <div v-if="hasReadOnlyProjection" class="projection-note">
        该订单尚未进入当前 Profile 的 PO 记录 Sheet；此处为客户订单只读投影，请在源 workbook 的客户订单 Sheet 中修改。
      </div>

      <!-- 数据表格 -->
      <div class="panel">
        <div v-if="editError" class="edit-error">{{ editError }}</div>
        <div class="table-shell">
          <table class="data-table">
            <thead>
              <tr>
                <th class="mono">#</th>
                <th v-for="h in visibleHeaders" :key="h">{{ h }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(row, rowIndex) in wb.dataRows"
                :key="sourceRowNumber(row) ?? `projection-${rowIndex}`"
                :class="{ 'read-only-row': sourceRowNumber(row) === null }"
              >
                <td class="mono row-num">{{ sourceRowNumber(row) ?? "—" }}</td>
                <td
                  v-for="h in visibleHeaders" :key="h"
                  :class="{
                    missing: requiredFields.has(h) && isMissing(row as Record<string, unknown>, h),
                    editing: editingCell?.row === row.__row_number__ && editingCell?.field === h,
                  }"
                  :title="sourceRowNumber(row) === null ? '客户订单只读投影' : '双击编辑'"
                  @dblclick="startEditForRow(row, h)"
                >
                  <template v-if="editingCell?.row === sourceRowNumber(row) && editingCell?.field === h">
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
.projection-note { margin-bottom: 10px; padding: 9px 12px; border: 1px solid #bfdbfe; border-radius: 8px; background: #eff6ff; color: #1e40af; font-size: 12px; line-height: 1.45; }
.edit-error { padding: 8px 10px; color: var(--red); background: var(--red-weak); border-bottom: 1px solid var(--line); font-size: 12px; }

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
tr.read-only-row td { color: var(--muted); cursor: default; }
</style>
