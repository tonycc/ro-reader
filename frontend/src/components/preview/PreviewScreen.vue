<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from "vue";
import { useWorkbench } from "../../stores/workbench";
import PreviewDocumentPanel from "./PreviewDocumentPanel.vue";
import type {
  PreviewSourceEntry,
  ValidationIssue,
} from "../../stores/api";

const wb = useWorkbench();
const showSourceSummary = ref(false);

const popoverVisible = ref(false);
const popoverEntry = ref<PreviewSourceEntry | null>(null);
const popoverStyle = ref<Record<string, string>>({});
const activeFieldEl = ref<HTMLElement | null>(null);
const issuePanelOpen = ref(false);

const sellers = ["SK", "YM", "GS PTE", "EMAX PTE"] as const;
const docTypes = computed(() => wb.previewScope === "invoice"
  ? [
      { key: "INVOICE_PL" as const, label: "Invoice & Packing List" },
    ]
  : [
      { key: "PI" as const, label: "PI" },
      { key: "PO" as const, label: "PO" },
    ]);
const docTypeLabelMap: Record<string, string> = {
  PI: "PI",
  PO: "PO",
  INVOICE: "Invoice / PL",
  PL: "PL",
  INVOICE_PL: "Invoice & Packing List",
};

const pd = computed(() => wb.previewData);
const isInvoicePlMode = computed(() => wb.previewDocType === "INVOICE" || wb.previewDocType === "PL" || wb.previewDocType === "INVOICE_PL");
const previewDocs = computed(() => {
  if (wb.previewDocuments.length) return wb.previewDocuments;
  if (!pd.value) return [];
  const docLabel = docTypeLabelMap[wb.previewDocType] || wb.previewDocType || "当前单据";
  return [{
    id: `${wb.selectedSeller}-${wb.previewDocType}`,
    seller: wb.selectedSeller,
    document: wb.previewDocType,
    label: `${wb.selectedSeller} · ${docLabel}`,
    preview: pd.value,
    errors: wb.blockingErrors,
    warnings: wb.warnings,
  }];
});
const hasData = computed(() => previewDocs.value.some((doc) => doc.preview?.lines?.length));
const errors = computed(() => wb.blockingErrors as { code?: string; message?: string }[]);
const currentDocLabel = computed(() => (
  isInvoicePlMode.value ? "Invoice & Packing List" : docTypeLabelMap[wb.previewDocType] || wb.previewDocType || "当前单据"
));
const issueErrors = computed<ValidationIssue[]>(() => wb.poIssues?.blocking_errors ?? []);
const issueCount = computed(() => wb.poIssues?.blocking_count ?? wb.poEntry?.blocking_count ?? errors.value.length);
const hasSelectedObject = computed(() => wb.previewScope === "invoice"
  ? Boolean(wb.selectedInvoiceGroup)
  : Boolean(wb.selectedPo));
const scopeTitle = computed(() => wb.previewScope === "invoice"
  ? wb.invoiceEntry?.display_invoice_no ?? ""
  : wb.selectedPo);
const sellerDisabled = (seller: string) => wb.previewScope === "invoice"
  && !wb.invoiceEntry?.sellers.includes(seller);

async function exportCurrentDocument() {
  await wb.doExport();
}

async function toggleIssuePanel() {
  issuePanelOpen.value = !issuePanelOpen.value;
  if (wb.previewScope === "po" && issuePanelOpen.value && !wb.poIssues && !wb.issuesLoading) {
    await wb.refreshPoIssues();
  }
}

function closeIssuePanel() {
  issuePanelOpen.value = false;
}

function formatIssueLocation(issue: ValidationIssue): string {
  const parts = [];
  if (issue.sheet) parts.push(issue.sheet);
  if (issue.row !== null && issue.row !== undefined) parts.push(`row ${issue.row}`);
  if (issue.field) parts.push(issue.field);
  return parts.join(" / ") || "未定位到具体单元格";
}

function onFieldClick(fieldRef: string, event: MouseEvent, entries?: PreviewSourceEntry[]) {
  const target = event.currentTarget as HTMLElement;
  const sourceEntries = entries ?? wb.previewSourceEntries;
  const match = sourceEntries.find((e) => e.preview_field === fieldRef);

  // Toggle off if clicking the same field
  if (popoverVisible.value && activeFieldEl.value === target) {
    closePopover();
    return;
  }

  // Remove active state from previous
  if (activeFieldEl.value) {
    activeFieldEl.value.classList.remove("field-active");
  }

  if (match) {
    popoverEntry.value = match;
    popoverVisible.value = true;
    target.classList.add("field-active");
    activeFieldEl.value = target;
    nextTick(() => positionPopover(target));
  }
}

function positionPopover(anchor: HTMLElement) {
  const popover = document.querySelector(".source-popover") as HTMLElement;
  if (!popover) return;

  const anchorRect = anchor.getBoundingClientRect();
  const popoverW = 320;
  const popoverH = Math.min(popover.scrollHeight, 260);
  const gap = 8;
  const viewportW = window.innerWidth;
  const viewportH = window.innerHeight;

  // Prefer below, flip to above if not enough room
  let top = anchorRect.bottom + gap;
  let arrowClass = "arrow-up";
  if (top + popoverH > viewportH - 12 && anchorRect.top - popoverH - gap > 0) {
    top = anchorRect.top - popoverH - gap;
    arrowClass = "arrow-down";
  }

  // Horizontal: center on anchor, clamp to viewport
  let left = anchorRect.left + anchorRect.width / 2 - popoverW / 2;
  left = Math.max(8, Math.min(left, viewportW - popoverW - 8));

  popoverStyle.value = {
    position: "fixed",
    top: `${top}px`,
    left: `${left}px`,
    width: `${popoverW}px`,
    maxHeight: "260px",
    zIndex: "9999",
  };
  // Set arrow class via a data attribute since style binding doesn't handle class
  popover.setAttribute("data-arrow", arrowClass);
}

function closePopover() {
  popoverVisible.value = false;
  popoverEntry.value = null;
  if (activeFieldEl.value) {
    activeFieldEl.value.classList.remove("field-active");
    activeFieldEl.value = null;
  }
}

function onDocumentClick(e: MouseEvent) {
  const target = e.target as HTMLElement;
  if (issuePanelOpen.value && !target.closest(".issue-panel-root")) {
    closeIssuePanel();
  }
  if (!popoverVisible.value) return;
  const popover = document.querySelector(".source-popover");
  // Close if click is outside popover and outside any clickable field
  if (popover && !popover.contains(target) && !target.closest(".clickable")) {
    closePopover();
  }
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === "Escape") {
    closeIssuePanel();
    closePopover();
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
  <div class="preview-screen">
    <div v-if="!hasSelectedObject" class="placeholder">
      {{ wb.previewScope === 'invoice' ? '选择左侧 Invoice 开始预览' : '选择左侧 PO 并切换单据预览' }}
    </div>
    <template v-else>
      <!-- Filter bar -->
      <div class="preview-filterbar">
        <div class="filter-left">
          <div v-if="wb.previewScope === 'invoice'" class="scope-heading" data-testid="invoice-scope-title">
            <strong>{{ scopeTitle }}</strong>
            <span>{{ wb.invoiceEntry?.po_count ?? 0 }} 个 PO</span>
          </div>
          <div class="filter-group">
            <span class="filter-label">公司主体</span>
            <button
              v-for="s in sellers" :key="s"
              class="filter-pill"
              :class="{ active: wb.selectedSeller === s }"
              :disabled="sellerDisabled(s)"
              :title="sellerDisabled(s) ? '该票据组在此主体下无可装配数据' : ''"
              @click="wb.selectSeller(s)"
            >
              {{ s }}
            </button>
          </div>
          <div class="filter-group">
            <span class="filter-label">单据</span>
            <button
              v-for="d in docTypes" :key="d.key"
              class="filter-pill"
              :class="{ active: wb.previewDocType === d.key }"
              :disabled="(wb.selectedSeller === 'SK' || wb.selectedSeller === 'YM') && d.key === 'PO'"
              :data-testid="wb.previewScope === 'invoice' ? `invoice-document-${d.key}` : undefined"
              @click="wb.refreshPreview(d.key)"
            >
              {{ d.label }}
            </button>
          </div>
        </div>
        <div class="filter-right">
          <div v-if="wb.previewScope === 'po' && (wb.poStatus === 'blocked' || issueCount > 0)" class="issue-panel-root">
            <button
              class="issue-badge-btn"
              :class="{ active: issuePanelOpen }"
              type="button"
              @click.stop="toggleIssuePanel"
            >
              阻断 {{ issueCount }} 项
            </button>
            <div v-if="issuePanelOpen" class="issue-panel">
              <div class="issue-panel-head">
                <strong>阻断原因</strong>
                <div class="issue-panel-head-right">
                  <span>{{ wb.selectedPo }}</span>
                  <button
                    class="issue-close-btn"
                    type="button"
                    aria-label="关闭阻断原因"
                    @click.stop="closeIssuePanel"
                  >
                    ×
                  </button>
                </div>
              </div>
              <div v-if="wb.issuesLoading" class="issue-panel-empty">正在读取原因…</div>
              <div v-else-if="wb.issuesError" class="issue-panel-empty error">{{ wb.issuesError }}</div>
              <div v-else-if="!issueErrors.length" class="issue-panel-empty">暂无阻断明细</div>
              <div v-else class="issue-list">
                <div v-for="(issue, index) in issueErrors" :key="`${issue.code}-${index}`" class="issue-row">
                  <div class="issue-title">{{ issue.message || issue.code }}</div>
                  <div class="issue-meta">{{ formatIssueLocation(issue) }}</div>
                  <div class="issue-code">{{ issue.code }}</div>
                </div>
              </div>
            </div>
          </div>
          <button
            class="ghost-btn export-btn"
            :disabled="!hasData || wb.exporting || wb.previewLoading"
            @click="exportCurrentDocument"
            v-if="hasData"
          >
            {{ wb.exporting ? "导出中…" : `导出 ${currentDocLabel}` }}
          </button>
          <button
            class="ghost-btn"
            :class="{ active: showSourceSummary }"
            @click="showSourceSummary = !showSourceSummary"
            v-if="hasData"
          >
            查看字段来源
          </button>
        </div>
      </div>

      <!-- Body -->
      <div class="preview-body">
        <div v-if="wb.previewError && !wb.previewLoading" class="alert alert-err">
          <div class="alert-item"><span class="alert-dot err"></span>{{ wb.previewError }}</div>
        </div>
        <div v-else-if="!hasData && !errors.length" class="status-msg">
          {{ previewDocs.length ? '单据无数据' : '正在加载预览…' }}
        </div>

        <!-- Loading overlay -->
        <div v-if="wb.previewLoading" class="loading-overlay">
          <span class="spinner" />
          <span>加载中…</span>
        </div>

        <div v-if="previewDocs.length" class="preview-doc-list">
          <section
            v-for="doc in previewDocs"
            :key="doc.id"
            class="preview-doc-section"
          >
            <div class="preview-doc-head">
              <h2 class="preview-doc-title">{{ doc.label }}</h2>
            </div>
            <div v-if="doc.errors.length" class="alert alert-err">
              <div v-for="(e, i) in doc.errors" :key="doc.id + '-e' + i" class="alert-item">
                <span class="alert-dot err"></span>
                {{ (e as any).message || (e as any).code }}
              </div>
            </div>
            <div v-if="doc.warnings.length" class="alert alert-warn">
              <div v-for="(w, i) in doc.warnings" :key="doc.id + '-w' + i" class="alert-item">
                <span class="alert-dot warn"></span>
                <span :class="{ 'severity-high': (w as any).severity === 'high' }">
                  {{ (w as any).message || (w as any).code }}
                </span>
              </div>
            </div>
            <PreviewDocumentPanel
              v-if="doc.preview && doc.preview.lines.length"
              :pd="doc.preview"
              @field-click="(fieldRef, event) => onFieldClick(fieldRef, event, doc.preview?.source_entries ?? [])"
            />
            <div v-else class="status-msg">当前单据无数据</div>
          </section>
        </div>

        <!-- Field Source Summary panel -->
        <div v-if="showSourceSummary && hasData" class="source-summary">
          <div class="panel-head">
            <h3 class="panel-title">字段来源摘要</h3>
            <span class="panel-subtitle">点击字段查看来源 popover，此处为完整列表</span>
          </div>
          <div class="panel-body">
            <table class="source-table" v-if="wb.previewSourceEntries.length">
              <thead>
                <tr>
                  <th>单据字段</th>
                  <th>来源</th>
                  <th>当前值</th>
                  <th>规则</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="(entry, ei) in wb.previewSourceEntries"
                  :key="'se'+ei"
                  :class="{
                    'row-template': entry.source_type === 'template_content',
                    'row-computed': entry.source_type === 'computed',
                    'row-generated': entry.source_type === 'system_generated',
                    'row-manual': entry.source_type === 'manual_input',
                  }"
                >
                  <td>{{ entry.label }}</td>
                  <td>
                    <span v-if="entry.source_type === 'base_field'" class="source-tag base">
                      {{ entry.sheet }}<span v-if="entry.field"> · {{ entry.field }}</span>
                      <span v-if="entry.row"> · Row {{ entry.row }}</span>
                    </span>
                    <span v-else-if="entry.source_type === 'computed'" class="source-tag computed">计算字段</span>
                    <span v-else-if="entry.source_type === 'system_generated'" class="source-tag generated">系统生成</span>
                    <span v-else-if="entry.source_type === 'manual_input'" class="source-tag manual">人工填写</span>
                    <span v-else class="source-tag template">模板固定文本</span>
                  </td>
                  <td class="mono">{{ entry.value }}</td>
                  <td class="rule">{{ entry.rule }}</td>
                </tr>
              </tbody>
            </table>
            <div v-else class="status-msg">暂无字段来源数据</div>
          </div>
        </div>
      </div>
    </template>

    <!-- Source Popover -->
    <Teleport to="body">
      <div
        v-if="popoverVisible && popoverEntry"
        class="source-popover"
        :style="popoverStyle"
      >
        <div class="popover-header">
          <span class="popover-label">{{ popoverEntry.label }}</span>
          <button class="popover-close" @click="closePopover">&times;</button>
        </div>
        <div class="popover-body">
          <div class="popover-row">
            <span class="popover-key">来源</span>
            <span v-if="popoverEntry.source_type === 'base_field'" class="source-tag base">
              {{ popoverEntry.sheet }}<span v-if="popoverEntry.field"> · {{ popoverEntry.field }}</span>
              <span v-if="popoverEntry.row"> · Row {{ popoverEntry.row }}</span>
            </span>
            <span v-else-if="popoverEntry.source_type === 'computed'" class="source-tag computed">计算字段</span>
            <span v-else-if="popoverEntry.source_type === 'system_generated'" class="source-tag generated">系统生成</span>
            <span v-else-if="popoverEntry.source_type === 'manual_input'" class="source-tag manual">人工填写</span>
            <span v-else class="source-tag template">模板固定文本</span>
          </div>
          <div class="popover-row">
            <span class="popover-key">当前值</span>
            <span class="mono">{{ popoverEntry.value }}</span>
          </div>
          <div class="popover-row">
            <span class="popover-key">规则</span>
            <span class="popover-rule">{{ popoverEntry.rule }}</span>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.preview-screen {
  height: 100%;
  display: flex;
  flex-direction: column;
}
.placeholder {
  padding: var(--space-8);
  text-align: center;
  color: var(--subtle);
}

/* Filter bar */
.preview-filterbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 48px;
  padding: 6px 12px;
  border-bottom: 1px solid var(--line);
  background: white;
  flex-wrap: wrap;
}
.filter-left { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.scope-heading { display: flex; align-items: baseline; gap: 8px; margin-right: 6px; }
.scope-heading strong { font-family: var(--mono); font-size: 18px; }
.scope-heading span { color: var(--muted); font-size: 12px; }
.filter-right { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.filter-group { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.filter-label { color: var(--muted); font-size: 12px; font-weight: 800; white-space: nowrap; }
.filter-pill {
  height: 30px; padding: 0 10px;
  border: 1px solid var(--line); border-radius: 999px;
  background: white; color: var(--muted);
  font-size: 12px; font-weight: 800; white-space: nowrap; cursor: pointer;
}
.filter-pill.active {
  border-color: #9bbcff; color: var(--blue);
  background: var(--blue-weak); box-shadow: inset 0 0 0 1px #c7d9ff;
}
.filter-pill:disabled { opacity: 0.45; cursor: not-allowed; background: #f2f4f7; }
.issue-panel-root { position: relative; flex-shrink: 0; }
.issue-badge-btn {
  height: 30px; padding: 0 10px;
  border: 1px solid #fecaca; border-radius: 999px;
  background: #fff5f5; color: var(--red);
  font-size: 12px; font-weight: 900; cursor: pointer;
}
.issue-badge-btn:hover,
.issue-badge-btn.active {
  border-color: #fca5a5;
  background: #fee2e2;
}
.issue-panel {
  position: absolute; top: 36px; right: 0; z-index: 70;
  width: min(420px, calc(100vw - 32px));
  max-height: 360px; overflow: auto;
  border: 1px solid #fecaca; border-radius: 8px;
  background: white; box-shadow: 0 16px 40px rgba(15, 23, 42, 0.16);
}
.issue-panel-head {
  position: sticky; top: 0; z-index: 1;
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 10px 12px; border-bottom: 1px solid #fee2e2;
  background: #fff7f7; color: var(--red); font-size: 12px;
}
.issue-panel-head-right { display: inline-flex; align-items: center; gap: 8px; }
.issue-panel-head span { color: var(--muted); font-family: var(--mono); font-weight: 700; }
.issue-close-btn {
  width: 22px; height: 22px;
  display: grid; place-items: center;
  border: 1px solid #fecaca; border-radius: 6px;
  background: white; color: var(--red);
  font-size: 16px; line-height: 1; cursor: pointer;
}
.issue-close-btn:hover { background: #fee2e2; border-color: #fca5a5; }
.issue-list { padding: 6px; }
.issue-row { padding: 9px 10px; border-radius: 7px; }
.issue-row + .issue-row { border-top: 1px solid var(--line); }
.issue-title { color: var(--text); font-size: 12px; font-weight: 800; line-height: 1.45; }
.issue-meta { margin-top: 4px; color: var(--muted); font-size: 11px; line-height: 1.35; }
.issue-code { margin-top: 4px; color: var(--subtle); font-family: var(--mono); font-size: 11px; }
.issue-panel-empty { padding: 14px 12px; color: var(--muted); font-size: 12px; }
.issue-panel-empty.error { color: var(--red); }
.ghost-btn {
  height: 30px; padding: 0 10px;
  border: 1px solid var(--line); border-radius: 6px;
  background: white; color: var(--muted);
  font-size: 12px; font-weight: 700; cursor: pointer;
}
.ghost-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.ghost-btn.active { border-color: #9bbcff; color: var(--blue); background: var(--blue-weak); }
.export-btn { border-color: #9bbcff; color: var(--blue); }

.preview-body { flex: 1; overflow: auto; padding: 16px 20px; }

.loading-overlay {
  display: flex; align-items: center; justify-content: center; gap: 10px;
  padding: 48px 20px; color: var(--muted); font-size: 13px;
}
.spinner {
  width: 18px; height: 18px;
  border: 2px solid var(--line); border-top-color: var(--blue);
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.alert { margin-bottom: 12px; border-radius: 8px; padding: 10px 12px; font-size: 12px; line-height: 1.5; }
.alert-err { border: 1px solid #fecaca; background: #fff5f5; color: var(--red); }
.alert-warn { border: 1px solid #fde68a; background: #fffbeb; color: #92400e; }
.alert-item { display: flex; align-items: flex-start; gap: 8px; }
.alert-item + .alert-item { margin-top: 4px; }
.alert-dot { width: 8px; height: 8px; border-radius: 99px; margin-top: 3px; flex-shrink: 0; }
.alert-dot.err { background: var(--red); }
.alert-dot.warn { background: #f59e0b; }
.severity-high { font-weight: 700; }
.status-msg { padding: var(--space-3); color: var(--muted); }

.preview-doc-list {
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.preview-doc-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.preview-doc-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 4px 2px 0;
}
.preview-doc-title {
  margin: 0;
  font-size: 14px;
  color: var(--text);
  font-weight: 900;
}

/* Source summary */
.source-summary { margin-top: 14px; background: white; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
.panel-head {
  min-height: 43px; display: flex; align-items: center; justify-content: space-between;
  gap: 12px; padding: 10px 12px; border-bottom: 1px solid var(--line);
  background: linear-gradient(#ffffff, #fbfcfd);
}
.panel-title { margin: 0; font-size: 13px; font-weight: 900; }
.panel-subtitle { color: var(--muted); font-size: 11px; white-space: nowrap; }
.panel-body { padding: 0; overflow-x: auto; }
.source-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.source-table th, .source-table td { border-bottom: 1px solid var(--line); padding: 9px 8px; text-align: left; vertical-align: top; }
.source-table th { color: var(--muted); background: #f9fafb; font-size: 11px; font-weight: 900; }
.source-table tr:last-child td { border-bottom: 0; }
.source-table td.mono { font-family: var(--mono); white-space: nowrap; }
.source-table td.rule { color: var(--muted); font-size: 11px; }
.row-template td { color: var(--subtle); }
.row-computed td { color: #6d28d9; }

.source-tag {
  display: inline-block; font-family: var(--mono); font-size: 11px;
  border-radius: 4px; padding: 2px 6px; white-space: nowrap;
}
.source-tag.base { background: #eef3f9; color: #2b3a51; }
.source-tag.computed { background: #f3e8ff; color: #6d28d9; }
.source-tag.generated { background: #e7f6ee; color: #18794e; }
.source-tag.manual { background: #fff4e5; color: #9a5b00; }
.source-tag.template { background: #f5f7fa; color: var(--subtle); }

/* Source Popover */
.source-popover {
  background: white; border: 1px solid var(--line);
  border-radius: 10px;
  box-shadow: 0 8px 30px rgba(21, 32, 51, 0.18), 0 2px 6px rgba(21, 32, 51, 0.08);
  overflow: hidden; overflow-y: auto;
  animation: popover-in 0.12s ease-out;
}
@keyframes popover-in {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

.source-popover::before {
  content: ""; position: absolute; width: 12px; height: 12px;
  background: white; border: 1px solid var(--line);
  transform: rotate(45deg); left: calc(50% - 6px);
}
.source-popover[data-arrow="arrow-up"]::before {
  top: -7px; border-right: 0; border-bottom: 0;
}
.source-popover[data-arrow="arrow-down"]::before {
  bottom: -7px; border-left: 0; border-top: 0;
}

.popover-header {
  display: flex; align-items: center; justify-content: space-between;
  gap: 10px; padding: 10px 14px; border-bottom: 1px solid var(--line);
  background: #fbfcfd;
}
.popover-label { font-weight: 800; font-size: 13px; color: #152033; }
.popover-close {
  width: 24px; height: 24px; border: 0; border-radius: 6px;
  background: transparent; color: var(--muted);
  font-size: 16px; line-height: 1; cursor: pointer;
  display: grid; place-items: center;
}
.popover-close:hover { background: #f2f4f7; color: var(--text); }

.popover-body { padding: 10px 14px 12px; }
.popover-row { display: flex; align-items: flex-start; gap: 10px; padding: 6px 0; font-size: 12px; line-height: 1.5; }
.popover-row + .popover-row { border-top: 1px solid #f5f7fa; }
.popover-key { flex-shrink: 0; width: 52px; color: var(--muted); font-weight: 700; font-size: 11px; }
.popover-rule { color: var(--muted); font-size: 11px; line-height: 1.45; }
.mono { font-family: var(--mono); font-size: 0.92em; }

@media (max-width: 1180px) {
  .preview-body { padding: 12px; }
}
</style>
