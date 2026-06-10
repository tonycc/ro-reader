import { createApp } from "vue";
import { createPinia } from "pinia";
import App from "./App.vue";
import { useWorkbench } from "./stores/workbench";
import "./styles/tokens.css";

const app = createApp(App);
const pinia = createPinia();
app.use(pinia);
app.mount("#app");

if (import.meta.env.DEV || import.meta.env.MODE === "test") {
  // Expose for E2E tests (bypass prompt() dialog which is unreliable in headless browsers).
  (window as any).__workbench__ = {
    openSession: (path: string) => useWorkbench(pinia).openSession(path),
  };
}
