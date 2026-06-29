<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from "vue";
import { useWorkbench } from "../../stores/workbench";

const wb = useWorkbench();
const poSearch = ref("");
const invoiceSearch = ref("");
const dropdownOpen = ref(false);
const selectedPos = ref<Set<string>>(new Set());
const dropdownRef = ref<HTMLElement | null>(null);

function initSelectAll() {
  selectedPos.value = new Set(wb.poList.map((p) => p.po_no));
}

function onDocClick(e: MouseEvent) {
  if (dropdownRef.value && !dropdownRef.value.contains(e.target as Node)) {
    dropdownOpen.value = false;
  }
}
onMounted(() => document.addEventListener("click", onDocClick));
onUnmounted(() => document.removeEventListener("click", onDocClick));

function toggleDropdown() {
  dropdownOpen.value = !dropdownOpen.value;
}

function isAllSelected(): boolean {
  const visible = dropdownFiltered.value;
  return visible.length > 0 && visible.every((p) => selectedPos.value.has(p.po_no));
}

function toggleAll() {
  const visible = dropdownFiltered.value;
  if (isAllSelected()) {
    // 取消选中当前可见的
    const next = new Set(selectedPos.value);
    for (const p of visible) next.delete(p.po_no);
    selectedPos.value = next;
  } else {
    // 选中当前可见的
    const next = new Set(selectedPos.value);
    for (const p of visible) next.add(p.po_no);
    selectedPos.value = next;
  }
}

function togglePo(po_no: string) {
  const next = new Set(selectedPos.value);
  if (next.has(po_no)) {
    next.delete(po_no);
  } else {
    next.add(po_no);
  }
  selectedPos.value = next;
}

const selectionLabel = computed(() => {
  if (wb.poList.length === 0) return "无 PO";
  if (poSearch.value) {
    const n = dropdownFiltered.value.length;
    if (n === 0) return "无匹配";
    if (isAllSelected()) return `已选 ${n} 项（全部）`;
    return `已选 ${selectedPos.value.size} / ${n}`;
  }
  if (isAllSelected()) return `${wb.poList.length} POs（全部）`;
  return `已选 ${selectedPos.value.size} / ${wb.poList.length}`;
});

const dropdownFiltered = computed(() => {
  if (!poSearch.value) return wb.poList;
  const q = poSearch.value.toLowerCase();
  return wb.poList.filter((p) => p.po_no.toLowerCase().includes(q));
});

const filtered = computed(() => {
  let list = wb.poList.filter((p) => selectedPos.value.has(p.po_no));
  if (poSearch.value) {
    const q = poSearch.value.toLowerCase();
    list = list.filter((p) => p.po_no.toLowerCase().includes(q));
  }
  return list;
});

const filteredInvoices = computed(() => {
  const query = invoiceSearch.value.trim().toLowerCase();
  if (!query) return wb.invoiceList;
  return wb.invoiceList.filter((item) => item.display_invoice_no.toLowerCase().includes(query));
});

const statusLabel: Record<string, string> = { ready: "就绪", partial: "待补全", blocked: "阻断", done: "已导出" };
const statusBadgeClass: Record<string, string> = { ready: "ready", partial: "fix", blocked: "blocked", done: "exported" };

watch(() => wb.poList.length, (n) => {
  if (n > 0) initSelectAll();
});
</script>

<template>
  <aside class="queue">
    <div class="queue-head">
      <div class="scope-switch" role="group" aria-label="预览视角">
        <button
          type="button"
          data-testid="preview-scope-po"
          :class="{ active: wb.previewScope === 'po' }"
          @click="wb.selectPreviewScope('po')"
        >PO 视角</button>
        <button
          type="button"
          data-testid="preview-scope-invoice"
          :class="{ active: wb.previewScope === 'invoice' }"
          @click="wb.selectPreviewScope('invoice')"
        >Invoice 视角</button>
      </div>
      <div class="section-title">
        <h2>{{ wb.previewScope === 'po' ? 'PO 工作队列' : 'Invoice 列表' }}</h2>
        <span>{{ wb.previewScope === 'po' ? wb.poList.length : wb.invoiceList.length }} total</span>
      </div>

      <!-- 下拉多选（内嵌搜索） -->
      <div v-if="wb.previewScope === 'po'" ref="dropdownRef" class="po-select">
        <div class="select-trigger" @click="toggleDropdown">
          <span class="search-icon">⌕</span>
          <input
            v-model="poSearch"
            class="trigger-input"
            placeholder="搜索 PO 号…"
            @focus="dropdownOpen = true"
            @click.stop
          />
          <span class="arrow" :class="{ open: dropdownOpen }">▾</span>
        </div>
        <div v-if="dropdownOpen" class="select-dropdown">
          <label class="dropdown-item all" @click.stop="toggleAll">
            <input type="checkbox" :checked="isAllSelected()" />
            <span>全选（{{ selectionLabel }}）</span>
          </label>
          <label
            v-for="po in dropdownFiltered" :key="po.po_no"
            class="dropdown-item"
            @click.stop="togglePo(po.po_no)"
          >
            <input type="checkbox" :checked="selectedPos.has(po.po_no)" />
            <span class="item-po-no">{{ po.po_no }}</span>
            <span class="badge" :class="statusBadgeClass[po.status]">{{ statusLabel[po.status] }}</span>
          </label>
          <div v-if="!dropdownFiltered.length" class="dropdown-item empty-item">无匹配 PO</div>
        </div>
      </div>
      <div v-else class="invoice-search">
        <span class="search-icon">⌕</span>
        <input v-model="invoiceSearch" placeholder="搜索 Invoice 号…" />
      </div>

    </div>

    <div v-if="wb.previewScope === 'po'" class="po-list">
      <article
        v-for="po in filtered" :key="po.po_no"
        class="po-card"
        :class="{ active: wb.selectedPo === po.po_no }"
        @click="wb.selectPo(po.po_no)"
      >
        <div class="po-main">
          <span class="po-no">{{ po.po_no }}</span>
          <span class="badge" :class="statusBadgeClass[po.status]">
            <span class="b-dot" />{{ statusLabel[po.status] }}
          </span>
        </div>
        <div class="po-meta">PO record {{ po.line_count }} 行</div>
      </article>
      <div v-if="!filtered.length && !wb.loading" class="empty-msg">没有匹配的 PO</div>
      <div v-if="wb.loading" class="empty-msg">解析中…</div>
    </div>
    <div v-else class="po-list invoice-list">
      <article
        v-for="invoice in filteredInvoices"
        :key="invoice.invoice_group_key"
        class="po-card invoice-card"
        :class="{ active: wb.selectedInvoiceGroup === invoice.invoice_group_key }"
        @click="wb.selectInvoiceGroup(invoice.invoice_group_key)"
      >
        <div class="po-main">
          <span class="po-no">{{ invoice.display_invoice_no }}</span>
          <span class="badge" :class="statusBadgeClass[invoice.status]">
            <span class="b-dot" />{{ statusLabel[invoice.status] }}
          </span>
        </div>
        <div class="po-meta">{{ invoice.po_count }} 个 PO · {{ invoice.sellers.join(', ') }}</div>
      </article>
      <div v-if="!filteredInvoices.length && !wb.loading" class="empty-msg">没有匹配的 Invoice</div>
    </div>
  </aside>
</template>

<style scoped>
.queue {
  display: flex; flex-direction: column; min-height: 0;
  background: var(--panel); border-right: 1px solid var(--line);
  overflow: hidden;
}
.queue * { box-sizing: border-box; }
.queue-head { padding: 16px 14px 12px; border-bottom: 1px solid var(--line); }
.scope-switch { display: grid; grid-template-columns: 1fr 1fr; margin-bottom: 12px; }
.scope-switch button {
  height: 32px; border: 1px solid var(--line); background: white; color: var(--muted);
  font-weight: 700; cursor: pointer;
}
.scope-switch button:first-child { border-radius: 6px 0 0 6px; }
.scope-switch button:last-child { border-radius: 0 6px 6px 0; border-left: 0; }
.scope-switch button.active { color: var(--blue); border-color: var(--blue); background: var(--blue-weak); }
.section-title { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 12px; }
.section-title h2 { margin: 0; font-size: 16px; }
.section-title span { color: var(--subtle); font-size: 12px; }

.po-select { position: relative; margin-bottom: 12px; }
.invoice-search {
  display: flex; align-items: center; gap: 5px; height: 34px; padding: 0 9px;
  border: 1px solid var(--line); border-radius: 6px; background: var(--panel-soft);
}
.invoice-search input { min-width: 0; flex: 1; border: 0; outline: 0; background: transparent; font: inherit; }
.select-trigger {
  display: flex; align-items: center; gap: 4px;
  width: 100%; height: 34px;
  border: 1px solid var(--line); border-radius: 8px;
  padding: 0 8px;
  background: var(--panel-soft);
  cursor: pointer;
}
.po-select { position: relative; margin-bottom: 12px; }
.select-trigger:hover { border-color: var(--subtle); }
.trigger-input {
  flex: 1; height: 100%;
  border: 0; outline: 0; background: transparent;
  color: var(--text); font: inherit; font-size: 12px;
}
.trigger-input::placeholder { color: var(--subtle); }
.arrow { color: var(--subtle); flex-shrink: 0; transition: transform 0.15s; }
.arrow.open { transform: rotate(180deg); }
.search-icon { color: var(--subtle); font-size: 14px; flex-shrink: 0; }

.select-dropdown {
  position: absolute; top: 38px; left: 0; right: 0; z-index: 50;
  max-height: 260px; overflow: auto;
  border: 1px solid var(--line); border-radius: 8px;
  background: white;
  box-shadow: 0 8px 24px rgba(0,0,0,0.08);
}
.dropdown-item {
  display: flex; align-items: center; gap: 8px;
  padding: 7px 10px;
  cursor: pointer; font-size: 12px;
  overflow: hidden;
}
.dropdown-item:hover { background: var(--panel-soft); }
.dropdown-item.all { border-bottom: 1px solid var(--line); font-weight: 700; }
.dropdown-item input[type="checkbox"] { accent-color: var(--blue); flex-shrink: 0; }
.item-po-no { font-family: var(--mono); font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.empty-item { color: var(--subtle); cursor: default; }

.po-list { overflow: auto; padding: 8px; flex: 1; }
.po-card {
  border: 1px solid transparent; border-radius: 6px;
  padding: 10px; margin-bottom: 6px;
  background: white; cursor: pointer;
}
.po-card:hover { background: var(--panel-soft); }
.po-card.active {
  border-color: #bdd1ff;
  background: var(--blue-weak);
  box-shadow: inset 3px 0 0 var(--blue);
}
.po-main { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 6px; }
.po-no { font-family: var(--mono); font-weight: 800; }
.badge {
  display: inline-flex; align-items: center; gap: 5px;
  height: 22px; padding: 0 8px;
  border-radius: 999px; font-size: 12px; white-space: nowrap;
  flex-shrink: 0;
}
.b-dot { display: inline-block; width: 7px; height: 7px; border-radius: 999px; background: currentColor; }
.ready { color: var(--green); background: var(--green-weak); }
.fix { color: var(--amber); background: var(--amber-weak); }
.blocked { color: var(--red); background: var(--red-weak); }
.exported { color: var(--muted); background: #eef1f5; }
.po-meta { color: var(--muted); font-size: 12px; }
.empty-msg { padding: var(--space-4); text-align: center; color: var(--subtle); }
</style>
