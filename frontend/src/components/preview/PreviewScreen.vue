<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from "vue";
import { useWorkbench } from "../../stores/workbench";
import type {
  PreviewFooterItem,
  PreviewSourceEntry,
} from "../../stores/api";

const wb = useWorkbench();
const showSourceSummary = ref(false);

const popoverVisible = ref(false);
const popoverEntry = ref<PreviewSourceEntry | null>(null);
const popoverStyle = ref<Record<string, string>>({});
const activeFieldEl = ref<HTMLElement | null>(null);

const sellers = ["SK", "YM", "GS PTE", "EMAX PTE"] as const;
const docTypes = [
  { key: "PI" as const, label: "PI" },
  { key: "PO" as const, label: "PO" },
  { key: "INVOICE" as const, label: "Invoice" },
  { key: "PL" as const, label: "PL" },
];
const docTypeLabelMap: Record<string, string> = {
  PI: "PI",
  PO: "PO",
  INVOICE: "Invoice",
  PL: "PL",
};

const pd = computed(() => wb.previewData);
const hasData = computed(() => pd.value && pd.value.lines && pd.value.lines.length > 0);
const errors = computed(() => wb.blockingErrors as { code?: string; message?: string }[]);
const warnings = computed(() => wb.warnings as { code?: string; message?: string; severity?: string }[]);
const currentDocLabel = computed(() => docTypeLabelMap[wb.previewDocType] || wb.previewDocType || "当前单据");

const DEFAULT_LAYOUT = {
  top: { left: [] as string[], center: [] as string[], right: [] as string[] },
  info: { left: [] as string[], right: [] as string[] },
};

const layout = computed(() => {
  return pd.value?.layout || DEFAULT_LAYOUT;
});

const footerTotalItems = computed<PreviewFooterItem[]>(() => {
  const raw = pd.value?.totals?.["_footer_items"];
  if (!Array.isArray(raw)) return [];
  return raw.filter((item): item is PreviewFooterItem => {
    if (!item || typeof item !== "object") return false;
    const key = (item as Record<string, unknown>).key;
    const label = (item as Record<string, unknown>).label;
    const value = (item as Record<string, unknown>).value;
    return typeof key === "string" && typeof label === "string" && typeof value === "string";
  });
});

function formatTermKey(key: string): string {
  return key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

async function exportCurrentDocument() {
  await wb.doExport();
}

function onFieldClick(fieldRef: string, event: MouseEvent) {
  const target = event.currentTarget as HTMLElement;
  const entries = wb.previewSourceEntries;
  const match = entries.find((e) => e.preview_field === fieldRef);

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
  if (!popoverVisible.value) return;
  const popover = document.querySelector(".source-popover");
  const target = e.target as HTMLElement;
  // Close if click is outside popover and outside any clickable field
  if (popover && !popover.contains(target) && !target.closest(".clickable")) {
    closePopover();
  }
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === "Escape" && popoverVisible.value) {
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

function isNumericCol(key: string) {
  return ["unit_price", "quantity", "amount", "net_weight", "gross_weight", "cbm", "carton_count"].includes(key);
}

// 通用字段取值：pd 顶级属性 → terms → resolved_values
function getFieldValue(field: string): string {
  if (!pd.value) return "";
  const extra = (pd.value as any).resolved_values;
  if (extra && extra[field] !== undefined) return String(extra[field]);
  const top = (pd.value as any)[field];
  if (top !== null && top !== undefined && top !== "") return String(top);
  const terms = pd.value.terms;
  if (terms && (terms as any)[field] !== undefined) return String((terms as any)[field]);
  return "";
}

const CONTINUATION_FIELDS = new Set([
  "bill_to_line2",
  "bill_to_line3",
  "ship_to_line2",
  "ship_to_line3",
  "manufacturer_address_2",
  "shipping_mark_2",
  "shipping_mark_3",
]);

function isContinuationField(field: string): boolean {
  return CONTINUATION_FIELDS.has(field);
}

function formatFieldLabel(field: string): string {
  if (field === "shipping_mark") return "SHIPPING MARK";
  return field.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
</script>

<template>
  <div class="preview-screen">
    <div v-if="!wb.selectedPo" class="placeholder">
      选择左侧 PO 并切换单据预览
    </div>
    <template v-else>
      <!-- Filter bar -->
      <div class="preview-filterbar">
        <div class="filter-left">
          <div class="filter-group">
            <span class="filter-label">公司主体</span>
            <button
              v-for="s in sellers" :key="s"
              class="filter-pill"
              :class="{ active: wb.selectedSeller === s }"
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
              @click="wb.refreshPreview(d.key)"
            >
              {{ d.label }}
            </button>
          </div>
        </div>
        <div class="filter-right">
          <button
            class="ghost-btn export-btn"
            :disabled="!hasData || wb.exporting || wb.previewLoading"
            @click="exportCurrentDocument"
            v-if="hasData"
          >
            {{ wb.exporting ? "导出中…" : `导出当前单据（${currentDocLabel}）` }}
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
        <!-- Errors / Warnings -->
        <div v-if="errors.length" class="alert alert-err">
          <div v-for="(e, i) in errors" :key="'e'+i" class="alert-item">
            <span class="alert-dot err"></span>
            {{ (e as any).message || e.code }}
          </div>
        </div>
        <div v-if="warnings.length" class="alert alert-warn">
          <div v-for="(w, i) in warnings" :key="'w'+i" class="alert-item">
            <span class="alert-dot warn"></span>
            <span :class="{ 'severity-high': (w as any).severity === 'high' }">
              {{ (w as any).message || w.code }}
            </span>
          </div>
        </div>

        <div v-if="!hasData && !errors.length" class="status-msg">
          {{ pd ? '单据无数据' : '正在加载预览…' }}
        </div>

        <!-- Loading overlay -->
        <div v-if="wb.previewLoading" class="loading-overlay">
          <span class="spinner" />
          <span>加载中…</span>
        </div>

        <!-- Document Card -->
        <div v-if="hasData && pd" class="document-card">
          <!-- Top line: layout-driven left / center / right -->
          <div class="doc-topline">
            <div class="top-left" v-if="layout.top.left.length">
              <template v-for="field in layout.top.left" :key="field">
                <template v-if="field === 'seller_info'">
                  <div class="company-block" v-if="pd.seller_info.length">
                    <strong>{{ pd.seller_info[0] }}</strong>
                    <template v-for="(line, i) in pd.seller_info.slice(1)" :key="'ci'+i">
                      <br />{{ line }}
                    </template>
                  </div>
                </template>
                <span v-else-if="field === 'to_label' && pd.to_label" class="to-line">{{ pd.to_label }}</span>
                <h1 v-else-if="field === 'title'">{{ pd.title }}</h1>
                <p v-else-if="field === 'seller'" class="top-field-line clickable" @click="onFieldClick('seller', $event)">Seller: {{ pd.seller }}</p>
                <p v-else-if="field === 'buyer'" class="top-field-line clickable" @click="onFieldClick('buyer', $event)">Buyer: {{ pd.buyer }}</p>
                <p v-else-if="field === 'po_no'" class="top-field-line clickable" @click="onFieldClick('po_no', $event)">PO: {{ pd.po_no }}</p>
                <div v-else-if="field === 'ship_to' && pd.ship_to" class="info-ship">
                  <div class="info-title">Ship To</div>
                  <p class="clickable" @click="onFieldClick('ship_to', $event)">{{ pd.ship_to }}</p>
                </div>
                <span v-else-if="field === 'invoice_no' && pd.invoice_no" class="top-clickable clickable" @click="onFieldClick('invoice_no', $event)">Invoice #: {{ pd.invoice_no }}</span>
                <span v-else-if="field === 'pi_no' && pd.pi_no && pd.document_type === 'PI'" class="top-clickable clickable" @click="onFieldClick('pi_no', $event)">PI #: {{ pd.pi_no }}</span>
                <div v-else-if="field === 'terms' && Object.keys(pd.terms).length" class="terms-block">
                  <div v-for="(val, key) in pd.terms" :key="'t_'+key" class="term-line">
                    <span class="term-key">{{ formatTermKey(key) }}</span>
                    <span class="term-val">{{ val }}</span>
                  </div>
                </div>
              </template>
            </div>
            <div class="top-center" v-if="layout.top.center.length">
              <template v-for="field in layout.top.center" :key="field">
                <template v-if="field === 'seller_info'">
                  <div class="company-block" v-if="pd.seller_info.length">
                    <strong>{{ pd.seller_info[0] }}</strong>
                    <template v-for="(line, i) in pd.seller_info.slice(1)" :key="'ci'+i">
                      <br />{{ line }}
                    </template>
                  </div>
                </template>
                <span v-else-if="field === 'to_label' && pd.to_label" class="to-line">{{ pd.to_label }}</span>
                <h1 v-else-if="field === 'title'">{{ pd.title }}</h1>
                <p v-else-if="field === 'seller'" class="top-field-line clickable" @click="onFieldClick('seller', $event)">Seller: {{ pd.seller }}</p>
                <p v-else-if="field === 'buyer'" class="top-field-line clickable" @click="onFieldClick('buyer', $event)">Buyer: {{ pd.buyer }}</p>
                <p v-else-if="field === 'po_no'" class="top-field-line clickable" @click="onFieldClick('po_no', $event)">PO: {{ pd.po_no }}</p>
                <div v-else-if="field === 'ship_to' && pd.ship_to" class="info-ship">
                  <div class="info-title">Ship To</div>
                  <p class="clickable" @click="onFieldClick('ship_to', $event)">{{ pd.ship_to }}</p>
                </div>
                <span v-else-if="field === 'invoice_no' && pd.invoice_no" class="top-clickable clickable" @click="onFieldClick('invoice_no', $event)">Invoice #: {{ pd.invoice_no }}</span>
                <span v-else-if="field === 'pi_no' && pd.pi_no && pd.document_type === 'PI'" class="top-clickable clickable" @click="onFieldClick('pi_no', $event)">PI #: {{ pd.pi_no }}</span>
                <div v-else-if="field === 'terms' && Object.keys(pd.terms).length" class="terms-block">
                  <div v-for="(val, key) in pd.terms" :key="'t_'+key" class="term-line">
                    <span class="term-key">{{ formatTermKey(key) }}</span>
                    <span class="term-val">{{ val }}</span>
                  </div>
                </div>
              </template>
            </div>
            <div class="top-right" v-if="layout.top.right.length">
              <template v-for="field in layout.top.right" :key="field">
                <template v-if="field === 'seller_info'">
                  <div class="company-block" v-if="pd.seller_info.length">
                    <strong>{{ pd.seller_info[0] }}</strong>
                    <template v-for="(line, i) in pd.seller_info.slice(1)" :key="'ci'+i">
                      <br />{{ line }}
                    </template>
                  </div>
                </template>
                <span v-else-if="field === 'to_label' && pd.to_label" class="to-line">{{ pd.to_label }}</span>
                <h1 v-else-if="field === 'title'">{{ pd.title }}</h1>
                <p v-else-if="field === 'seller'" class="top-field-line clickable" @click="onFieldClick('seller', $event)">Seller: {{ pd.seller }}</p>
                <p v-else-if="field === 'buyer'" class="top-field-line clickable" @click="onFieldClick('buyer', $event)">Buyer: {{ pd.buyer }}</p>
                <p v-else-if="field === 'po_no'" class="top-field-line clickable" @click="onFieldClick('po_no', $event)">PO: {{ pd.po_no }}</p>
                <div v-else-if="field === 'ship_to' && pd.ship_to" class="info-ship">
                  <div class="info-title">Ship To</div>
                  <p class="clickable" @click="onFieldClick('ship_to', $event)">{{ pd.ship_to }}</p>
                </div>
                <span v-else-if="field === 'invoice_no' && pd.invoice_no" class="top-clickable clickable" @click="onFieldClick('invoice_no', $event)">Invoice #: {{ pd.invoice_no }}</span>
                <span v-else-if="field === 'pi_no' && pd.pi_no && pd.document_type === 'PI'" class="top-clickable clickable" @click="onFieldClick('pi_no', $event)">PI #: {{ pd.pi_no }}</span>
                <div v-else-if="field === 'terms' && Object.keys(pd.terms).length" class="terms-block">
                  <div v-for="(val, key) in pd.terms" :key="'t_'+key" class="term-line">
                    <span class="term-key">{{ formatTermKey(key) }}</span>
                    <span class="term-val">{{ val }}</span>
                  </div>
                </div>
              </template>
            </div>
          </div>

          <!-- Info section: layout-driven left / right -->
          <div class="doc-info">
            <div class="info-left" v-if="layout.info.left.length">
              <table class="kv-table">
                <template v-for="field in layout.info.left" :key="field">
                  <template v-if="field === 'seller_info'">
                    <tr v-if="pd.seller_info.length">
                      <td colspan="2">
                        <strong>{{ pd.seller_info[0] }}</strong>
                        <template v-for="(line, i) in pd.seller_info.slice(1)" :key="'ci'+i">
                          <br />{{ line }}
                        </template>
                      </td>
                    </tr>
                  </template>
                  <tr v-else-if="field === 'invoice_no' && pd.invoice_no">
                    <td>Invoice #</td>
                    <td>
                      <span class="clickable" @click="onFieldClick('invoice_no', $event)">{{ pd.invoice_no }}</span>
                    </td>
                  </tr>
                  <tr v-else-if="field === 'pi_no' && pd.pi_no && pd.document_type === 'PI'">
                    <td>PI #</td>
                    <td>
                      <span class="clickable" @click="onFieldClick('pi_no', $event)">{{ pd.pi_no }}</span>
                    </td>
                  </tr>
                  <template v-else-if="field === 'terms'">
                    <tr v-for="(val, key) in pd.terms" :key="'t_'+key">
                      <td>{{ formatTermKey(key) }}</td>
                      <td>{{ val }}</td>
                    </tr>
                  </template>
                  <tr v-else-if="getFieldValue(field)">
                    <td :class="{ 'continuation-label': isContinuationField(field) }">
                      {{ isContinuationField(field) ? "" : formatFieldLabel(field) }}
                    </td>
                    <td :class="{ 'continuation-value': isContinuationField(field) }">
                      <span class="clickable" @click="onFieldClick(field, $event)">{{ getFieldValue(field) }}</span>
                    </td>
                  </tr>
                </template>
              </table>
            </div>
            <div class="info-right" v-if="layout.info.right.length">
              <table class="kv-table">
                <template v-for="field in layout.info.right" :key="field">
                  <tr v-if="field === 'invoice_no' && pd.invoice_no">
                    <td>Invoice No.</td>
                    <td>
                      <span class="clickable" @click="onFieldClick('invoice_no', $event)">{{ pd.invoice_no }}</span>
                    </td>
                  </tr>
                  <tr v-else-if="field === 'pi_no' && pd.pi_no && pd.document_type === 'PI'">
                    <td>PI #</td>
                    <td>
                      <span class="clickable" @click="onFieldClick('pi_no', $event)">{{ pd.pi_no }}</span>
                    </td>
                  </tr>
                  <template v-else-if="field === 'terms'">
                    <tr v-for="(val, key) in pd.terms" :key="'t_'+key">
                      <td>{{ formatTermKey(key) }}</td>
                      <td>{{ val }}</td>
                    </tr>
                  </template>
                  <tr v-else-if="field === 'seller'">
                    <td>Seller</td>
                    <td>{{ pd.seller }}</td>
                  </tr>
                  <tr v-else-if="field === 'buyer'">
                    <td>Buyer</td>
                    <td>{{ pd.buyer }}</td>
                  </tr>
                  <!-- 通用回退：未识别的字段名从 pd 或 pd.terms 取值 -->
                  <tr v-else-if="getFieldValue(field)">
                    <td :class="{ 'continuation-label': isContinuationField(field) }">
                      {{ isContinuationField(field) ? "" : formatFieldLabel(field) }}
                    </td>
                    <td :class="{ 'continuation-value': isContinuationField(field) }">
                      <span class="clickable" @click="onFieldClick(field, $event)">{{ getFieldValue(field) }}</span>
                    </td>
                  </tr>
                  <tr v-else-if="field === 'po_no'">
                    <td>PO</td>
                    <td>{{ pd.po_no }}</td>
                  </tr>
                  <tr v-else-if="field === 'ship_to' && pd.ship_to">
                    <td>Ship To</td>
                    <td>{{ pd.ship_to }}</td>
                  </tr>
                </template>
              </table>
            </div>
          </div>

          <!-- Lines table -->
          <table class="lines-table">
            <colgroup>
              <col v-for="(col, ci) in pd.column_labels" :key="'cg'+ci"
                :style="{ width: isNumericCol(col.key) ? '10%' : 'auto' }" />
            </colgroup>
            <thead>
              <tr>
                <th v-for="col in pd.column_labels" :key="'h_'+col.key"
                  :class="{ num: isNumericCol(col.key) }"
                >{{ col.label }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(line, li) in pd.lines" :key="'l'+li">
                <td v-for="col in pd.column_labels" :key="col.key"
                  :class="{ num: isNumericCol(col.key) }"
                >
                  <span
                    v-if="line[col.key] !== '' && line[col.key] !== null && line[col.key] !== undefined"
                    class="clickable"
                    @click="onFieldClick(`line[${li}].${col.key}`, $event)"
                  >{{ line[col.key] }}</span>
                  <template v-else>{{ line[col.key] }}</template>
                </td>
              </tr>
            </tbody>
            <tfoot>
              <tr class="total-row">
                <td v-for="col in pd.column_labels" :key="'t_'+col.key" :class="{ num: isNumericCol(col.key) }">
                  <template v-if="col.key === 'po_no' || col.key === 'description' || col.key === 'sap'">
                    <span v-if="col.key === 'po_no'">TOTAL</span>
                  </template>
                  <template v-else-if="col.key === 'quantity'">{{ pd.totals.total_quantity }}</template>
                  <template v-else-if="col.key === 'amount'">{{ pd.totals.total_amount }}</template>
                  <template v-else-if="col.key === 'net_weight'">{{ pd.totals.total_net_weight }}</template>
                  <template v-else-if="col.key === 'gross_weight'">{{ pd.totals.total_gross_weight }}</template>
                  <template v-else-if="col.key === 'cbm'">{{ pd.totals.total_cbm }}</template>
                  <template v-else-if="col.key === 'carton_count'">{{ pd.totals.total_carton_count }}</template>
                  <template v-else-if="col.key === 'unit_label'">{{ pd.totals.unit_label }}</template>
                </td>
              </tr>
            </tfoot>
          </table>

          <!-- Footer notes + Total box -->
          <div class="doc-footer-notes" v-if="pd.notes.length || pd.totals">
            <div class="note-lines">
              <p v-for="(note, ni) in pd.notes" :key="'n'+ni">{{ note }}</p>
            </div>
            <div class="total-box">
              <div v-for="item in footerTotalItems" :key="'footer-' + item.key">
                <span>{{ item.label }}</span><strong>{{ item.value }}</strong>
              </div>
            </div>
          </div>
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

/* Document card */
.document-card {
  background: white; border: 1px solid var(--line);
  border-radius: 8px; padding: 32px 40px 24px; overflow-x: auto;
}

.doc-topline {
  display: flex; align-items: flex-start;
  gap: 24px; padding-bottom: 12px; border-bottom: 2px solid #223047;
}
.top-left { flex: 1; min-width: 0; }
.top-center { flex: 0 0 auto; text-align: center; }
.top-right { flex: 1; min-width: 0; text-align: right; }
.top-right h1 { margin: 0 0 8px; font-size: 22px; line-height: 1.1; color: #223047; }
.top-field-line { margin: 0; color: var(--muted); font-family: var(--mono); font-size: 12px; line-height: 1.5; }
.top-field-line + .top-field-line { margin-top: 2px; }
.company-block { max-width: 560px; line-height: 1.55; font-size: 12px; }
.company-block strong { display: block; font-size: 13px; margin-bottom: 4px; }
.to-line { display: block; margin-top: 6px; font-weight: 700; color: #233047; }
.top-clickable { display: block; font-size: 12px; line-height: 1.55; }
.top-clickable + .top-clickable { margin-top: 2px; }
.terms-block { font-size: 12px; line-height: 1.55; }
.term-line { display: flex; gap: 8px; }
.term-line + .term-line { margin-top: 3px; }
.term-key { color: var(--muted); font-weight: 800; min-width: 100px; }
.term-val { color: var(--text); }

.doc-info { display: grid; grid-template-columns: 1.1fr 0.9fr; gap: 20px; padding: 14px 0 12px; font-size: 12px; line-height: 1.55; }
.info-left { min-width: 0; }
.info-right { min-width: 0; }
.info-title { color: var(--muted); font-size: 11px; font-weight: 900; margin-bottom: 4px; text-transform: uppercase; }
.info-ship p { margin: 0; white-space: pre-line; }
.kv-table { width: 100%; border-collapse: collapse; }
.kv-table td { padding: 2px 0 4px 10px; vertical-align: top; }
.kv-table td:first-child { color: var(--muted); font-weight: 800; white-space: nowrap; width: 94px; padding-left: 0; }
.kv-table td.continuation-label { color: transparent; user-select: none; }
.kv-table td.continuation-value { padding-top: 0; }

/* Clickable fields */
.clickable {
  cursor: pointer; border-bottom: 1px dashed var(--blue-weak);
  transition: background 0.15s;
}
.clickable:hover { background: var(--blue-weak); }
.clickable.field-active {
  background: var(--blue-weak); border-radius: 2px;
  outline: 2px solid var(--blue); outline-offset: 1px;
}

/* Lines table */
.lines-table {
  width: 100%; border-collapse: collapse; table-layout: auto;
  font-size: 12px; border: 1px solid var(--line);
}
.lines-table th, .lines-table td { border: 1px solid var(--line); padding: 7px 8px; vertical-align: top; overflow-wrap: anywhere; }
.lines-table th { color: #2b3a51; background: #eef3f9; font-size: 11px; font-weight: 900; text-align: left; }
.lines-table td.num, .lines-table th.num { text-align: right; font-family: var(--mono); white-space: nowrap; }
.lines-table .total-row td { font-weight: 900; background: #f8fafc; }

/* Footer */
.doc-footer-notes { display: grid; grid-template-columns: 1fr 260px; gap: 18px; padding-top: 12px; font-size: 12px; line-height: 1.55; }
.note-lines p { margin: 0; color: #233047; }
.note-lines p + p { margin-top: 4px; }
.total-box { border: 1px solid var(--line); border-radius: 8px; overflow: hidden; align-self: start; }
.total-box div { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 8px 10px; border-bottom: 1px solid var(--line); }
.total-box div:last-child { border-bottom: 0; }
.total-box span { color: var(--muted); font-weight: 800; }
.total-box strong { font-family: var(--mono); }

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
  .document-card { padding: 18px 20px; }
  .doc-footer-notes { grid-template-columns: 1fr; }
  .doc-info { grid-template-columns: 1fr; }
}
</style>
