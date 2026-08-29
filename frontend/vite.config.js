import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      // Proxy /fb-vnc/ to websockify (port 6080) for local dev VNC access.
      // ws:true enables WebSocket proxying required by noVNC.
      '/fb-vnc': {
        target: 'http://localhost:6080',
        changeOrigin: true,
        ws: true,
        rewrite: (path) => path.replace(/^\/fb-vnc/, ''),
      },
      '/websockify': {
        target: 'http://localhost:6080',
        changeOrigin: true,
        ws: true,
      }
    }
  },
  build: {
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        manualChunks(id) {
          // 1. Phân tách WebGL Three.js, React Globe & Space Engine (Tải riêng cho /map)
          if (
            id.includes('node_modules/three') ||
            id.includes('node_modules/react-globe.gl') ||
            id.includes('node_modules/three-globe') ||
            id.includes('node_modules/three-conic-polygon-geometry') ||
            id.includes('node_modules/three-geojson-geometry') ||
            id.includes('node_modules/kapsule') ||
            id.includes('node_modules/accessor-fn') ||
            id.includes('node_modules/satellite.js') ||
            id.includes('node_modules/topojson-client') ||
            id.includes('node_modules/d3-geo')
          ) {
            return 'globe-3d';
          }

          // 2. Biểu đồ Recharts & D3 Data Visualization (Tải riêng cho Dashboard)
          if (
            id.includes('node_modules/recharts') ||
            id.includes('node_modules/victory-vendor') ||
            id.includes('node_modules/d3-')
          ) {
            return 'charts';
          }

          // 3. Icon Pack Lucide
          if (id.includes('node_modules/lucide-react')) {
            return 'icons';
          }

          // 4. Web Terminal Emulator (Xterm.js)
          if (id.includes('node_modules/@xterm') || id.includes('node_modules/xterm')) {
            return 'terminal';
          }

          // 5. noVNC Canvas Client
          if (id.includes('node_modules/@novnc') || id.includes('node_modules/novnc')) {
            return 'vnc';
          }

          // 6. Core React, React-DOM, Router & Axios (Tải ban đầu siêu nhẹ)
          if (
            id.includes('node_modules/react/') ||
            id.includes('node_modules/react-dom/') ||
            id.includes('node_modules/react-router/') ||
            id.includes('node_modules/react-router-dom/') ||
            id.includes('node_modules/react-is/') ||
            id.includes('node_modules/axios/') ||
            id.includes('node_modules/scheduler/')
          ) {
            return 'react-core';
          }
        }
      }
    }
  }
})
