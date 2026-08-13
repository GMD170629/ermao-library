import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    proxy: {
      '/publication-api': {
        target: 'http://127.0.0.1:8787',
        changeOrigin: false,
        rewrite: (path) => path.replace(/^\/publication-api/, '')
      }
    }
  },
  preview: {
    proxy: {
      '/publication-api': {
        target: 'http://127.0.0.1:8787',
        changeOrigin: false,
        rewrite: (path) => path.replace(/^\/publication-api/, '')
      }
    }
  }
});
