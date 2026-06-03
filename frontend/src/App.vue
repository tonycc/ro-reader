<script setup lang="ts">
import TopBar from "./components/layout/TopBar.vue";
import StatusBar from "./components/layout/StatusBar.vue";
import PoList from "./components/po-list/PoList.vue";
import DataGrid from "./components/data-view/DataGrid.vue";
import PreviewPane from "./components/preview/PreviewPane.vue";
</script>

<template>
  <div class="app-shell">
    <TopBar />
    <div class="main-area">
      <aside class="sidebar"><PoList /></aside>
      <section class="center"><DataGrid /></section>
      <aside class="preview-col"><PreviewPane /></aside>
    </div>
    <StatusBar />
  </div>
</template>

<style scoped>
.app-shell { display: flex; flex-direction: column; height: 100vh; font-family: var(--font-sans); font-size: var(--text-sm); color: var(--fg-default); background: var(--surface-canvas); }
.main-area { display: flex; flex: 1; overflow: hidden; }
.sidebar { width: 220px; min-width: 180px; max-width: 320px; border-right: 1px solid var(--border-default); overflow-y: auto; background: var(--surface-default); flex-shrink: 0; }
.center { flex: 1; display: flex; flex-direction: column; overflow: hidden; min-width: 300px; }
.preview-col { flex: 1.6; min-width: 480px; max-width: 900px; border-left: 1px solid var(--border-default); overflow-y: auto; background: var(--surface-default); }
</style>
