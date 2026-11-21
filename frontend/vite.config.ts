import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// The browser talks only to this origin; /api is proxied to Django so the
// session and CSRF cookies are same-origin (no CORS, no tokens in JavaScript).
const backendUrl = process.env.BACKEND_URL ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': { target: backendUrl, changeOrigin: false },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
