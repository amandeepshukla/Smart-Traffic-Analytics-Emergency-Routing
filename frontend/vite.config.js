import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In development the backend runs on :8000 — proxy API + websocket so no CORS setup is needed.
const BACKEND = process.env.VITE_DEV_BACKEND || 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: BACKEND, changeOrigin: true },
      '/ws': { target: BACKEND.replace(/^http/, 'ws'), ws: true },
    },
  },
})
