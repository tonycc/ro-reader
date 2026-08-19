import { defineStore } from "pinia";
import { computed, ref } from "vue";
import {
  api,
  ApiError,
  type SchemaFieldIssue,
  type SchemaIssuesResponse,
  type SchemaMappingGroup,
  type SchemaSheetIssue,
} from "./api";
import { useWorkspace } from "./workspace";

/**
 * Schema 结构映射修复向导的状态。
 *
 * 触发前提：已有 active session（工作区激活成功）。向导内联在数据检查 tab，
 * 负责探测表头漂移、收集用户选择、保存 override 并让后端重建快照。
 */
export const useSchemaRepair = defineStore("schemaRepair", () => {
  const loading = ref(false);
  const error = ref("");
  const hasIssues = ref(false);
  const sheetIssues = ref<SchemaSheetIssue[]>([]);
  const fieldIssues = ref<SchemaFieldIssue[]>([]);
  const priceIssues = ref<SchemaFieldIssue[]>([]);

  // 用户为每个缺失字段选定的新表头：internal_key -> 选中的列名
  const selections = ref(new Map<string, string>());
  // 价格列选择独立存放：价格键 -> 选中的列名
  const priceSelections = ref(new Map<string, string>());

  const wizardOpen = ref(false);
  const saving = ref(false);
  const saveError = ref("");

  // PIN 软管控：系统内置校验码，进入向导前必须验证。
  const pinVerified = ref(false);
  const pinDialogOpen = ref(false);
  const pinError = ref("");

  const mappings = ref<SchemaMappingGroup[]>([]);
  const mappingsLoading = ref(false);
  const overviewOpen = ref(false);
  const overviewEditing = ref(false);
  const mappingSelections = ref(new Map<string, string>());
  const pinIntent = ref<"wizard" | "overview" | null>(null);

  // 激活失败（无 session）时按 workspace 直达；有 session 时该值仅作冗余。
  // 可由工作区设置面板显式指定修复目标；默认回落到当前工作区。
  const targetWorkspaceId = ref<string | null>(null);
  const workspaceId = computed(
    () => targetWorkspaceId.value ?? useWorkspace().currentWorkspaceId ?? undefined,
  );

  function setTargetWorkspace(id: string | null) {
    targetWorkspaceId.value = id;
  }

  /**
   * 激活失败处的直达入口：对指定工作区刷新问题并直接进入修复向导。
   * 失败时把错误放进 store.error，由承载面板的页面展示。
   */
  async function openRepairFor(id: string) {
    setTargetWorkspace(id);
    await refreshIssues();
    if (!error.value) enterWizard();
  }

  const allResolved = computed(() => {
    const fieldsDone = fieldIssues.value.every((issue) =>
      selections.value.has(issue.internal_key),
    );
    const pricesDone = priceIssues.value.every((issue) =>
      priceSelections.value.has(issue.internal_key),
    );
    const total = fieldIssues.value.length + priceIssues.value.length;
    return total > 0 && fieldsDone && pricesDone;
  });

  const issueCount = computed(
    () => sheetIssues.value.length + fieldIssues.value.length + priceIssues.value.length,
  );

  function applyInspection(data: SchemaIssuesResponse) {
    hasIssues.value = data.has_issues;
    sheetIssues.value = data.sheet_issues;
    fieldIssues.value = data.field_issues;
    priceIssues.value = data.price_issues ?? [];
  }

  async function refreshIssues() {
    loading.value = true;
    error.value = "";
    try {
      const data = await api.getSchemaIssues(workspaceId.value);
      applyInspection(data);
    } catch (e) {
      error.value = e instanceof ApiError ? e.message : String(e);
      hasIssues.value = false;
    } finally {
      loading.value = false;
    }
  }

  async function refreshMappings() {
    mappingsLoading.value = true;
    try {
      mappings.value = (await api.getSchemaMappings(workspaceId.value)).groups;
    } catch {
      mappings.value = [];
    } finally {
      mappingsLoading.value = false;
    }
  }

  function selectHeader(internalKey: string, header: string) {
    const next = new Map(selections.value);
    next.set(internalKey, header);
    selections.value = next;
  }

  function selectPriceHeader(priceKey: string, header: string) {
    const next = new Map(priceSelections.value);
    next.set(priceKey, header);
    priceSelections.value = next;
  }

  /** 进入修复向导：未验证系统校验码时先弹校验框。 */
  function enterWizard() {
    if (!pinVerified.value) {
      pinIntent.value = "wizard";
      pinDialogOpen.value = true;
      return;
    }
    wizardOpen.value = true;
  }

  /** 总览进入编辑：同样要先过 PIN。 */
  function enterOverviewEdit() {
    if (!pinVerified.value) {
      pinIntent.value = "overview";
      pinDialogOpen.value = true;
      return;
    }
    beginOverviewEdit();
  }

  function beginOverviewEdit() {
    const next = new Map<string, string>();
    for (const group of mappings.value) {
      for (const field of group.fields) {
        next.set(mappingKey(group, field.internal_key), field.effective_header);
      }
    }
    mappingSelections.value = next;
    overviewEditing.value = true;
  }

  function mappingKey(group: SchemaMappingGroup, internalKey: string): string {
    return `${group.kind ?? "field"}:${group.logical_sheet}:${internalKey}`;
  }

  function selectMapping(group: SchemaMappingGroup, internalKey: string, header: string) {
    const next = new Map(mappingSelections.value);
    next.set(mappingKey(group, internalKey), header);
    mappingSelections.value = next;
  }

  const mappingDirtyCount = computed(() => {
    let count = 0;
    for (const group of mappings.value) {
      for (const field of group.fields) {
        const selected = mappingSelections.value.get(mappingKey(group, field.internal_key));
        if (selected !== undefined && selected !== field.effective_header) count += 1;
      }
    }
    return count;
  });

  async function confirmPin(pin: string) {
    pinError.value = "";
    try {
      const result = await api.verifySchemaPin(pin);
      pinVerified.value = result.verified;
      pinDialogOpen.value = false;
      const intent = pinIntent.value;
      pinIntent.value = null;
      if (intent === "overview") beginOverviewEdit();
      else wizardOpen.value = true;
    } catch (e) {
      pinError.value = e instanceof ApiError ? e.message : "校验码不正确";
      throw e;
    }
  }

  function cancelPin() {
    pinDialogOpen.value = false;
    pinError.value = "";
    pinIntent.value = null;
  }

  function cancelOverviewEdit() {
    overviewEditing.value = false;
    mappingSelections.value = new Map();
    saveError.value = "";
  }

  function closeOverview() {
    overviewOpen.value = false;
    cancelOverviewEdit();
  }

  function toggleOverview() {
    if (overviewOpen.value) closeOverview();
    else overviewOpen.value = true;
  }

  async function saveMappings(): Promise<boolean> {
    if (!overviewEditing.value || mappingDirtyCount.value === 0) return false;
    saving.value = true;
    saveError.value = "";
    try {
      const fieldAliases: Record<string, Record<string, string>> = {};
      const priceColumns: Record<string, Record<string, string>> = {};
      for (const group of mappings.value) {
        for (const field of group.fields) {
          const selected = mappingSelections.value.get(mappingKey(group, field.internal_key));
          if (selected === undefined || selected === field.effective_header) continue;
          if (group.kind === "price") {
            (priceColumns.data_base_price_columns ??= {})[field.internal_key] = selected;
          } else {
            (fieldAliases[group.logical_sheet] ??= {})[field.internal_key] = selected;
          }
        }
      }
      const result = await api.saveSchemaOverride(
        {
          field_aliases: fieldAliases,
          ...(Object.keys(priceColumns).length > 0 ? { price_columns: priceColumns } : {}),
        },
        workspaceId.value,
      );
      applyInspection(result.remaining_issues);
      await refreshMappings();
      overviewEditing.value = false;
      mappingSelections.value = new Map();
      return true;
    } catch (e) {
      saveError.value = e instanceof ApiError ? e.message : `保存失败：${e}`;
      return false;
    } finally {
      saving.value = false;
    }
  }

  function closeWizard() {
    wizardOpen.value = false;
    selections.value = new Map();
    priceSelections.value = new Map();
    saveError.value = "";
  }

  /** 保存 override 并让后端重建快照；返回是否全部问题已消除。 */
  async function save(): Promise<boolean> {
    if (!allResolved.value) return false;
    saving.value = true;
    saveError.value = "";
    try {
      const fieldAliases: Record<string, Record<string, string>> = {};
      for (const issue of fieldIssues.value) {
        const header = selections.value.get(issue.internal_key);
        if (!header) continue;
        (fieldAliases[issue.logical_sheet] ??= {})[issue.internal_key] = header;
      }
      const priceColumns: Record<string, Record<string, string>> = {};
      for (const issue of priceIssues.value) {
        const header = priceSelections.value.get(issue.internal_key);
        if (!header) continue;
        // 价格键目前都在 DATA BASE 的 data_base_price_columns 块
        (priceColumns.data_base_price_columns ??= {})[issue.internal_key] = header;
      }
      const result = await api.saveSchemaOverride(
        {
          field_aliases: fieldAliases,
          ...(Object.keys(priceColumns).length > 0 ? { price_columns: priceColumns } : {}),
        },
        workspaceId.value,
      );
      applyInspection(result.remaining_issues);
      if (!result.remaining_issues.has_issues) {
        closeWizard();
        return true;
      }
      // 部分问题仍在，保持向导打开让用户继续
      selections.value = new Map();
      priceSelections.value = new Map();
      return false;
    } catch (e) {
      saveError.value = e instanceof ApiError ? e.message : `保存失败：${e}`;
      return false;
    } finally {
      saving.value = false;
    }
  }

  function reset() {
    loading.value = false;
    error.value = "";
    hasIssues.value = false;
    sheetIssues.value = [];
    fieldIssues.value = [];
    priceIssues.value = [];
    selections.value = new Map();
    priceSelections.value = new Map();
    wizardOpen.value = false;
    saving.value = false;
    saveError.value = "";
    pinVerified.value = false;
    pinDialogOpen.value = false;
    pinError.value = "";
    mappings.value = [];
    mappingsLoading.value = false;
    overviewOpen.value = false;
    overviewEditing.value = false;
    mappingSelections.value = new Map();
    pinIntent.value = null;
    targetWorkspaceId.value = null;
  }

  return {
    loading, error, hasIssues, sheetIssues, fieldIssues, priceIssues, selections, priceSelections,
    wizardOpen, saving, saveError,
    pinVerified, pinDialogOpen, pinError,
    mappings, mappingsLoading, overviewOpen, overviewEditing, mappingSelections,
    allResolved, issueCount, mappingDirtyCount,
    refreshIssues, refreshMappings, selectHeader, selectPriceHeader, selectMapping,
    enterWizard, enterOverviewEdit, cancelOverviewEdit, confirmPin, cancelPin,
    closeWizard, closeOverview, toggleOverview,
    save, saveMappings, reset, mappingKey,
    setTargetWorkspace, openRepairFor,
  };
});
