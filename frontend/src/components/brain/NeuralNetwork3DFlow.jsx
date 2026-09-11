import React, { useEffect, useRef, useState, useCallback } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import {
  SciFiCognitivePulseBurstIcon,
  SciFiZoomInIcon,
  SciFiZoomOutIcon,
  SciFiFullscreenExpandIcon,
  SciFiFullscreenExitIcon,
} from './BrainSciFiIcons';

/**
 * NeuromorphicBrainConnectome (NeuralNetwork3DFlow)
 * Scientific 3D Brain & Cognitive Connectome Visualizer for Tiểu Bảo Bảo.
 * 
 * Complies with International Computational Neuroscience & HCP Standards:
 * 1. Parametric Dual-Hemisphere Cortical Point Cloud: 10,500+ cortical neurons
 *    with anatomically realistic gyri and sulci folds and longitudinal fissure.
 * 2. HCP-Standard DTI Tractography (Fractional Anisotropy FA Color Standard):
 *    - Red (X-axis): Corpus Callosum commissural tracts bridging hemispheres.
 *    - Green (Y-axis): Superior Longitudinal Fasciculus (Frontal <-> Occipital).
 *    - Blue (Z-axis): Corticospinal Projection Tracts (Cortex -> Thalamus -> Brainstem).
 * 3. Soliton Wavefront Action Potential: Organic depolarization wave sweeping
 *    along axonal pathways, with high-speed photon particles streaming through tracts.
 * 4. Cognitive Architecture Mapping: Prefrontal (Working Memory), Neocortex (32GB Virtual Memory),
 *    Thalamus (Global Workspace), Hippocampus (Dream Engine), Hypothalamus/Brainstem (Neurochemistry).
 */

const COGNITIVE_ZONES = [
  {
    id: 'prefrontal',
    name: 'PREFRONTAL CORTEX',
    role: 'Working Memory (Miller 7 Slots)',
    center: new THREE.Vector3(0, 20, 105),
    color: '#00f3ff',
    tensor: 'Tokens [1, 512, 4096]',
    desc: 'Điều hành trung tâm, lập kế hoạch và duy trì 7 ngăn nhớ làm việc.',
  },
  {
    id: 'neocortex',
    name: 'PARIETAL NEOCORTEX',
    role: '32GB Virtual Memory (VSA)',
    center: new THREE.Vector3(0, 92, 10),
    color: '#bd00ff',
    tensor: '10,000-Bit HyperVectors',
    desc: 'Vỏ não ảo siêu không gian, truy xuất liên tưởng không chiếm dụng RAM vật lý.',
  },
  {
    id: 'thalamus',
    name: 'CENTRAL THALAMUS',
    role: 'Global Workspace Hub',
    center: new THREE.Vector3(0, 10, -10),
    color: '#ffd700',
    tensor: 'Salience Arb [S ≥ 0.65]',
    desc: 'Hạt nhân điều phối sự chú ý và luồng phát thanh ý thức toàn cầu.',
  },
  {
    id: 'hippocampus',
    name: 'LIMBIC HIPPOCAMPUS',
    role: 'Episodic Memory / Dream Engine',
    center: new THREE.Vector3(0, -22, -20),
    color: '#00ff9d',
    tensor: 'SWS/REM Consolidation',
    desc: 'Củng cố ký ức phân đoạn, tinh thể hóa tri thức qua chu kỳ ngủ đêm.',
  },
  {
    id: 'brainstem',
    name: 'HYPOTHALAMUS & BRAINSTEM',
    role: 'Sensory Bus & Neurochemistry',
    center: new THREE.Vector3(0, -38, -105),
    color: '#ff3366',
    tensor: 'DA / 5-HT / NE / CORT',
    desc: 'Trục điều hòa 6 chất dẫn truyền thần kinh sinh học và cân bằng nội môi.',
  },
];

export default function NeuralNetwork3DFlow({
  onTriggerPulse,
  pulseTrigger = 0,
  telemetry = null,
}) {
  const mountRef = useRef(null);
  const containerRef = useRef(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [activeZone, setActiveZone] = useState(COGNITIVE_ZONES[0]);
  const [activePreset, setActivePreset] = useState('perspective');
  const [autoRotate, setAutoRotate] = useState(false);
  const [pulseActive, setPulseActive] = useState(false);
  const [pulsePct, setPulsePct] = useState(0);

  const freeEnergy = telemetry?.active_inference?.free_energy;
  const totalPulses = telemetry?.total_pulses;

  // References for Three.js state
  const sceneRef = useRef(null);
  const cameraRef = useRef(null);
  const rendererRef = useRef(null);
  const controlsRef = useRef(null);
  const waveStateRef = useRef({ active: false, progress: 0, speed: 0.35 });
  const pulseParticlesRef = useRef(null);
  const neuronPointsRef = useRef(null);
  const cameraTweenRef = useRef({ active: false, targetPos: new THREE.Vector3(220, 140, 240) });

  // Update autoRotate directly on controls
  useEffect(() => {
    if (controlsRef.current) {
      controlsRef.current.autoRotate = autoRotate;
      controlsRef.current.autoRotateSpeed = 0.85;
    }
  }, [autoRotate]);

  // Set camera to preset angles with smooth flight interpolation
  const applyCameraPreset = useCallback((preset) => {
    if (!cameraRef.current || !controlsRef.current) return;
    setActivePreset(preset);
    const controls = controlsRef.current;
    controls.target.set(0, 15, 0);

    let targetPos = new THREE.Vector3(220, 140, 240);
    if (preset === 'perspective') {
      targetPos = new THREE.Vector3(220, 140, 240);
    } else if (preset === 'lateral') {
      targetPos = new THREE.Vector3(330, 20, 0);
    } else if (preset === 'top') {
      targetPos = new THREE.Vector3(0, 350, 10);
    } else if (preset === 'frontal') {
      targetPos = new THREE.Vector3(0, 30, 330);
    }
    cameraTweenRef.current = { active: true, targetPos };
  }, []);

  // Zoom control helper
  const handleZoom = useCallback((factor) => {
    if (!cameraRef.current || !controlsRef.current) return;
    const camera = cameraRef.current;
    const controls = controlsRef.current;
    const offset = camera.position.clone().sub(controls.target);
    offset.multiplyScalar(factor);
    if (offset.length() > 90 && offset.length() < 900) {
      camera.position.copy(controls.target).add(offset);
      controls.update();
    }
  }, []);

  // Trigger Action Potential Wavefront
  const fireActionPotential = useCallback(() => {
    waveStateRef.current.active = true;
    waveStateRef.current.progress = 0;
    setPulseActive(true);
    if (onTriggerPulse) onTriggerPulse();
  }, [onTriggerPulse]);

  // Expose global trigger for automated test verification
  useEffect(() => {
    window.__triggerBrainPulse = fireActionPotential;
    return () => {
      delete window.__triggerBrainPulse;
    };
  }, [fireActionPotential]);

  // Watch external pulseTrigger prop
  useEffect(() => {
    if (pulseTrigger > 0) {
      waveStateRef.current.active = true;
      waveStateRef.current.progress = 0;
      const timer = setTimeout(() => {
        setPulseActive(true);
      }, 0);
      return () => clearTimeout(timer);
    }
  }, [pulseTrigger]);

  // Toggle fullscreen mode
  const toggleFullscreen = () => {
    if (!containerRef.current) return;
    if (!document.fullscreenElement) {
      containerRef.current.requestFullscreen().catch(() => {});
      setIsFullscreen(true);
    } else {
      document.exitFullscreen().catch(() => {});
      setIsFullscreen(false);
    }
  };

  useEffect(() => {
    const handleFsChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
    };
    document.addEventListener('fullscreenchange', handleFsChange);
    return () => document.removeEventListener('fullscreenchange', handleFsChange);
  }, []);

  // Enable direct wheel zoom only in fullscreen mode
  useEffect(() => {
    if (controlsRef.current) {
      controlsRef.current.enableZoom = isFullscreen;
    }
  }, [isFullscreen]);

  // ── Three.js Scene Setup ──────────────────────────────────────────────────
  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    const width = mount.clientWidth || 900;
    const height = mount.clientHeight || 560;

    // 1. Scene & Camera Setup
    const scene = new THREE.Scene();
    sceneRef.current = scene;
    scene.background = new THREE.Color(0x040711); // Deep scientific cosmic slate
    scene.fog = new THREE.FogExp2(0x040711, 0.0016);

    const camera = new THREE.PerspectiveCamera(45, width / height, 1, 2500);
    camera.position.set(220, 140, 240);
    cameraRef.current = camera;

    // 2. High-Performance WebGL Renderer
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: 'high-performance' });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    mount.appendChild(renderer.domElement);
    rendererRef.current = renderer;

    // 3. Precision OrbitControls
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.06;
    controls.maxDistance = 850;
    controls.minDistance = 90;
    controls.enableZoom = false; // Free normal page scrolling
    controls.target.set(0, 15, 0);
    controlsRef.current = controls;

    // Ctrl + mouse wheel for precision 3D zooming without blocking normal page scrolling
    const handleDomWheel = (e) => {
      if (e.ctrlKey && cameraRef.current && controlsRef.current) {
        e.preventDefault();
        const factor = e.deltaY > 0 ? 1.08 : 0.92;
        const offset = cameraRef.current.position.clone().sub(controlsRef.current.target);
        offset.multiplyScalar(factor);
        if (offset.length() > 90 && offset.length() < 900) {
          cameraRef.current.position.copy(controlsRef.current.target).add(offset);
          controlsRef.current.update();
        }
      }
    };
    renderer.domElement.addEventListener('wheel', handleDomWheel, { passive: false });

    // 4. Lighting & Ambient Ambiance
    const ambientLight = new THREE.AmbientLight(0x334155, 1.4);
    scene.add(ambientLight);

    const frontalLight = new THREE.PointLight(0x00f3ff, 2.6, 500);
    frontalLight.position.set(0, 80, 180);
    scene.add(frontalLight);

    const parietalLight = new THREE.PointLight(0xbd00ff, 2.2, 500);
    parietalLight.position.set(0, 160, 0);
    scene.add(parietalLight);

    const occipitalLight = new THREE.PointLight(0x00ff9d, 1.8, 450);
    occipitalLight.position.set(0, -60, -180);
    scene.add(occipitalLight);

    // 5. Build Procedural Dual-Hemisphere Cortical Point Cloud
    const neuronCount = 10800;
    const neuronPositions = new Float32Array(neuronCount * 3);
    const neuronColors = new Float32Array(neuronCount * 3);
    const neuronBaseColors = new Float32Array(neuronCount * 3);

    const colPrefrontal = new THREE.Color('#00f3ff');
    const colNeocortex = new THREE.Color('#bd00ff');
    const colHippocampus = new THREE.Color('#00ff9d');
    const colOccipital = new THREE.Color('#38bdf8');

    let idx = 0;
    while (idx < neuronCount) {
      const hemisphere = Math.random() > 0.5 ? 1 : -1;
      const u = Math.random();
      const v = Math.random();
      const theta = u * 2.0 * Math.PI;
      const phi = Math.acos(2.0 * v - 1.0);

      // Anatomical dimensions of human brain ellipsoids
      const rX = 64 + Math.sin(phi * 4.0) * 4.0;
      const rY = 56 + Math.cos(theta * 3.0) * 3.5;
      const rZ = 86 + Math.sin(theta * 2.0) * 5.0;

      // Surface radius with sulcal/gyral procedural folding
      const gyrusPerturbation = 1.0 + 0.12 * Math.sin(theta * 8.0) * Math.cos(phi * 8.0);
      const radiusFactor = (0.55 + 0.45 * Math.cbrt(Math.random())) * gyrusPerturbation;

      let x = radiusFactor * rX * Math.sin(phi) * Math.cos(theta);
      let y = radiusFactor * rY * Math.sin(phi) * Math.sin(theta);
      let z = radiusFactor * rZ * Math.cos(phi);

      // Separation of left and right hemispheres (Longitudinal Fissure)
      const fissureGap = 4.8;
      x = hemisphere * (Math.abs(x) + fissureGap);

      // Anatomical vertical tilt & brain stem taper
      if (z < -38) {
        x *= 0.76;
        y -= (Math.abs(z) - 38) * 0.26;
      }

      neuronPositions[idx * 3] = x;
      neuronPositions[idx * 3 + 1] = y + 20;
      neuronPositions[idx * 3 + 2] = z;

      // Color coding based on functional cortical regions
      let c;
      if (z > 40) {
        c = colPrefrontal; // Frontal Lobe
      } else if (y > 35) {
        c = colNeocortex; // Parietal Neocortex
      } else if (y < 0 && Math.abs(z) < 35) {
        c = colHippocampus; // Deep Limbic / Hippocampus
      } else {
        c = colOccipital; // Occipital & Sensory
      }

      const lum = 0.65 + Math.random() * 0.35;
      neuronColors[idx * 3] = c.r * lum;
      neuronColors[idx * 3 + 1] = c.g * lum;
      neuronColors[idx * 3 + 2] = c.b * lum;

      neuronBaseColors[idx * 3] = c.r * lum;
      neuronBaseColors[idx * 3 + 1] = c.g * lum;
      neuronBaseColors[idx * 3 + 2] = c.b * lum;

      idx++;
    }

    const neuronGeo = new THREE.BufferGeometry();
    neuronGeo.setAttribute('position', new THREE.BufferAttribute(neuronPositions, 3));
    neuronGeo.setAttribute('color', new THREE.BufferAttribute(neuronColors, 3));

    const neuronMat = new THREE.PointsMaterial({
      size: 3.2,
      vertexColors: true,
      transparent: true,
      opacity: 0.82,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const neuronCloud = new THREE.Points(neuronGeo, neuronMat);
    scene.add(neuronCloud);
    neuronPointsRef.current = { geo: neuronGeo, baseColors: neuronBaseColors };

    // 6. Build HCP-Standard DTI Tractography Axonal Fiber Bundles
    // RGB Orientation Mapping: Red = L-R (X), Green = A-P (Y), Blue = S-I (Z)
    const tractSplines = [];
    const tractPoints = [];
    const tractColors = [];

    const addDtiTract = (controlPoints, subFibers = 6, spread = 3.2) => {
      const curve = new THREE.CatmullRomCurve3(controlPoints);
      tractSplines.push(curve);

      for (let s = 0; s < subFibers; s++) {
        const jitter = new THREE.Vector3(
          (Math.random() - 0.5) * spread,
          (Math.random() - 0.5) * spread,
          (Math.random() - 0.5) * spread
        );

        const subPts = curve.getPoints(36).map((pt) => pt.clone().add(jitter));

        for (let p = 0; p < subPts.length - 1; p++) {
          const p0 = subPts[p];
          const p1 = subPts[p + 1];

          // Compute fiber vector direction for DTI FA coloring
          const dir = p1.clone().sub(p0).normalize();
          const dtiRed = Math.abs(dir.x);   // Left-Right commissural (Red)
          const dtiGreen = Math.abs(dir.z); // Anterior-Posterior association (Green)
          const dtiBlue = Math.abs(dir.y);  // Superior-Inferior projection (Blue)

          tractPoints.push(p0.x, p0.y, p0.z);
          tractPoints.push(p1.x, p1.y, p1.z);

          const brightness = 0.58;
          tractColors.push(dtiRed * brightness, dtiGreen * brightness, dtiBlue * brightness);
          tractColors.push(dtiRed * brightness, dtiGreen * brightness, dtiBlue * brightness);
        }
      }
    };

    // Bundle 1: Corpus Callosum (Red commissural arch linking left and right hemispheres)
    for (let c = -42; c <= 42; c += 14) {
      addDtiTract([
        new THREE.Vector3(-46, 25, c),
        new THREE.Vector3(-22, 54, c),
        new THREE.Vector3(22, 54, c),
        new THREE.Vector3(46, 25, c),
      ], 8, 3.8);
    }

    // Bundle 2: Superior Longitudinal Fasciculus (Green association stream Frontal <-> Occipital)
    [-1, 1].forEach((side) => {
      addDtiTract([
        new THREE.Vector3(side * 28, 25, 96),
        new THREE.Vector3(side * 42, 60, 24),
        new THREE.Vector3(side * 38, 54, -46),
        new THREE.Vector3(side * 22, 10, -92),
      ], 10, 4.5);
    });

    // Bundle 3: Corticospinal Projection Tract (Blue projection stream Cortex -> Thalamus -> Brainstem)
    [-1, 1].forEach((side) => {
      addDtiTract([
        new THREE.Vector3(side * 36, 76, 10),
        new THREE.Vector3(side * 18, 40, 0),
        new THREE.Vector3(side * 8, 6, -16),
        new THREE.Vector3(0, -36, -52),
      ], 8, 3.2);
    });

    const tractGeo = new THREE.BufferGeometry();
    tractGeo.setAttribute('position', new THREE.Float32BufferAttribute(tractPoints, 3));
    tractGeo.setAttribute('color', new THREE.Float32BufferAttribute(tractColors, 3));

    const tractMat = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: 0.48,
      blending: THREE.AdditiveBlending,
    });
    const tractMesh = new THREE.LineSegments(tractGeo, tractMat);
    scene.add(tractMesh);

    // 7. Action Potential Photon Particles (Soliton Wave along Axons)
    const particleCount = 260;
    const particlePositions = new Float32Array(particleCount * 3);
    const particleProgress = new Float32Array(particleCount);
    const particleSplines = [];

    for (let i = 0; i < particleCount; i++) {
      particleProgress[i] = Math.random();
      const chosenSpline = tractSplines[Math.floor(Math.random() * tractSplines.length)];
      particleSplines.push(chosenSpline);
      const pt = chosenSpline.getPoint(particleProgress[i]);
      particlePositions[i * 3] = pt.x;
      particlePositions[i * 3 + 1] = pt.y;
      particlePositions[i * 3 + 2] = pt.z;
    }

    const particleGeo = new THREE.BufferGeometry();
    particleGeo.setAttribute('position', new THREE.BufferAttribute(particlePositions, 3));
    const particleMat = new THREE.PointsMaterial({
      color: 0xffffff,
      size: 4.8,
      transparent: true,
      opacity: 0.92,
      blending: THREE.AdditiveBlending,
    });
    const particleSystem = new THREE.Points(particleGeo, particleMat);
    scene.add(particleSystem);
    pulseParticlesRef.current = { geo: particleGeo, splines: particleSplines, progress: particleProgress };

    // 8. Interactive Zone Anchors (Cognitive Hologram Rings)
    const zoneGroup = new THREE.Group();
    COGNITIVE_ZONES.forEach((zone) => {
      const ringGeo = new THREE.RingGeometry(5.5, 7.2, 32);
      const ringMat = new THREE.MeshBasicMaterial({
        color: new THREE.Color(zone.color),
        side: THREE.DoubleSide,
        transparent: true,
        opacity: 0.7,
      });
      const ringMesh = new THREE.Mesh(ringGeo, ringMat);
      ringMesh.position.copy(zone.center);
      ringMesh.lookAt(camera.position);
      zoneGroup.add(ringMesh);
    });
    scene.add(zoneGroup);

    // 9. Animation Loop (Smooth 60 FPS)
    let animId;
    const clock = new THREE.Clock();

    const animate = () => {
      animId = requestAnimationFrame(animate);
      const delta = clock.getDelta();
      const time = clock.getElapsedTime();

      // Smooth camera tween
      if (cameraTweenRef.current.active) {
        camera.position.lerp(cameraTweenRef.current.targetPos, 0.05);
        if (camera.position.distanceTo(cameraTweenRef.current.targetPos) < 1.0) {
          cameraTweenRef.current.active = false;
        }
      }

      controls.update();

      // Subtle organic rotation when autoRotate is OFF
      if (!autoRotate) {
        scene.rotation.y = time * 0.04;
      }

      // Keep zone rings facing camera
      zoneGroup.children.forEach((mesh) => {
        mesh.lookAt(camera.position);
      });

      // Update particle stream along tracts
      const pPositions = particleGeo.attributes.position.array;
      const isWaveActive = waveStateRef.current.active;
      const speedMultiplier = isWaveActive ? 0.038 : 0.007;

      for (let i = 0; i < particleCount; i++) {
        particleProgress[i] = (particleProgress[i] + speedMultiplier) % 1.0;
        const curCurve = particleSplines[i];
        if (curCurve) {
          const pt = curCurve.getPoint(particleProgress[i]);
          pPositions[i * 3] = pt.x;
          pPositions[i * 3 + 1] = pt.y;
          pPositions[i * 3 + 2] = pt.z;
        }
      }
      particleGeo.attributes.position.needsUpdate = true;

      // Update Soliton Wavefront Propagation
      if (isWaveActive) {
        waveStateRef.current.progress += delta / 2.0;
        const prog = waveStateRef.current.progress;
        setPulsePct(Math.min(100, Math.round(prog * 100)));

        if (prog >= 1.0) {
          waveStateRef.current.active = false;
          waveStateRef.current.progress = 0;
          setPulseActive(false);
          setPulsePct(0);

          // Restore neuron colors
          const curCols = neuronGeo.attributes.color.array;
          const baseCols = neuronBaseColors;
          for (let k = 0; k < curCols.length; k++) {
            curCols[k] = baseCols[k];
          }
          neuronGeo.attributes.color.needsUpdate = true;
        } else {
          // Wavefront sweeps from Frontal (Z = +105) to Occipital (Z = -105)
          const sweepZ = 105 - prog * 210;
          const curCols = neuronGeo.attributes.color.array;
          const nPositions = neuronGeo.attributes.position.array;
          const baseCols = neuronBaseColors;

          for (let n = 0; n < neuronCount; n++) {
            const zVal = nPositions[n * 3 + 2];
            const distToWave = Math.abs(zVal - sweepZ);

            if (distToWave < 30) {
              const ignite = 1.0 - distToWave / 30;
              curCols[n * 3] = baseCols[n * 3] + ignite * (1.0 - baseCols[n * 3]);
              curCols[n * 3 + 1] = baseCols[n * 3 + 1] + ignite * (1.0 - baseCols[n * 3 + 1]);
              curCols[n * 3 + 2] = baseCols[n * 3 + 2] + ignite * (1.0 - baseCols[n * 3 + 2]);
            } else {
              curCols[n * 3] = THREE.MathUtils.lerp(curCols[n * 3], baseCols[n * 3], delta * 5);
              curCols[n * 3 + 1] = THREE.MathUtils.lerp(curCols[n * 3 + 1], baseCols[n * 3 + 1], delta * 5);
              curCols[n * 3 + 2] = THREE.MathUtils.lerp(curCols[n * 3 + 2], baseCols[n * 3 + 2], delta * 5);
            }
          }
          neuronGeo.attributes.color.needsUpdate = true;
        }
      }

      renderer.render(scene, camera);
    };

    animate();

    // 10. Responsive Resize
    const handleResize = () => {
      if (!mount) return;
      const w = mount.clientWidth;
      const h = mount.clientHeight;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    window.addEventListener('resize', handleResize);

    // 11. Clean Resource Disposal
    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener('resize', handleResize);
      renderer.domElement.removeEventListener('wheel', handleDomWheel);
      controls.dispose();
      renderer.dispose();
      neuronGeo.dispose();
      neuronMat.dispose();
      tractGeo.dispose();
      tractMat.dispose();
      particleGeo.dispose();
      particleMat.dispose();
      if (mount.contains(renderer.domElement)) {
        mount.removeChild(renderer.domElement);
      }
    };
  }, [autoRotate]);

  return (
    <div
      ref={containerRef}
      style={{
        position: 'relative',
        width: '100%',
        height: '580px',
        background: '#040711',
        borderRadius: '6px',
        overflow: 'hidden',
        border: '1px solid rgba(0, 243, 255, 0.3)',
        boxShadow: '0 12px 48px rgba(0,0,0,0.7), inset 0 0 35px rgba(0, 243, 255, 0.05)',
      }}
    >
      {/* ── Top Scientific Header & Controls Overlay ────────────────────────── */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          padding: '14px 20px',
          background: 'linear-gradient(180deg, rgba(4, 7, 17, 0.95) 0%, rgba(4, 7, 17, 0) 100%)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '12px',
          zIndex: 10,
          pointerEvents: 'none',
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span
              style={{
                width: '8px',
                height: '8px',
                borderRadius: '50%',
                background: '#00f3ff',
                boxShadow: '0 0 8px #00f3ff',
                animation: 'pulse 1.8s infinite',
              }}
            />
            <h2
              style={{
                margin: 0,
                fontSize: '0.92rem',
                color: '#ffffff',
                fontFamily: 'Rajdhani, sans-serif',
                letterSpacing: '1.8px',
                fontWeight: 700,
              }}
            >
              HOLOGRAPHIC COGNITIVE CONNECTOME 3D • BẢN ĐỒ NÃO BỘ TIỂU BẢO BẢO
            </h2>
          </div>
          <div style={{ fontSize: '0.7rem', color: 'rgba(224, 242, 254, 0.7)', fontFamily: 'Share Tech Mono', marginTop: '2px' }}>
            Chuẩn DTI Tractography Quốc Tế (RGB = XYZ) • 10,800 Cortical Neurons • Soliton Wave
            {typeof freeEnergy === 'number' && ` • F=${freeEnergy.toFixed(3)}`}
            {typeof totalPulses === 'number' && ` • Pulses: ${totalPulses}`}
          </div>
        </div>

        {/* Right Controls: Presets, AutoRotate, Fullscreen & Trigger Pulse */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap', pointerEvents: 'auto' }}>
          {/* Preset Camera Views */}
          <div style={{ display: 'flex', background: 'rgba(0, 0, 0, 0.6)', borderRadius: '3px', border: '1px solid rgba(0, 243, 255, 0.2)' }}>
            <button
              type="button"
              onClick={() => applyCameraPreset('perspective')}
              style={{
                padding: '4px 8px',
                fontSize: '0.68rem',
                fontFamily: 'Share Tech Mono',
                background: activePreset === 'perspective' ? 'rgba(0, 243, 255, 0.25)' : 'transparent',
                color: activePreset === 'perspective' ? 'var(--accent-cyan)' : 'rgba(224, 242, 254, 0.6)',
                border: 'none',
                cursor: 'pointer',
              }}
            >
              Toàn Cảnh 3D
            </button>
            <button
              type="button"
              onClick={() => applyCameraPreset('lateral')}
              style={{
                padding: '4px 8px',
                fontSize: '0.68rem',
                fontFamily: 'Share Tech Mono',
                background: activePreset === 'lateral' ? 'rgba(0, 243, 255, 0.25)' : 'transparent',
                color: activePreset === 'lateral' ? 'var(--accent-cyan)' : 'rgba(224, 242, 254, 0.6)',
                border: 'none',
                cursor: 'pointer',
              }}
            >
              Bán Cầu Ngang
            </button>
            <button
              type="button"
              onClick={() => applyCameraPreset('top')}
              style={{
                padding: '4px 8px',
                fontSize: '0.68rem',
                fontFamily: 'Share Tech Mono',
                background: activePreset === 'top' ? 'rgba(0, 243, 255, 0.25)' : 'transparent',
                color: activePreset === 'top' ? 'var(--accent-cyan)' : 'rgba(224, 242, 254, 0.6)',
                border: 'none',
                cursor: 'pointer',
              }}
            >
              Từ Trên Đỉnh
            </button>
            <button
              type="button"
              onClick={() => applyCameraPreset('frontal')}
              style={{
                padding: '4px 8px',
                fontSize: '0.68rem',
                fontFamily: 'Share Tech Mono',
                background: activePreset === 'frontal' ? 'rgba(0, 243, 255, 0.25)' : 'transparent',
                color: activePreset === 'frontal' ? 'var(--accent-cyan)' : 'rgba(224, 242, 254, 0.6)',
                border: 'none',
                cursor: 'pointer',
              }}
            >
              Mặt Trước
            </button>
          </div>

          {/* AutoRotate Toggle */}
          <button
            type="button"
            onClick={() => setAutoRotate(!autoRotate)}
            style={{
              padding: '4px 10px',
              fontSize: '0.68rem',
              fontFamily: 'Share Tech Mono',
              background: autoRotate ? 'rgba(0, 255, 157, 0.2)' : 'rgba(0, 0, 0, 0.6)',
              color: autoRotate ? '#00ff9d' : 'rgba(224, 242, 254, 0.6)',
              border: `1px solid ${autoRotate ? '#00ff9d' : 'rgba(0, 243, 255, 0.2)'}`,
              borderRadius: '3px',
              cursor: 'pointer',
            }}
          >
            Xoay 360° [{autoRotate ? 'BẬT' : 'TẮT'}]
          </button>

          {/* Zoom In / Out */}
          <div style={{ display: 'flex', gap: '3px' }}>
            <button
              type="button"
              onClick={() => handleZoom(0.85)}
              title="Phóng to (Ctrl + Cuộn chuột lên)"
              style={{
                padding: '4px 8px',
                background: 'rgba(0, 243, 255, 0.1)',
                border: '1px solid rgba(0, 243, 255, 0.3)',
                color: 'var(--accent-cyan)',
                borderRadius: '3px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
              }}
            >
              <SciFiZoomInIcon size={13} color="var(--accent-cyan)" />
            </button>
            <button
              type="button"
              onClick={() => handleZoom(1.15)}
              title="Thu nhỏ (Ctrl + Cuộn chuột xuống)"
              style={{
                padding: '4px 8px',
                background: 'rgba(0, 243, 255, 0.1)',
                border: '1px solid rgba(0, 243, 255, 0.3)',
                color: 'var(--accent-cyan)',
                borderRadius: '3px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
              }}
            >
              <SciFiZoomOutIcon size={13} color="var(--accent-cyan)" />
            </button>
            <button
              type="button"
              onClick={toggleFullscreen}
              title={isFullscreen ? 'Thoát toàn màn hình' : 'Toàn màn hình'}
              style={{
                padding: '4px 8px',
                background: 'rgba(0, 243, 255, 0.1)',
                border: '1px solid rgba(0, 243, 255, 0.3)',
                color: 'var(--accent-cyan)',
                borderRadius: '3px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
              }}
            >
              {isFullscreen ? (
                <SciFiFullscreenExitIcon size={13} color="var(--accent-cyan)" />
              ) : (
                <SciFiFullscreenExpandIcon size={13} color="var(--accent-cyan)" />
              )}
            </button>
          </div>

          {/* Action Potential Status Badge */}
          <div
            style={{
              padding: '4px 10px',
              background: 'rgba(0, 243, 255, 0.08)',
              border: '1px solid rgba(0, 243, 255, 0.25)',
              borderRadius: '3px',
              fontSize: '0.7rem',
              fontFamily: 'Share Tech Mono',
              color: pulseActive ? '#00ff9d' : '#00f3ff',
            }}
          >
            {pulseActive ? `ACTION POTENTIAL: [${pulsePct}%]` : 'CONNECTOME: SẴN SÀNG'}
          </div>

          {/* Action Potential Trigger Button */}
          <button
            type="button"
            onClick={fireActionPotential}
            style={{
              padding: '6px 14px',
              fontSize: '0.74rem',
              fontFamily: 'Share Tech Mono',
              fontWeight: 700,
              background: 'linear-gradient(135deg, rgba(0, 243, 255, 0.3), rgba(0, 255, 157, 0.35))',
              color: '#ffffff',
              border: '1px solid #00f3ff',
              borderRadius: '3px',
              cursor: 'pointer',
              boxShadow: '0 0 14px rgba(0, 243, 255, 0.35)',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            <SciFiCognitivePulseBurstIcon size={14} color="#ffffff" />
            <span>KÍCH HOẠT XUNG THẦN KINH</span>
          </button>
        </div>
      </div>

      {/* ── WebGL Canvas Mount ──────────────────────────────────────────────── */}
      <div ref={mountRef} style={{ width: '100%', height: '100%', cursor: 'grab' }} />

      {/* ── Bottom HUD Footer: DTI Legend & Cognitive Zone Analytics ───────── */}
      <div
        style={{
          position: 'absolute',
          bottom: 12,
          left: 16,
          right: 16,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-end',
          flexWrap: 'wrap',
          gap: '10px',
          pointerEvents: 'none',
          fontSize: '0.7rem',
          fontFamily: 'Share Tech Mono',
        }}
      >
        {/* DTI Tractography Color Legend */}
        <div
          style={{
            background: 'rgba(4, 7, 17, 0.88)',
            padding: '8px 14px',
            borderRadius: '4px',
            border: '1px solid rgba(0, 243, 255, 0.25)',
            boxShadow: '0 4px 16px rgba(0,0,0,0.5)',
            display: 'flex',
            flexDirection: 'column',
            gap: '4px',
            pointerEvents: 'auto',
          }}
        >
          <div style={{ color: '#00f3ff', fontWeight: 700, letterSpacing: '1px', fontSize: '0.68rem' }}>
            CHUẨN MÃ HÓA HƯỚNG TRỤC THẦN KINH DTI (HCP FA):
          </div>
          <div style={{ display: 'flex', gap: '14px', flexWrap: 'wrap', fontSize: '0.66rem' }}>
            <span style={{ color: '#ff3366', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
              ● Trục X (Đỏ): Liên bán cầu (Corpus Callosum)
            </span>
            <span style={{ color: '#00ff9d', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
              ● Trục Y (Xanh lá): Trước - Sau (Frontal-Occipital)
            </span>
            <span style={{ color: '#00f3ff', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
              ● Trục Z (Xanh lam): Trên - Dưới (Projection)
            </span>
          </div>
        </div>

        {/* Cognitive Zones Interactive Chips */}
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', pointerEvents: 'auto' }}>
          {COGNITIVE_ZONES.map((zone) => (
            <div
              key={zone.id}
              onClick={() => setActiveZone(zone)}
              style={{
                background: activeZone.id === zone.id ? 'rgba(0, 243, 255, 0.25)' : 'rgba(4, 7, 17, 0.82)',
                border: `1px solid ${activeZone.id === zone.id ? zone.color : 'rgba(255, 255, 255, 0.15)'}`,
                boxShadow: activeZone.id === zone.id ? `0 0 10px ${zone.color}44` : 'none',
                padding: '6px 10px',
                borderRadius: '3px',
                cursor: 'pointer',
                textAlign: 'center',
                transition: 'all 0.2s ease',
              }}
            >
              <div style={{ color: zone.color, fontWeight: 700, fontSize: '0.68rem' }}>
                {zone.name}
              </div>
              <div style={{ color: '#ffffff', fontSize: '0.62rem' }}>
                {zone.tensor}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
