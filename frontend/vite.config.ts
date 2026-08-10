import { readFileSync } from 'node:fs'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const apiTarget = process.env.RO_WORKBENCH_API_TARGET ?? "http://127.0.0.1:54321"
const releaseVersion = readFileSync(new URL("../VERSION", import.meta.url), "utf8").trim()

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  define: {
    "import.meta.env.VITE_APP_VERSION": JSON.stringify(releaseVersion),
  },
  server: {
    port: 6173,
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
})
