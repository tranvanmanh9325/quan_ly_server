import React, { useState, useEffect, useRef, useCallback, useMemo, useDeferredValue, useTransition } from 'react';
import axios from 'axios';
import Globe from 'react-globe.gl';
import * as THREE from 'three';
import { mesh } from 'topojson-client';
import { 
  SciFiGlobeIcon, SciFiRefreshIcon, SciFiPulseBadge, SciFiPlayIcon, SciFiStopIcon,
  SciFiSatelliteIcon, SciFiOrbitRingIcon, SciFiTargetLockIcon, SciFiServerNodeIcon, 
  SciFiUserNodesIcon, SciFiSpeedGaugeIcon, SciFiCameraResetIcon, SciFiCloseIcon
} from '../components/SciFiIcons';
import { VIETNAM_MARITIME_ISLANDS, VIETNAM_MARITIME_BOUNDARIES } from '../data/vietnamIslandsGeo';
import { SATELLITE_CATALOG, getSatellitePosition, getSatelliteOrbitPath } from '../data/satellitesData';
import { createSatellite3DObject, updateSatellite3DTransform } from '../utils/satelliteModelGenerator';
import GlobeHudLegend from '../components/GlobeHudLegend';
import SatelliteTelemetryCard from '../components/SatelliteTelemetryCard';

// 110m resolution: 105KB vs 756KB (50m) — 90% fewer border vertices, imperceptible at 600px canvas
const LOCAL_WORLD_ATLAS_URL = '/data/countries-110m.json';
const CDN_WORLD_ATLAS_URL = 'https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json';

// Resized 1024x512 local texture: 35KB vs 698KB — fits 600x440px canvas pixel-perfect
const EARTH_TEXTURE_URL = '/textures/earth-night-1024.jpg';

/**
 * Sets up Photorealistic NASA 3-Point Space Lighting in Three.js Scene.
 * Pure sunlight with specular highlights on Kapton foil + Earthshine albedo + Deep space ambient.
 */
function setupSpaceLighting(scene) {
  if (!scene) return null;

  // 1. PRIMARY SUNLIGHT (DirectionalLight 2.8 - Pure White Sunlight in Vacuum)
  const sunLight = new THREE.DirectionalLight(0xffffff, 2.8);
  sunLight.position.set(140, 70, 100);
  sunLight.userData = { isCustomSpaceLight: true };
  scene.add(sunLight);

  // 2. EARTHSHINE (DirectionalLight 0.85 - Ocean Blue Albedo reflected from Earth)
  const earthshineLight = new THREE.DirectionalLight(0x336699, 0.85);
  earthshineLight.position.set(-60, -80, -50);
  earthshineLight.userData = { isCustomSpaceLight: true };
  scene.add(earthshineLight);

  // 3. DEEP SPACE AMBIENT (AmbientLight 0.4 - Deep Space Navy base)
  const spaceAmbient = new THREE.AmbientLight(0x0f172a, 0.4);
  spaceAmbient.userData = { isCustomSpaceLight: true };
  scene.add(spaceAmbient);

  // 4. SELECTED TARGET POINTLIGHT (Spotlight for active tracked satellite)
  const targetPointLight = new THREE.PointLight(0x00f3ff, 0, 30, 2);
  targetPointLight.userData = { isCustomSpaceLight: true };
  scene.add(targetPointLight);

  return { sunLight, earthshineLight, spaceAmbient, targetPointLight };
}

/**
 * Calculates dynamic arc altitude based on Great-Circle chord distance
 * Short distances (Hanoi -> Nghe An) stay sleek and low (~0.035),
 * while long transcontinental links curve naturally up to 0.30.
 */
function getDynamicArcAltitude(lat1, lon1, lat2, lon2) {
  const toRad = Math.PI / 180;
  const phi1 = lat1 * toRad;
  const phi2 = lat2 * toRad;
  const deltaPhi = (lat2 - lat1) * toRad;
  const deltaLambda = (lon2 - lon1) * toRad;

  const a = Math.sin(deltaPhi / 2) ** 2 +
            Math.cos(phi1) * Math.cos(phi2) * (Math.sin(deltaLambda / 2) ** 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  const chordNormalized = Math.sin(c / 2);
  const altitude = 0.025 + 0.28 * Math.pow(chordNormalized, 0.7);
  return Math.min(Math.max(altitude, 0.025), 0.30);
}

export default function WorldMapPage() {
  const [geoData, setGeoData] = useState({ server: null, connections: [] });
  const [bordersData, setBordersData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState(null);
  const [selectedNode, setSelectedNode] = useState(null);
  const [autoRotate, setAutoRotate] = useState(true);
  const [rotationSpeed, setRotationSpeed] = useState(0.5);

  // Satellite Tracking & Orbit Controls
  const [showSatellites, setShowSatellites] = useState(true);
  const [showOrbits, setShowOrbits] = useState(true);
  const [selectedSatellite, setSelectedSatellite] = useState(null);

  // useDeferredValue: pass borders to Globe at low priority so first paint isn't blocked
  const deferredBorders = useDeferredValue(bordersData);
  const [, startBordersTransition] = useTransition();

  // Measured container dimensions — passed explicitly to Globe to prevent misalignment
  const [globeDimensions, setGlobeDimensions] = useState({ width: 600, height: 440 });

  const globeRef = useRef();
  const globeContainerRef = useRef();
  const lightingRefs = useRef(null);



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

  // Static Satellite Dataset — passed as static reference, 0 React re-renders
  const staticSatellitesData = useMemo(() => {
    return showSatellites ? SATELLITE_CATALOG : [];
  }, [showSatellites]);

  // Combined laser arcs: Client connections + Satellite C2 Downlink Lasers
  const combinedArcsData = useMemo(() => {
    const sLat = parseFloat(geoData.server?.lat) || 20.98;
    const sLon = parseFloat(geoData.server?.lon) || 105.83;

    // 1. Client connection arcs
    const arcs = (geoData.connections || []).map((client, idx) => {
      const parsedLat = parseFloat(client.lat);
      const parsedLon = parseFloat(client.lon);
      const hasGps = Number.isFinite(parsedLat) && Number.isFinite(parsedLon)
        && (parsedLat !== 0 || parsedLon !== 0);
      const endLat = hasGps ? parsedLat : sLat + 0.01;
      const endLng = hasGps ? parsedLon : sLon + 0.01;
      return {
        id: `client-arc-${idx}`,
        startLat: sLat, startLng: sLon,
        endLat, endLng,
        dynamicAltitude: getDynamicArcAltitude(sLat, sLon, endLat, endLng),
        client,
        // High-energy photon laser: transparent tips with bright neon cyan core
        color: ['rgba(0,243,255,0)', 'rgba(0,255,157,0.95)', 'rgba(0,243,255,0)'],
      };
    });

    // 2. Downlink laser from selected satellite (or VINASAT-1 by default when satellites shown)
    if (showSatellites) {
      const activeSat = selectedSatellite || SATELLITE_CATALOG[0]; // VINASAT-1
      if (activeSat) {
        const nowSec = Date.now() / 1000;
        const satPos = getSatellitePosition(activeSat, nowSec);
        arcs.push({
          id: `sat-downlink-${activeSat.id}`,
          startLat: satPos.lat,
          startLng: satPos.lng,
          endLat: sLat,
          endLng: sLon,
          dynamicAltitude: 0.22,
          color: ['rgba(0,243,255,0.1)', activeSat.color || '#00ff9d', 'rgba(0,255,157,0.95)'],
          isSatelliteDownlink: true,
        });
      }
    }

    return arcs;
  }, [geoData, showSatellites, selectedSatellite]);

  const pointsData = useMemo(() => {

    const points = [];
    const sLat = parseFloat(geoData.server?.lat) || 20.98;
    const sLon = parseFloat(geoData.server?.lon) || 105.83;

    points.push({ id: 'server', lat: sLat, lng: sLon, size: 0.5, color: '#00ff9d', type: 'server' });

    (geoData.connections || []).forEach((client, idx) => {
      const parsedLat = parseFloat(client.lat);
      const parsedLon = parseFloat(client.lon);
      const hasGps = Number.isFinite(parsedLat) && Number.isFinite(parsedLon)
        && (parsedLat !== 0 || parsedLon !== 0);
      if (hasGps) {
        points.push({ id: `client-${idx}`, lat: parsedLat, lng: parsedLon, size: 0.35, color: '#00f3ff', type: 'client', client });
      }
    });

    // All major and archipelago centers for VN islands
    VIETNAM_MARITIME_ISLANDS.forEach(item => {
      points.push({
        id: item.id, lat: item.lat, lng: item.lon,
        size: item.type === 'archipelago_cluster' ? 0.28 : 0.2,
        color: '#00ff9d', label: item.label, type: 'island',
      });
    });

    return points;
  }, [geoData]);

  // Combined paths data: Country borders + VN Maritime Patrol Perimeters + Satellite Orbits
  const combinedPathsData = useMemo(() => {
    const paths = [...deferredBorders, ...VIETNAM_MARITIME_BOUNDARIES];
    if (showOrbits) {
      SATELLITE_CATALOG.forEach(sat => {
        paths.push(getSatelliteOrbitPath(sat, 72));
      });
    }
    return paths;
  }, [deferredBorders, showOrbits]);


  // htmlElementsData: DOM overlay markers with Directional Anti-Collision Slotting
  const htmlMarkersData = useMemo(() => {
    const markers = [];
    const srv = geoData.server;
    if (!srv) return markers;

    const sLat = parseFloat(srv.lat) || 20.98;
    const sLon = parseFloat(srv.lon) || 105.83;

    // Server HQ marker — shoots Top-Right
    markers.push({
      id: 'hq',
      lat: sLat, lng: sLon,
      type: 'server',
      label: 'SERVER HQ // C2',
      sublabel: srv.city ? `${srv.city}, ${srv.country || 'VN'}` : 'Định Công, Hà Nội, VN',
      dir: 'top-right',
      color: '#00ff9d',
      glowColor: 'rgba(0,255,157,0.45)',
    });

    // Client callout markers with dynamic anti-collision direction
    (geoData.connections || []).forEach((client, idx) => {
      const parsedLat = parseFloat(client.lat);
      const parsedLon = parseFloat(client.lon);
      const hasGps = Number.isFinite(parsedLat) && Number.isFinite(parsedLon)
        && (parsedLat !== 0 || parsedLon !== 0);
      if (hasGps) {
        const dLat = parsedLat - sLat;
        const dLng = parsedLon - sLon;
        // Directional slotting: if node is south of server (e.g. Nghe An), shoot bottom-left
        let dir = 'bottom-left';
        if (Math.abs(dLat) < 6.0 && Math.abs(dLng) < 6.0) {
          dir = dLat < 0 ? (dLng >= 0 ? 'bottom-right' : 'bottom-left') : 'top-left';
        }

        markers.push({
          id: `client-${idx}`,
          lat: parsedLat, lng: parsedLon,
          type: 'client',
          label: `CLIENT // ${client.ip?.slice(-8) || 'NODE'}`,
          sublabel: client.city ? `${client.city}, ${client.country || ''}` : (client.ip || 'Unknown IP'),
          dir,
          color: '#00f3ff',
          glowColor: 'rgba(0,243,255,0.45)',
          client,
        });
      }
    });

    return markers;
  }, [geoData]);

  // Multi-Stage Sonar Waves (HQ Surveillance + Sovereign Maritime Radars)
  const ringsData = useMemo(() => {
    const sLat = parseFloat(geoData.server?.lat) || 20.98;
    const sLon = parseFloat(geoData.server?.lon) || 105.83;
    return [
      // 1. Server HQ Primary Long-Range Sonar
      {
        id: 'hq_primary',
        lat: sLat, lng: sLon,
        maxR: 4.5,
        propagationSpeed: 1.4,
        repeatPeriod: 1800,
        color: (t) => `rgba(0, 255, 157, ${Math.pow(1 - t, 2) * 0.75})`,
      },
      // 2. Server HQ High-Frequency Tactical Echo
      {
        id: 'hq_hf',
        lat: sLat, lng: sLon,
        maxR: 2.0,
        propagationSpeed: 1.0,
        repeatPeriod: 900,
        color: (t) => `rgba(0, 243, 255, ${Math.pow(1 - t, 1.5) * 0.85})`,
      },
      // 3. Quần đảo Hoàng Sa — Radar Hải quân
      {
        id: 'hoang_sa_radar',
        lat: 16.50, lng: 112.00,
        maxR: 2.6,
        propagationSpeed: 1.1,
        repeatPeriod: 2200,
        color: (t) => `rgba(0, 255, 157, ${Math.pow(1 - t, 2) * 0.6})`,
      },
      // 4. Quần đảo Trường Sa — Radar Hải quân
      {
        id: 'truong_sa_radar',
        lat: 9.80, lng: 114.00,
        maxR: 3.5,
        propagationSpeed: 1.2,
        repeatPeriod: 2600,
        color: (t) => `rgba(0, 255, 157, ${Math.pow(1 - t, 2) * 0.6})`,
      },
    ];
  }, [geoData.server]);

  const resetCamera = useCallback(() => {
    globeRef.current?.pointOfView({ lat: 16.0, lng: 105.85, altitude: 2.0 }, 800);
  }, []);

  const serverInfo = geoData.server || {};
  const connections = geoData.connections || [];

  const getPointLabel = useCallback((d) => {
    if (d.type === 'island') return `<div style="font-family:'Share Tech Mono',monospace;font-size:10px;color:#00ff9d;background:rgba(2,13,26,0.95);padding:3px 8px;border:1px solid rgba(0,255,157,0.4);border-radius:2px;letter-spacing:0.5px">◆ ${d.label}</div>`;
    return '';
  }, []);

  // Military CAD-style Dogleg Leader Line + Reticle Marker
  const createHtmlMarkerElement = useCallback((d) => {
    const isServer = d.type === 'server';
    const color = d.color;
    const glowColor = d.glowColor;
    const dir = d.dir || (isServer ? 'top-right' : 'bottom-left');

    const isTop = dir.startsWith('top');
    const isRight = dir.endsWith('right');
    const stemLen = 18;
    const shelfLen = isServer ? 115 : 95;

    const cardX = isRight ? stemLen + 2 : -(stemLen + shelfLen + 2);
    const cardY = isTop ? -(stemLen + 24) : (stemLen + 4);

    const el = document.createElement('div');
    el.style.cssText = `
      position: relative;
      pointer-events: none;
      user-select: none;
      font-family: 'Share Tech Mono', monospace;
    `;

    // Center target reticle at (0,0)
    const reticle = document.createElement('div');
    reticle.style.cssText = `
      position: absolute;
      top: 0; left: 0;
      width: 12px; height: 12px;
      transform: translate(-50%, -50%);
      pointer-events: auto;
      cursor: pointer;
    `;
    reticle.innerHTML = `
      <svg width="12" height="12" viewBox="0 0 12 12" style="overflow:visible">
        <circle cx="6" cy="6" r="4.5" fill="none" stroke="${color}" stroke-width="1" stroke-dasharray="3 2" opacity="0.85"/>
        <polygon points="6,2.5 8.5,6 6,9.5 3.5,6" fill="${color}"/>
      </svg>
    `;
    el.appendChild(reticle);

    // SVG Dogleg Leader Line
    const svgLine = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svgLine.style.cssText = `
      position: absolute;
      top: 0; left: 0;
      overflow: visible;
      pointer-events: none;
      filter: drop-shadow(0 0 3px ${glowColor});
    `;
    const dPath = isRight
      ? (isTop ? `M 0 0 L ${stemLen} ${-stemLen} L ${stemLen + shelfLen} ${-stemLen}` : `M 0 0 L ${stemLen} ${stemLen} L ${stemLen + shelfLen} ${stemLen}`)
      : (isTop ? `M 0 0 L ${-stemLen} ${-stemLen} L ${-(stemLen + shelfLen)} ${-stemLen}` : `M 0 0 L ${-stemLen} ${stemLen} L ${-(stemLen + shelfLen)} ${stemLen}`);

    svgLine.innerHTML = `
      <path d="${dPath}" fill="none" stroke="${color}" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>
      <circle cx="${isRight ? stemLen + shelfLen : -(stemLen + shelfLen)}" cy="${isTop ? -stemLen : stemLen}" r="1.8" fill="${color}"/>
    `;
    el.appendChild(svgLine);

    // Card attached on shelf
    const card = document.createElement('div');
    card.style.cssText = `
      position: absolute;
      left: ${cardX}px;
      top: ${cardY}px;
      width: ${shelfLen}px;
      background: linear-gradient(135deg, rgba(2,10,22,0.95) 0%, rgba(0,20,38,0.92) 100%);
      border: 1px solid ${color};
      border-left: 2.5px solid ${color};
      padding: 3px 6px;
      border-radius: 2px;
      box-shadow: 0 0 10px ${glowColor}, inset 0 0 8px rgba(0,0,0,0.8);
      white-space: nowrap;
      pointer-events: auto;
      cursor: pointer;
    `;

    card.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;gap:4px">
        <span style="font-size:${isServer ? '9px' : '8px'};font-weight:bold;color:${color};letter-spacing:0.8px">${d.label}</span>
        <span style="display:inline-block;width:4px;height:4px;border-radius:50%;background:${color};box-shadow:0 0 4px ${color}"></span>
      </div>
      ${d.sublabel ? `<div style="font-size:7.5px;color:rgba(255,255,255,0.7);letter-spacing:0.4px;overflow:hidden;text-overflow:ellipsis;margin-top:1px">${d.sublabel}</div>` : ''}
    `;

    card.onclick = (e) => {
      e.stopPropagation();
      if (d.client) setSelectedNode(d.client);
      globeRef.current?.pointOfView({ lat: d.lat, lng: d.lng, altitude: 1.6 }, 800);
    };

    el.appendChild(card);
    return el;
  }, []);

  // 3D Procedural Satellite Object Factory for react-globe.gl
  const renderSatelliteObject = useCallback((sat) => {
    return createSatellite3DObject(sat, 1.4);
  }, []);

  // In-Place 3D Coordinate Mutator for Three.js (Zero React Re-render overhead)
  const updateSatelliteObject = useCallback((obj, sat) => {
    if (!globeRef.current || !obj) return;
    const nowSec = Date.now() / 1000;
    const pos = getSatellitePosition(sat, nowSec);
    if (!pos) return;

    const coords = globeRef.current.getCoords(pos.lat, pos.lng, pos.altitude);
    if (coords) {
      const isSelected = selectedSatellite?.id === sat.id;
      updateSatellite3DTransform(obj, sat, coords, isSelected, lightingRefs.current?.targetPointLight);
    }
  }, [selectedSatellite]);

  // Zero-Re-render High-Performance Animation Loop for 60 FPS on Intel HD 4400
  useEffect(() => {
    if (!showSatellites) return;
    let animFrameId;
    const frameTicker = () => {
      if (globeRef.current) {
        // Triggers in-place update for customThreeObject without recreating mesh
        globeRef.current.customLayerData(staticSatellitesData);
      }
      animFrameId = requestAnimationFrame(frameTicker);
    };
    animFrameId = requestAnimationFrame(frameTicker);
    return () => cancelAnimationFrame(animFrameId);
  }, [showSatellites, staticSatellitesData]);

  // Smooth camera tracking to satellite sub-point
  const handleTrackSatellite = useCallback((sat) => {
    if (!sat || !globeRef.current) return;
    const pos = getSatellitePosition(sat, Date.now() / 1000);
    if (pos) {
      globeRef.current.pointOfView({ lat: pos.lat, lng: pos.lng, altitude: 1.8 }, 1000);
    }
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
        if (obj.isLight && !obj.userData?.isCustomSpaceLight) obj.castShadow = false;
        if (obj.isMesh) { obj.castShadow = false; obj.receiveShadow = false; }
      });

      // Initialize Photorealistic NASA 3-Point Space Lighting
      lightingRefs.current = setupSpaceLighting(scene);
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
          <span>[ALERT] {errorMsg}</span>
          <button onClick={() => setErrorMsg(null)} style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', display: 'flex', alignItems: 'center' }}>
            <SciFiCloseIcon size={13} color="var(--accent-pink)" />
          </button>
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
          <button onClick={() => setShowSatellites(prev => !prev)} style={{
            background: showSatellites ? 'rgba(255, 230, 0, 0.15)' : 'rgba(255,255,255,0.08)',
            border: showSatellites ? '1px solid #ffe600' : '1px solid rgba(255,255,255,0.2)',
            color: showSatellites ? '#ffe600' : '#ccc', padding: '4px 9px',
            fontFamily: 'Share Tech Mono', fontSize: '0.72rem', fontWeight: 'bold',
            cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px', borderRadius: '3px',
          }}>
            <SciFiSatelliteIcon size={14} color={showSatellites ? '#ffe600' : '#ccc'} />
            <span>SATS: {showSatellites ? 'ON' : 'OFF'}</span>
          </button>
          <button onClick={() => setShowOrbits(prev => !prev)} style={{
            background: showOrbits ? 'rgba(0, 243, 255, 0.15)' : 'rgba(255,255,255,0.08)',
            border: showOrbits ? '1px solid var(--accent-cyan)' : '1px solid rgba(255,255,255,0.2)',
            color: showOrbits ? 'var(--accent-cyan)' : '#ccc', padding: '4px 9px',
            fontFamily: 'Share Tech Mono', fontSize: '0.72rem', fontWeight: 'bold',
            cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px', borderRadius: '3px',
          }}>
            <SciFiOrbitRingIcon size={14} color={showOrbits ? 'var(--accent-cyan)' : '#ccc'} />
            <span>ORBITS: {showOrbits ? 'ON' : 'OFF'}</span>
          </button>
          <button onClick={() => setAutoRotate(!autoRotate)} style={{
            background: autoRotate ? 'rgba(0, 255, 157, 0.15)' : 'rgba(255,255,255,0.08)',
            border: autoRotate ? '1px solid var(--accent-green)' : '1px solid rgba(255,255,255,0.2)',
            color: autoRotate ? 'var(--accent-green)' : '#ccc', padding: '4px 9px',
            fontFamily: 'Share Tech Mono', fontSize: '0.72rem', fontWeight: 'bold',
            cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '5px', borderRadius: '3px',
          }}>
            {autoRotate ? <SciFiStopIcon size={9} color="var(--accent-green)" /> : <SciFiPlayIcon size={9} color="#ccc" />}
            <span>ROTATE: {autoRotate ? 'ON' : 'OFF'}</span>
          </button>
          <button onClick={() => setRotationSpeed(prev => prev === 0.5 ? 1.0 : prev === 1.0 ? 2.0 : 0.5)} style={{
            background: 'rgba(0, 243, 255, 0.08)', border: '1px solid var(--accent-cyan)',
            color: 'var(--accent-cyan)', padding: '4px 9px', fontFamily: 'Share Tech Mono',
            fontSize: '0.72rem', fontWeight: 'bold', cursor: 'pointer', borderRadius: '3px',
            display: 'flex', alignItems: 'center', gap: '5px',
          }}>
            <SciFiSpeedGaugeIcon size={13} color="var(--accent-cyan)" />
            <span>SPD: {rotationSpeed === 0.5 ? '1X' : rotationSpeed === 1.0 ? '2X' : '3X'}</span>
          </button>
          <button onClick={resetCamera} style={{
            background: 'rgba(0, 243, 255, 0.08)', border: '1px solid var(--accent-cyan)',
            color: 'var(--accent-cyan)', padding: '4px 9px', fontFamily: 'Share Tech Mono',
            fontSize: '0.72rem', fontWeight: 'bold', cursor: 'pointer', borderRadius: '3px',
            display: 'flex', alignItems: 'center', gap: '5px',
          }}>
            <SciFiCameraResetIcon size={13} color="var(--accent-cyan)" />
            <span>RESET</span>
          </button>
          <button onClick={fetchGeolocationData} disabled={loading} style={{
            background: 'rgba(0, 243, 255, 0.08)', border: '1px solid var(--accent-cyan)',
            color: 'var(--accent-cyan)', padding: '4px 10px', fontFamily: 'Share Tech Mono',
            fontSize: '0.72rem', fontWeight: 'bold', cursor: 'pointer',
            display: 'flex', alignItems: 'center', gap: '5px', borderRadius: '3px',
          }}>
            <SciFiRefreshIcon size={11} color="var(--accent-cyan)" />
            <span>{loading ? 'SCANNING...' : 'RE-SCAN'}</span>
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

              // combinedPathsData: country borders + VN Maritime Patrol Perimeters + Satellite Orbit trails
              pathsData={combinedPathsData}
              pathPoints={d => d.coords}
              pathPointLat={p => p[0]}
              pathPointLng={p => p[1]}
              pathPointAlt={p => p[2] || 0}
              pathColor={d => d.color || 'rgba(0, 243, 255, 0.45)'}
              pathStroke={d => d.stroke || 0.45}
              pathDashLength={d => d.dashLength || 1}
              pathDashGap={d => d.dashGap || 0}
              pathTransitionDuration={0}

              // combinedArcsData: Client telemetry arcs + Satellite C2 Downlink Lasers
              arcsData={combinedArcsData}
              arcStartLat={d => d.startLat}
              arcStartLng={d => d.startLng}
              arcEndLat={d => d.endLat}
              arcEndLng={d => d.endLng}
              arcColor={d => d.color}
              arcAltitude={d => d.dynamicAltitude || 0.1}
              arcStroke={0.22}
              arcDashLength={0.35}
              arcDashGap={0.65}
              arcDashAnimateTime={1800}

              // ── 3D Photorealistic Satellites Custom Layer (Zero Re-render 60 FPS) ──
              customLayerData={staticSatellitesData}
              customThreeObject={renderSatelliteObject}
              customThreeObjectUpdate={updateSatelliteObject}
              onCustomLayerClick={(sat) => {
                setSelectedSatellite(sat);
                handleTrackSatellite(sat);
              }}

              // Throttle raycasting — only raycast 'point' and 'custom' objects
              pointerEventsFilter={obj => obj.__globeObjType === 'point' || obj.__globeObjType === 'custom'}


              pointsData={pointsData}
              pointLat={d => d.lat}
              pointLng={d => d.lng}
              pointColor={d => d.color}
              pointAltitude={d => d.type === 'server' ? 0.04 : d.type === 'client' ? 0.03 : 0.005}
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
              ringColor={d => (typeof d.color === 'function' ? d.color : (t => `rgba(0,255,157,${(1 - t) * 0.7})`))}
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

            {/* Satellite Telemetry HUD Card Overlay */}
            {selectedSatellite && (
              <SatelliteTelemetryCard
                satellite={selectedSatellite}
                onClose={() => setSelectedSatellite(null)}
                onTrackCamera={handleTrackSatellite}
              />
            )}



            {loading && (
              <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono', fontSize: '0.8rem', background: 'rgba(2,13,26,0.8)', pointerEvents: 'none' }}>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ marginBottom: '5px', fontSize: '1rem' }}>◈</div>
                  LOADING WORLD ATLAS...
                </div>
              </div>
            )}

            <div style={{ position: 'absolute', bottom: '8px', left: '12px', fontFamily: 'Share Tech Mono', fontSize: '0.65rem', color: 'rgba(255,255,255,0.35)', pointerEvents: 'none' }}>
              DRAG: ROTATE · SCROLL: ZOOM · CLICK: TARGET
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
            <div style={{ fontSize: '0.78rem', color: 'var(--accent-green)', fontFamily: 'Share Tech Mono', fontWeight: 'bold', borderBottom: '1px solid rgba(0, 255, 157, 0.2)', paddingBottom: '5px', display: 'flex', alignItems: 'center', gap: '7px' }}>
              <SciFiServerNodeIcon size={14} color="var(--accent-green)" />
              <span>SERVER HQ TELEMETRY</span>
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
              <div style={{ display: 'flex', alignItems: 'center', gap: '7px' }}>
                <SciFiUserNodesIcon size={14} color="var(--accent-cyan)" />
                <span>CONNECTED NODES ({connections.length})</span>
              </div>
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

          {/* Satellite Constellation Quick Selector Panel */}
          <div className="glass-panel" style={{ flex: 1, padding: '12px', display: 'flex', flexDirection: 'column', gap: '8px', overflow: 'hidden', minHeight: '160px' }}>
            <div style={{ fontSize: '0.78rem', color: '#ffe600', fontFamily: 'Share Tech Mono', fontWeight: 'bold', borderBottom: '1px solid rgba(255, 230, 0, 0.2)', paddingBottom: '5px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '7px' }}>
                <SciFiSatelliteIcon size={14} color="#ffe600" />
                <span>SATELLITES ({SATELLITE_CATALOG.length})</span>
              </div>
              <span style={{ fontSize: '0.62rem', color: 'rgba(255,255,255,0.5)' }}>C2 TRACKING</span>
            </div>
            <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {SATELLITE_CATALOG.map((sat) => {
                const isSelected = selectedSatellite?.id === sat.id;
                const satColor = sat.color || '#00ff9d';
                return (
                  <div
                    key={sat.id}
                    onClick={() => {
                      setSelectedSatellite(sat);
                      handleTrackSatellite(sat);
                    }}
                    style={{
                      background: isSelected ? 'rgba(255, 230, 0, 0.12)' : 'rgba(0,0,0,0.35)',
                      border: isSelected ? `1px solid ${satColor}` : '1px solid rgba(255,255,255,0.08)',
                      borderLeft: `2.5px solid ${satColor}`,
                      padding: '5px 8px',
                      borderRadius: '3px',
                      cursor: 'pointer',
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      fontSize: '0.7rem',
                      fontFamily: 'Share Tech Mono',
                      transition: 'all 0.2s',
                    }}
                  >
                    <div>
                      <div style={{ color: '#fff', fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: '5px' }}>
                        <span style={{ width: '4px', height: '4px', borderRadius: '50%', background: satColor, boxShadow: `0 0 4px ${satColor}` }} />
                        {sat.name}
                      </div>
                      <div style={{ fontSize: '0.62rem', color: 'rgba(255,255,255,0.5)', marginTop: '1px' }}>
                        {sat.type} · {sat.altitudeKm.toLocaleString()} km · {sat.country.split(' ')[0]}
                      </div>
                    </div>
                    <span style={{
                      fontSize: '0.58rem',
                      color: isSelected ? '#020d1a' : satColor,
                      background: isSelected ? satColor : 'rgba(255,255,255,0.05)',
                      padding: '1px 5px',
                      borderRadius: '2px',
                      fontWeight: 'bold',
                    }}>
                      {isSelected ? 'TRACKED' : sat.type}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>

        </div>
      </div>

    </div>
  );
}
