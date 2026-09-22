import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { compression } from 'vite-plugin-compression2'
import { visualizer } from 'rollup-plugin-visualizer'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    react(),
    // Pre-compress assets with Brotli (served by nginx with brotli_static on)
    compression({
      algorithm: 'brotliCompress',
      threshold: 1024, // Only compress files > 1KB
      deleteOriginalAssets: false,
    }),
    // Gzip fallback for browsers without Brotli support
    compression({
      algorithm: 'gzip',
      threshold: 1024,
      deleteOriginalAssets: false,
    }),
    // Bundle size visualizer — only active when ANALYZE=true
    process.env.ANALYZE && visualizer({
      open: true,
      filename: 'dist/stats.html',
      gzipSize: true,
      brotliSize: true,
    }),
  ].filter(Boolean),
  server: {
    proxy: {
      '/api/ai': {
        target: 'http://localhost:8084',
        changeOrigin: true,
      },
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
    // Target modern browsers for smaller output (ES2020 features)
    target: 'es2020',
    // Inline small assets as base64 (<= 4KB) to reduce HTTP requests
    assetsInlineLimit: 4096,
    chunkSizeWarningLimit: 600,
    rolldownOptions: {
      output: {
        // Deterministic file naming with content hash for long-term caching
        entryFileNames: 'assets/[name]-[hash].js',
        chunkFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash].[ext]',
        codeSplitting: {
          groups: [
            // 1. WebGL Three.js, React Globe & Space Engine (lazy-loaded for /map)
            {
              name: 'globe-3d',
              test: /node_modules[\\/](?:three|react-globe\.gl|three-globe|three-conic-polygon-geometry|three-geojson-geometry|kapsule|accessor-fn|satellite\.js|topojson-client|d3-geo)/,
              priority: 50,
            },
            // 2. Recharts & D3 Data Visualization (lazy-loaded for Dashboard)
            {
              name: 'charts',
              test: /node_modules[\\/](?:recharts|victory-vendor|d3-)/,
              priority: 40,
            },
            // 3. Lucide Icon Pack (tree-shaken by named imports)
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
            // 6. Core React, React-DOM, Router & Axios (critical first-load bundle)
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
