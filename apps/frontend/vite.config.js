import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Default dev API target; can be overridden by VITE_API_PROXY_TARGET.
const API_TARGET = process.env.VITE_API_PROXY_TARGET || 'http://localhost:8001';

export default defineConfig({
  plugins: [react()],
  server: {
    // Dev-only proxy: keeps the frontend bundle untouched while routing
    // /api and /voice to the FastAPI backend. Without this proxy, the
    // dashboard's relative /api/v1/... requests would hit Vite's
    // index.html and silently fall back to an empty payload.
    proxy: {
      '/api':    { target: API_TARGET, changeOrigin: true },
      '/voice':  { target: API_TARGET, changeOrigin: true },
      '/health': { target: API_TARGET, changeOrigin: true },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.js'],
  },
});
