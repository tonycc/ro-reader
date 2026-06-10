<script setup lang="ts">
import type { PreviewPayload } from "../../stores/api";

defineProps<{
  fields: string[];
  pd: PreviewPayload;
}>();

const emit = defineEmits<{
  fieldClick: [field: string, event: MouseEvent];
}>();

function onFieldClick(field: string, event: MouseEvent) {
  emit("fieldClick", field, event);
}

function formatTermKey(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
</script>

<template>
  <template v-for="field in fields" :key="field">
    <template v-if="field === 'seller_info'">
      <div class="company-block" v-if="pd.seller_info.length">
        <strong>{{ pd.seller_info[0] }}</strong>
        <template v-for="(line, i) in pd.seller_info.slice(1)" :key="'ci' + i">
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
      <div v-for="(val, key) in pd.terms" :key="'t_' + key" class="term-line">
        <span class="term-key">{{ formatTermKey(key) }}</span>
        <span class="term-val">{{ val }}</span>
      </div>
    </div>
  </template>
</template>
