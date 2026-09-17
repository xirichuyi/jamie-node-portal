import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/postcss';
import { fileURLToPath, URL } from 'node:url';

// Self-hosted static frontend; no Cloudflare/Node runtime on the 1 GB server.
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': fileURLToPath(new URL('.', import.meta.url)) } },
  css: { postcss: { plugins: [tailwindcss()] } },
  build: { outDir: 'dist/portal', emptyOutDir: true },
  server: { host: '127.0.0.1', port: 5173, strictPort: true },
});
