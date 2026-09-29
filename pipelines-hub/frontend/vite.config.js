import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const backend = process.env.HUB_BACKEND || 'http://localhost:8799'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5188,
    proxy: { '/api': backend, '/mcp': backend },
  },
})
