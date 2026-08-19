/**
 * 表头修复向导 demo 的 mock 数据。
 *
 * 对应设计方案中 `GET /api/workspaces/{id}/schema/issues` 的响应结构。
 * 两种场景：
 * - clean：无问题（base 文件表头与内置 schema 一致）
 * - drift：表头漂移（PO NO. → PO NUMBER 等）
 */

export interface HeaderSuggestion {
  header: string;
  /** 0-1 的置信度 */
  confidence: number;
  reason: "exact_match" | "normalized_match" | "fuzzy_match";
}

export interface SchemaIssue {
  /** 逻辑字段键，如 po_no */
  field: string;
  /** 面向用户的字段名，如 "PO 号" */
  fieldLabel: string;
  /** 内置 schema 期望的表头 */
  expected: string;
  /** 所在 Sheet（面向用户的名称） */
  sheet: string;
  /** 自动建议，按置信度降序 */
  suggestions: HeaderSuggestion[];
  /** 文件中所有未被使用的表头（"选择其他列"候选） */
  availableHeaders: string[];
}

export interface SchemaIssuesResponse {
  issues: SchemaIssue[];
}

/** 场景 1：表头漂移 —— 客户把 PO NO. 改成 PO NUMBER，SHIP QTY 改成 SHIPQTY */
export const driftScenario: SchemaIssuesResponse = {
  issues: [
    {
      field: "po_no",
      fieldLabel: "PO 号",
      expected: "PO NO.",
      sheet: "PO RECORD 26",
      suggestions: [
        { header: "PO NUMBER", confidence: 0.95, reason: "normalized_match" },
        { header: "PO NO", confidence: 0.9, reason: "normalized_match" },
      ],
      availableHeaders: ["PO NUMBER", "PO NO", "ORDER NO.", "PO#"],
    },
    {
      field: "ship_qty",
      fieldLabel: "出货数量",
      expected: "SHIP QTY",
      sheet: "PO RECORD 26",
      suggestions: [
        { header: "SHIPQTY", confidence: 0.88, reason: "fuzzy_match" },
        { header: "SHIPPED QTY", confidence: 0.72, reason: "fuzzy_match" },
      ],
      availableHeaders: ["SHIPQTY", "SHIPPED QTY", "QTY", "SHIP QUANTITY"],
    },
  ],
};

/** 场景 2：无问题 —— 验证通过 */
export const cleanScenario: SchemaIssuesResponse = {
  issues: [],
};

export interface ValidateResult {
  ok: boolean;
  message: string;
  remainingIssues: SchemaIssue[];
}

/** 全量字段映射总览：一个 Sheet 内所有逻辑字段的当前生效映射 */
export interface FieldMappingRow {
  /** 逻辑字段键 */
  field: string;
  /** 面向用户的字段名 */
  fieldLabel: string;
  /** 内置默认表头 */
  builtin: string;
  /** 当前生效表头（= override 或 builtin） */
  effective: string;
  /** 是否被 override */
  isOverride: boolean;
  /** 文件中是否存在该表头 */
  found: boolean;
  /** 文件中该 Sheet 的所有表头（下拉候选） */
  availableHeaders: string[];
}

export interface SheetMappingGroup {
  /** Sheet 逻辑名 */
  sheetKey: string;
  /** Sheet 显示名 */
  sheetName: string;
  rows: FieldMappingRow[];
}

/** 全量映射 mock（drift 场景：PO record 有两个字段被改） */
export const fullMappingDrift: SheetMappingGroup[] = [
  {
    sheetKey: "DATA BASE",
    sheetName: "DATA BASE TEMPLATE",
    rows: [
      {
        field: "sap",
        fieldLabel: "SAP 编号",
        builtin: "SAP",
        effective: "SAP",
        isOverride: false,
        found: true,
        availableHeaders: ["SAP", "Material Description", "GS MODEL", "Category", "MOQ"],
      },
      {
        field: "description",
        fieldLabel: "物料描述",
        builtin: "Material Description",
        effective: "Material Description",
        isOverride: false,
        found: true,
        availableHeaders: ["SAP", "Material Description", "GS MODEL", "Category", "MOQ"],
      },
      {
        field: "gs_model",
        fieldLabel: "GS 型号",
        builtin: "GS MODEL",
        effective: "GS MODEL",
        isOverride: false,
        found: true,
        availableHeaders: ["SAP", "Material Description", "GS MODEL", "Category", "MOQ"],
      },
      {
        field: "category",
        fieldLabel: "品类",
        builtin: "Category",
        effective: "Category",
        isOverride: false,
        found: true,
        availableHeaders: ["SAP", "Material Description", "GS MODEL", "Category", "MOQ"],
      },
    ],
  },
  {
    sheetKey: "PO record",
    sheetName: "PO RECORD 26",
    rows: [
      {
        field: "po_no",
        fieldLabel: "PO 号",
        builtin: "PO NO.",
        effective: "PO NO.",
        isOverride: false,
        found: false,
        availableHeaders: ["PO NUMBER", "ITEM LINE#", "SAP Number", "DESCRIPTION", "SHIPQTY", "INV#"],
      },
      {
        field: "item_line",
        fieldLabel: "行项目号",
        builtin: "ITEM LINE#",
        effective: "ITEM LINE#",
        isOverride: false,
        found: true,
        availableHeaders: ["PO NUMBER", "ITEM LINE#", "SAP Number", "DESCRIPTION", "SHIPQTY", "INV#"],
      },
      {
        field: "sap",
        fieldLabel: "SAP 编号",
        builtin: "SAP Number",
        effective: "SAP Number",
        isOverride: false,
        found: true,
        availableHeaders: ["PO NUMBER", "ITEM LINE#", "SAP Number", "DESCRIPTION", "SHIPQTY", "INV#"],
      },
      {
        field: "description",
        fieldLabel: "描述",
        builtin: "DESCRIPTION",
        effective: "DESCRIPTION",
        isOverride: false,
        found: true,
        availableHeaders: ["PO NUMBER", "ITEM LINE#", "SAP Number", "DESCRIPTION", "SHIPQTY", "INV#"],
      },
      {
        field: "ship_qty",
        fieldLabel: "出货数量",
        builtin: "SHIP QTY",
        effective: "SHIP QTY",
        isOverride: false,
        found: false,
        availableHeaders: ["PO NUMBER", "ITEM LINE#", "SAP Number", "DESCRIPTION", "SHIPQTY", "INV#"],
      },
      {
        field: "inv_no",
        fieldLabel: "发票号",
        builtin: "INV#",
        effective: "INV#",
        isOverride: false,
        found: true,
        availableHeaders: ["PO NUMBER", "ITEM LINE#", "SAP Number", "DESCRIPTION", "SHIPQTY", "INV#"],
      },
    ],
  },
  {
    sheetKey: "客户PO",
    sheetName: "new PO template",
    rows: [
      {
        field: "purchasing_document",
        fieldLabel: "采购订单号",
        builtin: "PO#",
        effective: "PO#",
        isOverride: false,
        found: true,
        availableHeaders: ["PO#", "PO-Item", "Material", "Order Quantity"],
      },
      {
        field: "item",
        fieldLabel: "行项目",
        builtin: "PO-Item",
        effective: "PO-Item",
        isOverride: false,
        found: true,
        availableHeaders: ["PO#", "PO-Item", "Material", "Order Quantity"],
      },
      {
        field: "material",
        fieldLabel: "物料号",
        builtin: "Material",
        effective: "Material",
        isOverride: false,
        found: true,
        availableHeaders: ["PO#", "PO-Item", "Material", "Order Quantity"],
      },
      {
        field: "order_quantity",
        fieldLabel: "订单数量",
        builtin: "Order Quantity",
        effective: "Order Quantity",
        isOverride: false,
        found: true,
        availableHeaders: ["PO#", "PO-Item", "Material", "Order Quantity"],
      },
    ],
  },
];

/** 全量映射 mock（clean 场景：全部匹配） */
export const fullMappingClean: SheetMappingGroup[] = fullMappingDrift.map((group) => ({
  ...group,
  rows: group.rows.map((row) => ({ ...row, found: true })),
}));

/** 模拟保存 + 验证：如果所有 issue 都选择了表头则通过 */
export function simulateValidate(selections: Map<string, string>, issues: SchemaIssue[]): ValidateResult {
  const remaining = issues.filter((issue) => !selections.get(issue.field));
  if (remaining.length === 0) {
    return { ok: true, message: "验证通过，所有列对应关系有效", remainingIssues: [] };
  }
  return {
    ok: false,
    message: `仍有 ${remaining.length} 个列未设置对应关系`,
    remainingIssues: remaining,
  };
}

export type DemoScenario = "drift" | "clean";

export const scenarios: Record<DemoScenario, SchemaIssuesResponse> = {
  drift: driftScenario,
  clean: cleanScenario,
};

/* ===== 修复 PIN 模拟（软管控） ===== */

/** demo 模拟系统校验码（生产环境读本机 schema_pin.txt） */
export const DEMO_PIN = "1234";

/** 最大连续尝试次数 */
export const PIN_MAX_ATTEMPTS = 5;

/** 锁定时长（秒） */
export const PIN_LOCK_SECONDS = 600;

/** 模拟 PIN 校验 */
export function verifyPin(input: string): boolean {
  return input === DEMO_PIN;
}
