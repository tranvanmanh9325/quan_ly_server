import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { geoOrthographic, geoPath, geoGraticule } from 'd3-geo';
import { feature } from 'topojson-client';
import { SciFiGlobeIcon, SciFiRefreshIcon, SciFiPulseBadge, SciFiPlayIcon, SciFiStopIcon } from '../components/SciFiIcons';

// World Atlas TopoJSON CDN — 110m resolution (public domain, Natural Earth)
const WORLD_ATLAS_URL = 'https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json';

export default function WorldMapPage() {
  const [geoData, setGeoData] = useState({ server: null, connections: [] });
  const [worldGeo, setWorldGeo] = useState(null);
  const [loading, setLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState(null);
  const [selectedNode, setSelectedNode] = useState(null);
  const [autoRotate, setAutoRotate] = useState(true);
  const [rotationSpeed, setRotationSpeed] = useState(0.006);
  // Track drag state separately for cursor styling in JSX (refs cannot be read during render)
  const [isDragging, setIsDragging] = useState(false);

  const canvasRef = useRef(null);
  const isDraggingRef = useRef(false);
  const lastMousePosRef = useRef({ x: 0, y: 0 });
  // d3-geo rotation state: [lambda (yaw), phi (pitch), gamma (roll)]
  // Initial: centered on Vietnam/Southeast Asia (lon=105.85 → negate → -105.85)
  const rotRef = useRef([-105.85, -16.0, 0]);

  // Auto-focus globe: when connections arrive, center globe on the average
  // position between server and all client nodes so all pins are visible.
  useEffect(() => {
    const conns = geoData.connections || [];
    if (conns.length === 0 || !geoData.server) return;

    // Compute centroid of all points (server + clients)
    const allLats = [parseFloat(geoData.server.lat) || 0, ...conns.map(c => parseFloat(c.lat) || 0)];
    const allLons = [parseFloat(geoData.server.lon) || 0, ...conns.map(c => parseFloat(c.lon) || 0)];
    const avgLat = allLats.reduce((s, v) => s + v, 0) / allLats.length;
    const avgLon = allLons.reduce((s, v) => s + v, 0) / allLons.length;

    // d3-geo: rotation[0] = -longitude, rotation[1] = -latitude
    rotRef.current = [-avgLon, -avgLat + 5, 0]; // +5 offset to shift globe slightly south
  }, [geoData.connections?.length]); // re-focus only when connection count changes

  // --- Data Fetching ---

  // Fetch World Atlas TopoJSON on mount
  useEffect(() => {
    fetch(WORLD_ATLAS_URL)
      .then(res => res.json())
      .then(topo => {
        const countries = feature(topo, topo.objects.countries);
        const land = feature(topo, topo.objects.land);
        setWorldGeo({ countries, land });
      })
      .catch(err => console.error('Failed to load world atlas:', err));
  }, []);

  // Fetch Geolocation API
  useEffect(() => {
    let isMounted = true;
    const loadData = async () => {
      try {
        const res = await axios.get('/api/metrics/geolocation');
        if (!isMounted) return;
        if (res.data) {
          setGeoData({
            server: res.data.server || null,
            connections: res.data.connections || []
          });
        }
      } catch (err) {
        if (isMounted) setErrorMsg(`Failed to fetch geolocation: ${err.message}`);
      } finally {
        if (isMounted) setLoading(false);
      }
    };
    loadData();
    const interval = setInterval(loadData, 30000);
    return () => { isMounted = false; clearInterval(interval); };
  }, []);

  /**
   * Client self-registration: browser sends GPS coordinates to server.
   * Server extracts the real IP server-side (from X-Forwarded-For/X-Real-IP),
   * and does its own city/ISP lookup via SSH curl (supports both IPv4 and IPv6).
   * Frontend only needs to provide GPS coords for precise pin placement.
   */
  useEffect(() => {
    const doCheckin = async () => {
      try {
        // Step 1: Get GPS coords (prompt permission if needed)
        const getGps = () => new Promise((resolve) => {
          if (!navigator.geolocation) { resolve({ lat: 0, lon: 0 }); return; }
          navigator.geolocation.getCurrentPosition(
            (pos) => resolve({ lat: pos.coords.latitude, lon: pos.coords.longitude }),
            ()    => resolve({ lat: 0, lon: 0 }),
            { timeout: 8000, maximumAge: 300000 }
          );
        });
        const { lat, lon } = await getGps();

        // Step 2: POST checkin — server extracts real IP and echoes it back.
        // City/ISP resolved server-side via SSH curl (supports IPv4 + IPv6).
        await axios.post('/api/metrics/client-checkin', { lat, lon });

        // Step 3: Re-fetch map so this client appears immediately
        const res = await axios.get('/api/metrics/geolocation');
        if (res.data) {
          setGeoData({ server: res.data.server || null, connections: res.data.connections || [] });
        }
      } catch (err) {
        console.warn('[WorldMap] Client checkin failed (non-critical):', err.message);
      }
    };

    doCheckin();
    // Re-checkin every 4 minutes to stay within the 5-minute TTL
    const interval = setInterval(doCheckin, 4 * 60 * 1000);
    return () => clearInterval(interval);
  }, []);


  const fetchGeolocationData = async () => {
    setLoading(true);
    setErrorMsg(null);
    try {
      const res = await axios.get('/api/metrics/geolocation');
      if (res.data) {
        setGeoData({ server: res.data.server || null, connections: res.data.connections || [] });
      }
    } catch (err) {
      setErrorMsg(`Failed to fetch geolocation: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  // --- 3D Canvas Rendering Engine ---
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !worldGeo) return;
    const ctx = canvas.getContext('2d');
    let animFrameId;
    let pulseTime = 0;

    const sLat = parseFloat(geoData.server?.lat) || 10.8231;
    const sLon = parseFloat(geoData.server?.lon) || 106.6297;

    const render = () => {
      const W = canvas.clientWidth;
      const H = canvas.clientHeight;
      if (canvas.width !== W || canvas.height !== H) {
        canvas.width = W;
        canvas.height = H;
      }
      ctx.clearRect(0, 0, W, H);

      // Auto rotate
      if (autoRotate && !isDraggingRef.current) {
        rotRef.current[0] -= rotationSpeed * (180 / Math.PI);
      }

      const radius = Math.min(W, H) * 0.42;

      const projection = geoOrthographic()
        .scale(radius)
        .translate([W / 2, H / 2])
        .clipAngle(90)
        .rotate(rotRef.current);

      const pathGen = geoPath(projection, ctx);
      const graticule = geoGraticule();

      pulseTime += 0.035;

      // 1. Atmosphere Glow
      const cx = W / 2, cy = H / 2;
      const atmoGrad = ctx.createRadialGradient(cx, cy, radius * 0.88, cx, cy, radius * 1.25);
      atmoGrad.addColorStop(0, 'rgba(0, 243, 255, 0.07)');
      atmoGrad.addColorStop(0.6, 'rgba(0, 255, 157, 0.03)');
      atmoGrad.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.fillStyle = atmoGrad;
      ctx.beginPath();
      ctx.arc(cx, cy, radius * 1.25, 0, Math.PI * 2);
      ctx.fill();

      // 2. Ocean fill (sphere background)
      ctx.beginPath();
      pathGen({ type: 'Sphere' });
      ctx.fillStyle = '#030d1a';
      ctx.fill();

      // 3. Sphere border
      ctx.beginPath();
      pathGen({ type: 'Sphere' });
      ctx.strokeStyle = 'rgba(0, 243, 255, 0.3)';
      ctx.lineWidth = 1.5;
      ctx.stroke();

      // 4. Graticule grid lines
      ctx.beginPath();
      pathGen(graticule());
      ctx.strokeStyle = 'rgba(0, 243, 255, 0.06)';
      ctx.lineWidth = 0.6;
      ctx.stroke();

      // 5. Land fill — actual country borders
      if (worldGeo.land) {
        ctx.beginPath();
        pathGen(worldGeo.land);
        ctx.fillStyle = 'rgba(0, 30, 50, 0.92)';
        ctx.fill();
      }

      // 6. Country borders
      if (worldGeo.countries) {
        worldGeo.countries.features.forEach(feat => {
          ctx.beginPath();
          pathGen(feat);
          ctx.strokeStyle = 'rgba(0, 243, 255, 0.3)';
          ctx.lineWidth = 0.7;
          ctx.stroke();
        });
      }

      // 7. Draw 3D Elevated Laser Arcs between clients and server
      const clients = geoData.connections || [];
      clients.forEach(client => {
        const parsedLat = parseFloat(client.lat);
        const parsedLon = parseFloat(client.lon);
        // Only use GPS coords if they are real (non-zero) — 0,0 means no GPS
        const hasGps = Number.isFinite(parsedLat) && Number.isFinite(parsedLon)
                    && (parsedLat !== 0 || parsedLon !== 0);
        const cLat = hasGps ? parsedLat : sLat;
        const cLon = hasGps ? parsedLon : sLon;

        // Build great-circle arc with elevation via interpolated midpoints
        const steps = 40;
        let prevPt = null;
        for (let i = 0; i <= steps; i++) {
          const t = i / steps;
          // Linear interpolation lat/lon
          const iLat = cLat + (sLat - cLat) * t;
          const iLon = cLon + (sLon - cLon) * t;
          // Elevation: lift midpoints above sphere
          const lift = Math.sin(t * Math.PI) * 18; // degrees above surface
          const ptProj = projection([iLon, iLat + lift * (lift / radius)]);
          if (ptProj) {
            if (prevPt) {
              ctx.beginPath();
              ctx.moveTo(prevPt[0], prevPt[1]);
              ctx.lineTo(ptProj[0], ptProj[1]);
              ctx.strokeStyle = `rgba(0, 243, 255, ${0.5 + 0.3 * Math.sin(pulseTime + i * 0.2)})`;
              ctx.lineWidth = 1.6;
              ctx.setLineDash([6, 4]);
              ctx.lineDashOffset = -pulseTime * 18;
              ctx.stroke();
              ctx.setLineDash([]);
            }
            prevPt = ptProj;
          } else {
            prevPt = null; // behind the globe
          }
        }

        // --- Client Teardrop Pin ---
        const clientProj = projection([cLon, cLat]);
        if (clientProj) {
          const [px, py] = clientProj;
          const pinH = 20; // total pin height
          const pinR = 7;  // circle head radius
          const circleCy = py - pinH + pinR;

          // Sonar ripple (single ring, fading out)
          const rippleR = pinR + 6 + Math.sin(pulseTime * 2.5 + cLon) * 4;
          const rippleAlpha = 0.6 - (Math.sin(pulseTime * 2.5 + cLon) * 0.5 + 0.5) * 0.45;
          ctx.beginPath();
          ctx.arc(px, circleCy, rippleR, 0, Math.PI * 2);
          ctx.strokeStyle = `rgba(0, 243, 255, ${rippleAlpha})`;
          ctx.lineWidth = 1.2;
          ctx.stroke();

          // Pin shadow glow (drawn first, slightly larger, blurred)
          ctx.shadowColor = '#00f3ff';
          ctx.shadowBlur = 14;

          // Teardrop body path
          ctx.beginPath();
          ctx.arc(px, circleCy, pinR, Math.PI * 0.2, Math.PI * 0.8, true); // top arc
          ctx.bezierCurveTo(
            px - pinR * 0.6, py - pinH * 0.2,
            px, py + 2,
            px, py + 2
          );
          ctx.bezierCurveTo(
            px, py + 2,
            px + pinR * 0.6, py - pinH * 0.2,
            px + pinR, circleCy + pinR * Math.sin(Math.PI * 0.8)
          );
          ctx.fillStyle = 'rgba(0, 188, 220, 0.85)';
          ctx.fill();
          ctx.strokeStyle = '#00f3ff';
          ctx.lineWidth = 1.5;
          ctx.stroke();
          ctx.shadowBlur = 0;

          // Inner white dot (light source)
          ctx.beginPath();
          ctx.arc(px, circleCy, pinR * 0.32, 0, Math.PI * 2);
          ctx.fillStyle = 'rgba(255, 255, 255, 0.9)';
          ctx.fill();

          // Label: prefer real city, skip "Unknown", fallback to last IP octet pair
          const rawCity = (client.city || '').trim();
          const labelCity = rawCity && rawCity !== 'Unknown' && rawCity !== 'Internal LAN'
            ? rawCity
            : (client.ip ? client.ip.split('.').slice(0, 2).join('.') + '.*' : 'CLIENT');
          ctx.fillStyle = '#a8e8ff';
          ctx.font = '9px "Share Tech Mono"';
          ctx.fillText(`[${labelCity}]`, px + pinR + 4, circleCy + 3);
        }
      });

      // 8. Server HQ — Large Teardrop Pin + Crosshair + 3-ring Sonar
      const serverProj = projection([sLon, sLat]);
      if (serverProj) {
        const [sx, sy] = serverProj;
        const sPinH = 30;
        const sPinR = 11;
        const sCy = sy - sPinH + sPinR;

        // 3 sonar ripple rings radiating outward
        for (let ring = 0; ring < 3; ring++) {
          const phase = (pulseTime * 1.2 + ring * 1.1) % (Math.PI * 2);
          const ringR = sPinR + 10 + ring * 12 + Math.sin(phase) * 5;
          const ringAlpha = Math.max(0, 0.65 - ring * 0.22 - Math.sin(phase) * 0.15);
          ctx.beginPath();
          ctx.arc(sx, sCy, ringR, 0, Math.PI * 2);
          ctx.strokeStyle = `rgba(0, 255, 157, ${ringAlpha})`;
          ctx.lineWidth = ring === 0 ? 1.5 : 1;
          ctx.stroke();
        }

        // Pin glow shadow
        ctx.shadowColor = '#00ff9d';
        ctx.shadowBlur = 22;

        // Server teardrop body
        ctx.beginPath();
        ctx.arc(sx, sCy, sPinR, Math.PI * 0.2, Math.PI * 0.8, true);
        ctx.bezierCurveTo(
          sx - sPinR * 0.6, sy - sPinH * 0.2,
          sx, sy + 3,
          sx, sy + 3
        );
        ctx.bezierCurveTo(
          sx, sy + 3,
          sx + sPinR * 0.6, sy - sPinH * 0.2,
          sx + sPinR, sCy + sPinR * Math.sin(Math.PI * 0.8)
        );
        ctx.fillStyle = 'rgba(0, 180, 100, 0.9)';
        ctx.fill();
        ctx.strokeStyle = '#00ff9d';
        ctx.lineWidth = 2;
        ctx.stroke();
        ctx.shadowBlur = 0;

        // Crosshair inside the circle head
        const chSize = sPinR * 0.65;
        ctx.strokeStyle = 'rgba(255,255,255,0.85)';
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.moveTo(sx - chSize, sCy);
        ctx.lineTo(sx + chSize, sCy);
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(sx, sCy - chSize);
        ctx.lineTo(sx, sCy + chSize);
        ctx.stroke();

        // Center dot of crosshair
        ctx.beginPath();
        ctx.arc(sx, sCy, 2.5, 0, Math.PI * 2);
        ctx.fillStyle = '#fff';
        ctx.fill();

        // HQ Label
        ctx.shadowColor = '#00ff9d';
        ctx.shadowBlur = 8;
        ctx.fillStyle = '#00ff9d';
        ctx.font = 'bold 10px "Share Tech Mono"';
        ctx.fillText('[HQ] SERVER', sx + sPinR + 5, sCy + 4);
        ctx.shadowBlur = 0;
      }

      animFrameId = requestAnimationFrame(render);
    };

    render();
    return () => cancelAnimationFrame(animFrameId);
  }, [worldGeo, geoData, autoRotate, rotationSpeed]);

  // --- Mouse Interaction ---
  const handleMouseDown = (e) => {
    isDraggingRef.current = true;
    setIsDragging(true);
    lastMousePosRef.current = { x: e.clientX, y: e.clientY };
  };

  const handleMouseMove = (e) => {
    if (!isDraggingRef.current) return;
    const dx = e.clientX - lastMousePosRef.current.x;
    const dy = e.clientY - lastMousePosRef.current.y;
    // Sensitivity factor — maps pixel delta to degree rotation
    const sensitivity = 0.25;
    rotRef.current[0] -= dx * sensitivity;
    rotRef.current[1] = Math.max(-90, Math.min(90, rotRef.current[1] + dy * sensitivity));
    lastMousePosRef.current = { x: e.clientX, y: e.clientY };
  };

  const handleMouseUp = () => {
    isDraggingRef.current = false;
    setIsDragging(false);
  };

  const resetCamera = () => { rotRef.current = [-105.85, -16.0, 0]; };

  const serverInfo = geoData.server || {};
  const connections = geoData.connections || [];

  return (
    <div style={{ padding: '20px', height: '100%', display: 'flex', flexDirection: 'column', gap: '16px', overflowY: 'auto' }}>

      {/* Error Banner */}
      {errorMsg && (
        <div style={{
          background: 'rgba(255, 0, 85, 0.15)', border: '1px solid var(--accent-pink)',
          color: 'var(--accent-pink)', padding: '10px 16px', borderRadius: '4px',
          fontFamily: 'Share Tech Mono', fontSize: '0.85rem', fontWeight: 'bold',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center'
        }}>
          <span>⚠️ {errorMsg}</span>
          <button onClick={() => setErrorMsg(null)} style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer' }}>✕</button>
        </div>
      )}

      {/* Header Bar */}
      <div className="glass-panel" style={{ padding: '16px 20px', display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', gap: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <SciFiGlobeIcon size={28} color="var(--accent-cyan)" />
          <div>
            <h2 style={{ margin: 0, fontSize: '1.2rem', letterSpacing: '1px', color: '#fff', fontFamily: 'Rajdhani, sans-serif', textShadow: '0 0 10px var(--accent-cyan)' }}>
              INTERACTIVE 3D CYBERPUNK GEOLOCATION GLOBE
            </h2>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono' }}>
              REAL-WORLD COUNTRY BORDERS · 360° DRAG ROTATION · LIVE LASER TELEMETRY
            </span>
          </div>
        </div>
        <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
          <button onClick={() => setAutoRotate(!autoRotate)} style={{
            background: autoRotate ? 'rgba(0, 255, 157, 0.15)' : 'rgba(255,255,255,0.08)',
            border: autoRotate ? '1px solid var(--accent-green)' : '1px solid rgba(255,255,255,0.2)',
            color: autoRotate ? 'var(--accent-green)' : '#ccc', padding: '6px 12px',
            fontFamily: 'Share Tech Mono', fontSize: '0.78rem', fontWeight: 'bold',
            cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px', borderRadius: '3px'
          }}>
            {autoRotate ? <SciFiStopIcon size={12} color="var(--accent-green)" /> : <SciFiPlayIcon size={12} color="#ccc" />}
            <span>AUTO-ROTATE: {autoRotate ? 'ON' : 'OFF'}</span>
          </button>

          <button onClick={() => setRotationSpeed(prev => prev === 0.006 ? 0.014 : prev === 0.014 ? 0.025 : 0.006)} style={{
            background: 'rgba(0, 243, 255, 0.1)', border: '1px solid var(--accent-cyan)',
            color: 'var(--accent-cyan)', padding: '6px 12px', fontFamily: 'Share Tech Mono',
            fontSize: '0.78rem', fontWeight: 'bold', cursor: 'pointer', borderRadius: '3px'
          }}>
            SPEED: {rotationSpeed === 0.006 ? '1X' : rotationSpeed === 0.014 ? '2X' : '3X'}
          </button>

          <button onClick={resetCamera} style={{
            background: 'rgba(0, 243, 255, 0.1)', border: '1px solid var(--accent-cyan)',
            color: 'var(--accent-cyan)', padding: '6px 12px', fontFamily: 'Share Tech Mono',
            fontSize: '0.78rem', fontWeight: 'bold', cursor: 'pointer', borderRadius: '3px'
          }}>RESET VIEW</button>

          <button onClick={fetchGeolocationData} disabled={loading} style={{
            background: 'rgba(0, 243, 255, 0.1)', border: '1px solid var(--accent-cyan)',
            color: 'var(--accent-cyan)', padding: '6px 14px', fontFamily: 'Share Tech Mono',
            fontSize: '0.8rem', fontWeight: 'bold', cursor: 'pointer',
            display: 'flex', alignItems: 'center', gap: '6px', borderRadius: '3px'
          }}>
            <SciFiRefreshIcon size={14} color="var(--accent-cyan)" />
            <span>{loading ? 'REFRESHING...' : 'RE-SCAN NODES'}</span>
          </button>
        </div>
      </div>

      {/* Main Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 2.5fr) minmax(300px, 1fr)', gap: '16px', flex: 1 }}>

        {/* 3D Globe Canvas Panel */}
        <div className="glass-panel" style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px', minHeight: '520px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid rgba(0,243,255,0.15)', paddingBottom: '8px' }}>
            <div style={{ fontFamily: 'Share Tech Mono', fontSize: '0.85rem', color: 'var(--accent-cyan)', fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: 'var(--accent-green)', boxShadow: '0 0 8px var(--accent-green)' }} />
              REAL-WORLD 3D GLOBE [DRAG TO ORBIT 360°]
            </div>
            <div style={{ fontFamily: 'Share Tech Mono', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
              HQ: <span style={{ color: 'var(--accent-green)' }}>{serverInfo.city || 'HCM'}, {serverInfo.country || 'VN'}</span>
            </div>
          </div>

          <div style={{ flex: 1, position: 'relative', minHeight: '440px', background: '#020d1a', borderRadius: '4px', border: '1px solid rgba(0,243,255,0.25)', overflow: 'hidden', cursor: isDragging ? 'grabbing' : 'grab' }}>
            <canvas
              ref={canvasRef}
              onMouseDown={handleMouseDown}
              onMouseMove={handleMouseMove}
              onMouseUp={handleMouseUp}
              onMouseLeave={handleMouseUp}
              style={{ width: '100%', height: '100%', display: 'block' }}
            />
            {!worldGeo && (
              <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono', fontSize: '0.85rem' }}>
                LOADING WORLD ATLAS DATA...
              </div>
            )}
            <div style={{ position: 'absolute', bottom: '12px', left: '16px', fontFamily: 'Share Tech Mono', fontSize: '0.72rem', color: 'rgba(255,255,255,0.4)', pointerEvents: 'none' }}>
              ✦ TIP: Drag globe to rotate · Real-world country borders via Natural Earth
            </div>
          </div>

          <div style={{ display: 'flex', gap: '20px', fontSize: '0.78rem', fontFamily: 'Share Tech Mono', color: 'var(--text-secondary)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ width: '10px', height: '10px', borderRadius: '50%', background: 'var(--accent-green)', display: 'inline-block', boxShadow: '0 0 6px var(--accent-green)' }} />
              <span>SERVER HQ</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ width: '10px', height: '10px', borderRadius: '50%', background: 'var(--accent-cyan)', display: 'inline-block', boxShadow: '0 0 6px var(--accent-cyan)' }} />
              <span>CLIENT DEVICE</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ width: '20px', height: '2px', background: 'var(--accent-cyan)', display: 'inline-block' }} />
              <span>LASER ARC</span>
            </div>
          </div>
        </div>

        {/* HUD Panels */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>

          {/* Server Telemetry */}
          <div className="glass-panel" style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <div style={{ fontSize: '0.85rem', color: 'var(--accent-green)', fontFamily: 'Share Tech Mono', fontWeight: 'bold', borderBottom: '1px solid rgba(0, 255, 157, 0.2)', paddingBottom: '6px' }}>
              ✦ SERVER HQ TELEMETRY
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '0.82rem', fontFamily: 'Share Tech Mono' }}>
              {[
                ['IP ADDRESS:', serverInfo.query || 'N/A', '#fff'],
                ['LOCATION:', `${serverInfo.city || 'N/A'}, ${serverInfo.country || 'N/A'}`, 'var(--accent-green)'],
                ['COORDINATES:', `${serverInfo.lat || '?'}°N ${serverInfo.lon || '?'}°E`, '#fff'],
                ['ISP / HOST:', serverInfo.isp || 'N/A', 'var(--accent-cyan)'],
                ['ACTIVE SESSIONS:', `${connections.length} DEVICE(S)`, 'var(--accent-yellow)'],
              ].map(([label, val, color]) => (
                <div key={label} style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: 'var(--text-secondary)' }}>{label}</span>
                  <span style={{ color, fontWeight: 'bold' }}>{val}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Connected Clients */}
          <div className="glass-panel" style={{ flex: 1, padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px', overflow: 'hidden' }}>
            <div style={{ fontSize: '0.85rem', color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono', fontWeight: 'bold', borderBottom: '1px solid rgba(0, 243, 255, 0.2)', paddingBottom: '6px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span>✦ CONNECTED NODES ({connections.length})</span>
              <SciFiPulseBadge size={16} color="var(--accent-cyan)" />
            </div>
            <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {loading && connections.length === 0 ? (
                <div style={{ color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono', fontSize: '0.8rem', textAlign: 'center', padding: '20px' }}>
                  RESOLVING GEOLOCATION MATRIX...
                </div>
              ) : connections.length === 0 ? (
                <div style={{ color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono', fontSize: '0.8rem', textAlign: 'center', padding: '20px' }}>
                  No active external clients connected.
                </div>
              ) : (
                connections.map((conn, idx) => (
                  <div key={idx} onClick={() => setSelectedNode(conn)} style={{
                    background: selectedNode?.ip === conn.ip ? 'rgba(0, 243, 255, 0.15)' : 'rgba(0,0,0,0.4)',
                    border: selectedNode?.ip === conn.ip ? '1px solid var(--accent-cyan)' : '1px solid rgba(0, 243, 255, 0.15)',
                    padding: '10px', borderRadius: '4px', cursor: 'pointer',
                    display: 'flex', flexDirection: 'column', gap: '4px',
                    fontSize: '0.78rem', fontFamily: 'Share Tech Mono'
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', color: '#fff', fontWeight: 'bold' }}>
                      <span>IP: {conn.ip}</span>
                      <span style={{ color: 'var(--accent-green)' }}>{conn.user || 'client'}</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--text-secondary)' }}>
                      <span>LOCATION:</span>
                      <span style={{ color: 'var(--accent-cyan)' }}>{conn.city || 'LAN'}, {conn.country || 'Local'}</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--text-secondary)', fontSize: '0.72rem' }}>
                      <span>TERMINAL / STATE:</span>
                      <span>{conn.terminal || conn.loginTime || 'ACTIVE'}</span>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}