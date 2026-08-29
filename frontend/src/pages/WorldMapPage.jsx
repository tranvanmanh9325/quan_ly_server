import React, { useState, useEffect, useRef, useCallback, useMemo, useDeferredValue, useTransition } from 'react';
import axios from 'axios';
import Globe from 'react-globe.gl';
import { mesh } from 'topojson-client';
import { SciFiGlobeIcon, SciFiRefreshIcon, SciFiPulseBadge, SciFiPlayIcon, SciFiStopIcon } from '../components/SciFiIcons';
import { VIETNAM_MARITIME_ISLANDS } from '../data/vietnamIslandsGeo';
import GlobeHudLegend from '../components/GlobeHudLegend';

// 110m resolution: 105KB vs 756KB (50m) — 90% fewer border vertices, imperceptible at 600px canvas
const LOCAL_WORLD_ATLAS_URL = '/data/countries-110m.json';
const CDN_WORLD_ATLAS_URL = 'https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json';

// Resized 1024x512 local texture: 35KB vs 698KB — fits 600x440px canvas pixel-perfect
const EARTH_TEXTURE_URL = '/textures/earth-night-1024.jpg';

export default function WorldMapPage() {
  const [geoData, setGeoData] = useState({ server: null, connections: [] });
  const [bordersData, setBordersData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState(null);
  const [selectedNode, setSelectedNode] = useState(null);
  const [autoRotate, setAutoRotate] = useState(true);
  const [rotationSpeed, setRotationSpeed] = useState(0.5);

  // useDeferredValue: pass borders to Globe at low priority so first paint isn't blocked
  const deferredBorders = useDeferredValue(bordersData);
  const [, startBordersTransition] = useTransition();

  // Measured container dimensions — passed explicitly to Globe to prevent misalignment
  const [globeDimensions, setGlobeDimensions] = useState({ width: 600, height: 440 });

  const globeRef = useRef();
  const globeContainerRef = useRef();

  // ResizeObserver: measure container and feed exact width/height to Globe
  // This fixes the "globe shifted right" bug caused by Globe auto-measuring window.innerWidth
  useEffect(() => {
    const el = globeContainerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(entries => {
      const { width, height } = entries[0].contentRect;
      setGlobeDimensions({ width: Math.floor(width), height: Math.floor(height) });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // --- Load TopoJSON border mesh (1 MultiLineString vs 241 polygon features) ---
  useEffect(() => {
    const loadTopoData = async () => {
      try {
        let res = await fetch(LOCAL_WORLD_ATLAS_URL);
        if (!res.ok) res = await fetch(CDN_WORLD_ATLAS_URL);
        const topo = await res.json();
        // (a,b)=>a!==b keeps only shared country borders, removing coast lines from count
        const borderMesh = mesh(topo, topo.objects.countries, (a, b) => a !== b);
        const paths = (borderMesh.coordinates || []).map(coords => ({
          coords: coords.map(([lng, lat]) => [lat, lng]),
        }));
        // startTransition: defer border update to low priority, don't block first globe paint
        startBordersTransition(() => setBordersData(paths));
      } catch (err) {
        console.error('[Globe] TopoJSON local failed, trying CDN:', err);
        try {
          const res = await fetch(CDN_WORLD_ATLAS_URL);
          const topo = await res.json();
          const borderMesh = mesh(topo, topo.objects.countries, (a, b) => a !== b);
          const paths = (borderMesh.coordinates || []).map(coords => ({
            coords: coords.map(([lng, lat]) => [lat, lng]),
          }));
          startBordersTransition(() => setBordersData(paths));
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

  // Sync autoRotate + speed to OrbitControls
  useEffect(() => {
    const ctrl = globeRef.current?.controls();
    if (!ctrl) return;
    ctrl.autoRotate = autoRotate;
    ctrl.autoRotateSpeed = rotationSpeed;
  }, [autoRotate, rotationSpeed]);

  // Auto-focus camera when connections arrive
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
        client,
        // 3-stop gradient: transparent at tips → bright cyan at center → laser glow
        color: ['rgba(0,255,157,0)', 'rgba(0,243,255,0.95)', 'rgba(0,255,157,0)'],
      };
    });
  }, [geoData]);

  const pointsData = useMemo(() => {
    const points = [];
    const sLat = parseFloat(geoData.server?.lat) || 20.98;
    const sLon = parseFloat(geoData.server?.lon) || 105.83;

    points.push({ id: 'server', lat: sLat, lng: sLon, size: 0.6, color: '#00ff9d', type: 'server' });

    (geoData.connections || []).forEach((client, idx) => {
      const parsedLat = parseFloat(client.lat);
      const parsedLon = parseFloat(client.lon);
      const hasGps = Number.isFinite(parsedLat) && Number.isFinite(parsedLon)
        && (parsedLat !== 0 || parsedLon !== 0);
      if (hasGps) {
        points.push({ id: `client-${idx}`, lat: parsedLat, lng: parsedLon, size: 0.35, color: '#00f3ff', type: 'client', client });
      }
    });

    // Only cluster centers for VN islands (skip sub-dots to reduce point count)
    VIETNAM_MARITIME_ISLANDS.forEach(item => {
      points.push({
        id: item.id, lat: item.lat, lng: item.lon,
        size: item.type === 'archipelago_cluster' ? 0.28 : 0.2,
        color: '#00ff9d', label: item.label, type: 'island',
      });
    });

    return points;
  }, [geoData]);

  // htmlElementsData: DOM overlay markers (CSS-styleable) — replaces plain WebGL labelsData
  // Each item: { lat, lng, type, label, sublabel, color }
  const htmlMarkersData = useMemo(() => {
    const markers = [];
    const sLat = parseFloat(geoData.server?.lat) || 20.98;
    const sLon = parseFloat(geoData.server?.lon) || 105.83;

    // Server HQ callout
    if (geoData.server) {
      markers.push({
        id: 'hq',
        lat: sLat, lng: sLon,
        type: 'server',
        label: 'SERVER HQ',
        sublabel: serverInfo.city ? `${serverInfo.city}, ${serverInfo.country || 'VN'}` : 'Phường Định Công, VN',
        color: '#00ff9d',
        borderColor: 'rgba(0,255,157,0.65)',
        glowColor: 'rgba(0,255,157,0.25)',
      });
    }

    // Client callout markers
    (geoData.connections || []).forEach((client, idx) => {
      const parsedLat = parseFloat(client.lat);
      const parsedLon = parseFloat(client.lon);
      const hasGps = Number.isFinite(parsedLat) && Number.isFinite(parsedLon)
        && (parsedLat !== 0 || parsedLon !== 0);
      if (hasGps) {
        markers.push({
          id: `client-${idx}`,
          lat: parsedLat, lng: parsedLon,
          type: 'client',
          label: 'CLIENT NODE',
          sublabel: client.city ? `${client.city}, ${client.country || ''}` : (client.ip || 'Unknown'),
          color: '#00f3ff',
          borderColor: 'rgba(0,243,255,0.6)',
          glowColor: 'rgba(0,243,255,0.2)',
          client,
        });
      }
    });

    return markers;
  }, [geoData, serverInfo]);


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

  // Tooltip on hover (still used for island and fallback)
  const getPointLabel = useCallback((d) => {
    if (d.type === 'island') return `<div style="font-family:'Share Tech Mono',monospace;font-size:10px;color:#00ff9d;background:rgba(2,13,26,0.95);padding:3px 8px;border:1px solid rgba(0,255,157,0.4);border-radius:2px;letter-spacing:0.5px">◆ ${d.label}</div>`;
    return '';
  }, []);

  // Create DOM element for htmlElementsData markers — Palantir/Cesium callout style
  // Uses raw DOM API (not React) as required by react-globe.gl htmlElement prop
  const createHtmlMarkerElement = useCallback((d) => {
    const isServer = d.type === 'server';
    const color = d.color;
    const borderColor = d.borderColor;
    const glowColor = d.glowColor;

    const el = document.createElement('div');
    el.style.cssText = `
      position: relative;
      pointer-events: none;
      transform: translate(-50%, -100%);
      padding-bottom: 8px;
    `;

    // Leader line (connector from box to pin)
    const leaderLine = document.createElement('div');
    leaderLine.style.cssText = `
      position: absolute;
      bottom: 0;
      left: 50%;
      transform: translateX(-50%);
      width: 1px;
      height: 8px;
      background: linear-gradient(to bottom, ${borderColor}, transparent);
    `;
    el.appendChild(leaderLine);

    // Callout box
    const box = document.createElement('div');
    box.style.cssText = `
      background: linear-gradient(135deg, rgba(2,10,22,0.94) 0%, rgba(0,20,38,0.90) 100%);
      border: 1px solid ${borderColor};
      border-radius: 2px;
      padding: ${isServer ? '5px 10px' : '4px 8px'};
      font-family: 'Share Tech Mono', monospace;
      white-space: nowrap;
      box-shadow: 0 0 12px ${glowColor}, inset 0 1px 0 ${glowColor};
      clip-path: polygon(6px 0, 100% 0, 100% calc(100% - 6px), calc(100% - 6px) 100%, 0 100%, 0 6px);
    `;

    // Badge row
    const badgeRow = document.createElement('div');
    badgeRow.style.cssText = `
      display: flex;
      align-items: center;
      gap: 5px;
      margin-bottom: ${isServer ? '2px' : '0'};
    `;

    // Pulse dot
    const pulseDot = document.createElement('div');
    pulseDot.style.cssText = `
      width: 5px;
      height: 5px;
      border-radius: 50%;
      background: ${color};
      box-shadow: 0 0 4px ${color};
      flex-shrink: 0;
    `;
    badgeRow.appendChild(pulseDot);

    // Label text
    const labelSpan = document.createElement('span');
    labelSpan.style.cssText = `
      font-size: ${isServer ? '10px' : '9px'};
      font-weight: bold;
      color: ${color};
      letter-spacing: 1px;
      text-shadow: 0 0 8px ${color};
    `;
    labelSpan.textContent = d.label;
    badgeRow.appendChild(labelSpan);

    box.appendChild(badgeRow);

    // Sublabel (city/IP info)
    if (d.sublabel) {
      const sub = document.createElement('div');
      sub.style.cssText = `
        font-size: 8px;
        color: rgba(255,255,255,0.55);
        letter-spacing: 0.5px;
        line-height: 1.3;
      `;
      sub.textContent = d.sublabel;
      box.appendChild(sub);
    }

    el.appendChild(box);
    return el;
  }, []);



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
      // Force pixelRatio=1 — prevents 4x pixel calculation on HiDPI displays on Intel HD 4400
      renderer.setPixelRatio(1);
      renderer.shadowMap.enabled = false;
      renderer.shadowMap.autoUpdate = false;
    }

    const scene = globeRef.current?.scene();
    if (scene) {
      scene.traverse(obj => {
        if (obj.isLight) obj.castShadow = false;
        if (obj.isMesh) { obj.castShadow = false; obj.receiveShadow = false; }
      });
    }
  }, []);


  return (
    <div style={{ padding: '12px', height: '100%', display: 'flex', flexDirection: 'column', gap: '10px', overflowY: 'auto', boxSizing: 'border-box' }}>

      {errorMsg && (
        <div style={{
          background: 'rgba(255, 0, 85, 0.15)', border: '1px solid var(--accent-pink)',
          color: 'var(--accent-pink)', padding: '7px 14px', borderRadius: '4px',
          fontFamily: 'Share Tech Mono', fontSize: '0.8rem', fontWeight: 'bold',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0,
        }}>
          <span>⚠️ {errorMsg}</span>
          <button onClick={() => setErrorMsg(null)} style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer' }}>✕</button>
        </div>
      )}

      {/* Header */}
      <div className="glass-panel" style={{ padding: '10px 14px', display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <SciFiGlobeIcon size={22} color="var(--accent-cyan)" />
          <div>
            <h2 style={{ margin: 0, fontSize: '0.98rem', letterSpacing: '1px', color: '#fff', fontFamily: 'Rajdhani, sans-serif', textShadow: '0 0 10px var(--accent-cyan)' }}>
              INTERACTIVE 3D CYBERPUNK GEOLOCATION GLOBE
            </h2>
            <span style={{ fontSize: '0.65rem', color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono' }}>
              REAL-WORLD BORDERS · 360° DRAG · LIVE LASER TELEMETRY · WebGL GPU
            </span>
          </div>
        </div>
        <div style={{ display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap' }}>
          <button onClick={() => setAutoRotate(!autoRotate)} style={{
            background: autoRotate ? 'rgba(0, 255, 157, 0.15)' : 'rgba(255,255,255,0.08)',
            border: autoRotate ? '1px solid var(--accent-green)' : '1px solid rgba(255,255,255,0.2)',
            color: autoRotate ? 'var(--accent-green)' : '#ccc', padding: '4px 9px',
            fontFamily: 'Share Tech Mono', fontSize: '0.72rem', fontWeight: 'bold',
            cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '5px', borderRadius: '3px',
          }}>
            {autoRotate ? <SciFiStopIcon size={9} color="var(--accent-green)" /> : <SciFiPlayIcon size={9} color="#ccc" />}
            ROTATE: {autoRotate ? 'ON' : 'OFF'}
          </button>
          <button onClick={() => setRotationSpeed(prev => prev === 0.5 ? 1.0 : prev === 1.0 ? 2.0 : 0.5)} style={{
            background: 'rgba(0, 243, 255, 0.08)', border: '1px solid var(--accent-cyan)',
            color: 'var(--accent-cyan)', padding: '4px 9px', fontFamily: 'Share Tech Mono',
            fontSize: '0.72rem', fontWeight: 'bold', cursor: 'pointer', borderRadius: '3px',
          }}>
            SPD: {rotationSpeed === 0.5 ? '1X' : rotationSpeed === 1.0 ? '2X' : '3X'}
          </button>
          <button onClick={resetCamera} style={{
            background: 'rgba(0, 243, 255, 0.08)', border: '1px solid var(--accent-cyan)',
            color: 'var(--accent-cyan)', padding: '4px 9px', fontFamily: 'Share Tech Mono',
            fontSize: '0.72rem', fontWeight: 'bold', cursor: 'pointer', borderRadius: '3px',
          }}>RESET</button>
          <button onClick={fetchGeolocationData} disabled={loading} style={{
            background: 'rgba(0, 243, 255, 0.08)', border: '1px solid var(--accent-cyan)',
            color: 'var(--accent-cyan)', padding: '4px 10px', fontFamily: 'Share Tech Mono',
            fontSize: '0.72rem', fontWeight: 'bold', cursor: 'pointer',
            display: 'flex', alignItems: 'center', gap: '4px', borderRadius: '3px',
          }}>
            <SciFiRefreshIcon size={11} color="var(--accent-cyan)" />
            {loading ? 'SCANNING...' : 'RE-SCAN'}
          </button>
        </div>
      </div>

      {/* Main grid — stretch to fill remaining height */}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 290px', gap: '10px', flex: 1, minHeight: 0 }}>

        {/* Globe panel — flex column, globe expands to fill, legend sits at bottom */}
        <div className="glass-panel" style={{ padding: '10px', display: 'flex', flexDirection: 'column', gap: '6px', overflow: 'hidden' }}>
          {/* Panel title bar */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid rgba(0,243,255,0.14)', paddingBottom: '5px', flexShrink: 0 }}>
            <div style={{ fontFamily: 'Share Tech Mono', fontSize: '0.76rem', color: 'var(--accent-cyan)', fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: 'var(--accent-green)', boxShadow: '0 0 5px var(--accent-green)' }} />
              REAL-WORLD 3D GLOBE [DRAG TO ORBIT 360°]
            </div>
            <div style={{ fontFamily: 'Share Tech Mono', fontSize: '0.68rem', color: 'var(--text-secondary)' }}>
              HQ: <span style={{ color: 'var(--accent-green)' }}>{serverInfo.city || 'Định Công'}, {serverInfo.country || 'VN'}</span>
            </div>
          </div>

          {/* Globe canvas container — flex:1 fills all remaining panel space */}
          <div
            ref={globeContainerRef}
            style={{
              flex: 1,
              position: 'relative',
              background: '#020d1a',
              borderRadius: '4px',
              border: '1px solid rgba(0,243,255,0.22)',
              overflow: 'hidden',
              minHeight: 0,
            }}
          >
            <Globe
              ref={globeRef}
              width={globeDimensions.width}
              height={globeDimensions.height}
              backgroundColor="rgba(2,13,26,1)"
              animateIn={false}
              waitForGlobeReady={true}

              rendererConfig={{
                antialias: false,
                precision: 'mediump',
                alpha: false,
                stencil: false,
              }}

              globeImageUrl={EARTH_TEXTURE_URL}
              bumpImageUrl={null}
              showGraticules={false}
              showAtmosphere={false}
              globeCurvatureResolution={6}  // Reduce globe triangles ~4000 vs ~16000 default

              // deferredBorders: low-priority update — globe renders before borders arrive
              pathsData={deferredBorders}
              pathPoints={d => d.coords}
              pathPointLat={p => p[0]}
              pathPointLng={p => p[1]}
              pathColor={() => 'rgba(0, 243, 255, 0.5)'}
              pathStroke={0.5}
              pathDashLength={1}
              pathDashGap={0}
              pathTransitionDuration={0}

              arcsData={arcsData}
              arcStartLat={d => d.startLat}
              arcStartLng={d => d.startLng}
              arcEndLat={d => d.endLat}
              arcEndLng={d => d.endLng}
              arcColor={d => d.color}
              arcAltitude={0.2}
              arcStroke={0.2}
              arcDashLength={0.4}
              arcDashGap={0.15}
              arcDashAnimateTime={2400}

              // Throttle raycasting — only raycast 'point' objects, skip border geometry entirely
              pointerEventsFilter={obj => obj.__globeObjType === 'point'}

              pointsData={pointsData}
              pointLat={d => d.lat}
              pointLng={d => d.lng}
              pointColor={d => d.color}
              pointAltitude={d => d.type === 'server' ? 0.05 : d.type === 'client' ? 0.03 : 0.005}
              pointRadius={d => d.size}
              pointResolution={12}
              pointsMerge={false}
              pointLabel={getPointLabel}

              ringsData={ringsData}
              ringLat={d => d.lat}
              ringLng={d => d.lng}
              ringMaxRadius={d => d.maxR}
              ringPropagationSpeed={d => d.propagationSpeed}
              ringRepeatPeriod={d => d.repeatPeriod}
              ringColor={() => t => `rgba(0,255,157,${(1 - t) * 0.7})`}
              ringResolution={32}
              ringAltitude={0.002}

              htmlElementsData={htmlMarkersData}
              htmlLat={d => d.lat}
              htmlLng={d => d.lng}
              htmlAltitude={d => d.type === 'server' ? 0.08 : 0.06}
              htmlElement={createHtmlMarkerElement}
              htmlTransitionDuration={0}
              htmlElementVisibilityModifier={(el, isVisible) => {
                el.style.opacity = isVisible ? '1' : '0';
                el.style.transition = 'opacity 0.3s';
              }}

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
              <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono', fontSize: '0.8rem', background: 'rgba(2,13,26,0.8)', pointerEvents: 'none' }}>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ marginBottom: '5px', fontSize: '1rem' }}>◈</div>
                  LOADING WORLD ATLAS...
                </div>
              </div>
            )}

            <div style={{ position: 'absolute', bottom: '8px', left: '12px', fontFamily: 'Share Tech Mono', fontSize: '0.65rem', color: 'rgba(255,255,255,0.35)', pointerEvents: 'none' }}>
              ✦ Drag to rotate · Scroll to zoom · Click pins
            </div>
          </div>

          {/* HUD Legend Bar — Military / Palantir mission control style */}
          <GlobeHudLegend
            serverCount={geoData.server ? 1 : 0}
            clientCount={connections.length}
            isLive={!loading}
          />
        </div>


        {/* Right HUD column */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', overflow: 'hidden' }}>

          {/* Server Telemetry */}
          <div className="glass-panel" style={{ padding: '12px', display: 'flex', flexDirection: 'column', gap: '9px', flexShrink: 0 }}>
            <div style={{ fontSize: '0.78rem', color: 'var(--accent-green)', fontFamily: 'Share Tech Mono', fontWeight: 'bold', borderBottom: '1px solid rgba(0, 255, 157, 0.2)', paddingBottom: '5px' }}>
              ✦ SERVER HQ TELEMETRY
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '0.75rem', fontFamily: 'Share Tech Mono' }}>
              {[
                ['IP ADDRESS:', serverInfo.query || 'N/A', '#fff'],
                ['LOCATION:', `${serverInfo.city || 'N/A'}, ${serverInfo.country || 'N/A'}`, 'var(--accent-green)'],
                ['COORDINATES:', `${serverInfo.lat || '?'}°N ${serverInfo.lon || '?'}°E`, '#fff'],
                ['ISP / HOST:', serverInfo.isp || 'N/A', 'var(--accent-cyan)'],
                ['SESSIONS:', `${connections.length} DEVICE(S)`, 'var(--accent-yellow)'],
              ].map(([label, val, color]) => (
                <div key={label} style={{ display: 'flex', justifyContent: 'space-between', gap: '6px' }}>
                  <span style={{ color: 'var(--text-secondary)', flexShrink: 0 }}>{label}</span>
                  <span style={{ color, fontWeight: 'bold', textAlign: 'right', wordBreak: 'break-all' }}>{val}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Connected Clients */}
          <div className="glass-panel" style={{ flex: 1, padding: '12px', display: 'flex', flexDirection: 'column', gap: '9px', overflow: 'hidden' }}>
            <div style={{ fontSize: '0.78rem', color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono', fontWeight: 'bold', borderBottom: '1px solid rgba(0, 243, 255, 0.2)', paddingBottom: '5px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span>✦ CONNECTED NODES ({connections.length})</span>
              <SciFiPulseBadge size={13} color="var(--accent-cyan)" />
            </div>
            <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '7px' }}>
              {loading && connections.length === 0 ? (
                <div style={{ color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono', fontSize: '0.75rem', textAlign: 'center', padding: '14px' }}>
                  RESOLVING MATRIX...
                </div>
              ) : connections.length === 0 ? (
                <div style={{ color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono', fontSize: '0.75rem', textAlign: 'center', padding: '14px' }}>
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
                    background: selectedNode?.ip === conn.ip ? 'rgba(0, 243, 255, 0.14)' : 'rgba(0,0,0,0.38)',
                    border: selectedNode?.ip === conn.ip ? '1px solid var(--accent-cyan)' : '1px solid rgba(0, 243, 255, 0.13)',
                    padding: '7px 9px', borderRadius: '4px', cursor: 'pointer',
                    display: 'flex', flexDirection: 'column', gap: '3px',
                    fontSize: '0.72rem', fontFamily: 'Share Tech Mono',
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', color: '#fff', fontWeight: 'bold' }}>
                      <span style={{ wordBreak: 'break-all' }}>IP: {conn.ip}</span>
                      <span style={{ color: 'var(--accent-green)', marginLeft: '6px', flexShrink: 0 }}>{conn.user || 'client'}</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--text-secondary)' }}>
                      <span>LOC:</span>
                      <span style={{ color: 'var(--accent-cyan)' }}>{conn.city || 'LAN'}, {conn.country || 'Local'}</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--text-secondary)', fontSize: '0.67rem' }}>
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
