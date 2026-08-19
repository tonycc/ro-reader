<script setup lang="ts">
import { computed, ref } from "vue";
import MappingOverviewPage from "./MappingOverviewPage.vue";
import PinDialog from "./PinDialog.vue";
import {
  scenarios,
  simulateValidate,
  fullMappingDrift,
  fullMappingClean,
  verifyPin,
  PIN_MAX_ATTEMPTS,
  PIN_LOCK_SECONDS,
  type DemoScenario,
  type SchemaIssuesResponse,
  type ValidateResult,
} from "./mockData";

/**
 * Schema 配置 demo —— 内联在「数据检查」tab 中。
 * 模拟真实工作台结构：
 *   - 顶部 IssueSummaryBar（N 项阻断 / N 项警告徽章，点击展开）
 *   - schema 错误进入「阻断」面板，每条带「修复列对应关系」入口
 *   - 修复向导 / 全部字段对应关系 作为 tab 内的内联视图
 * 纯前端 mock，不调用后端。
 */

const scenario = ref<DemoScenario>("drift");
const data = computed<SchemaIssuesResponse>(() => scenarios[scenario.value]);

/** 用户为每个字段选择的表头：field -> header（用 ref + 替换 Map 保证追踪可靠） */
const selections = ref(new Map<string, string>());

/** 数据检查 tab 内的视图：数据表格 / 修复向导 / 字段对应关系总览 */
const checkView = ref<"table" | "wizard" | "overview">("table");

/** IssueSummaryBar 阻断面板是否展开 */
const issuePanelOpen = ref(false);

/** 保存验证结果 */
const validateResult = ref<ValidateResult | null>(null);
const saving = ref(false);

/* ===== 修复 PIN 状态（软管控，系统默认始终开启） ===== */
/** 本次会话是否已通过 PIN 验证 */
const pinVerified = ref(false);
/** PIN 弹窗是否打开 */
const pinDialogOpen = ref(false);
/** 连续输错次数 */
const pinAttempts = ref(0);
/** 锁定剩余秒数 */
const pinLockSeconds = ref(0);
/** PIN 弹窗组件引用（用于回显错误） */
const pinDialogRef = ref<InstanceType<typeof PinDialog> | null>(null);

const pinAttemptsLeft = computed(() => PIN_MAX_ATTEMPTS - pinAttempts.value);

/** 总览页数据：drift 用漂移版，clean 用全部匹配版 */
const overviewGroups = computed(() =>
  scenario.value === "clean" ? fullMappingClean : fullMappingDrift,
);

/** schema 阻断错误的数量（drift 场景才有） */
const schemaBlockingCount = computed(() =>
  scenario.value === "drift" ? data.value.issues.length : 0,
);

function switchScenario(s: DemoScenario) {
  scenario.value = s;
  selections.value = new Map();
  validateResult.value = null;
  issuePanelOpen.value = false;
  checkView.value = "table";
}

function onSelect(field: string, header: string) {
  const next = new Map(selections.value);
  next.set(field, header);
  selections.value = next;
  validateResult.value = null;
}

function onPick(field: string, event: Event) {
  const value = (event.target as HTMLSelectElement).value;
  if (value) onSelect(field, value);
}

const allResolved = computed(() =>
  data.value.issues.every((issue) => selections.value.has(issue.field)),
);

const hasChanges = computed(() => selections.value.size > 0);

/** 点击「保存并验证」：进入向导时已校验 PIN，这里直接保存 */
function requestSave() {
  doSave();
}

async function doSave() {
  saving.value = true;
  validateResult.value = null;
  await new Promise((r) => setTimeout(r, 600));
  validateResult.value = simulateValidate(selections.value, data.value.issues);
  saving.value = false;
}

/** PIN 弹窗确认：验证通过后进入修复向导 */
function onPinConfirm(input: string) {
  if (verifyPin(input)) {
    pinVerified.value = true;
    pinAttempts.value = 0;
    pinDialogOpen.value = false;
    checkView.value = "wizard";
  } else {
    pinAttempts.value += 1;
    if (pinAttempts.value >= PIN_MAX_ATTEMPTS) {
      pinLockSeconds.value = PIN_LOCK_SECONDS;
      const timer = setInterval(() => {
        pinLockSeconds.value -= 1;
        if (pinLockSeconds.value <= 0) {
          clearInterval(timer);
          pinAttempts.value = 0;
          pinLockSeconds.value = 0;
          pinDialogOpen.value = false;
        }
      }, 1000);
      pinDialogRef.value?.onConfirmFail("校验码错误，已锁定");
    } else {
      pinDialogRef.value?.onConfirmFail("校验码错误，请重试");
    }
  }
}

function onPinCancel() {
  pinDialogOpen.value = false;
}

/** 进入修复向导：未验证系统校验码时先弹框 */
function enterWizard() {
  issuePanelOpen.value = false;
  if (!pinVerified.value) {
    pinDialogOpen.value = true;
    return;
  }
  checkView.value = "wizard";
}

/** 从阻断面板进入修复向导 */
function openWizard() {
  enterWizard();
}

/** 模拟数据表格的列（drift 场景下因为找不到列而显示占位） */
const tableHeaders = ["#", "SAP Number", "品名", "Order Quantity", "FINALQTY"];
const tableRows = [
  ["1", "EMAX-1001", "ROD ASSY", "500", "500"],
  ["2", "EMAX-1002", "COMBO SET", "300", "300"],
  ["3", "EMAX-1005", "REEL 5M", "120", "120"],
];
</script>

<template>
  <div class="demo-page">
    <!-- demo 场景切换工具栏 -->
    <div class="demo-toolbar">
      <span class="demo-label">Demo 场景：</span>
      <button class="scenario-btn" :class="{ active: scenario === 'drift' }" @click="switchScenario('drift')">表头漂移</button>
      <button class="scenario-btn" :class="{ active: scenario === 'clean' }" @click="switchScenario('clean')">无问题</button>
      <span class="demo-file">PO RECORD 2026.xlsx</span>
    </div>

    <!-- ===== 模拟真实工作台：数据检查 tab ===== -->
    <div class="workbench-shell">
      <!-- 工作台顶部 tab 栏（模拟，只有「数据检查」激活） -->
      <nav class="wb-tabs">
        <button class="wb-tab active">数据检查</button>
        <button class="wb-tab" disabled>单据预览</button>
        <button class="wb-tab" disabled>导出确认</button>
      </nav>

      <div class="wb-content">
        <!-- ===== IssueSummaryBar：阻断 / 警告徽章 ===== -->
        <div class="issue-bar">
          <span v-if="schemaBlockingCount === 0" class="issue-badge ready">✓ 就绪</span>

          <!-- schema 阻断错误徽章 -->
          <div v-if="schemaBlockingCount" class="data-issue-root">
            <button class="issue-badge blocked" type="button" @click="issuePanelOpen = !issuePanelOpen">
              {{ schemaBlockingCount }} 项阻断
            </button>
            <div v-if="issuePanelOpen" class="data-issue-panel">
              <div class="data-issue-head">
                <strong>阻断原因</strong>
                <div class="data-issue-head-right">
                  <span>PO RECORD 2026</span>
                  <button class="data-issue-close-btn" type="button" aria-label="关闭" @click.stop="issuePanelOpen = false">×</button>
                </div>
              </div>
              <div class="data-issue-list">
                <div v-for="issue in data.issues" :key="issue.field" class="data-issue-row">
                  <div class="data-issue-title">找不到「{{ issue.expected }}」列（{{ issue.fieldLabel }}）</div>
                  <div class="data-issue-meta">{{ issue.sheet }} · 列对应关系</div>
                  <button class="repair-link" type="button" @click="openWizard">修复列对应关系 →</button>
                </div>
              </div>
            </div>
          </div>

          <!-- 数据检查 meta -->
          <span class="issue-meta">PO RECORD 2026 · {{ tableRows.length }} 行 · PO 基础检查</span>

          <!-- 右侧：切换到字段对应关系总览 -->
          <button class="overview-link" type="button" @click="checkView = checkView === 'overview' ? 'table' : 'overview'">
            {{ checkView === 'overview' ? '返回数据表格' : '全部字段对应关系' }}
          </button>
        </div>

        <!-- ===== 视图 1：数据表格（默认） ===== -->
        <div v-if="checkView === 'table'" class="panel">
          <div v-if="schemaBlockingCount" class="schema-blocked-note">
            <span class="blocked-icon">⚠</span>
            <span>因找不到必需的列，无法完整读取数据。请先 <button class="inline-link" type="button" @click="enterWizard">修复列对应关系</button>。</span>
          </div>
          <div class="table-shell">
            <table class="data-table">
              <thead>
                <tr><th v-for="h in tableHeaders" :key="h">{{ h }}</th></tr>
              </thead>
              <tbody>
                <tr v-for="(row, i) in tableRows" :key="i">
                  <td v-for="(cell, j) in row" :key="j" :class="{ 'mono': j === 0 }">{{ cell }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- ===== 视图 2：修复向导（内联） ===== -->
        <template v-if="checkView === 'wizard'">
          <header class="page-header">
            <button class="back-link" type="button" @click="checkView = 'table'">← 返回数据检查</button>
            <h1 class="page-title">修复列对应关系</h1>
            <p class="page-sub">发现 {{ data.issues.length }} 处列名对不上。请按表格和原列名核对，再在「对应到」中选择文件里的实际列。</p>
          </header>

          <div class="table-wrap">
            <table class="repair-table">
              <thead>
                <tr>
                  <th>数据字段</th>
                  <th>表格</th>
                  <th>原列名</th>
                  <th>对应到</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="issue in data.issues"
                  :key="issue.field"
                  :class="{ resolved: selections.has(issue.field) }"
                >
                  <td class="col-field">
                    <span class="status" :class="{ ok: selections.has(issue.field) }">{{ selections.has(issue.field) ? "✓" : "✗" }}</span>
                    {{ issue.fieldLabel }}
                  </td>
                  <td class="col-sheet">{{ issue.sheet }}</td>
                  <td class="col-old">{{ issue.expected }}</td>
                  <td class="col-new">
                    <select
                      class="pick-select"
                      :value="selections.get(issue.field) ?? ''"
                      :aria-label="`为 ${issue.fieldLabel} 选择对应列`"
                      @change="onPick(issue.field, $event)"
                    >
                      <option value="" disabled>请选择</option>
                      <option v-for="(h, i) in issue.availableHeaders" :key="h" :value="h">{{ String.fromCharCode(65 + i) }}:{{ h }}</option>
                    </select>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <footer class="page-footer">
            <div class="footer-right">
              <span v-if="!allResolved" class="footer-hint">还有 {{ data.issues.filter((i) => !selections.has(i.field)).length }} 个列未设置</span>
              <button class="btn-save" :disabled="!allResolved || saving" @click="requestSave">
                {{ saving ? "验证中…" : "保存并验证" }}
              </button>
            </div>
          </footer>
        </template>

        <!-- ===== 视图 3：全部字段对应关系（内联） ===== -->
        <template v-if="checkView === 'overview'">
          <MappingOverviewPage :groups="overviewGroups" :selections="selections" @select="onSelect" />
          <footer class="page-footer">
            <div class="footer-right">
              <span v-if="hasChanges" class="footer-hint">有未保存的修改</span>
              <button class="btn-save" :disabled="!hasChanges || saving" @click="requestSave">
                {{ saving ? "验证中…" : "保存并验证" }}
              </button>
            </div>
          </footer>
        </template>

        <!-- 验证结果 -->
        <div v-if="validateResult" class="validate-result" :class="validateResult.ok ? 'ok' : 'fail'">
          <span class="validate-icon">{{ validateResult.ok ? "✓" : "✗" }}</span>
          <span>{{ validateResult.message }}</span>
        </div>
      </div>
    </div>

    <!-- PIN 输入弹窗 -->
    <PinDialog
      ref="pinDialogRef"
      :open="pinDialogOpen"
      :attempts-left="pinAttemptsLeft"
      :lock-seconds="pinLockSeconds"
      @confirm="onPinConfirm"
      @cancel="onPinCancel"
    />
  </div>
</template>

<style scoped>
.demo-page { min-height: 100vh; background: var(--bg); font-family: var(--sans); font-size: 13px; color: var(--text); }
.demo-toolbar { display: flex; align-items: center; gap: var(--space-2); padding: var(--space-2) var(--space-4); background: var(--panel); border-bottom: 1px solid var(--line); }
.demo-label { color: var(--muted); font-size: var(--text-sm); }
.scenario-btn { height: 26px; padding: 0 var(--space-3); border: 1px solid var(--line-strong); border-radius: 999px; background: var(--panel); font-size: var(--text-sm); cursor: pointer; color: var(--muted); }
.scenario-btn.active { background: var(--blue); border-color: var(--blue); color: #fff; }
.demo-file { margin-left: auto; color: var(--subtle); font-size: var(--text-sm); font-family: var(--mono); }

/* ===== 模拟工作台外壳 ===== */
.workbench-shell { max-width: 980px; margin: 0 auto; padding: var(--space-4); }
.wb-tabs { display: flex; gap: 2px; background: var(--panel); border: 1px solid var(--line); border-bottom: none; border-radius: 8px 8px 0 0; padding: 0 var(--space-3); }
.wb-tab { height: 40px; padding: 0 var(--space-4); border: 0; border-bottom: 3px solid transparent; background: transparent; color: var(--muted); font-weight: 700; }
.wb-tab.active { color: var(--blue); border-bottom-color: var(--blue); }
.wb-tab:disabled { color: var(--subtle); cursor: default; opacity: 0.6; }
.wb-content { background: var(--panel); border: 1px solid var(--line); border-top: none; border-radius: 0 0 8px 8px; padding: var(--space-4); display: flex; flex-direction: column; gap: var(--space-3); }

/* ===== IssueSummaryBar（复用真实样式） ===== */
.issue-bar { display: flex; align-items: center; gap: 10px; padding: 10px 14px; border: 1px solid var(--line); border-radius: 8px; background: white; flex-wrap: wrap; }
.issue-badge { display: inline-flex; align-items: center; gap: 4px; height: 22px; padding: 0 8px; border-radius: 999px; font-size: 12px; border: 0; }
.ready { color: var(--green); background: var(--green-weak); }
.blocked { color: var(--red); background: var(--red-weak); cursor: pointer; font-weight: 700; }
.blocked:hover { box-shadow: inset 0 0 0 1px #fca5a5; }
.issue-meta { color: var(--muted); font-size: 12px; }
.overview-link { margin-left: auto; border: none; background: none; color: var(--blue); font-size: 12px; cursor: pointer; padding: 0; }
.overview-link:hover { text-decoration: underline; }
.data-issue-root { position: relative; display: inline-flex; }
.data-issue-panel { position: absolute; top: 28px; left: 0; z-index: 60; width: min(420px, calc(100vw - 32px)); max-height: 360px; overflow: auto; border-radius: 8px; background: white; box-shadow: 0 16px 40px rgba(15, 23, 42, 0.16); border: 1px solid #fecaca; }
.data-issue-head { position: sticky; top: 0; z-index: 1; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 12px; font-size: 12px; border-bottom: 1px solid #fee2e2; background: #fff7f7; color: var(--red); }
.data-issue-head-right { display: inline-flex; align-items: center; gap: 8px; }
.data-issue-head span { color: var(--muted); font-family: var(--mono); font-weight: 700; }
.data-issue-close-btn { width: 22px; height: 22px; display: grid; place-items: center; border-radius: 6px; background: white; font-size: 16px; line-height: 1; cursor: pointer; border: 1px solid #fecaca; color: var(--red); }
.data-issue-list { padding: 6px; }
.data-issue-row { padding: 9px 10px; }
.data-issue-row + .data-issue-row { border-top: 1px solid var(--line); }
.data-issue-title { color: var(--text); font-size: 12px; font-weight: 800; line-height: 1.45; }
.data-issue-meta { margin-top: 4px; color: var(--muted); font-size: 11px; line-height: 1.35; }
.repair-link { margin-top: 6px; border: none; background: none; color: var(--blue); font-size: 12px; cursor: pointer; padding: 0; font-weight: 600; }
.repair-link:hover { text-decoration: underline; }

/* ===== 数据表格 ===== */
.panel { border: 1px solid var(--line); border-radius: 12px; background: var(--panel); overflow: hidden; }
.schema-blocked-note { display: flex; align-items: center; gap: 8px; padding: 9px 12px; border-bottom: 1px solid #fde68a; background: #fffbeb; color: #92400e; font-size: 12px; }
.blocked-icon { font-weight: 700; }
.inline-link { border: none; background: none; color: var(--blue); font-size: 12px; cursor: pointer; padding: 0; font-weight: 600; text-decoration: underline; }
.table-shell { overflow: auto; }
.data-table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: 12px; }
th, td { border-bottom: 1px solid var(--line); padding: 9px 10px; text-align: left; white-space: nowrap; }
th { background: #f7f9fc; color: var(--muted); font-weight: 800; border-bottom-color: var(--line-strong); }
.mono { font-family: var(--mono); }

/* ===== 向导 / 总览 ===== */
.back-link { border: none; background: none; color: var(--muted); font-size: 12px; cursor: pointer; padding: 0; margin-bottom: 4px; }
.back-link:hover { color: var(--blue); }
.page-header { margin-bottom: var(--space-1); }
.page-title { margin: 0; font-size: 17px; font-weight: 600; }
.page-sub { margin: 4px 0 0; color: var(--muted); font-size: 12px; }
.table-wrap { overflow: auto; }
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
.col-old { font-family: var(--mono); white-space: nowrap; }
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
.page-footer { display: flex; align-items: center; justify-content: flex-end; padding-top: var(--space-3); border-top: 1px solid var(--line); }
.footer-right { display: flex; align-items: center; gap: var(--space-3); }
.footer-hint { color: var(--amber); font-size: var(--text-sm); }
.btn-save { height: 34px; padding: 0 var(--space-4); border: none; border-radius: var(--radius-sm); background: var(--blue); color: #fff; font-size: 13px; cursor: pointer; }
.btn-save:disabled { opacity: 0.5; cursor: not-allowed; }
.validate-result { display: flex; align-items: center; gap: var(--space-2); padding: var(--space-3) var(--space-4); border-radius: var(--radius-md); font-weight: 500; }
.validate-result.ok { background: var(--green-weak); color: var(--green); border: 1px solid var(--green); }
.validate-result.fail { background: var(--amber-weak); color: var(--amber); border: 1px solid var(--amber); }
.validate-icon { font-weight: 700; }
</style>
