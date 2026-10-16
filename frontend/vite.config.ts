import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [react()],
    server: {
      port: 5173,
      // Forward /api/* to the FastAPI backend during development
      proxy: {
        '/api': env.VITE_PROXY_TARGET || 'http://localhost:8000',
      },
    },
  }
})
