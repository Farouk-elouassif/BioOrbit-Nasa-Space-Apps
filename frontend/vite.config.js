import { defineConfig } from 'vite';

// Server-side proxy: no ingestion secrets or cross-origin access needed in the browser.
const proxy = { '/api': { target: process.env.BIOORBIT_BACKEND_URL || 'https://requests-curriculum-organisation-ace.trycloudflare.com', changeOrigin: true } };
export default defineConfig({ server: { proxy }, preview: { proxy }, build: { rollupOptions: { output: { manualChunks(id) {
  if (id.includes('/three/examples/')) return 'three-controls';
  if (id.includes('/three/')) return 'three-renderer';
} } } } });
