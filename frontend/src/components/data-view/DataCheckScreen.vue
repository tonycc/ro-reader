<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from "vue";
import { useWorkbench } from "../../stores/workbench";
import type { ValidationIssue } from "../../stores/api";

const wb = useWorkbench();
const editingCell = ref<{ row: number; field: string } | null>(null);
const editValue = ref("");
const issuePanelOpen = ref(false);
const warningPanelOpen = ref(false);

const visibleHeaders = computed(() => wb.dataHeaders.filter((h) => h && !String(h).startsWith("__")));
const requiredFields = new Set(["SAP Number", "FINALQTY", "PO NO.", "INV#"]);
const previewBlockingErrors = computed<ValidationIssue[]>(() => (
  wb.blockingErrors.map((issue, index) => normalizeIssue(issue, index, "blocking_error", "PREVIEW_BLOCKING", "预览阻断"))
));
const issueErrors = computed<ValidationIssue[]>(() => dedupeIssues([
  ...(wb.poIssues?.blocking_errors ?? []),
  ...previewBlockingErrors.value,
]));
const blockingCount = computed(() => issueErrors.value.length);
const previewWarnings = computed<ValidationIssue[]>(() => (
  wb.warnings.map((issue, index) => normalizeIssue(issue, index, "warning", "PREVIEW_WARNING", "预览警告"))
));
const warningIssues = computed<ValidationIssue[]>(() => dedupeIssues([
  ...(wb.poIssues?.warnings ?? []),
  ...previewWarnings.value,
]));
const warningCount = computed(() => warningIssues.value.length);

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
function normalizeIssue(
  issue: unknown,
  index: number,
  fallbackKind: string,
  fallbackCodePrefix: string,
  fallbackMessage: string,
): ValidationIssue {
  const raw = issue && typeof issue === "object" ? issue as Record<string, unknown> : {};
  const severity = raw.severity === "high" || raw.severity === "low" ? raw.severity : null;
  return {
    kind: String(raw.kind ?? fallbackKind),
    code: String(raw.code ?? `${fallbackCodePrefix}_${index + 1}`),
    message: String(raw.message ?? raw.code ?? fallbackMessage),
    sheet: typeof raw.sheet === "string" ? raw.sheet : null,
    row: typeof raw.row === "number" ? raw.row : null,
    field: typeof raw.field === "string" ? raw.field : null,
    severity,
  };
}
function dedupeIssues(issues: ValidationIssue[]): ValidationIssue[] {
  const seen = new Set<string>();
  const result: ValidationIssue[] = [];
  for (const issue of issues) {
    const key = [
      issue.kind,
      issue.code,
      issue.message,
      issue.sheet ?? "",
      issue.row ?? "",
      issue.field ?? "",
    ].join("|");
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(issue);
  }
  return result;
}
function closeIssuePanel() {
  issuePanelOpen.value = false;
}
function closeWarningPanel() {
  warningPanelOpen.value = false;
}
async function toggleIssuePanel() {
  issuePanelOpen.value = !issuePanelOpen.value;
  if (issuePanelOpen.value) warningPanelOpen.value = false;
  if (issuePanelOpen.value && !wb.poIssues && !wb.issuesLoading) {
    await wb.refreshPoIssues();
  }
}
async function toggleWarningPanel() {
  warningPanelOpen.value = !warningPanelOpen.value;
  if (warningPanelOpen.value) issuePanelOpen.value = false;
  if (warningPanelOpen.value && !wb.poIssues && !wb.issuesLoading) {
    await wb.refreshPoIssues();
  }
}
function formatIssueLocation(issue: ValidationIssue): string {
  const parts = [];
  if (issue.sheet) parts.push(issue.sheet);
  if (issue.row !== null && issue.row !== undefined) parts.push(`row ${issue.row}`);
  if (issue.field) parts.push(issue.field);
  return parts.join(" / ") || "未定位到具体单元格";
}
function onDocumentClick(e: MouseEvent) {
  if (!issuePanelOpen.value && !warningPanelOpen.value) return;
  const target = e.target as HTMLElement;
  if (!target.closest(".data-issue-root")) closeIssuePanel();
  if (!target.closest(".data-warning-root")) closeWarningPanel();
}
function onKeydown(e: KeyboardEvent) {
  if (e.key === "Escape") {
    closeIssuePanel();
    closeWarningPanel();
  }
}
onMounted(() => {
  document.addEventListener("click", onDocumentClick, true);
  document.addEventListener("keydown", onKeydown);
});
onUnmounted(() => {
  document.removeEventListener("click", onDocumentClick, true);
  document.removeEventListener("keydown", onKeydown);
});
</script>

<template>
  <div class="check-screen">
    <div v-if="!wb.selectedPo" class="placeholder">选择左侧 PO 开始数据检查</div>
    <template v-else>
      <!-- 问题摘要 -->
      <div class="issue-bar">
        <span class="issue-badge ready" v-if="blockingCount === 0 && warningCount === 0">✓ 数据完整</span>
        <div v-if="blockingCount" class="data-issue-root">
          <button class="issue-badge blocked" type="button" @click="toggleIssuePanel">
            {{ blockingCount }} 项阻断
          </button>
          <div v-if="issuePanelOpen" class="data-issue-panel">
            <div class="data-issue-head">
              <strong>阻断原因</strong>
              <div class="data-issue-head-right">
                <span>{{ wb.selectedPo }}</span>
                <button
                  class="data-issue-close-btn"
                  type="button"
                  aria-label="关闭阻断原因"
                  @click.stop="closeIssuePanel"
                >
                  ×
                </button>
              </div>
            </div>
            <div v-if="wb.issuesLoading" class="data-issue-empty">正在读取原因…</div>
            <div v-else-if="wb.issuesError" class="data-issue-empty error">{{ wb.issuesError }}</div>
            <div v-else-if="!issueErrors.length" class="data-issue-empty">暂无阻断明细</div>
            <div v-else class="data-issue-list">
              <div v-for="(issue, index) in issueErrors" :key="`${issue.code}-${index}`" class="data-issue-row">
                <div class="data-issue-title">{{ issue.message || issue.code }}</div>
                <div class="data-issue-meta">{{ formatIssueLocation(issue) }}</div>
                <div class="data-issue-code">{{ issue.code }}</div>
              </div>
            </div>
          </div>
        </div>
        <div v-if="warningCount" class="data-warning-root">
          <button class="issue-badge fix" type="button" @click="toggleWarningPanel">
            {{ warningCount }} 项警告
          </button>
          <div v-if="warningPanelOpen" class="data-warning-panel">
            <div class="data-warning-head">
              <strong>预警详情</strong>
              <div class="data-warning-head-right">
                <span>{{ wb.selectedPo }}</span>
                <button
                  class="data-warning-close-btn"
                  type="button"
                  aria-label="关闭预警详情"
                  @click.stop="closeWarningPanel"
                >
                  ×
                </button>
              </div>
            </div>
            <div v-if="wb.issuesLoading" class="data-warning-empty">正在读取预警…</div>
            <div v-else-if="wb.issuesError" class="data-warning-empty error">{{ wb.issuesError }}</div>
            <div v-else-if="!warningIssues.length" class="data-warning-empty">暂无预警明细</div>
            <div v-else class="data-warning-list">
              <div v-for="(issue, index) in warningIssues" :key="`${issue.code}-${index}`" class="data-warning-row">
                <div class="data-warning-title">{{ issue.message || issue.code }}</div>
                <div class="data-warning-meta">{{ formatIssueLocation(issue) }}</div>
                <div class="data-warning-code">{{ issue.code }}</div>
              </div>
            </div>
          </div>
        </div>
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
  border: 0;
}
.ready { color: var(--green); background: var(--green-weak); }
.blocked { color: var(--red); background: var(--red-weak); cursor: pointer; font-weight: 700; }
.blocked:hover { box-shadow: inset 0 0 0 1px #fca5a5; }
.fix { color: var(--amber); background: var(--amber-weak); cursor: pointer; font-weight: 700; }
.fix:hover { box-shadow: inset 0 0 0 1px #fbbf24; }
.issue-meta { color: var(--muted); font-size: 12px; }
.data-issue-root,
.data-warning-root { position: relative; display: inline-flex; }
.data-issue-panel {
  position: absolute; top: 28px; left: 0; z-index: 60;
  width: min(420px, calc(100vw - 32px));
  max-height: 360px; overflow: auto;
  border: 1px solid #fecaca; border-radius: 8px;
  background: white; box-shadow: 0 16px 40px rgba(15, 23, 42, 0.16);
}
.data-issue-head {
  position: sticky; top: 0; z-index: 1;
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 10px 12px; border-bottom: 1px solid #fee2e2;
  background: #fff7f7; color: var(--red); font-size: 12px;
}
.data-issue-head-right { display: inline-flex; align-items: center; gap: 8px; }
.data-issue-head span { color: var(--muted); font-family: var(--mono); font-weight: 700; }
.data-issue-close-btn {
  width: 22px; height: 22px;
  display: grid; place-items: center;
  border: 1px solid #fecaca; border-radius: 6px;
  background: white; color: var(--red);
  font-size: 16px; line-height: 1; cursor: pointer;
}
.data-issue-close-btn:hover { background: #fee2e2; border-color: #fca5a5; }
.data-issue-list { padding: 6px; }
.data-issue-row { padding: 9px 10px; border-radius: 7px; }
.data-issue-row + .data-issue-row { border-top: 1px solid var(--line); }
.data-issue-title { color: var(--text); font-size: 12px; font-weight: 800; line-height: 1.45; }
.data-issue-meta { margin-top: 4px; color: var(--muted); font-size: 11px; line-height: 1.35; }
.data-issue-code { margin-top: 4px; color: var(--subtle); font-family: var(--mono); font-size: 11px; }
.data-issue-empty { padding: 14px 12px; color: var(--muted); font-size: 12px; }
.data-issue-empty.error { color: var(--red); }
.data-warning-panel {
  position: absolute; top: 28px; left: 0; z-index: 60;
  width: min(420px, calc(100vw - 32px));
  max-height: 360px; overflow: auto;
  border: 1px solid #fde68a; border-radius: 8px;
  background: white; box-shadow: 0 16px 40px rgba(15, 23, 42, 0.16);
}
.data-warning-head {
  position: sticky; top: 0; z-index: 1;
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 10px 12px; border-bottom: 1px solid #fde68a;
  background: #fffbeb; color: #92400e; font-size: 12px;
}
.data-warning-head-right { display: inline-flex; align-items: center; gap: 8px; }
.data-warning-head span { color: var(--muted); font-family: var(--mono); font-weight: 700; }
.data-warning-close-btn {
  width: 22px; height: 22px;
  display: grid; place-items: center;
  border: 1px solid #fde68a; border-radius: 6px;
  background: white; color: #92400e;
  font-size: 16px; line-height: 1; cursor: pointer;
}
.data-warning-close-btn:hover { background: #fef3c7; border-color: #fbbf24; }
.data-warning-list { padding: 6px; }
.data-warning-row { padding: 9px 10px; border-radius: 7px; }
.data-warning-row + .data-warning-row { border-top: 1px solid var(--line); }
.data-warning-title { color: var(--text); font-size: 12px; font-weight: 800; line-height: 1.45; }
.data-warning-meta { margin-top: 4px; color: var(--muted); font-size: 11px; line-height: 1.35; }
.data-warning-code { margin-top: 4px; color: var(--subtle); font-family: var(--mono); font-size: 11px; }
.data-warning-empty { padding: 14px 12px; color: var(--muted); font-size: 12px; }
.data-warning-empty.error { color: var(--red); }

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
