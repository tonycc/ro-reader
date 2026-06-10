<script setup lang="ts">
import { ref, onMounted } from "vue";
import { useWorkbench } from "../../stores/workbench";

const wb = useWorkbench();
const STORAGE_KEY = "ro-workbench-base-path";

const configuredPath = ref("");
const editValue = ref("");
const showSettings = ref(false);
const status = ref<"idle" | "loading" | "loaded" | "error">("idle");
const pathCheckResult = ref<"idle" | "checking" | "ok" | "fail">("idle");
const pathCheckMsg = ref("");

onMounted(() => {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved) {
    configuredPath.value = saved;
    editValue.value = saved;
  }
});

function openSettings() {
  editValue.value = configuredPath.value;
  showSettings.value = true;
}

function saveSettings() {
  const p = editValue.value.trim();
  if (p) {
    configuredPath.value = p;
    localStorage.setItem(STORAGE_KEY, p);
  } else {
    configuredPath.value = "";
    localStorage.removeItem(STORAGE_KEY);
  }
  showSettings.value = false;
}

async function checkPath() {
  const p = editValue.value.trim();
  if (!p) { pathCheckResult.value = "fail"; pathCheckMsg.value = "请输入路径"; return; }
  pathCheckResult.value = "checking";
  pathCheckMsg.value = "";
  try {
    const resp = await fetch("/api/check-path", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: p }),
    });
    const data = await resp.json();
    if (data.ok) {
      pathCheckResult.value = "ok";
      pathCheckMsg.value = `有效 · ${data.sheets?.length || 0} 个 Sheet · ${(data.size / 1024).toFixed(0)} KB`;
    } else {
      pathCheckResult.value = "fail";
      pathCheckMsg.value = data.error || "检测失败";
    }
  } catch {
    pathCheckResult.value = "fail";
    pathCheckMsg.value = "API 服务未连接";
  }
}

async function loadData() {
  if (!configuredPath.value) return;
  status.value = "loading";
  try {
    await wb.openSession(configuredPath.value);
    status.value = wb.error ? "error" : "loaded";
  } catch {
    status.value = "error";
  }
}
</script>

<template>
  <header class="topbar">
    <div class="brand">
      <div class="brand-mark">RO</div>
      <div class="file-title">
        <strong v-if="wb.baseFile">{{ wb.baseFile.split("/").pop() }}</strong>
        <strong v-else-if="configuredPath">{{ configuredPath.split("/").pop() }}</strong>
        <strong v-else>未配置文件</strong>
        <span v-if="wb.baseFile">本机文件 · {{ wb.poList.length }} 个 PO · 可重新加载</span>
        <span v-else-if="configuredPath">已配置路径 · 点击加载</span>
        <span v-else>请在系统设置中配置文件路径</span>
      </div>
      <button v-if="configuredPath" class="load-btn" @click="loadData" :disabled="status === 'loading'">
        {{ status === 'loading' ? '加载中…' : '加载数据' }}
      </button>
    </div>

    <div class="top-actions">
      <button class="primary-btn" @click="openSettings">系统设置</button>
    </div>
  </header>

  <!-- 设置面板 -->
  <Teleport to="body">
    <div v-if="showSettings" class="settings-overlay" @click.self="showSettings = false">
      <div class="settings-panel">
        <div class="settings-head">
          <h2>系统设置</h2>
          <button class="close-btn" @click="showSettings = false">✕</button>
        </div>

        <div class="settings-body">
          <div class="setting-group">
            <label>Base 文件路径</label>
            <p class="setting-desc">RO DATA BASE & PO record template.xlsx 的完整路径</p>
            <div class="path-row">
              <input
                v-model="editValue"
                class="setting-input"
                placeholder="例: C:\Users\xxx\RO DATA BASE & PO record template.xlsx"
                @input="pathCheckResult = 'idle'; pathCheckMsg = ''"
              />
              <button class="check-btn" @click="checkPath" :disabled="pathCheckResult === 'checking'">
                {{ pathCheckResult === 'checking' ? '检测中…' : '检测' }}
              </button>
            </div>
            <p v-if="pathCheckMsg" class="path-check-msg" :class="pathCheckResult">
              <span v-if="pathCheckResult === 'ok'">✓</span>
              <span v-else>✗</span>
              {{ pathCheckMsg }}
            </p>
          </div>

          <div class="setting-group">
            <label>软件版本</label>
            <div class="version-info">
              <div class="version-row"><span>RO Generator</span><code>v0.0.0</code></div>
              <div class="version-row"><span>RO Workbench API</span><code>v0.0.0</code></div>
              <div class="version-row"><span>前端界面</span><code>v0.0.0</code></div>
            </div>
          </div>
        </div>

        <div class="settings-foot">
          <button class="secondary-btn" @click="showSettings = false">取消</button>
          <button class="primary-btn" @click="saveSettings">保存</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.topbar {
  display: flex; align-items: center; justify-content: space-between;
  gap: 24px; padding: 0 18px;
  background: rgba(255, 255, 255, 0.92);
  border-bottom: 1px solid var(--line);
  backdrop-filter: blur(18px);
}
.brand { display: flex; align-items: center; gap: 12px; min-width: 400px; }
.brand-mark {
  width: 28px; height: 28px; border-radius: 8px;
  display: grid; place-items: center;
  color: white;
  background: linear-gradient(135deg, #2563eb, #14b8a6);
  font-weight: 800;
}
.file-title { display: flex; flex-direction: column; gap: 2px; line-height: 1.15; }
.file-title strong { font-size: 14px; font-weight: 700; }
.file-title span { color: var(--muted); font-size: 12px; }
.load-btn {
  height: 30px; padding: 0 12px;
  border: 1px solid var(--blue); border-radius: 6px;
  background: var(--blue-weak); color: var(--blue);
  font: inherit; font-size: 12px; font-weight: 700; cursor: pointer;
  white-space: nowrap; margin-left: 4px;
}
.load-btn:hover { background: #dce7ff; }
.load-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.top-actions { display: flex; align-items: center; gap: 8px; }
.icon-btn, .secondary-btn, .primary-btn {
  border: 1px solid var(--line); border-radius: 8px;
  background: white; color: var(--text);
  height: 34px; font: inherit;
}
.icon-btn { width: 34px; display: grid; place-items: center; }
.secondary-btn { padding: 0 12px; cursor: pointer; }
.primary-btn {
  padding: 0 15px;
  border-color: #1d4ed8; color: white;
  background: var(--blue); font-weight: 700; cursor: pointer;
}
button { cursor: pointer; }
button:disabled { opacity: 0.5; cursor: not-allowed; }

/* 设置面板 */
.settings-overlay {
  position: fixed; inset: 0; z-index: 1000;
  background: rgba(0,0,0,0.3);
  display: grid; place-items: center;
}
.settings-panel {
  width: 480px; max-height: 80vh;
  background: var(--panel);
  border-radius: 14px;
  box-shadow: 0 20px 60px rgba(0,0,0,0.18);
  display: flex; flex-direction: column;
  overflow: hidden;
}
.settings-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 18px 22px 14px;
  border-bottom: 1px solid var(--line);
}
.settings-head h2 { margin: 0; font-size: 16px; }
.close-btn {
  width: 28px; height: 28px; border: 0; border-radius: 6px;
  background: var(--panel-soft); color: var(--muted);
  font-size: 14px; cursor: pointer; display: grid; place-items: center;
}
.close-btn:hover { background: var(--red-weak); color: var(--red); }

.settings-body { padding: 20px 22px; overflow: auto; flex: 1; }
.setting-group { margin-bottom: 22px; }
.setting-group label { display: block; font-weight: 700; font-size: 13px; margin-bottom: 4px; }
.setting-desc { margin: 0 0 8px; color: var(--muted); font-size: 12px; }
.setting-input {
  width: 100%; height: 36px;
  border: 1px solid var(--line); border-radius: 8px;
  padding: 0 10px; font: inherit; font-size: 13px;
  color: var(--text); background: var(--panel-soft);
}
.setting-input:focus { border-color: var(--blue); outline: 0; }
.path-row { display: flex; gap: 8px; }
.check-btn {
  height: 36px; padding: 0 14px; flex-shrink: 0;
  border: 1px solid var(--line); border-radius: 8px;
  background: white; color: var(--text);
  font: inherit; font-size: 12px; cursor: pointer;
}
.check-btn:hover { border-color: var(--blue); color: var(--blue); }
.check-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.path-check-msg { margin: 6px 0 0; font-size: 12px; }
.path-check-msg.ok { color: var(--green); }
.path-check-msg.fail { color: var(--red); }

.version-info {
  border: 1px solid var(--line); border-radius: 10px;
  overflow: hidden;
}
.version-row {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid var(--line);
  font-size: 13px;
}
.version-row:last-child { border-bottom: 0; }
.version-row span { color: var(--muted); }
.version-row code { font-family: var(--mono); color: var(--text); font-size: 13px; }

.settings-foot {
  display: flex; justify-content: flex-end; gap: 8px;
  padding: 14px 22px;
  border-top: 1px solid var(--line);
  background: var(--panel-soft);
}
</style>
