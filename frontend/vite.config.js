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
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/recharts')) {
            return 'charts';
          }
          if (id.includes('node_modules/lucide-react')) {
            return 'icons';
          }
          if (id.includes('node_modules/@xterm') || id.includes('node_modules/xterm')) {
            return 'terminal';
          }
          if (id.includes('node_modules/react') || id.includes('node_modules/react-dom') || id.includes('node_modules/react-router-dom') || id.includes('node_modules/axios')) {
            return 'vendor';
          }
        }
      }
    }
  }
})
