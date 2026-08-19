<script setup lang="ts">
import { storeToRefs } from "pinia";
import TopBar from "./components/layout/TopBar.vue";
import StatusBar from "./components/layout/StatusBar.vue";
import QueueSidebar from "./components/po-list/QueueSidebar.vue";
import DataCheckScreen from "./components/data-view/DataCheckScreen.vue";
import PreviewScreen from "./components/preview/PreviewScreen.vue";
import ExportScreen from "./components/export/ExportScreen.vue";
import LibreOfficePrompt from "./components/common/LibreOfficePrompt.vue";
import PinDialog from "./components/schema/PinDialog.vue";
import { useWorkbench } from "./stores/workbench";
import { useSchemaRepair } from "./stores/schemaRepair";

const wb = useWorkbench();
const repair = useSchemaRepair();
const { activeTab } = storeToRefs(wb);
const selectWorkflowTab = wb.setActiveTab;

async function onPinConfirm(pin: string) {
  try {
    await repair.confirmPin(pin);
  } catch {
    // store 已写入 pinError，弹窗保持打开
  }
}
</script>

<template>
  <div class="app">
    <TopBar />
    <main class="workspace">
      <QueueSidebar />
      <section class="main">
        <nav class="mode-tabs">
          <div class="tabs">
            <button class="tab" :class="{ active: activeTab === 'check' }" @click="selectWorkflowTab('check')">数据检查</button>
            <button class="tab" :class="{ active: activeTab === 'preview' }" @click="selectWorkflowTab('preview')">单据预览</button>
            <button class="tab" :class="{ active: activeTab === 'export' }" @click="selectWorkflowTab('export')">导出确认</button>
          </div>
          <div class="tab-tools">
            <span v-if="activeTab === 'export'" style="color: var(--muted)">导出前请确认单据内容</span>
          </div>
        </nav>
        <div class="content">
          <DataCheckScreen v-if="activeTab === 'check'" />
          <PreviewScreen v-if="activeTab === 'preview'" />
          <ExportScreen v-if="activeTab === 'export'" />
        </div>
      </section>
    </main>
    <StatusBar />
    <LibreOfficePrompt v-if="wb.libreOfficeMissing" />
    <PinDialog
      :open="repair.pinDialogOpen"
      :error-message="repair.pinError"
      @confirm="onPinConfirm"
      @cancel="repair.cancelPin()"
    />
  </div>
</template>

<style scoped>
.app {
  height: 100vh;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) 30px;
  font-family: var(--sans);
  font-size: 13px;
  color: var(--text);
  background: var(--bg);
}
.workspace {
  display: grid;
  grid-template-columns: 292px minmax(0, 1fr);
  min-height: 0;
}
.main {
  min-width: 0;
  min-height: 0;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
}
.mode-tabs {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  background: var(--panel);
  border-bottom: 1px solid var(--line);
}
.tabs { display: flex; gap: 2px; }
.tab {
  height: 44px;
  padding: 0 16px;
  border: 0;
  border-bottom: 3px solid transparent;
  background: transparent;
  color: var(--muted);
  font-weight: 700;
  cursor: pointer;
}
.tab.active {
  color: var(--blue);
  border-bottom-color: var(--blue);
}
.tab-tools {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}
.content {
  min-height: 0;
  overflow: auto;
}

@media (max-width: 900px) {
  .workspace { grid-template-columns: 240px minmax(0, 1fr); }
}
@media (max-width: 560px) {
  .workspace { grid-template-columns: minmax(0, 1fr); }
  .workspace :deep(.queue) { display: none; }
}
</style>
