import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// During development the browser talks only to Vite (port 5173).
// Vite forwards API calls - including the SSE stream - to FastAPI on port 8000,
// so no CORS setup is needed in the browser.
const API_TARGET = process.env.VITE_API_TARGET || 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: API_TARGET, changeOrigin: true },
      '/getTrades': { target: API_TARGET, changeOrigin: true },
    },
  },
});
