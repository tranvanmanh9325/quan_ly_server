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
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            // 1. Phân tách WebGL Three.js, React Globe & Space Engine (Tải riêng cho /map)
            {
              name: 'globe-3d',
              test: /node_modules[\\/](?:three|react-globe\.gl|three-globe|three-conic-polygon-geometry|three-geojson-geometry|kapsule|accessor-fn|satellite\.js|topojson-client|d3-geo)/,
              priority: 50,
            },
            // 2. Biểu đồ Recharts & D3 Data Visualization (Tải riêng cho Dashboard)
            {
              name: 'charts',
              test: /node_modules[\\/](?:recharts|victory-vendor|d3-)/,
              priority: 40,
            },
            // 3. Icon Pack Lucide
            {
              name: 'icons',
              test: /node_modules[\\/]lucide-react/,
              priority: 30,
            },
            // 4. Web Terminal Emulator (Xterm.js)
            {
              name: 'terminal',
              test: /node_modules[\\/](?:@xterm|xterm)/,
              priority: 25,
            },
            // 5. noVNC Canvas Client
            {
              name: 'vnc',
              test: /node_modules[\\/](?:@novnc|novnc)/,
              priority: 25,
            },
            // 6. Core React, React-DOM, Router & Axios (Tải ban đầu siêu nhẹ)
            {
              name: 'react-core',
              test: /node_modules[\\/](?:react|react-dom|react-router|react-router-dom|react-is|axios|scheduler)/,
              priority: 20,
            },
          ],
        },
      },
    },
  }
})
