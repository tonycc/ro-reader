<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import type { ValidationIssue } from "../../stores/api";

const props = defineProps<{
  objectLabel: string
  metaLabel: string
  blockingErrors: ValidationIssue[]
  warnings: ValidationIssue[]
  loading: boolean
  error: string
}>();

const issuePanelOpen = ref(false);
const warningPanelOpen = ref(false);
const issueErrors = computed(() => dedupeIssues(props.blockingErrors));
const warningIssues = computed(() => dedupeIssues(props.warnings));

function dedupeIssues(issues: ValidationIssue[]): ValidationIssue[] {
  const seen = new Set<string>();
  return issues.filter((issue) => {
    const key = [issue.kind, issue.code, issue.message, issue.sheet ?? "", issue.row ?? "", issue.field ?? ""].join("|");
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function toggleIssuePanel() {
  issuePanelOpen.value = !issuePanelOpen.value;
  if (issuePanelOpen.value) warningPanelOpen.value = false;
}

function toggleWarningPanel() {
  warningPanelOpen.value = !warningPanelOpen.value;
  if (warningPanelOpen.value) issuePanelOpen.value = false;
}

function formatIssueLocation(issue: ValidationIssue): string {
  const parts = [];
  if (issue.sheet) parts.push(issue.sheet);
  if (issue.row !== null && issue.row !== undefined) parts.push(`row ${issue.row}`);
  if (issue.field) parts.push(issue.field);
  return parts.join(" / ") || "未定位到具体单元格";
}

function onDocumentClick(event: MouseEvent) {
  if (!issuePanelOpen.value && !warningPanelOpen.value) return;
  const target = event.target as HTMLElement;
  if (!target.closest(".data-issue-root")) issuePanelOpen.value = false;
  if (!target.closest(".data-warning-root")) warningPanelOpen.value = false;
}

function onKeydown(event: KeyboardEvent) {
  if (event.key !== "Escape") return;
  issuePanelOpen.value = false;
  warningPanelOpen.value = false;
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
  <div class="issue-bar">
    <span v-if="!loading && !error && !issueErrors.length && !warningIssues.length" class="issue-badge ready">✓ 就绪</span>
    <div v-if="issueErrors.length" class="data-issue-root">
      <button class="issue-badge blocked" type="button" @click="toggleIssuePanel">
        {{ issueErrors.length }} 项阻断
      </button>
      <div v-if="issuePanelOpen" class="data-issue-panel">
        <div class="data-issue-head">
          <strong>阻断原因</strong>
          <div class="data-issue-head-right">
            <span>{{ objectLabel }}</span>
            <button class="data-issue-close-btn" type="button" aria-label="关闭阻断原因" @click.stop="issuePanelOpen = false">×</button>
          </div>
        </div>
        <div v-if="loading" class="data-issue-empty">正在读取原因…</div>
        <div v-else-if="error" class="data-issue-empty error">{{ error }}</div>
        <div v-else class="data-issue-list">
          <div v-for="(issue, index) in issueErrors" :key="`${issue.code}-${index}`" class="data-issue-row">
            <div class="data-issue-title">{{ issue.message || issue.code }}</div>
            <div class="data-issue-meta">{{ formatIssueLocation(issue) }}</div>
            <div class="data-issue-code">{{ issue.code }}</div>
          </div>
        </div>
      </div>
    </div>
    <div v-if="warningIssues.length" class="data-warning-root">
      <button class="issue-badge fix" type="button" @click="toggleWarningPanel">
        {{ warningIssues.length }} 项警告
      </button>
      <div v-if="warningPanelOpen" class="data-warning-panel">
        <div class="data-warning-head">
          <strong>预警详情</strong>
          <div class="data-warning-head-right">
            <span>{{ objectLabel }}</span>
            <button class="data-warning-close-btn" type="button" aria-label="关闭预警详情" @click.stop="warningPanelOpen = false">×</button>
          </div>
        </div>
        <div v-if="loading" class="data-warning-empty">正在读取预警…</div>
        <div v-else-if="error" class="data-warning-empty error">{{ error }}</div>
        <div v-else class="data-warning-list">
          <div v-for="(issue, index) in warningIssues" :key="`${issue.code}-${index}`" class="data-warning-row">
            <div class="data-warning-title">{{ issue.message || issue.code }}</div>
            <div class="data-warning-meta">{{ formatIssueLocation(issue) }}</div>
            <div class="data-warning-code">{{ issue.code }}</div>
          </div>
        </div>
      </div>
    </div>
    <span v-if="loading" class="issue-meta">正在读取检查结果…</span>
    <span v-else-if="error" class="issue-meta error">{{ error }}</span>
    <span v-else class="issue-meta">{{ metaLabel }}</span>
  </div>
</template>

<style scoped>
.issue-bar { display: flex; align-items: center; gap: 10px; padding: 10px 14px; margin-bottom: 12px; border: 1px solid var(--line); border-radius: 8px; background: white; flex-wrap: wrap; }
.issue-badge { display: inline-flex; align-items: center; gap: 4px; height: 22px; padding: 0 8px; border-radius: 999px; font-size: 12px; border: 0; }
.ready { color: var(--green); background: var(--green-weak); }
.blocked { color: var(--red); background: var(--red-weak); cursor: pointer; font-weight: 700; }
.blocked:hover { box-shadow: inset 0 0 0 1px #fca5a5; }
.fix { color: var(--amber); background: var(--amber-weak); cursor: pointer; font-weight: 700; }
.fix:hover { box-shadow: inset 0 0 0 1px #fbbf24; }
.issue-meta { color: var(--muted); font-size: 12px; }
.issue-meta.error { color: var(--red); }
.data-issue-root, .data-warning-root { position: relative; display: inline-flex; }
.data-issue-panel, .data-warning-panel { position: absolute; top: 28px; left: 0; z-index: 60; width: min(420px, calc(100vw - 32px)); max-height: 360px; overflow: auto; border-radius: 8px; background: white; box-shadow: 0 16px 40px rgba(15, 23, 42, 0.16); }
.data-issue-panel { border: 1px solid #fecaca; }
.data-warning-panel { border: 1px solid #fde68a; }
.data-issue-head, .data-warning-head { position: sticky; top: 0; z-index: 1; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 12px; font-size: 12px; }
.data-issue-head { border-bottom: 1px solid #fee2e2; background: #fff7f7; color: var(--red); }
.data-warning-head { border-bottom: 1px solid #fde68a; background: #fffbeb; color: #92400e; }
.data-issue-head-right, .data-warning-head-right { display: inline-flex; align-items: center; gap: 8px; }
.data-issue-head span, .data-warning-head span { color: var(--muted); font-family: var(--mono); font-weight: 700; }
.data-issue-close-btn, .data-warning-close-btn { width: 22px; height: 22px; display: grid; place-items: center; border-radius: 6px; background: white; font-size: 16px; line-height: 1; cursor: pointer; }
.data-issue-close-btn { border: 1px solid #fecaca; color: var(--red); }
.data-warning-close-btn { border: 1px solid #fde68a; color: #92400e; }
.data-issue-list, .data-warning-list { padding: 6px; }
.data-issue-row, .data-warning-row { padding: 9px 10px; }
.data-issue-row + .data-issue-row, .data-warning-row + .data-warning-row { border-top: 1px solid var(--line); }
.data-issue-title, .data-warning-title { color: var(--text); font-size: 12px; font-weight: 800; line-height: 1.45; }
.data-issue-meta, .data-warning-meta { margin-top: 4px; color: var(--muted); font-size: 11px; line-height: 1.35; }
.data-issue-code, .data-warning-code { margin-top: 4px; color: var(--subtle); font-family: var(--mono); font-size: 11px; }
.data-issue-empty, .data-warning-empty { padding: 14px 12px; color: var(--muted); font-size: 12px; }
.data-issue-empty.error, .data-warning-empty.error { color: var(--red); }
</style>
