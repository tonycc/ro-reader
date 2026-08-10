import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const apiTarget = process.env.RO_WORKBENCH_API_TARGET ?? "http://127.0.0.1:54321"

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
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
