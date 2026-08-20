<script setup lang="ts">
import { computed } from "vue";
import LayoutTopZone from "./LayoutTopZone.vue";
import type { PreviewFooterItem, PreviewHeaderCell, PreviewPayload } from "../../stores/api";

const props = defineProps<{ pd: PreviewPayload }>();
const emit = defineEmits<{
  fieldClick: [fieldRef: string, event: MouseEvent]
}>();

const DEFAULT_LAYOUT = {
  top: { left: [] as string[], center: [] as string[], right: [] as string[] },
  info: { left: [] as string[], right: [] as string[] },
};

const layout = computed(() => props.pd.layout || DEFAULT_LAYOUT);

const footerTotalItems = computed<PreviewFooterItem[]>(() => {
  const raw = props.pd.totals?.["_footer_items"];
  if (!Array.isArray(raw)) return [];
  return raw.filter((item): item is PreviewFooterItem => {
    if (!item || typeof item !== "object") return false;
    return typeof item.key === "string" && typeof item.label === "string" && typeof item.value === "string";
  });
});

function emitFieldClick(fieldRef: string, event: MouseEvent) {
  emit("fieldClick", fieldRef, event);
}

function formatTermKey(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

function isNumericCol(key: string) {
  return [
    "unit_price",
    "quantity",
    "amount",
    "net_weight",
    "gross_weight",
    "cbm",
    "carton_count",
    "carton_from",
    "carton_to",
  ].includes(key);
}

// 合并表头的第一行不包含每个叶子列，table-layout: fixed 不能再从首行自动推断列宽。
// 每个叶子列都必须有比例；漏列会被挤成 0%，和相邻列叠在一起。
const MERGED_HEADER_COLUMN_WIDTHS: Record<string, string> = {
  carton_from: "5%",
  carton_to: "5%",
  po_no: "10%",
  sap: "8%",
  description: "14%",
  quantity: "8%",
  carton_count: "7%",
  net_weight: "8%",
  gross_weight: "8%",
  length: "6%",
  width: "5%",
  height: "5%",
  cbm: "6%",
};

function columnWidth(key: string): string {
  // G 列 PCS 在模板里没有表头，只是数量旁的单位。fixed 布局下
  // auto 会和 PO/品名平分剩余宽度，把单价、数量表头和数字错开。
  if (key === "unit_label") return "4%";
  if (columnHeaderRows.value.length > 1) {
    return MERGED_HEADER_COLUMN_WIDTHS[key] || "6%";
  }
  return isNumericCol(key) ? "10%" : "auto";
}

function isNumericHeader(cell: PreviewHeaderCell): boolean {
  return columnHeaderRows.value.length === 1 && !!cell.key && isNumericCol(cell.key);
}

function getFieldValue(field: string): string {
  const extra = props.pd.resolved_values;
  if (extra && extra[field] !== undefined) return String(extra[field]);
  const top = (props.pd as unknown as Record<string, unknown>)[field];
  if (top !== null && top !== undefined && top !== "") return String(top);
  const terms = props.pd.terms;
  if (terms && terms[field] !== undefined) return String(terms[field]);
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
  return CONTINUATION_FIELDS.has(field) || getHeaderLabel(field) === "";
}

function formatFieldLabel(field: string): string {
  if (field === "shipping_mark") return "SHIPPING MARK";
  return field.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function getHeaderLabel(field: string): string {
  const templateLabel = props.pd.header_labels?.[field];
  if (templateLabel !== undefined) return templateLabel;
  if (field === "invoice_no") return "Invoice No.";
  if (field === "pi_no") return "PI #";
  if (field === "po_no") return "PO";
  if (field === "ship_to") return "Ship To";
  if (field === "seller") return "Seller";
  if (field === "buyer") return "Buyer";
  return formatFieldLabel(field);
}

const costBreakdownLabels = computed(() => props.pd.cost_breakdown_column_labels || []);
const costBreakdownRows = computed(() => props.pd.cost_breakdown || []);

const columnHeaderRows = computed<PreviewHeaderCell[][]>(() => {
  const configured = props.pd.column_header_rows;
  if (Array.isArray(configured) && configured.length > 0) return configured;
  return [props.pd.column_labels.map((column) => ({ key: column.key, label: column.label }))];
});
</script>

<template>
  <div class="document-card" :class="{ 'template-heading': pd.seller_info.length > 0 }">
    <div class="doc-topline">
      <div class="top-left" v-if="layout.top.left.length">
        <LayoutTopZone :fields="layout.top.left" :pd="pd" @field-click="emitFieldClick" />
      </div>
      <div class="top-center" v-if="layout.top.center.length">
        <LayoutTopZone :fields="layout.top.center" :pd="pd" @field-click="emitFieldClick" />
      </div>
      <div class="top-right" v-if="layout.top.right.length">
        <LayoutTopZone :fields="layout.top.right" :pd="pd" @field-click="emitFieldClick" />
      </div>
    </div>

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
            <tr v-else-if="field === 'invoice_no'">
              <td>{{ getHeaderLabel(field) }}</td>
              <td>
                <span v-if="pd.invoice_no" class="clickable" @click="emitFieldClick('invoice_no', $event)">{{ pd.invoice_no }}</span>
                <span v-else class="empty-value"></span>
              </td>
            </tr>
            <tr v-else-if="field === 'pi_no' && pd.document_type === 'PI'">
              <td>{{ getHeaderLabel(field) }}</td>
              <td>
                <span v-if="getFieldValue(field)" class="clickable" @click="emitFieldClick('pi_no', $event)">{{ getFieldValue(field) }}</span>
                <span v-else class="empty-value"></span>
              </td>
            </tr>
            <template v-else-if="field === 'terms'">
              <tr v-for="(val, key) in pd.terms" :key="'t_'+key">
                <td>{{ getHeaderLabel(String(key)) || formatTermKey(key) }}</td>
                <td>{{ val }}</td>
              </tr>
            </template>
            <tr v-else>
              <td :class="{ 'continuation-label': isContinuationField(field) }">
                {{ isContinuationField(field) ? "" : getHeaderLabel(field) }}
              </td>
              <td :class="{ 'continuation-value': isContinuationField(field) }">
                <span v-if="getFieldValue(field)" class="clickable" @click="emitFieldClick(field, $event)">{{ getFieldValue(field) }}</span>
                <span v-else class="empty-value"></span>
              </td>
            </tr>
          </template>
        </table>
      </div>
      <div class="info-right" v-if="layout.info.right.length">
        <table class="kv-table">
          <template v-for="field in layout.info.right" :key="field">
            <tr v-if="field === 'invoice_no'">
              <td>{{ getHeaderLabel(field) }}</td>
              <td>
                <span v-if="pd.invoice_no" class="clickable" @click="emitFieldClick('invoice_no', $event)">{{ pd.invoice_no }}</span>
                <span v-else class="empty-value"></span>
              </td>
            </tr>
            <tr v-else-if="field === 'pi_no' && pd.document_type === 'PI'">
              <td>{{ getHeaderLabel(field) }}</td>
              <td>
                <span v-if="getFieldValue(field)" class="clickable" @click="emitFieldClick('pi_no', $event)">{{ getFieldValue(field) }}</span>
                <span v-else class="empty-value"></span>
              </td>
            </tr>
            <template v-else-if="field === 'terms'">
              <tr v-for="(val, key) in pd.terms" :key="'t_'+key">
                <td>{{ getHeaderLabel(String(key)) || formatTermKey(key) }}</td>
                <td>{{ val }}</td>
              </tr>
            </template>
            <tr v-else>
              <td :class="{ 'continuation-label': isContinuationField(field) }">
                {{ isContinuationField(field) ? "" : getHeaderLabel(field) }}
              </td>
              <td :class="{ 'continuation-value': isContinuationField(field) }">
                <span v-if="getFieldValue(field)" class="clickable" @click="emitFieldClick(field, $event)">{{ getFieldValue(field) }}</span>
                <span v-else class="empty-value"></span>
              </td>
            </tr>
          </template>
        </table>
      </div>
    </div>

    <table class="lines-table" :class="{ 'merged-header-table': columnHeaderRows.length > 1 }">
      <colgroup>
        <col v-for="(col, ci) in pd.column_labels" :key="'cg'+ci"
          :style="{ width: columnWidth(col.key) }" />
      </colgroup>
      <thead>
        <tr v-for="(headerRow, ri) in columnHeaderRows" :key="'header-row-' + ri">
          <th
            v-for="(cell, ci) in headerRow"
            :key="'h_' + ri + '_' + ci + '_' + (cell.key || cell.label)"
            :colspan="cell.colspan || 1"
            :rowspan="cell.rowspan || 1"
            :class="{ num: isNumericHeader(cell) }"
          >{{ cell.label }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(line, li) in pd.lines" :key="'l'+li">
          <td v-for="col in pd.column_labels" :key="col.key"
            :class="{ num: isNumericCol(col.key), 'unit-col': col.key === 'unit_label' }"
          >
            <span
              v-if="line[col.key] !== '' && line[col.key] !== null && line[col.key] !== undefined"
              class="clickable"
              @click="emitFieldClick(`line[${li}].${col.key}`, $event)"
            >{{ line[col.key] }}</span>
            <template v-else>{{ line[col.key] }}</template>
          </td>
        </tr>
      </tbody>
      <tfoot>
        <tr class="total-row">
          <td v-for="col in pd.column_labels" :key="'t_'+col.key" :class="{ num: isNumericCol(col.key), 'unit-col': col.key === 'unit_label' }">
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

    <section v-if="costBreakdownRows.length" class="cost-breakdown">
      <h4>Cost breakdown and actual manufacturer breakdown</h4>
      <table class="lines-table breakdown-table">
        <thead>
          <tr>
            <th v-for="col in costBreakdownLabels" :key="'cb-h_' + col.key">{{ col.label }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(line, li) in costBreakdownRows" :key="'cb-l' + li">
            <td v-for="col in costBreakdownLabels" :key="'cb-' + col.key">
              <span
                v-if="line[col.key] !== '' && line[col.key] !== null && line[col.key] !== undefined"
                class="clickable"
                @click="emitFieldClick(`cost_breakdown[${li}].${col.key}`, $event)"
              >{{ line[col.key] }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

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
</template>

<style scoped>
.document-card {
  background: white; border: 1px solid var(--line);
  border-radius: 8px; padding: 32px 40px 24px; overflow-x: auto;
}
.doc-topline {
  display: flex; align-items: flex-start;
  gap: 24px; padding-bottom: 12px; border-bottom: 2px solid #223047;
}
.template-heading .doc-topline { border-bottom: 0; padding-bottom: 24px; }
.top-left { flex: 1; min-width: 0; }
.top-center { flex: 1 1 auto; min-width: 0; text-align: center; }
.top-right { flex: 1; min-width: 0; text-align: right; }
.doc-info {
  display: grid; grid-template-columns: minmax(0, 0.95fr) minmax(0, 1.05fr);
  gap: 40px; padding: 14px 0 12px; font-size: 12px; line-height: 1.55;
}
.info-left { min-width: 0; }
.info-right { min-width: 0; }
.kv-table { width: 100%; border-collapse: collapse; table-layout: fixed; }
.kv-table td { padding: 2px 0 4px 10px; vertical-align: top; }
.kv-table td:first-child { color: var(--muted); font-weight: 800; white-space: nowrap; padding-left: 0; }
.info-left .kv-table td:first-child { width: 126px; }
.info-right .kv-table td:first-child {
  width: 226px; padding-right: 12px; white-space: normal;
}
.kv-table td:last-child { overflow-wrap: anywhere; }
.kv-table td.continuation-label { color: transparent; user-select: none; }
.kv-table td.continuation-value { padding-top: 0; }
.empty-value {
  display: inline-block; min-width: 80px; min-height: 1em;
  border-bottom: 1px solid var(--line-strong, #9aa5b5);
}
.clickable {
  cursor: pointer; border-bottom: 1px dashed var(--blue-weak);
  transition: background 0.15s;
}
.clickable:hover { background: var(--blue-weak); }
.clickable.field-active {
  background: var(--blue-weak);
  outline: 1px solid #9bbcff;
  border-radius: 3px;
}
.lines-table { width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 12px; }
.lines-table th {
  border-top: 1px solid #223047; border-bottom: 1px solid #223047;
  background: #f7f9fc; color: var(--muted);
  padding: 7px 8px; text-align: left; font-weight: 900; white-space: pre-line;
}
.merged-header-table thead th { text-align: center; vertical-align: middle; }
.merged-header-table th,
.merged-header-table td {
  border-right: 1px solid #d7dfeb;
}
.merged-header-table tr > :first-child {
  border-left: 1px solid #d7dfeb;
}
.lines-table td { border-bottom: 1px solid var(--line); padding: 7px 8px; vertical-align: top; }
.lines-table .num { text-align: right; font-variant-numeric: tabular-nums; }
.lines-table .unit-col { padding-left: 2px; white-space: nowrap; }
.total-row td { font-weight: 900; border-top: 1px solid #223047; background: #fbfcfe; }
.doc-footer-notes {
  display: grid; grid-template-columns: 1fr 260px; gap: 20px;
  padding-top: 12px; font-size: 12px;
}
.note-lines p { margin: 0 0 6px; color: var(--text); }
.total-box {
  border-top: 1px solid #223047; padding-top: 8px;
  font-variant-numeric: tabular-nums;
}
.total-box div { display: flex; justify-content: space-between; gap: 16px; margin-bottom: 6px; }
.total-box span { color: var(--muted); font-weight: 800; }
.total-box strong { color: var(--text); }
.cost-breakdown { margin-top: 24px; }
.cost-breakdown h4 { margin: 0 0 8px; font-size: 14px; color: var(--text); }
.breakdown-table { font-size: 11px; }
@media (max-width: 760px) {
  .document-card { padding: 20px 18px; }
  .doc-topline { flex-direction: column; gap: 12px; }
  .top-right { text-align: left; }
  .doc-info { grid-template-columns: 1fr; }
  .doc-footer-notes { grid-template-columns: 1fr; }
}
</style>
