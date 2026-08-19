<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useSchemaRepair } from "../../stores/schemaRepair";
import { useWorkbench } from "../../stores/workbench";
import type { SchemaMappingField, SchemaMappingGroup } from "../../stores/api";

/**
 * 全部字段对应关系总览。
 * 按 Sheet 组分页，一次只看一组；点「修改对应关系」并验证 PIN 后，
 * 当前对应列变为下拉框。保存仍提交所有分组里的改动。
 */

const repair = useSchemaRepair();
const wb = useWorkbench();
const activeKey = ref("");

onMounted(() => {
  void repair.refreshMappings();
});

function groupKey(group: SchemaMappingGroup): string {
  return `${group.logical_sheet}-${group.kind ?? "field"}`;
}

function tabLabel(group: SchemaMappingGroup): string {
  return group.kind === "price" ? "价格列" : group.sheet_label;
}

watch(
  () => repair.mappings,
  (groups) => {
    if (groups.length === 0) {
      activeKey.value = "";
      return;
    }
    if (!groups.some((group) => groupKey(group) === activeKey.value)) {
      const first = groups[0];
      if (first) activeKey.value = groupKey(first);
    }
  },
  { immediate: true },
);

const activeGroup = computed(
  () => repair.mappings.find((group) => groupKey(group) === activeKey.value) ?? null,
);

const tabItems = computed(() => {
  void repair.mappingSelections;
  return repair.mappings.map((group) => ({
    group,
    key: groupKey(group),
    label: tabLabel(group),
    mark: tabMark(group),
  }));
});

function optionLabel(group: SchemaMappingGroup, header: string): string {
  const letter = group.column_letters?.[header];
  return letter ? `${letter}:${header}` : header;
}

function currentValue(group: SchemaMappingGroup, field: SchemaMappingField): string {
  return repair.mappingSelections.get(repair.mappingKey(group, field.internal_key))
    ?? field.effective_header;
}

function isDirty(group: SchemaMappingGroup, field: SchemaMappingField): boolean {
  const selected = repair.mappingSelections.get(repair.mappingKey(group, field.internal_key));
  return selected !== undefined && selected !== field.effective_header;
}

function onSelect(group: SchemaMappingGroup, internalKey: string, event: Event) {
  const value = (event.target as HTMLSelectElement).value;
  if (value) repair.selectMapping(group, internalKey, value);
}

function headersOf(group: SchemaMappingGroup): string[] {
  return group.available_headers ?? [];
}

function groupDirtyCount(group: SchemaMappingGroup): number {
  return group.fields.filter((field) => isDirty(group, field)).length;
}

function groupOverrideCount(group: SchemaMappingGroup): number {
  return group.fields.filter((field) => field.is_overridden).length;
}

function tabMark(group: SchemaMappingGroup): { text: string; kind: "dirty" | "override" } | null {
  const dirty = groupDirtyCount(group);
  if (dirty > 0) return { text: String(dirty), kind: "dirty" };
  const overridden = groupOverrideCount(group);
  if (overridden > 0) return { text: String(overridden), kind: "override" };
  return null;
}

async function onSave() {
  const saved = await repair.saveMappings();
  if (!saved) return;
  try {
    await wb.reloadData();
  } catch {
    // workbench.error 已写入；对应关系本身已保存
  }
}
</script>

<template>
  <div class="overview-panel">
    <div class="overview-head">
      <div>
        <div class="overview-title">字段对应关系总览</div>
        <p class="overview-sub">旧列还在、只想改指到新加的列时，在这里调整。</p>
      </div>
      <div class="head-actions">
        <template v-if="repair.overviewEditing">
          <span v-if="repair.saveError" class="save-error">{{ repair.saveError }}</span>
          <span v-else class="head-hint">
            {{ repair.mappingDirtyCount > 0 ? `已改 ${repair.mappingDirtyCount} 项` : "尚未修改" }}
          </span>
          <button class="cancel-btn" type="button" @click="repair.cancelOverviewEdit()">取消</button>
          <button
            class="save-btn"
            type="button"
            :disabled="repair.mappingDirtyCount === 0 || repair.saving"
            @click="onSave()"
          >
            {{ repair.saving ? "保存中…" : "保存" }}
          </button>
        </template>
        <template v-else>
          <button
            class="edit-btn"
            type="button"
            @click="repair.enterOverviewEdit()"
          >修改对应关系</button>
          <button class="close-btn" type="button" @click="repair.closeOverview()">关闭</button>
        </template>
      </div>
    </div>

    <div v-if="repair.mappingsLoading" class="overview-loading">加载中…</div>
    <div v-else class="overview-body">
      <div class="group-tabs" role="tablist" aria-label="数据表分组">
        <button
          v-for="item in tabItems"
          :key="item.key"
          class="group-tab"
          :class="{ active: item.key === activeKey }"
          type="button"
          role="tab"
          :aria-selected="item.key === activeKey"
          @click="activeKey = item.key"
        >
          {{ item.label }}
          <span v-if="item.mark" class="tab-mark" :class="item.mark.kind">{{ item.mark.text }}</span>
        </button>
      </div>
      <section v-if="activeGroup" class="mapping-group">
        <div class="group-head">
          <span class="group-label">{{ activeGroup.sheet_label }}</span>
          <span class="group-sheet mono">{{ activeGroup.actual_sheet }}</span>
          <span v-if="activeGroup.header_row" class="group-row">表头第 {{ activeGroup.header_row }} 行</span>
        </div>
        <table class="mapping-table">
          <thead>
            <tr>
              <th>{{ activeGroup.kind === "price" ? "价格项" : "内部字段" }}</th>
              <th>当前对应列</th>
              <th>内置默认</th>
              <th>来源</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="f in activeGroup.fields"
              :key="f.internal_key"
              :class="{ overridden: f.is_overridden, dirty: isDirty(activeGroup, f) }"
            >
              <td class="mono">{{ f.internal_key }}</td>
              <td class="col-current">
                <select
                  v-if="repair.overviewEditing"
                  class="pick-select"
                  :value="currentValue(activeGroup, f)"
                  :aria-label="`为 ${f.internal_key} 选择对应列`"
                  @change="onSelect(activeGroup, f.internal_key, $event)"
                >
                  <option
                    v-for="h in headersOf(activeGroup)"
                    :key="h"
                    :value="h"
                  >{{ optionLabel(activeGroup, h) }}</option>
                  <option
                    v-if="!headersOf(activeGroup).includes(currentValue(activeGroup, f))"
                    :value="currentValue(activeGroup, f)"
                  >{{ currentValue(activeGroup, f) }}（文件中不存在）</option>
                </select>
                <span v-else>{{ optionLabel(activeGroup, f.effective_header) }}</span>
              </td>
              <td class="muted">{{ f.builtin_header ?? "—" }}</td>
              <td>
                <span v-if="isDirty(activeGroup, f)" class="badge-override">本次修改</span>
                <span v-else-if="f.is_overridden" class="badge-override">已修改</span>
                <span v-else class="badge-builtin">默认</span>
              </td>
            </tr>
          </tbody>
        </table>
      </section>
    </div>
  </div>
</template>

<style scoped>
.overview-panel {
  margin-bottom: 12px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--panel);
  overflow: hidden;
}
.overview-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--line);
  background: var(--panel-soft);
}
.overview-title { font-weight: 700; font-size: 14px; }
.overview-sub { margin: 4px 0 0; color: var(--muted); font-size: 12px; line-height: 1.45; }
.head-actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.head-hint { color: var(--muted); font-size: 12px; }
.cancel-btn,
.close-btn,
.edit-btn {
  height: 30px;
  padding: 0 12px;
  border: 1px solid var(--line-strong);
  border-radius: 8px;
  background: var(--panel);
  color: var(--muted);
  font-size: 12px;
  cursor: pointer;
}
.edit-btn {
  border-color: var(--blue);
  color: var(--blue);
  background: var(--blue-weak);
  font-weight: 700;
}
.overview-loading { padding: 24px; text-align: center; color: var(--subtle); }
.overview-body { padding: 0 0 12px; }
.group-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
  padding: 0 12px;
  border-bottom: 1px solid var(--line);
  background: var(--panel);
}
.group-tab {
  height: 36px;
  padding: 0 12px;
  border: 0;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.group-tab.active {
  color: var(--blue);
  border-bottom-color: var(--blue);
}
.tab-mark {
  min-width: 16px;
  height: 16px;
  padding: 0 5px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 700;
  line-height: 16px;
  text-align: center;
}
.tab-mark.dirty {
  background: var(--amber);
  color: white;
}
.tab-mark.override {
  background: var(--line);
  color: var(--muted);
}
.mapping-group { padding: 12px 16px 0; }
.group-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.group-label { font-weight: 700; font-size: 13px; }
.group-sheet { color: var(--muted); font-size: 12px; }
.group-row { color: var(--subtle); font-size: 12px; }
.mapping-table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  font-size: 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: hidden;
}
.mapping-table th, .mapping-table td {
  padding: 7px 12px;
  text-align: left;
  border-bottom: 1px solid var(--line);
  vertical-align: middle;
}
.mapping-table th {
  background: #f7f9fc;
  color: var(--muted);
  font-weight: 700;
}
.mapping-table tbody tr:last-child td { border-bottom: none; }
.col-current { min-width: 220px; width: 36%; }
.mono { font-family: var(--mono); }
.muted { color: var(--muted); }
tr.overridden td { background: #fffaf0; }
tr.dirty td { background: #fffbeb; }
.badge-override {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--amber);
  color: white;
  font-size: 11px;
  font-weight: 600;
}
.badge-builtin {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--line);
  color: var(--muted);
  font-size: 11px;
}
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
.save-error { color: var(--red); font-size: 12px; max-width: 220px; }
.save-btn {
  height: 30px;
  padding: 0 14px;
  border: none;
  border-radius: 8px;
  background: var(--blue);
  color: white;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}
.save-btn:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
