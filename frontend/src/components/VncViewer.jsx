import { useEffect, useRef } from 'react';

// VncViewer loads noVNC's RFB class directly into the React DOM — no iframe.
// This eliminates all iframe viewport sizing issues and gives full control
// over the canvas container dimensions via React's layout engine.
export default function VncViewer({ style }) {
  const containerRef = useRef(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let destroyed = false;
    let rfb = null;
    let reconnectTimer = null;

    // Build WebSocket URL from current window origin.
    // Works in all environments: Docker nginx, Vite dev proxy, ngrok.
    const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProto}//${window.location.host}/fb-vnc/`;

    function clearContainer() {

      // Remove any leftover noVNC DOM elements from previous sessions
      while (container.firstChild) {
        container.removeChild(container.firstChild);
      }
    }

    async function initVNC() {
      if (destroyed) return;
      clearTimeout(reconnectTimer);
      clearContainer();

      try {
        // new Function trick: creates the import() call at runtime, completely
        // invisible to Vite's bundler static analysis. The browser natively
        // resolves /fb-vnc/core/rfb.js through nginx → metrics-service websockify.
        const dynamicImport = new Function('path', 'return import(path)');
        const RFB = (await dynamicImport('/fb-vnc/core/rfb.js')).default;
        if (destroyed) return;

        rfb = new RFB(container, wsUrl);
        rfb.scaleViewport = false; // Disable noVNC aspect-ratio letterboxing so CSS handles 100% fill
        rfb.viewOnly = false;
        rfb.background = '#000000';

        rfb.addEventListener('connect', () => {
          console.log('[VncViewer] Connected');
        });

        rfb.addEventListener('disconnect', (e) => {
          rfb = null;
          if (!destroyed) {
            if (!e.detail.clean) {
              // VNC server not ready yet — retry in 2s
              reconnectTimer = setTimeout(initVNC, 2000);
            }
          }
        });

        rfb.addEventListener('credentialsrequired', () => {
          rfb?.sendCredentials({ password: '' });
        });

      } catch (err) {
        console.error('[VncViewer] Init error:', err);
        if (!destroyed) {
          reconnectTimer = setTimeout(initVNC, 3000);
        }
      }
    }

    initVNC();

    return () => {
      destroyed = true;
      clearTimeout(reconnectTimer);
      if (rfb) {
        rfb.disconnect();
        rfb = null;
      }
      // Clean up any remaining noVNC DOM elements
      clearContainer();
    };
  }, []); // wsUrl is derived inside effect — no deps needed

  return (
    <div
      ref={containerRef}
      className="vnc-viewer-container"
      style={{
        width: '100%',
        height: '100%',
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        overflow: 'hidden',
        background: '#000',
        ...style,
      }}
    >
      <style>{`
        .vnc-viewer-container {
          position: absolute !important;
          top: 0 !important;
          left: 0 !important;
          right: 0 !important;
          bottom: 0 !important;
          width: 100% !important;
          height: 100% !important;
          overflow: hidden !important;
        }
        .vnc-viewer-container > div,
        .vnc-viewer-container canvas {
          position: absolute !important;
          top: 0 !important;
          left: 0 !important;
          right: 0 !important;
          bottom: 0 !important;
          width: 100% !important;
          height: 100% !important;
          object-fit: fill !important;
          margin: 0 !important;
          padding: 0 !important;
          outline: none !important;
          display: block !important;
          box-sizing: border-box !important;
        }
      `}</style>
    </div>
  );
}




