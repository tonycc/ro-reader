<script setup lang="ts">
import { computed, reactive } from "vue";
import type { SheetMappingGroup } from "./mockData";

/**
 * 全量字段映射总览页。
 * 按 Sheet 分组展示所有逻辑字段的当前生效映射，用户可直接下拉修改。
 * 与修复向导共享选择状态（通过 selections prop 传入/传出）。
 */
const props = defineProps<{
  groups: SheetMappingGroup[];
  /** 修复向导中已做的选择（field -> header），用于同步显示 */
  selections: Map<string, string>;
}>();

const emit = defineEmits<{
  select: [field: string, header: string];
}>();

/** 本地编辑状态：field -> 用户选中的表头（初始化为 effective） */
const localSelections = reactive(new Map<string, string>());

function currentValue(row: { field: string; effective: string }): string {
  // 优先本地编辑，其次向导选择，最后生效值
  return (
    localSelections.get(row.field) ??
    props.selections.get(row.field) ??
    row.effective
  );
}

function onChange(field: string, event: Event) {
  const value = (event.target as HTMLSelectElement).value;
  localSelections.set(field, value);
  emit("select", field, value);
}

function isModified(row: { field: string; effective: string }): boolean {
  return currentValue(row) !== row.effective;
}

function statusOf(row: { field: string; found: boolean; isOverride: boolean }): {
  label: string;
  className: string;
} {
  if (!row.found && !isModified(row as never)) {
    return { label: "未找到", className: "status-missing" };
  }
  if (isModified(row as never) || row.isOverride) {
    return { label: "自定义", className: "status-override" };
  }
  return { label: "正常", className: "status-ok" };
}

const modifiedCount = computed(() => {
  let count = 0;
  for (const group of props.groups) {
    for (const row of group.rows) {
      if (isModified(row)) count++;
    }
  }
  return count;
});

const missingCount = computed(() => {
  let count = 0;
  for (const group of props.groups) {
    for (const row of group.rows) {
      if (!row.found && !isModified(row)) count++;
    }
  }
  return count;
});
</script>

<template>
  <div class="overview">
    <header class="overview-header">
      <h1 class="overview-title">列对应关系总览</h1>
      <p class="overview-sub">
        查看和调整所有字段与 Excel 列的对应关系
        <span v-if="missingCount > 0" class="missing-badge">
          {{ missingCount }} 个列未找到
        </span>
        <span v-if="modifiedCount > 0" class="modified-badge">
          {{ modifiedCount }} 项已修改
        </span>
      </p>
    </header>

    <div v-for="group in groups" :key="group.sheetKey" class="sheet-group">
      <h2 class="sheet-name">{{ group.sheetName }}</h2>
      <table class="mapping-table">
        <thead>
          <tr>
            <th class="col-label">字段</th>
            <th class="col-builtin">标准列名</th>
            <th class="col-effective">对应到文件中的列</th>
            <th class="col-status">状态</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in group.rows"
            :key="row.field"
            :class="{
              'row-missing': !row.found && !isModified(row),
              'row-modified': isModified(row),
            }"
          >
            <td class="col-label">{{ row.fieldLabel }}</td>
            <td class="col-builtin">
              <code>{{ row.builtin }}</code>
            </td>
            <td class="col-effective">
              <select
                class="mapping-select"
                :class="{ modified: isModified(row) }"
                :value="currentValue(row)"
                @change="onChange(row.field, $event)"
              >
                <option
                  v-for="h in row.availableHeaders"
                  :key="h"
                  :value="h"
                >
                  {{ h }}
                </option>
                <!-- 当前值不在候选里时保留显示（例如未找到的列名） -->
                <option
                  v-if="!row.availableHeaders.includes(currentValue(row))"
                  :value="currentValue(row)"
                >
                  {{ currentValue(row) }}（文件中不存在）
                </option>
              </select>
            </td>
            <td class="col-status">
              <span class="status-pill" :class="statusOf(row).className">
                {{ statusOf(row).label }}
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.overview {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.overview-header {
  margin-bottom: var(--space-2);
}
.overview-title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}
.overview-sub {
  margin: 4px 0 0;
  color: var(--muted);
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.missing-badge {
  padding: 1px 8px;
  border-radius: 999px;
  background: var(--red-weak);
  color: var(--red);
  font-size: var(--text-xs);
}
.modified-badge {
  padding: 1px 8px;
  border-radius: 999px;
  background: var(--amber-weak);
  color: var(--amber);
  font-size: var(--text-xs);
}
.sheet-group {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  overflow: hidden;
}
.sheet-name {
  margin: 0;
  padding: var(--space-3) var(--space-4);
  font-size: 13px;
  font-weight: 600;
  background: var(--panel-soft);
  border-bottom: 1px solid var(--line);
  color: var(--muted);
}
.mapping-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.mapping-table th {
  text-align: left;
  padding: var(--space-2) var(--space-4);
  color: var(--muted);
  font-weight: 500;
  font-size: var(--text-sm);
  border-bottom: 1px solid var(--line);
}
.mapping-table td {
  padding: var(--space-2) var(--space-4);
  border-bottom: 1px solid var(--line);
  vertical-align: middle;
}
.mapping-table tr:last-child td {
  border-bottom: none;
}
.row-missing {
  background: var(--red-weak);
}
.row-modified {
  background: var(--amber-weak);
}
.col-label {
  width: 140px;
}
.col-builtin {
  width: 180px;
}
.col-builtin code {
  font-family: var(--mono);
  font-size: var(--text-sm);
  background: var(--panel-soft);
  padding: 1px 5px;
  border-radius: 3px;
}
.mapping-select {
  height: 28px;
  padding: 0 var(--space-2);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-sm);
  font-size: 13px;
  min-width: 200px;
  background: var(--panel);
}
.mapping-select.modified {
  border-color: var(--amber);
  font-weight: 500;
}
.status-pill {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: var(--text-xs);
}
.status-ok {
  background: var(--green-weak);
  color: var(--green);
}
.status-override {
  background: var(--amber-weak);
  color: var(--amber);
}
.status-missing {
  background: var(--red-weak);
  color: var(--red);
}
</style>
