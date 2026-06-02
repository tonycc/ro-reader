<script setup lang="ts">
import TopBar from "./components/layout/TopBar.vue";
import StatusBar from "./components/layout/StatusBar.vue";
import PoList from "./components/po-list/PoList.vue";
import DataGrid from "./components/data-view/DataGrid.vue";
import ChainSelector from "./components/selectors/ChainSelector.vue";
import MonthSelector from "./components/selectors/MonthSelector.vue";
import PreviewPane from "./components/preview/PreviewPane.vue";
</script>

<template>
  <div class="app-shell">
    <TopBar />
    <div class="main-area">
      <aside class="sidebar"><PoList /></aside>
      <section class="center">
        <DataGrid />
        <div class="selectors-row">
          <ChainSelector />
          <MonthSelector />
        </div>
      </section>
      <aside class="preview-col"><PreviewPane /></aside>
    </div>
    <StatusBar />
  </div>
</template>

<style scoped>
.app-shell { display: flex; flex-direction: column; height: 100vh; font-family: var(--font-sans); font-size: var(--text-sm); color: var(--fg-default); background: var(--surface-canvas); }
.main-area { display: flex; flex: 1; overflow: hidden; }
.sidebar { width: 240px; min-width: 200px; max-width: 360px; border-right: 1px solid var(--border-default); overflow-y: auto; background: var(--surface-default); }
.center { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.selectors-row { display: flex; border-top: 1px solid var(--border-default); padding: var(--space-2) var(--space-4); gap: var(--space-4); background: var(--surface-sunken); min-height: 60px; align-items: center; }
.preview-col { width: 480px; min-width: 360px; border-left: 1px solid var(--border-default); overflow-y: auto; background: var(--surface-default); }
</style>
