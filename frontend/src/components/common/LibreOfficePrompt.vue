<script setup lang="ts">
import { onBeforeUnmount, onMounted } from "vue";
import { useWorkbench } from "../../stores/workbench";

const wb = useWorkbench();

const DOWNLOAD_URL = "https://www.libreoffice.org/download/";

function close() {
  wb.dismissLibreOfficePrompt();
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === "Escape") close();
}

onMounted(() => window.addEventListener("keydown", onKeydown));
onBeforeUnmount(() => window.removeEventListener("keydown", onKeydown));
</script>

<template>
  <div class="lo-backdrop" @click.self="close">
    <div class="lo-card" role="dialog" aria-modal="true" aria-labelledby="lo-title">
      <div class="lo-icon" aria-hidden="true">📄</div>
      <h2 id="lo-title" class="lo-title">需要安装 LibreOffice</h2>
      <p class="lo-body">
        导出 PDF 需要本机安装 <strong>LibreOffice</strong>：单据先按 Excel 模板渲染，
        再由 LibreOffice 转换为 PDF，以保证版式与 Excel 完全一致。
        当前未检测到，安装后重试即可。
      </p>
      <p class="lo-note">Excel 导出不受影响；已安装却仍提示时，可设置环境变量
        <code>RO_SOFFICE_PATH</code> 指向 soffice 可执行文件。</p>
      <div class="lo-actions">
        <button class="lo-btn lo-secondary" @click="close">关闭</button>
        <a
          class="lo-btn lo-primary"
          :href="DOWNLOAD_URL"
          target="_blank"
          rel="noopener noreferrer"
          @click="close"
        >前往下载</a>
      </div>
    </div>
  </div>
</template>

<style scoped>
.lo-backdrop {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  background: rgba(16, 24, 40, 0.45);
}
.lo-card {
  width: 100%;
  max-width: 420px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  box-shadow: 0 12px 40px rgba(16, 24, 40, 0.24);
  padding: 24px;
  color: var(--text);
}
.lo-icon { font-size: 32px; line-height: 1; margin-bottom: 8px; }
.lo-title { margin: 0 0 10px; font-size: 16px; font-weight: 700; }
.lo-body { margin: 0 0 10px; font-size: 13px; line-height: 1.6; color: var(--text); }
.lo-note { margin: 0 0 18px; font-size: 12px; line-height: 1.55; color: var(--muted); }
.lo-note code {
  font-family: var(--mono);
  background: var(--panel-soft);
  border: 1px solid var(--line);
  border-radius: 4px;
  padding: 0 4px;
}
.lo-actions { display: flex; justify-content: flex-end; gap: 8px; }
.lo-btn {
  height: 34px;
  padding: 0 16px;
  display: inline-flex;
  align-items: center;
  border-radius: var(--radius-sm);
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  text-decoration: none;
}
.lo-secondary {
  border: 1px solid var(--line-strong);
  background: var(--panel);
  color: var(--muted);
}
.lo-primary {
  border: 1px solid var(--blue);
  background: var(--blue);
  color: #fff;
}
</style>
