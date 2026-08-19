<script setup lang="ts">
import { computed } from "vue";
import { useSchemaRepair } from "../../stores/schemaRepair";
import { useWorkbench } from "../../stores/workbench";
import type { SchemaFieldIssue } from "../../stores/api";

/**
 * Schema 修复向导（内联在数据检查 tab）。
 * 流程：PIN 校验 → 在表格中为每行选择对应列 → 保存并重建快照。
 */

const repair = useSchemaRepair();
const wb = useWorkbench();

const issueCount = computed(() => repair.issueCount);

/** 把 "EMAX PTE/combo" 这类价格键转成用户可读标签。 */
const CATEGORY_LABELS: Record<string, string> = {
  combo: "Combo",
  rod: "Rod",
  reel: "Reel",
};
function priceLabel(priceKey: string): string {
  const [seller, category] = priceKey.split("/");
  const cat = CATEGORY_LABELS[category] ?? category;
  return seller ? `${seller} · ${cat} 单价` : priceKey;
}

function dataFieldName(issue: SchemaFieldIssue, isPrice: boolean): string {
  return isPrice ? priceLabel(issue.internal_key) : issue.expected_header;
}

function sheetName(issue: SchemaFieldIssue): string {
  return issue.actual_sheet || issue.sheet_label;
}

function selectedHeader(issue: SchemaFieldIssue, isPrice: boolean): string {
  const map = isPrice ? repair.priceSelections : repair.selections;
  return map.get(issue.internal_key) ?? "";
}

function optionLabel(issue: SchemaFieldIssue, header: string): string {
  const letter = issue.column_letters?.[header];
  return letter ? `${letter}:${header}` : header;
}

function isResolved(issue: SchemaFieldIssue, isPrice: boolean): boolean {
  return selectedHeader(issue, isPrice) !== "";
}

async function onSave() {
  const cleared = await repair.save();
  if (!cleared && repair.saveError) return;
  try {
    await wb.reloadData();
  } catch {
    // workbench.error 已写入；override 本身已保存
  }
}

function onSelect(internalKey: string, event: Event) {
  const value = (event.target as HTMLSelectElement).value;
  if (value) repair.selectHeader(internalKey, value);
}

function onSelectPrice(priceKey: string, event: Event) {
  const value = (event.target as HTMLSelectElement).value;
  if (value) repair.selectPriceHeader(priceKey, value);
}
</script>

<template>
  <div v-if="repair.wizardOpen" class="repair-panel">
    <div class="repair-head">
      <div>
        <div class="repair-title">修复列对应关系</div>
        <div class="repair-sub">
          base 文件有 {{ issueCount }} 处列名对不上。请按表格和原列名核对，再在「对应到」中选择文件里的实际列。
        </div>
      </div>
      <button class="close-btn" type="button" @click="repair.closeWizard()">关闭</button>
    </div>

    <div v-if="repair.sheetIssues.length" class="sheet-issues">
      <div v-for="item in repair.sheetIssues" :key="item.logical_sheet" class="sheet-issue">
        整张「{{ item.sheet_label }}」（{{ item.actual_sheet }}）Sheet 不存在，无法在界面内修复，请检查 base 文件。
      </div>
    </div>

    <div class="table-wrap">
      <table class="repair-table">
        <thead>
          <tr>
            <th class="col-field">数据字段</th>
            <th class="col-sheet">表格</th>
            <th class="col-old">原列名</th>
            <th class="col-new">对应到</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="issue in repair.fieldIssues"
            :key="issue.internal_key"
            :class="{ resolved: isResolved(issue, false) }"
          >
            <td class="col-field">
              <span class="status" :class="{ ok: isResolved(issue, false) }">{{ isResolved(issue, false) ? "✓" : "✗" }}</span>
              {{ dataFieldName(issue, false) }}
            </td>
            <td class="col-sheet" :title="issue.sheet_label">{{ sheetName(issue) }}</td>
            <td class="col-old">{{ issue.expected_header }}</td>
            <td class="col-new">
              <select
                class="pick-select"
                :value="selectedHeader(issue, false)"
                :aria-label="`为 ${dataFieldName(issue, false)} 选择对应列`"
                @change="onSelect(issue.internal_key, $event)"
              >
                <option value="" disabled>请选择</option>
                <option v-for="h in issue.available_headers" :key="h" :value="h">{{ optionLabel(issue, h) }}</option>
              </select>
            </td>
          </tr>

          <tr v-if="repair.priceIssues.length" class="group-row">
            <td colspan="4">价格列（选错会导致单价取不到或取错）</td>
          </tr>
          <tr
            v-for="issue in repair.priceIssues"
            :key="`price-${issue.internal_key}`"
            class="price-row"
            :class="{ resolved: isResolved(issue, true) }"
          >
            <td class="col-field">
              <span class="status" :class="{ ok: isResolved(issue, true) }">{{ isResolved(issue, true) ? "✓" : "✗" }}</span>
              {{ dataFieldName(issue, true) }}
            </td>
            <td class="col-sheet" :title="issue.sheet_label">{{ sheetName(issue) }}</td>
            <td class="col-old">{{ issue.expected_header }}</td>
            <td class="col-new">
              <select
                class="pick-select"
                :value="selectedHeader(issue, true)"
                :aria-label="`为 ${dataFieldName(issue, true)} 选择对应列`"
                @change="onSelectPrice(issue.internal_key, $event)"
              >
                <option value="" disabled>请选择</option>
                <option v-for="h in issue.available_headers" :key="h" :value="h">{{ optionLabel(issue, h) }}</option>
              </select>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="repair-foot">
      <span v-if="repair.saveError" class="save-error">{{ repair.saveError }}</span>
      <button
        class="save-btn"
        type="button"
        :disabled="!repair.allResolved || repair.saving"
        @click="onSave"
      >
        {{ repair.saving ? "保存中…" : "保存并重新校验" }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.repair-panel {
  margin-bottom: 12px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--panel);
  overflow: hidden;
}
.repair-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--line);
  background: var(--panel-soft);
}
.repair-title { font-weight: 700; font-size: 14px; }
.repair-sub { margin-top: 4px; color: var(--muted); font-size: 12px; line-height: 1.5; }
.close-btn {
  flex-shrink: 0;
  height: 30px;
  padding: 0 12px;
  border: 1px solid var(--line-strong);
  border-radius: 8px;
  background: var(--panel);
  color: var(--muted);
  font-size: 12px;
  cursor: pointer;
}
.sheet-issues { padding: 10px 16px 0; }
.sheet-issue {
  padding: 9px 12px;
  margin-bottom: 8px;
  border: 1px solid #fecaca;
  border-radius: 8px;
  background: var(--red-weak);
  color: var(--red);
  font-size: 12px;
}
.table-wrap { padding: 12px 16px; overflow: auto; }
.repair-table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  font-size: 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: hidden;
}
.repair-table th,
.repair-table td {
  padding: 8px 12px;
  text-align: left;
  border-bottom: 1px solid var(--line);
  vertical-align: middle;
}
.repair-table th {
  background: #f7f9fc;
  color: var(--muted);
  font-weight: 700;
  white-space: nowrap;
}
.repair-table tbody tr:last-child td { border-bottom: none; }
.repair-table tbody tr.resolved td { background: #f4faf6; }
.col-field { font-weight: 600; white-space: nowrap; }
.col-sheet { color: var(--muted); white-space: nowrap; }
.col-old {
  font-family: var(--mono);
  color: var(--text);
  white-space: nowrap;
}
.col-new { min-width: 220px; width: 36%; }
.status {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  margin-right: 6px;
  border-radius: 50%;
  background: var(--red-weak);
  color: var(--red);
  font-size: 10px;
  font-weight: 700;
  vertical-align: middle;
}
.status.ok { background: var(--green-weak); color: var(--green); }
.group-row td {
  background: #fffbeb;
  color: #b45309;
  font-weight: 600;
  font-size: 12px;
}
.price-row td { background: #fffdf7; }
.price-row.resolved td { background: #f4faf6; }
.pick-select {
  width: 100%;
  height: 32px;
  padding: 0 8px;
  border: 1px solid var(--line-strong);
  border-radius: 6px;
  font-size: 12px;
  background: var(--panel);
  color: var(--text);
}
.pick-select:focus {
  outline: none;
  border-color: var(--blue);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15);
}
.repair-foot {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  padding: 12px 16px;
  border-top: 1px solid var(--line);
}
.save-error { color: var(--red); font-size: 12px; margin-right: auto; }
.save-btn {
  height: 34px;
  padding: 0 18px;
  border: none;
  border-radius: 8px;
  background: var(--blue);
  color: white;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
.save-btn:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
