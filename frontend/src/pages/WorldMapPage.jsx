import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import axios from 'axios';
import Globe from 'react-globe.gl';
import { mesh } from 'topojson-client';
import { SciFiGlobeIcon, SciFiRefreshIcon, SciFiPulseBadge, SciFiPlayIcon, SciFiStopIcon } from '../components/SciFiIcons';
import { VIETNAM_MARITIME_ISLANDS } from '../data/vietnamIslandsGeo';

const LOCAL_WORLD_ATLAS_URL = '/data/countries-50m.json';
const CDN_WORLD_ATLAS_URL = 'https://cdn.jsdelivr.net/npm/world-atlas@2/countries-50m.json';
const GLOBE_HEIGHT = 420;

export default function WorldMapPage() {
  const [geoData, setGeoData] = useState({ server: null, connections: [] });
  const [bordersData, setBordersData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState(null);
  const [selectedNode, setSelectedNode] = useState(null);
  const [autoRotate, setAutoRotate] = useState(true);
  const [rotationSpeed, setRotationSpeed] = useState(0.5);

  const globeRef = useRef();
  const globeContainerRef = useRef();

  // --- Load TopoJSON: extract border mesh as line paths (1 geometry vs 241 polygon features) ---
  useEffect(() => {
    const loadTopoData = async () => {
      try {
        let res = await fetch(LOCAL_WORLD_ATLAS_URL);
        if (!res.ok) res = await fetch(CDN_WORLD_ATLAS_URL);
        const topo = await res.json();

        // topojson.mesh with (a,b)=>a!==b gives shared borders only — 1 MultiLineString
        const borderMesh = mesh(topo, topo.objects.countries, (a, b) => a !== b);

        // Convert MultiLineString coordinates into path array for Globe pathsData
        const paths = (borderMesh.coordinates || []).map(coords => ({
          coords: coords.map(([lng, lat]) => [lat, lng]),
        }));
        setBordersData(paths);
      } catch (err) {
        console.error('[Globe] TopoJSON load failed, trying CDN:', err);
        try {
          const res = await fetch(CDN_WORLD_ATLAS_URL);
          const topo = await res.json();
          const borderMesh = mesh(topo, topo.objects.countries, (a, b) => a !== b);
          const paths = (borderMesh.coordinates || []).map(coords => ({
            coords: coords.map(([lng, lat]) => [lat, lng]),
          }));
          setBordersData(paths);
        } catch (cdnErr) {
          console.error('[Globe] All atlas sources failed:', cdnErr);
        }
      }
    };
    loadTopoData();
  }, []);

  // --- Client Check-in ---
  useEffect(() => {
    const doCheckin = async () => {
      try {
        let lat = 0, lon = 0, city = 'Unknown', country = 'Unknown', countryCode = '';
        try {
          const pos = await new Promise((res, rej) =>
            navigator.geolocation.getCurrentPosition(res, rej, { timeout: 5000, maximumAge: 300000 })
          );
          lat = pos.coords.latitude;
          lon = pos.coords.longitude;
        } catch (_) { /* no GPS */ }

        if (lat !== 0 || lon !== 0) {
          try {
            const geo = await axios.get(
              `https://api.bigdatacloud.net/data/reverse-geocode-client?latitude=${lat}&longitude=${lon}&localityLanguage=vi`
            ).then(r => r.data);
            if (geo) {
              const subdivision = (geo.principalSubdivision || '').trim();
              const cityName = (geo.city || geo.locality || '').trim();
              city = subdivision
                ? (cityName && !cityName.toLowerCase().includes(subdivision.toLowerCase()) ? `${cityName}, ${subdivision}` : subdivision)
                : (cityName || 'Unknown');
              country = geo.countryName || 'Vietnam';
              countryCode = geo.countryCode || 'VN';
            }
          } catch (_) { /* non-blocking */ }
        }

        await axios.post('/api/metrics/client-checkin', { lat, lon, city, country, countryCode });
        const res = await axios.get('/api/metrics/geolocation');
        if (res.data) setGeoData({ server: res.data.server || null, connections: res.data.connections || [] });
      } catch (err) {
        console.warn('[WorldMap] Client checkin failed:', err.message);
      }
    };
    doCheckin();
    const interval = setInterval(doCheckin, 4 * 60 * 1000);
    return () => clearInterval(interval);
  }, []);

  const fetchGeolocationData = async () => {
    setLoading(true);
    setErrorMsg(null);
    try {
      const res = await axios.get('/api/metrics/geolocation');
      if (res.data) setGeoData({ server: res.data.server || null, connections: res.data.connections || [] });
    } catch (err) {
      setErrorMsg(`Failed to fetch geolocation: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchGeolocationData(); }, []);

  // --- Sync auto-rotate state to Globe controls ---
  useEffect(() => {
    const ctrl = globeRef.current?.controls();
    if (!ctrl) return;
    ctrl.autoRotate = autoRotate;
    ctrl.autoRotateSpeed = rotationSpeed;
  }, [autoRotate, rotationSpeed]);

  // --- Auto-focus on connections ---
  useEffect(() => {
    if (!globeRef.current || !geoData.server) return;
    const conns = geoData.connections || [];
    if (conns.length === 0) return;
    const allLats = [parseFloat(geoData.server.lat) || 0, ...conns.map(c => parseFloat(c.lat) || 0)];
    const allLons = [parseFloat(geoData.server.lon) || 0, ...conns.map(c => parseFloat(c.lon) || 0)];
    const avgLat = allLats.reduce((s, v) => s + v, 0) / allLats.length;
    const avgLon = allLons.reduce((s, v) => s + v, 0) / allLons.length;
    globeRef.current.pointOfView({ lat: avgLat, lng: avgLon, altitude: 2.2 }, 1000);
  }, [geoData.connections?.length]);

  // --- Arc data ---
  const arcsData = useMemo(() => {
    const sLat = parseFloat(geoData.server?.lat) || 20.98;
    const sLon = parseFloat(geoData.server?.lon) || 105.83;
    return (geoData.connections || []).map((client, idx) => {
      const parsedLat = parseFloat(client.lat);
      const parsedLon = parseFloat(client.lon);
      const hasGps = Number.isFinite(parsedLat) && Number.isFinite(parsedLon)
        && (parsedLat !== 0 || parsedLon !== 0);
      return {
        id: idx,
        startLat: sLat, startLng: sLon,
        endLat: hasGps ? parsedLat : sLat + 0.01,
        endLng: hasGps ? parsedLon : sLon + 0.01,
        client, color: ['#00f3ff', '#00ff9d'],
      };
    });
  }, [geoData]);

  // --- Points data (server + clients + island centers only) ---
  const pointsData = useMemo(() => {
    const points = [];
    const sLat = parseFloat(geoData.server?.lat) || 20.98;
    const sLon = parseFloat(geoData.server?.lon) || 105.83;

    points.push({
      id: 'server', lat: sLat, lng: sLon,
      size: 0.6, color: '#00ff9d', type: 'server',
    });

    (geoData.connections || []).forEach((client, idx) => {
      const parsedLat = parseFloat(client.lat);
      const parsedLon = parseFloat(client.lon);
      const hasGps = Number.isFinite(parsedLat) && Number.isFinite(parsedLon)
        && (parsedLat !== 0 || parsedLon !== 0);
      if (hasGps) {
        points.push({ id: `client-${idx}`, lat: parsedLat, lng: parsedLon, size: 0.35, color: '#00f3ff', type: 'client', client });
      }
    });

    // Only archipelago cluster centers (not sub-islands) to reduce point count
    VIETNAM_MARITIME_ISLANDS.forEach(item => {
      points.push({
        id: item.id, lat: item.lat, lng: item.lon,
        size: item.type === 'archipelago_cluster' ? 0.28 : 0.2,
        color: '#00ff9d', label: item.label, type: 'island',
      });
    });

    return points;
  }, [geoData]);

  // --- Rings: only server HQ (minimize GPU particle emitters) ---
  const ringsData = useMemo(() => {
    const sLat = parseFloat(geoData.server?.lat) || 20.98;
    const sLon = parseFloat(geoData.server?.lon) || 105.83;
    return [{ lat: sLat, lng: sLon, maxR: 3.5, propagationSpeed: 1.2, repeatPeriod: 1000 }];
  }, [geoData.server]);

  const resetCamera = useCallback(() => {
    globeRef.current?.pointOfView({ lat: 16.0, lng: 105.85, altitude: 2.0 }, 800);
  }, []);

  const serverInfo = geoData.server || {};
  const connections = geoData.connections || [];

  const getPointLabel = useCallback((d) => {
    if (d.type === 'server') return `<div style="font-family:'Share Tech Mono',monospace;font-size:11px;color:#00ff9d;background:rgba(2,13,26,0.9);padding:5px 9px;border:1px solid rgba(0,255,157,0.55);border-radius:3px"><b>[HQ]</b> ${serverInfo.city || 'Định Công'}, VN<br/>IP: ${serverInfo.query || 'N/A'}</div>`;
    if (d.type === 'client') return `<div style="font-family:'Share Tech Mono',monospace;font-size:11px;color:#00f3ff;background:rgba(2,13,26,0.9);padding:5px 9px;border:1px solid rgba(0,243,255,0.55);border-radius:3px"><b>[CLIENT]</b><br/>${d.client?.city || d.client?.ip || 'Unknown'}, ${d.client?.country || ''}</div>`;
    if (d.type === 'island') return `<div style="font-family:'Share Tech Mono',monospace;font-size:10px;color:#00ff9d;background:rgba(2,13,26,0.9);padding:3px 7px;border:1px solid rgba(0,255,157,0.35);border-radius:2px">🏝 ${d.label}</div>`;
    return '';
  }, [serverInfo]);

  // --- Globe ready: apply all performance settings at once ---
  const handleGlobeReady = useCallback(() => {
    setLoading(false);
    globeRef.current?.pointOfView({ lat: 16.0, lng: 105.85, altitude: 2.2 }, 0);

    const ctrl = globeRef.current?.controls();
    if (ctrl) {
      ctrl.autoRotate = true;
      ctrl.autoRotateSpeed = 0.5;
      ctrl.enableDamping = true;
      ctrl.dampingFactor = 0.1;
      ctrl.minDistance = 101;
      ctrl.maxDistance = 600;
    }

    const renderer = globeRef.current?.renderer();
    if (renderer) {
      // Cap pixel ratio at 1 for Intel HD 4400 — prevents rendering 4x pixels on HiDPI
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1));
      renderer.shadowMap.enabled = false;
      renderer.shadowMap.autoUpdate = false;
    }

    // Disable shadow casting on all existing scene objects
    const scene = globeRef.current?.scene();
    if (scene) {
      scene.traverse(obj => {
        if (obj.isLight) obj.castShadow = false;
        if (obj.isMesh) { obj.castShadow = false; obj.receiveShadow = false; }
      });
    }
  }, []);

  return (
    <div style={{ padding: '16px', height: '100%', display: 'flex', flexDirection: 'column', gap: '12px', overflowY: 'auto' }}>

      {errorMsg && (
        <div style={{
          background: 'rgba(255, 0, 85, 0.15)', border: '1px solid var(--accent-pink)',
          color: 'var(--accent-pink)', padding: '8px 16px', borderRadius: '4px',
          fontFamily: 'Share Tech Mono', fontSize: '0.82rem', fontWeight: 'bold',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <span>⚠️ {errorMsg}</span>
          <button onClick={() => setErrorMsg(null)} style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer' }}>✕</button>
        </div>
      )}

      {/* Header Bar */}
      <div className="glass-panel" style={{ padding: '12px 16px', display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', gap: '10px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <SciFiGlobeIcon size={24} color="var(--accent-cyan)" />
          <div>
            <h2 style={{ margin: 0, fontSize: '1.05rem', letterSpacing: '1px', color: '#fff', fontFamily: 'Rajdhani, sans-serif', textShadow: '0 0 10px var(--accent-cyan)' }}>
              INTERACTIVE 3D CYBERPUNK GEOLOCATION GLOBE
            </h2>
            <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono' }}>
              REAL-WORLD BORDERS · 360° DRAG · LIVE LASER TELEMETRY · WebGL GPU
            </span>
          </div>
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
          <button onClick={() => setAutoRotate(!autoRotate)} style={{
            background: autoRotate ? 'rgba(0, 255, 157, 0.15)' : 'rgba(255,255,255,0.08)',
            border: autoRotate ? '1px solid var(--accent-green)' : '1px solid rgba(255,255,255,0.2)',
            color: autoRotate ? 'var(--accent-green)' : '#ccc', padding: '5px 10px',
            fontFamily: 'Share Tech Mono', fontSize: '0.74rem', fontWeight: 'bold',
            cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '5px', borderRadius: '3px',
          }}>
            {autoRotate ? <SciFiStopIcon size={10} color="var(--accent-green)" /> : <SciFiPlayIcon size={10} color="#ccc" />}
            AUTO-ROTATE: {autoRotate ? 'ON' : 'OFF'}
          </button>
          <button onClick={() => setRotationSpeed(prev => prev === 0.5 ? 1.0 : prev === 1.0 ? 2.0 : 0.5)} style={{
            background: 'rgba(0, 243, 255, 0.1)', border: '1px solid var(--accent-cyan)',
            color: 'var(--accent-cyan)', padding: '5px 10px', fontFamily: 'Share Tech Mono',
            fontSize: '0.74rem', fontWeight: 'bold', cursor: 'pointer', borderRadius: '3px',
          }}>
            SPEED: {rotationSpeed === 0.5 ? '1X' : rotationSpeed === 1.0 ? '2X' : '3X'}
          </button>
          <button onClick={resetCamera} style={{
            background: 'rgba(0, 243, 255, 0.1)', border: '1px solid var(--accent-cyan)',
            color: 'var(--accent-cyan)', padding: '5px 10px', fontFamily: 'Share Tech Mono',
            fontSize: '0.74rem', fontWeight: 'bold', cursor: 'pointer', borderRadius: '3px',
          }}>RESET VIEW</button>
          <button onClick={fetchGeolocationData} disabled={loading} style={{
            background: 'rgba(0, 243, 255, 0.1)', border: '1px solid var(--accent-cyan)',
            color: 'var(--accent-cyan)', padding: '5px 12px', fontFamily: 'Share Tech Mono',
            fontSize: '0.74rem', fontWeight: 'bold', cursor: 'pointer',
            display: 'flex', alignItems: 'center', gap: '5px', borderRadius: '3px',
          }}>
            <SciFiRefreshIcon size={13} color="var(--accent-cyan)" />
            {loading ? 'SCANNING...' : 'RE-SCAN NODES'}
          </button>
        </div>
      </div>

      {/* Main Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 300px', gap: '12px', flex: 1, minHeight: 0 }}>

        {/* Globe Panel */}
        <div className="glass-panel" style={{ padding: '12px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid rgba(0,243,255,0.15)', paddingBottom: '6px' }}>
            <div style={{ fontFamily: 'Share Tech Mono', fontSize: '0.8rem', color: 'var(--accent-cyan)', fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ width: '7px', height: '7px', borderRadius: '50%', background: 'var(--accent-green)', boxShadow: '0 0 6px var(--accent-green)' }} />
              REAL-WORLD 3D GLOBE [DRAG TO ORBIT 360°]
            </div>
            <div style={{ fontFamily: 'Share Tech Mono', fontSize: '0.72rem', color: 'var(--text-secondary)' }}>
              HQ: <span style={{ color: 'var(--accent-green)' }}>{serverInfo.city || 'Định Công'}, {serverInfo.country || 'VN'}</span>
            </div>
          </div>

          <div
            ref={globeContainerRef}
            style={{ position: 'relative', height: `${GLOBE_HEIGHT}px`, background: '#020d1a', borderRadius: '4px', border: '1px solid rgba(0,243,255,0.25)', overflow: 'hidden', flexShrink: 0 }}
          >
            <Globe
              ref={globeRef}
              width={undefined}
              height={GLOBE_HEIGHT}
              backgroundColor="rgba(2,13,26,1)"
              animateIn={false}

              // --- Performance: low-level WebGL config ---
              rendererConfig={{
                antialias: false,
                precision: 'mediump',
                powerPreference: 'high-performance',
                alpha: false,
                stencil: false,
              }}

              // --- Globe surface ---
              globeImageUrl="//unpkg.com/three-globe/example/img/earth-night.jpg"
              bumpImageUrl={null}
              showGraticules={false}
              showAtmosphere={false}

              // --- Country borders: pathsData (line strip) instead of polygon meshes ---
              pathsData={bordersData}
              pathPoints={d => d.coords}
              pathPointLat={p => p[0]}
              pathPointLng={p => p[1]}
              pathColor={() => 'rgba(0, 243, 255, 0.5)'}
              pathStroke={0.5}
              pathDashLength={1}
              pathDashGap={0}
              pathTransitionDuration={0}

              // --- Arcs ---
              arcsData={arcsData}
              arcStartLat={d => d.startLat}
              arcStartLng={d => d.startLng}
              arcEndLat={d => d.endLat}
              arcEndLng={d => d.endLng}
              arcColor={d => d.color}
              arcAltitude={0.25}
              arcStroke={0.9}
              arcDashLength={0.45}
              arcDashGap={0.2}
              arcDashAnimateTime={2800}

              // --- Points ---
              pointsData={pointsData}
              pointLat={d => d.lat}
              pointLng={d => d.lng}
              pointColor={d => d.color}
              pointAltitude={d => d.type === 'server' ? 0.06 : d.type === 'client' ? 0.04 : 0.01}
              pointRadius={d => d.size}
              pointResolution={6}
              pointsMerge={false}
              pointLabel={getPointLabel}

              // --- Rings (only server HQ) ---
              ringsData={ringsData}
              ringLat={d => d.lat}
              ringLng={d => d.lng}
              ringMaxRadius={d => d.maxR}
              ringPropagationSpeed={d => d.propagationSpeed}
              ringRepeatPeriod={d => d.repeatPeriod}
              ringColor={() => t => `rgba(0,255,157,${(1 - t) * 0.8})`}
              ringResolution={32}
              ringAltitude={0.002}

              // --- Labels (server HQ only) ---
              labelsData={pointsData.filter(p => p.type === 'server')}
              labelLat={d => d.lat}
              labelLng={d => d.lng}
              labelText={() => '[HQ]'}
              labelSize={0.9}
              labelColor={() => '#00ff9d'}
              labelAltitude={0.1}
              labelResolution={2}
              labelDotRadius={0.4}
              labelDotOrientation={() => 'bottom'}

              onGlobeReady={handleGlobeReady}
              onPointClick={(point) => {
                if (point.type === 'client' && point.client) {
                  setSelectedNode(point.client);
                  const lat = parseFloat(point.client.lat);
                  const lng = parseFloat(point.client.lon);
                  if (Number.isFinite(lat) && Number.isFinite(lng)) {
                    globeRef.current?.pointOfView({ lat, lng, altitude: 1.5 }, 800);
                  }
                }
              }}
            />

            {loading && (
              <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono', fontSize: '0.82rem', background: 'rgba(2,13,26,0.8)', pointerEvents: 'none' }}>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ marginBottom: '6px', fontSize: '1.1rem' }}>◈</div>
                  LOADING WORLD ATLAS...
                </div>
              </div>
            )}
            <div style={{ position: 'absolute', bottom: '10px', left: '14px', fontFamily: 'Share Tech Mono', fontSize: '0.68rem', color: 'rgba(255,255,255,0.38)', pointerEvents: 'none' }}>
              ✦ Drag to rotate · Scroll to zoom · Click pins
            </div>
          </div>

          {/* Legend */}
          <div style={{ display: 'flex', gap: '16px', fontSize: '0.73rem', fontFamily: 'Share Tech Mono', color: 'var(--text-secondary)' }}>
            {[
              { color: 'var(--accent-green)', label: 'SERVER HQ' },
              { color: 'var(--accent-cyan)', label: 'CLIENT DEVICE' },
              { color: '#00ff9d', label: 'VN ISLANDS' },
            ].map(({ color, label }) => (
              <div key={label} style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: color, display: 'inline-block', boxShadow: `0 0 4px ${color}` }} />
                <span>{label}</span>
              </div>
            ))}
            <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
              <span style={{ width: '16px', height: '2px', background: 'var(--accent-cyan)', display: 'inline-block' }} />
              <span>LASER ARC</span>
            </div>
          </div>
        </div>

        {/* HUD Panels */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', overflow: 'hidden' }}>
          <div className="glass-panel" style={{ padding: '14px', display: 'flex', flexDirection: 'column', gap: '10px', flexShrink: 0 }}>
            <div style={{ fontSize: '0.82rem', color: 'var(--accent-green)', fontFamily: 'Share Tech Mono', fontWeight: 'bold', borderBottom: '1px solid rgba(0, 255, 157, 0.2)', paddingBottom: '5px' }}>
              ✦ SERVER HQ TELEMETRY
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '7px', fontSize: '0.78rem', fontFamily: 'Share Tech Mono' }}>
              {[
                ['IP ADDRESS:', serverInfo.query || 'N/A', '#fff'],
                ['LOCATION:', `${serverInfo.city || 'N/A'}, ${serverInfo.country || 'N/A'}`, 'var(--accent-green)'],
                ['COORDINATES:', `${serverInfo.lat || '?'}°N ${serverInfo.lon || '?'}°E`, '#fff'],
                ['ISP / HOST:', serverInfo.isp || 'N/A', 'var(--accent-cyan)'],
                ['SESSIONS:', `${connections.length} DEVICE(S)`, 'var(--accent-yellow)'],
              ].map(([label, val, color]) => (
                <div key={label} style={{ display: 'flex', justifyContent: 'space-between', gap: '8px' }}>
                  <span style={{ color: 'var(--text-secondary)', flexShrink: 0 }}>{label}</span>
                  <span style={{ color, fontWeight: 'bold', textAlign: 'right', wordBreak: 'break-all' }}>{val}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="glass-panel" style={{ flex: 1, padding: '14px', display: 'flex', flexDirection: 'column', gap: '10px', overflow: 'hidden' }}>
            <div style={{ fontSize: '0.82rem', color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono', fontWeight: 'bold', borderBottom: '1px solid rgba(0, 243, 255, 0.2)', paddingBottom: '5px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span>✦ CONNECTED NODES ({connections.length})</span>
              <SciFiPulseBadge size={14} color="var(--accent-cyan)" />
            </div>
            <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {loading && connections.length === 0 ? (
                <div style={{ color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono', fontSize: '0.78rem', textAlign: 'center', padding: '16px' }}>
                  RESOLVING GEOLOCATION MATRIX...
                </div>
              ) : connections.length === 0 ? (
                <div style={{ color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono', fontSize: '0.78rem', textAlign: 'center', padding: '16px' }}>
                  No active external clients.
                </div>
              ) : (
                connections.map((conn, idx) => (
                  <div key={idx} onClick={() => {
                    setSelectedNode(conn);
                    const lat = parseFloat(conn.lat);
                    const lng = parseFloat(conn.lon);
                    if (Number.isFinite(lat) && Number.isFinite(lng) && (lat !== 0 || lng !== 0)) {
                      globeRef.current?.pointOfView({ lat, lng, altitude: 1.5 }, 800);
                    }
                  }} style={{
                    background: selectedNode?.ip === conn.ip ? 'rgba(0, 243, 255, 0.15)' : 'rgba(0,0,0,0.4)',
                    border: selectedNode?.ip === conn.ip ? '1px solid var(--accent-cyan)' : '1px solid rgba(0, 243, 255, 0.15)',
                    padding: '8px 10px', borderRadius: '4px', cursor: 'pointer',
                    display: 'flex', flexDirection: 'column', gap: '3px',
                    fontSize: '0.75rem', fontFamily: 'Share Tech Mono',
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', color: '#fff', fontWeight: 'bold' }}>
                      <span style={{ wordBreak: 'break-all' }}>IP: {conn.ip}</span>
                      <span style={{ color: 'var(--accent-green)', marginLeft: '8px', flexShrink: 0 }}>{conn.user || 'client'}</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--text-secondary)' }}>
                      <span>LOCATION:</span>
                      <span style={{ color: 'var(--accent-cyan)' }}>{conn.city || 'LAN'}, {conn.country || 'Local'}</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--text-secondary)', fontSize: '0.7rem' }}>
                      <span>STATE:</span>
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
