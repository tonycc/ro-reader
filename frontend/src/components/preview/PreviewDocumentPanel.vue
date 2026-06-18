<script setup lang="ts">
import { computed } from "vue";
import LayoutTopZone from "./LayoutTopZone.vue";
import type { PreviewFooterItem, PreviewPayload } from "../../stores/api";

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
  return ["unit_price", "quantity", "amount", "net_weight", "gross_weight", "cbm", "carton_count"].includes(key);
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
  return CONTINUATION_FIELDS.has(field);
}

function formatFieldLabel(field: string): string {
  if (field === "shipping_mark") return "SHIPPING MARK";
  return field.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
</script>

<template>
  <div class="document-card">
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
              <td>Invoice #</td>
              <td>
                <span v-if="pd.invoice_no" class="clickable" @click="emitFieldClick('invoice_no', $event)">{{ pd.invoice_no }}</span>
                <span v-else class="empty-value"></span>
              </td>
            </tr>
            <tr v-else-if="field === 'pi_no' && pd.pi_no && pd.document_type === 'PI'">
              <td>PI #</td>
              <td>
                <span class="clickable" @click="emitFieldClick('pi_no', $event)">{{ pd.pi_no }}</span>
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
                <span class="clickable" @click="emitFieldClick(field, $event)">{{ getFieldValue(field) }}</span>
              </td>
            </tr>
          </template>
        </table>
      </div>
      <div class="info-right" v-if="layout.info.right.length">
        <table class="kv-table">
          <template v-for="field in layout.info.right" :key="field">
            <tr v-if="field === 'invoice_no'">
              <td>Invoice No.</td>
              <td>
                <span v-if="pd.invoice_no" class="clickable" @click="emitFieldClick('invoice_no', $event)">{{ pd.invoice_no }}</span>
                <span v-else class="empty-value"></span>
              </td>
            </tr>
            <tr v-else-if="field === 'pi_no' && pd.pi_no && pd.document_type === 'PI'">
              <td>PI #</td>
              <td>
                <span class="clickable" @click="emitFieldClick('pi_no', $event)">{{ pd.pi_no }}</span>
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
            <tr v-else-if="getFieldValue(field)">
              <td :class="{ 'continuation-label': isContinuationField(field) }">
                {{ isContinuationField(field) ? "" : formatFieldLabel(field) }}
              </td>
              <td :class="{ 'continuation-value': isContinuationField(field) }">
                <span class="clickable" @click="emitFieldClick(field, $event)">{{ getFieldValue(field) }}</span>
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
              @click="emitFieldClick(`line[${li}].${col.key}`, $event)"
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
.top-left { flex: 1; min-width: 0; }
.top-center { flex: 0 0 auto; text-align: center; }
.top-right { flex: 1; min-width: 0; text-align: right; }
.doc-info { display: grid; grid-template-columns: 1.1fr 0.9fr; gap: 20px; padding: 14px 0 12px; font-size: 12px; line-height: 1.55; }
.info-left { min-width: 0; }
.info-right { min-width: 0; }
.kv-table { width: 100%; border-collapse: collapse; }
.kv-table td { padding: 2px 0 4px 10px; vertical-align: top; }
.kv-table td:first-child { color: var(--muted); font-weight: 800; white-space: nowrap; width: 94px; padding-left: 0; }
.kv-table td.continuation-label { color: transparent; user-select: none; }
.kv-table td.continuation-value { padding-top: 0; }
.empty-value { display: inline-block; min-width: 80px; min-height: 1em; }
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
  padding: 7px 8px; text-align: left; font-weight: 900;
}
.lines-table td { border-bottom: 1px solid var(--line); padding: 7px 8px; vertical-align: top; }
.lines-table .num { text-align: right; font-variant-numeric: tabular-nums; }
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
@media (max-width: 760px) {
  .document-card { padding: 20px 18px; }
  .doc-topline { flex-direction: column; gap: 12px; }
  .top-right { text-align: left; }
  .doc-info { grid-template-columns: 1fr; }
  .doc-footer-notes { grid-template-columns: 1fr; }
}
</style>
