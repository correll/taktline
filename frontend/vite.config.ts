import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
      '/uploads': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      // Only the share *card image* goes to the backend in dev — `/i/<id>`
      // itself must stay with Vite so the SPA route renders it. In production
      // the backend serves both, and `/i/<id>` returns index.html with the
      // item's Open Graph tags patched in.
      '^/i/[^/]+/card\\.png$': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      // Same shape for the lot QR: `/o/<id>/<token>` must stay with Vite so the
      // SPA renders the tracking page, but the image under it is served by the
      // backend. Without this the <img> gets index.html and the code is a
      // broken-image icon on every lot.
      '^/o/[^/]+/[^/]+/qr\\.svg$': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  resolve: {
    alias: { '@': '/src' },
  },
})
