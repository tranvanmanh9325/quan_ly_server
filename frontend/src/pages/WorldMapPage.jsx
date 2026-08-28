import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import axios from 'axios';
import Globe from 'react-globe.gl';
import { feature } from 'topojson-client';
import { SciFiGlobeIcon, SciFiRefreshIcon, SciFiPulseBadge, SciFiPlayIcon, SciFiStopIcon } from '../components/SciFiIcons';
import { VIETNAM_MARITIME_ISLANDS } from '../data/vietnamIslandsGeo';

// High-Resolution World Atlas TopoJSON (50m scale)
const LOCAL_WORLD_ATLAS_URL = '/data/countries-50m.json';
const CDN_WORLD_ATLAS_URL = 'https://cdn.jsdelivr.net/npm/world-atlas@2/countries-50m.json';

export default function WorldMapPage() {
  const [geoData, setGeoData] = useState({ server: null, connections: [] });
  const [countries, setCountries] = useState({ features: [] });
  const [loading, setLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState(null);
  const [selectedNode, setSelectedNode] = useState(null);
  const [autoRotate, setAutoRotate] = useState(true);
  const [rotationSpeed, setRotationSpeed] = useState(0.5); // deg/frame for globe.gl
  const [hovered, setHovered] = useState(null);

  const globeRef = useRef();
  const globeContainerRef = useRef();

  // --- Load TopoJSON countries geometry (pre-compute once) ---
  useEffect(() => {
    const loadTopoData = async () => {
      try {
        let res = await fetch(LOCAL_WORLD_ATLAS_URL);
        if (!res.ok) res = await fetch(CDN_WORLD_ATLAS_URL);
        const topo = await res.json();
        setCountries(feature(topo, topo.objects.countries));
      } catch (err) {
        console.error('Failed to load local world atlas, trying fallback CDN:', err);
        try {
          const res = await fetch(CDN_WORLD_ATLAS_URL);
          const topo = await res.json();
          setCountries(feature(topo, topo.objects.countries));
        } catch (cdnErr) {
          console.error('All world atlas data sources failed:', cdnErr);
        }
      }
    };
    loadTopoData();
  }, []);

  // --- Client Check-in (GPS → Geolocation → POST) ---
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
            const geo = await axios.get(`https://api.bigdatacloud.net/data/reverse-geocode-client?latitude=${lat}&longitude=${lon}&localityLanguage=vi`)
              .then(r => r.data);
            if (geo) {
              const subdivision = (geo.principalSubdivision || '').trim();
              const cityName = (geo.city || geo.locality || '').trim();
              city = subdivision
                ? (cityName && !cityName.toLowerCase().includes(subdivision.toLowerCase()) ? `${cityName}, ${subdivision}` : subdivision)
                : (cityName || 'Unknown');
              country = geo.countryName || 'Vietnam';
              countryCode = geo.countryCode || 'VN';
            }
          } catch (_) { /* non-blocking fallback handled on server */ }
        }

        await axios.post('/api/metrics/client-checkin', { lat, lon, city, country, countryCode });

        const res = await axios.get('/api/metrics/geolocation');
        if (res.data) {
          setGeoData({ server: res.data.server || null, connections: res.data.connections || [] });
        }
      } catch (err) {
        console.warn('[WorldMap] Client checkin failed (non-critical):', err.message);
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
      if (res.data) {
        setGeoData({ server: res.data.server || null, connections: res.data.connections || [] });
      }
    } catch (err) {
      setErrorMsg(`Failed to fetch geolocation: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchGeolocationData();
  }, []);

  // --- Auto-rotate control ---
  useEffect(() => {
    if (!globeRef.current) return;
    const controls = globeRef.current.controls();
    if (!controls) return;
    controls.autoRotate = autoRotate;
    controls.autoRotateSpeed = rotationSpeed;
  }, [autoRotate, rotationSpeed]);

  // --- Initial camera position: centered on Vietnam ---
  useEffect(() => {
    if (!globeRef.current) return;
    // Wait for globe to be ready
    setTimeout(() => {
      globeRef.current?.pointOfView({ lat: 16.0, lng: 105.85, altitude: 2.0 }, 0);
    }, 500);
  }, []);

  // --- Auto-focus camera when connections arrive ---
  useEffect(() => {
    if (!globeRef.current) return;
    const conns = geoData.connections || [];
    if (conns.length === 0 || !geoData.server) return;

    const allLats = [parseFloat(geoData.server.lat) || 0, ...conns.map(c => parseFloat(c.lat) || 0)];
    const allLons = [parseFloat(geoData.server.lon) || 0, ...conns.map(c => parseFloat(c.lon) || 0)];
    const avgLat = allLats.reduce((s, v) => s + v, 0) / allLats.length;
    const avgLon = allLons.reduce((s, v) => s + v, 0) / allLons.length;

    globeRef.current.pointOfView({ lat: avgLat, lng: avgLon, altitude: 2.2 }, 1000);
  }, [geoData.connections?.length]);

  // --- Build arc data for react-globe.gl ---
  const arcsData = useMemo(() => {
    const sLat = parseFloat(geoData.server?.lat) || 20.98;
    const sLon = parseFloat(geoData.server?.lon) || 105.83;
    const clients = geoData.connections || [];

    return clients.map((client, idx) => {
      const parsedLat = parseFloat(client.lat);
      const parsedLon = parseFloat(client.lon);
      const hasGps = Number.isFinite(parsedLat) && Number.isFinite(parsedLon)
        && (parsedLat !== 0 || parsedLon !== 0);
      return {
        id: idx,
        startLat: sLat,
        startLng: sLon,
        endLat: hasGps ? parsedLat : sLat + 0.01,
        endLng: hasGps ? parsedLon : sLon + 0.01,
        client,
        color: ['#00f3ff', '#00ff9d'],
      };
    });
  }, [geoData]);

  // --- Build points data (server + clients + Vietnam islands) ---
  const pointsData = useMemo(() => {
    const points = [];
    const sLat = parseFloat(geoData.server?.lat) || 20.98;
    const sLon = parseFloat(geoData.server?.lon) || 105.83;

    // Server HQ
    points.push({
      id: 'server',
      lat: sLat,
      lng: sLon,
      size: 0.6,
      color: '#00ff9d',
      label: `[HQ] SERVER\n${geoData.server?.city || 'Định Công'}, ${geoData.server?.country || 'Việt Nam'}`,
      type: 'server',
    });

    // Client devices
    const clients = geoData.connections || [];
    clients.forEach((client, idx) => {
      const parsedLat = parseFloat(client.lat);
      const parsedLon = parseFloat(client.lon);
      const hasGps = Number.isFinite(parsedLat) && Number.isFinite(parsedLon)
        && (parsedLat !== 0 || parsedLon !== 0);
      if (hasGps) {
        points.push({
          id: `client-${idx}`,
          lat: parsedLat,
          lng: parsedLon,
          size: 0.35,
          color: '#00f3ff',
          label: `[${client.city || client.ip || 'CLIENT'}]\n${client.country || ''}`,
          type: 'client',
          client,
        });
      }
    });

    // Vietnam Maritime Islands
    VIETNAM_MARITIME_ISLANDS.forEach(item => {
      if (item.type === 'archipelago_cluster') {
        // Add cluster center
        points.push({
          id: item.id,
          lat: item.lat,
          lng: item.lon,
          size: 0.28,
          color: '#00ff9d',
          label: item.label,
          type: 'island',
        });
        // Add individual islands
        if (item.islands) {
          item.islands.forEach(isl => {
            points.push({
              id: `${item.id}-${isl.name}`,
              lat: isl.lat,
              lng: isl.lon,
              size: 0.18,
              color: '#00ff9d',
              label: isl.name,
              type: 'island-dot',
            });
          });
        }
      } else {
        points.push({
          id: item.id,
          lat: item.lat,
          lng: item.lon,
          size: 0.22,
          color: item.color || '#00f3ff',
          label: item.label,
          type: 'island',
        });
      }
    });

    return points;
  }, [geoData]);

  // --- Ring pulses (sonar effect on server + archipelago clusters) ---
  const ringsData = useMemo(() => {
    const rings = [];
    const sLat = parseFloat(geoData.server?.lat) || 20.98;
    const sLon = parseFloat(geoData.server?.lon) || 105.83;

    rings.push({ lat: sLat, lng: sLon, maxR: 3.5, propagationSpeed: 1.5, repeatPeriod: 900, color: '#00ff9d' });

    VIETNAM_MARITIME_ISLANDS.forEach(item => {
      if (item.type === 'archipelago_cluster') {
        rings.push({ lat: item.lat, lng: item.lon, maxR: 2.5, propagationSpeed: 1.2, repeatPeriod: 1200, color: '#00ff9d' });
      }
    });

    return rings;
  }, [geoData.server]);

  const resetCamera = useCallback(() => {
    globeRef.current?.pointOfView({ lat: 16.0, lng: 105.85, altitude: 2.0 }, 800);
  }, []);

  const serverInfo = geoData.server || {};
  const connections = geoData.connections || [];

  // Tooltip HTML for each point
  const getPointLabel = useCallback((d) => {
    if (d.type === 'island-dot') return `<div style="font-family:'Share Tech Mono',monospace;font-size:11px;color:#00ff9d;background:rgba(2,13,26,0.9);padding:4px 8px;border:1px solid rgba(0,255,157,0.4);border-radius:3px">${d.label}</div>`;
    if (d.type === 'island') return `<div style="font-family:'Share Tech Mono',monospace;font-size:11px;color:#00ff9d;background:rgba(2,13,26,0.9);padding:4px 8px;border:1px solid rgba(0,255,157,0.4);border-radius:3px">🏝 ${d.label}</div>`;
    if (d.type === 'server') return `<div style="font-family:'Share Tech Mono',monospace;font-size:11px;color:#00ff9d;background:rgba(2,13,26,0.9);padding:6px 10px;border:1px solid rgba(0,255,157,0.6);border-radius:3px"><b>[HQ] SERVER</b><br/>${serverInfo.city || 'Định Công'}, ${serverInfo.country || 'Việt Nam'}<br/>IP: ${serverInfo.query || 'N/A'}</div>`;
    if (d.type === 'client') return `<div style="font-family:'Share Tech Mono',monospace;font-size:11px;color:#00f3ff;background:rgba(2,13,26,0.9);padding:6px 10px;border:1px solid rgba(0,243,255,0.6);border-radius:3px"><b>[CLIENT]</b><br/>${d.client?.city || d.client?.ip || 'Unknown'}, ${d.client?.country || ''}<br/>IP: ${d.client?.ip || 'N/A'}</div>`;
    return d.label;
  }, [serverInfo]);

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
              REAL-WORLD COUNTRY BORDERS · 360° DRAG ROTATION · LIVE LASER TELEMETRY · WebGL GPU-ACCELERATED
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

          <button onClick={() => setRotationSpeed(prev => prev === 0.5 ? 1.0 : prev === 1.0 ? 2.0 : 0.5)} style={{
            background: 'rgba(0, 243, 255, 0.1)', border: '1px solid var(--accent-cyan)',
            color: 'var(--accent-cyan)', padding: '6px 12px', fontFamily: 'Share Tech Mono',
            fontSize: '0.78rem', fontWeight: 'bold', cursor: 'pointer', borderRadius: '3px'
          }}>
            SPEED: {rotationSpeed === 0.5 ? '1X' : rotationSpeed === 1.0 ? '2X' : '3X'}
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

        {/* 3D Globe WebGL Panel */}
        <div className="glass-panel" style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px', minHeight: '520px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid rgba(0,243,255,0.15)', paddingBottom: '8px' }}>
            <div style={{ fontFamily: 'Share Tech Mono', fontSize: '0.85rem', color: 'var(--accent-cyan)', fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: 'var(--accent-green)', boxShadow: '0 0 8px var(--accent-green)' }} />
              REAL-WORLD 3D GLOBE [DRAG TO ORBIT 360°] — WebGL GPU
            </div>
            <div style={{ fontFamily: 'Share Tech Mono', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
              HQ: <span style={{ color: 'var(--accent-green)' }}>{serverInfo.city || 'Định Công'}, {serverInfo.country || 'VN'}</span>
            </div>
          </div>

          <div
            ref={globeContainerRef}
            style={{ flex: 1, position: 'relative', minHeight: '440px', background: '#020d1a', borderRadius: '4px', border: '1px solid rgba(0,243,255,0.25)', overflow: 'hidden' }}
          >
            <Globe
              ref={globeRef}
              // --- Layout ---
              width={undefined}
              height={undefined}
              backgroundColor="rgba(2,13,26,1)"

              // --- Globe surface: dark cyberpunk texture ---
              globeImageUrl="//unpkg.com/three-globe/example/img/earth-night.jpg"
              bumpImageUrl="//unpkg.com/three-globe/example/img/earth-topology.png"
              showGraticules={true}
              showAtmosphere={true}
              atmosphereColor="#00f3ff"
              atmosphereAltitude={0.12}

              // --- Country polygons (country border outlines) ---
              polygonsData={countries.features}
              polygonCapColor={() => 'rgba(0, 30, 55, 0.75)'}
              polygonSideColor={() => 'rgba(0, 100, 180, 0.1)'}
              polygonStrokeColor={() => 'rgba(0, 243, 255, 0.35)'}
              polygonAltitude={0.001}
              polygonsTransitionDuration={0}

              // --- Arcs (laser connections) ---
              arcsData={arcsData}
              arcStartLat={d => d.startLat}
              arcStartLng={d => d.startLng}
              arcEndLat={d => d.endLat}
              arcEndLng={d => d.endLng}
              arcColor={d => d.color}
              arcAltitude={0.3}
              arcStroke={1.5}
              arcDashLength={0.5}
              arcDashGap={0.25}
              arcDashAnimateTime={2500}
              arcLabel={d => `<div style="font-family:'Share Tech Mono';font-size:10px;color:#00f3ff;background:rgba(2,13,26,0.9);padding:3px 7px;border:1px solid rgba(0,243,255,0.4);border-radius:2px">[LINK] → ${d.client?.city || d.client?.ip || 'CLIENT'}</div>`}

              // --- Points (server HQ + clients + islands) ---
              pointsData={pointsData}
              pointLat={d => d.lat}
              pointLng={d => d.lng}
              pointColor={d => d.color}
              pointAltitude={d => d.type === 'server' ? 0.08 : d.type === 'client' ? 0.05 : 0.02}
              pointRadius={d => d.size}
              pointResolution={8}
              pointsMerge={false}
              pointLabel={getPointLabel}

              // --- Rings (sonar pulse effect) ---
              ringsData={ringsData}
              ringLat={d => d.lat}
              ringLng={d => d.lng}
              ringMaxRadius={d => d.maxR}
              ringPropagationSpeed={d => d.propagationSpeed}
              ringRepeatPeriod={d => d.repeatPeriod}
              ringColor={d => t => `rgba(0,255,157,${1 - t})`}
              ringResolution={64}
              ringAltitude={0.003}

              // --- Labels (archipelago + server badges) ---
              labelsData={pointsData.filter(p => p.type === 'server' || p.type === 'island')}
              labelLat={d => d.lat}
              labelLng={d => d.lng}
              labelText={d => d.type === 'server' ? '[HQ]' : d.label}
              labelSize={d => d.type === 'server' ? 1.0 : 0.55}
              labelColor={d => d.type === 'server' ? '#00ff9d' : '#00f3ff'}
              labelAltitude={d => d.type === 'server' ? 0.12 : 0.06}
              labelResolution={2}
              labelDotRadius={d => d.type === 'server' ? 0.45 : 0.22}
              labelDotOrientation={() => 'bottom'}

              // --- Interaction ---
              onGlobeReady={() => {
                setLoading(false);
                // Apply initial camera
                globeRef.current?.pointOfView({ lat: 16.0, lng: 105.85, altitude: 2.2 }, 0);
                const controls = globeRef.current?.controls();
                if (controls) {
                  controls.autoRotate = true;
                  controls.autoRotateSpeed = 0.5;
                  controls.enableDamping = true;
                  controls.dampingFactor = 0.08;
                  controls.minDistance = 101; // prevent zooming inside the globe
                  controls.maxDistance = 800;
                }
              }}
              onPointClick={(point) => {
                if (point.type === 'client' && point.client) {
                  setSelectedNode(point.client);
                }
              }}
            />

            {/* Loading overlay */}
            {loading && (
              <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono', fontSize: '0.85rem', background: 'rgba(2,13,26,0.7)', pointerEvents: 'none' }}>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ marginBottom: '8px', fontSize: '1.2rem' }}>◈</div>
                  LOADING WORLD ATLAS DATA...
                </div>
              </div>
            )}

            {/* Tip overlay */}
            <div style={{ position: 'absolute', bottom: '12px', left: '16px', fontFamily: 'Share Tech Mono', fontSize: '0.72rem', color: 'rgba(255,255,255,0.45)', pointerEvents: 'none' }}>
              ✦ TIP: Drag to rotate 360° · Scroll wheel to Zoom · Click pins for details
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
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ width: '10px', height: '10px', borderRadius: '50%', background: '#00ff9d', display: 'inline-block', boxShadow: '0 0 6px #00ff9d' }} />
              <span>VIETNAM ISLANDS</span>
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
                  <div key={idx} onClick={() => {
                    setSelectedNode(conn);
                    const parsedLat = parseFloat(conn.lat);
                    const parsedLon = parseFloat(conn.lon);
                    if (Number.isFinite(parsedLat) && Number.isFinite(parsedLon) && (parsedLat !== 0 || parsedLon !== 0)) {
                      globeRef.current?.pointOfView({ lat: parsedLat, lng: parsedLon, altitude: 1.5 }, 800);
                    }
                  }} style={{
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