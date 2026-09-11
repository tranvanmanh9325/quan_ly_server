/**
 * ============================================================================
 * NEUROMORPHIC HOLOGRAPHIC BRAIN CONNECTOME 3D (BẢN ĐỒ NÃO BỘ TIỂU BẢO BẢO)
 * ============================================================================
 * Architectural Paradigm:
 * 1. Dual-Hemisphere Cortical Point Cloud (10,800+ bio-distributed neurons).
 * 2. DTI Tractography Bundles (Corpus Callosum, SLF, Corticospinal Projection).
 * 3. Directional FA Color Encoding (RGB = XYZ).
 * 4. Soliton Action Potential Wavefront (Traveling Depolarization Wave).
 * 5. Interactive Deep Focus & Inspection for 5 Anatomical Cognitive Centers:
 *    - Prefrontal Cortex (Working Memory & Tokens)
 *    - Parietal Neocortex (32GB VSA Hyperdimensional Space)
 *    - Central Thalamus (Global Workspace Hub)
 *    - Limbic Hippocampus (Dream Engine & Consolidation)
 *    - Hypothalamus & Brainstem (Sensory Bus & Neurochemistry)
 * 6. Smooth Camera Target & Flight Tween Lerp, 3D Pulsing Beacon, Raycaster Selection.
 * 7. 100% Bespoke Handcrafted Cyberpunk SVG Icons (Zero Unicode / Zero Library Icons).
 * 8. High-Contrast Deep Matte Neuro-Inspector HUD (Crystal clear readability).
 * ============================================================================
 */

import React, { useEffect, useRef, useState, useCallback } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import {
  SciFiZoomInIcon,
  SciFiZoomOutIcon,
  SciFiFullscreenExpandIcon,
  SciFiFullscreenExitIcon,
  SciFiCognitivePulseBurstIcon,
  SciFiSyncRefreshLoopIcon,
  SciFiDeepBrainStimulationIcon,
  SciFiCyberCloseCancelIcon,
  SciFiMembraneVoltageIcon,
  SciFiSynapticFrequencyIcon,
  SciFiNeuroChemistryFlaskIcon,
  SciFiOverviewHomeIcon,
  SciFiPerspectiveEyeIcon,
  SciFiAxialTopIcon,
  SciFiCoronalFrontIcon,
  SciFiSagittalLateralIcon,
} from './BrainSciFiIcons';

// ── 5 Core Anatomical & Cognitive Centers ─────────────────────────────────────
const COGNITIVE_ZONES = [
  {
    id: 'prefrontal',
    name: 'PREFRONTAL CORTEX',
    role: 'Working Memory & Attention',
    center: new THREE.Vector3(0, 45, 115),
    color: '#00f3ff',
    tensor: 'Tokens [1, 512, 4096]',
    desc: 'Vỏ não trước trán: Duy trì bộ đệm ký ức làm việc và phân bổ chú ý điều hành.',
    metrics: { potential: '-55 mV', firingRate: '64.2 Hz', keyChemical: 'Dopamine D1 Receptor' },
  },
  {
    id: 'parietal',
    name: 'PARIETAL NEOCORTEX',
    role: 'Hyperdimensional VSA Store',
    center: new THREE.Vector3(0, 85, -25),
    color: '#bd00ff',
    tensor: '10,000-Bit HyperVectors',
    desc: 'Vỏ não đỉnh: Lưu trữ tri thức ngữ nghĩa dài hạn 32GB mmap và khoảng cách Hamming.',
    metrics: { potential: '-62 mV', firingRate: '38.0 Hz', keyChemical: 'Acetylcholine Synapses' },
  },
  {
    id: 'thalamus',
    name: 'CENTRAL THALAMUS',
    role: 'Global Workspace Hub',
    center: new THREE.Vector3(0, 10, -10),
    color: '#ffd700',
    tensor: 'Salience Arb [S ≥ 0.65]',
    desc: 'Đồi thị trung tâm: Trọng tài điều phối tiêu điểm ý thức toàn cầu và ức chế cạnh.',
    metrics: { potential: '-48 mV', firingRate: '72.4 Hz', keyChemical: 'GABAergic Relay / Glutamate' },
  },
  {
    id: 'hippocampus',
    name: 'LIMBIC HIPPOCAMPUS',
    role: 'Episodic Memory / Dream Engine',
    center: new THREE.Vector3(0, -22, -20),
    color: '#00ff9d',
    tensor: 'SWS/REM Consolidation',
    desc: 'Vùng hải mã: Tinh thể hóa ký ức phân đoạn và kích hoạt giấc mơ ban đêm.',
    metrics: { potential: '-58 mV', firingRate: '45.1 Hz', keyChemical: 'BDNF / Theta Rhythm' },
  },
  {
    id: 'brainstem',
    name: 'HYPOTHALAMUS & BRAINSTEM',
    role: 'Sensory Bus & Neurochemistry',
    center: new THREE.Vector3(0, -38, -105),
    color: '#ff3366',
    tensor: 'DA / 5-HT / NE / CORT',
    desc: 'Trục hạ đồi & thân não: Điều hòa 6 chất dẫn truyền thần kinh và cân bằng nội môi.',
    metrics: { potential: '-42 mV', firingRate: '52.8 Hz', keyChemical: 'DA: 0.82 | 5-HT: 0.74 | NE: 0.68' },
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
  const [activeZone, setActiveZone] = useState(null);
  const activeZoneRef = useRef(null);
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
  const zoneGroupRef = useRef(null);
  const waveStateRef = useRef({ active: false, progress: 0, speed: 0.35 });
  const pulseParticlesRef = useRef(null);
  const neuronPointsRef = useRef(null);
  const cameraTweenRef = useRef({
    active: false,
    targetPos: new THREE.Vector3(220, 140, 240),
    controlsTarget: new THREE.Vector3(0, 15, 0),
    speed: 0.05,
  });

  // Update autoRotate directly on controls
  useEffect(() => {
    if (controlsRef.current) {
      controlsRef.current.autoRotate = autoRotate;
      controlsRef.current.autoRotateSpeed = 0.85;
    }
  }, [autoRotate]);

  // Handle cognitive zone selection with smooth camera focus & flight
  const handleSelectZone = useCallback((zone) => {
    setActiveZone(zone);
    activeZoneRef.current = zone;

    if (!cameraRef.current || !controlsRef.current) return;

    const center = zone.center.clone();
    let offsetDir = center.clone().normalize();
    if (offsetDir.lengthSq() < 0.001) {
      offsetDir.set(0.4, 0.4, 0.8).normalize();
    }

    // Set camera position at comfortable observation distance (~125 units)
    const targetPos = center.clone().add(offsetDir.multiplyScalar(125)).add(new THREE.Vector3(15, 20, 25));

    cameraTweenRef.current = {
      active: true,
      targetPos,
      controlsTarget: center,
      speed: 0.055,
    };

    // Trigger local action potential pulse
    waveStateRef.current.active = true;
    waveStateRef.current.progress = 0;
    setPulseActive(true);
  }, []);

  // Reset camera to wide overview angle
  const resetToOverview = useCallback(() => {
    setActiveZone(null);
    activeZoneRef.current = null;
    setActivePreset('perspective');

    if (!cameraRef.current || !controlsRef.current) return;
    cameraTweenRef.current = {
      active: true,
      targetPos: new THREE.Vector3(220, 140, 240),
      controlsTarget: new THREE.Vector3(0, 15, 0),
      speed: 0.05,
    };
  }, []);

  // Set camera to preset angles with smooth flight interpolation
  const applyCameraPreset = useCallback((preset) => {
    if (!cameraRef.current || !controlsRef.current) return;
    setActivePreset(preset);
    setActiveZone(null);
    activeZoneRef.current = null;

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

    cameraTweenRef.current = {
      active: true,
      targetPos,
      controlsTarget: new THREE.Vector3(0, 15, 0),
      speed: 0.05,
    };
  }, []);

  // Zoom control helper
  const handleZoom = useCallback((factor) => {
    if (!cameraRef.current || !controlsRef.current) return;
    const camera = cameraRef.current;
    const controls = controlsRef.current;
    const offset = camera.position.clone().sub(controls.target);
    offset.multiplyScalar(factor);
    if (offset.length() > 60 && offset.length() < 900) {
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
    window.__selectBrainZone = handleSelectZone;
    return () => {
      delete window.__triggerBrainPulse;
      delete window.__selectBrainZone;
    };
  }, [fireActionPotential, handleSelectZone]);

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
    controls.minDistance = 60;
    controls.enableZoom = false; // Normal page scrolling preserved
    controls.target.set(0, 15, 0);
    controlsRef.current = controls;

    // Ctrl + mouse wheel for precision 3D zooming without blocking page scrolling
    const handleDomWheel = (e) => {
      if (e.ctrlKey && cameraRef.current && controlsRef.current) {
        e.preventDefault();
        const factor = e.deltaY > 0 ? 1.08 : 0.92;
        const offset = cameraRef.current.position.clone().sub(controlsRef.current.target);
        offset.multiplyScalar(factor);
        if (offset.length() > 60 && offset.length() < 900) {
          cameraRef.current.position.copy(controlsRef.current.target).add(offset);
          controlsRef.current.update();
        }
      }
    };
    renderer.domElement.addEventListener('wheel', handleDomWheel, { passive: false });

    // 4. Lighting & Ambient Ambiance
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.85);
    scene.add(ambientLight);

    const pointLight = new THREE.PointLight(0x00f3ff, 2.2, 800);
    pointLight.position.set(0, 150, 100);
    scene.add(pointLight);

    const pinkLight = new THREE.PointLight(0xff3366, 1.8, 800);
    pinkLight.position.set(0, -120, -100);
    scene.add(pinkLight);

    // 5. Dual-Hemisphere Cortical Point Cloud (10,800+ Biological Neurons)
    const neuronCount = 10800;
    const neuronPositions = new Float32Array(neuronCount * 3);
    const neuronBaseColors = new Float32Array(neuronCount * 3);
    const neuronCurrentColors = new Float32Array(neuronCount * 3);
    const neuronSizes = new Float32Array(neuronCount);

    let idx = 0;
    for (let i = 0; i < neuronCount; i++) {
      const isRightHemisphere = Math.random() > 0.5;
      const hemiSign = isRightHemisphere ? 1 : -1;

      const u = Math.random();
      const v = Math.random();
      const theta = u * 2.0 * Math.PI;
      const phi = Math.acos(2.0 * v - 1.0);
      const r = 0.35 + 0.65 * Math.cbrt(Math.random());

      let x = r * Math.sin(phi) * Math.cos(theta);
      let y = r * Math.sin(phi) * Math.sin(theta);
      let z = r * Math.cos(phi);

      const aX = 110.0;
      const bY = 78.0;
      const cZ = 135.0;

      x *= aX;
      y *= bY;
      z *= cZ;

      const gyriWave = Math.sin(x * 0.12) * Math.cos(z * 0.10) * 8.5 +
                       Math.sin(y * 0.15) * 5.0;
      const sulciIndent = Math.cos(x * 0.22) * Math.sin(z * 0.18) * 4.0;
      const perturbation = (gyriWave + sulciIndent) * (r > 0.7 ? 1.0 : 0.2);

      x += perturbation * (x / (aX || 1));
      y += perturbation * (y / (bY || 1));
      z += perturbation * (z / (cZ || 1));

      x = Math.abs(x) * hemiSign;
      const fissureGap = 6.5;
      x += (isRightHemisphere ? fissureGap : -fissureGap);

      if (y < 0 && z < -20) {
        y *= 0.72;
      }

      neuronPositions[idx * 3] = x;
      neuronPositions[idx * 3 + 1] = y;
      neuronPositions[idx * 3 + 2] = z;

      const normX = Math.abs(x) / (aX + fissureGap);
      const normY = (y + bY) / (2 * bY);
      const normZ = (z + cZ) / (2 * cZ);

      const rCol = 0.08 + 0.85 * normX;
      const gCol = 0.15 + 0.80 * normY;
      const bCol = 0.25 + 0.75 * normZ;

      neuronBaseColors[idx * 3] = rCol;
      neuronBaseColors[idx * 3 + 1] = gCol;
      neuronBaseColors[idx * 3 + 2] = bCol;

      neuronCurrentColors[idx * 3] = rCol;
      neuronCurrentColors[idx * 3 + 1] = gCol;
      neuronCurrentColors[idx * 3 + 2] = bCol;

      neuronSizes[idx] = 1.6 + Math.random() * 2.2;
      idx++;
    }

    const neuronGeo = new THREE.BufferGeometry();
    neuronGeo.setAttribute('position', new THREE.BufferAttribute(neuronPositions, 3));
    neuronGeo.setAttribute('color', new THREE.BufferAttribute(neuronCurrentColors, 3));
    neuronGeo.setAttribute('size', new THREE.BufferAttribute(neuronSizes, 1));

    const neuronMat = new THREE.PointsMaterial({
      size: 2.4,
      vertexColors: true,
      transparent: true,
      opacity: 0.82,
      blending: THREE.AdditiveBlending,
    });

    const neuronCloud = new THREE.Points(neuronGeo, neuronMat);
    scene.add(neuronCloud);
    neuronPointsRef.current = { geo: neuronGeo, mat: neuronMat };

    // 6. DTI Tractography Bundles (Anatomical Fiber Tracts)
    const tractSplines = [];
    const tractPoints = [];
    const tractColors = [];

    // Corpus Callosum (Red FA: Left-Right Inter-hemispheric)
    for (let c = 0; c < 28; c++) {
      const zOffset = -70 + (c / 28) * 160;
      const archHeight = 35 + Math.sin((c / 28) * Math.PI) * 25;
      const span = 85;

      const p0 = new THREE.Vector3(-span, archHeight * 0.4, zOffset);
      const p1 = new THREE.Vector3(-span * 0.45, archHeight, zOffset + 5);
      const p2 = new THREE.Vector3(0, archHeight * 1.15, zOffset);
      const p3 = new THREE.Vector3(span * 0.45, archHeight, zOffset - 5);
      const p4 = new THREE.Vector3(span, archHeight * 0.4, zOffset);

      const curve = new THREE.CatmullRomCurve3([p0, p1, p2, p3, p4]);
      tractSplines.push(curve);

      const pts = curve.getPoints(40);
      for (let j = 0; j < pts.length - 1; j++) {
        tractPoints.push(pts[j].x, pts[j].y, pts[j].z);
        tractPoints.push(pts[j + 1].x, pts[j + 1].y, pts[j + 1].z);
        tractColors.push(1.0, 0.15, 0.35);
        tractColors.push(1.0, 0.15, 0.35);
      }
    }

    // Superior Longitudinal Fasciculus (Green FA: Frontal to Occipital)
    [-1, 1].forEach((side) => {
      for (let s = 0; s < 18; s++) {
        const xOffset = side * (45 + s * 2.8);
        const yOffset = 15 + (s % 4) * 8;

        const p0 = new THREE.Vector3(xOffset, yOffset + 20, 115);
        const p1 = new THREE.Vector3(xOffset * 1.1, yOffset + 45, 45);
        const p2 = new THREE.Vector3(xOffset * 1.15, yOffset + 40, -35);
        const p3 = new THREE.Vector3(xOffset * 0.8, yOffset + 10, -110);

        const curve = new THREE.CatmullRomCurve3([p0, p1, p2, p3]);
        tractSplines.push(curve);

        const pts = curve.getPoints(36);
        for (let j = 0; j < pts.length - 1; j++) {
          tractPoints.push(pts[j].x, pts[j].y, pts[j].z);
          tractPoints.push(pts[j + 1].x, pts[j + 1].y, pts[j + 1].z);
          tractColors.push(0.0, 0.95, 0.55);
          tractColors.push(0.0, 0.95, 0.55);
        }
      }
    });

    // Corticospinal Projection (Blue FA: Motor Cortex down to Brainstem)
    [-1, 1].forEach((side) => {
      for (let p = 0; p < 14; p++) {
        const xStart = side * (30 + p * 3.5);
        const zStart = -15 + (p % 3) * 10;

        const p0 = new THREE.Vector3(xStart, 72, zStart);
        const p1 = new THREE.Vector3(xStart * 0.65, 30, zStart - 15);
        const p2 = new THREE.Vector3(xStart * 0.35, -5, -45);
        const p3 = new THREE.Vector3(side * 8, -48, -95);

        const curve = new THREE.CatmullRomCurve3([p0, p1, p2, p3]);
        tractSplines.push(curve);

        const pts = curve.getPoints(32);
        for (let j = 0; j < pts.length - 1; j++) {
          tractPoints.push(pts[j].x, pts[j].y, pts[j].z);
          tractPoints.push(pts[j + 1].x, pts[j + 1].y, pts[j + 1].z);
          tractColors.push(0.0, 0.85, 1.0);
          tractColors.push(0.0, 0.85, 1.0);
        }
      }
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

    // 8. Interactive Zone Anchors (Cognitive Hologram Rings & Beacons)
    const zoneGroup = new THREE.Group();
    zoneGroupRef.current = zoneGroup;

    COGNITIVE_ZONES.forEach((zone) => {
      const ringGeo = new THREE.RingGeometry(6.5, 8.8, 36);
      const ringMat = new THREE.MeshBasicMaterial({
        color: new THREE.Color(zone.color),
        side: THREE.DoubleSide,
        transparent: true,
        opacity: 0.75,
      });
      const ringMesh = new THREE.Mesh(ringGeo, ringMat);
      ringMesh.position.copy(zone.center);
      ringMesh.userData = { zone };
      zoneGroup.add(ringMesh);

      // Inner pulsating core sphere
      const sphereGeo = new THREE.SphereGeometry(2.8, 16, 16);
      const sphereMat = new THREE.MeshBasicMaterial({
        color: new THREE.Color(zone.color),
        transparent: true,
        opacity: 0.85,
        wireframe: true,
      });
      const sphereMesh = new THREE.Mesh(sphereGeo, sphereMat);
      sphereMesh.position.copy(zone.center);
      sphereMesh.userData = { zone, isCore: true };
      zoneGroup.add(sphereMesh);
    });
    scene.add(zoneGroup);

    // 9. Raycaster 2-Way Interaction: Click on 3D Beacon Rings directly
    const raycaster = new THREE.Raycaster();
    const mouse = new THREE.Vector2();

    const handleCanvasClick = (event) => {
      const rect = renderer.domElement.getBoundingClientRect();
      mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

      raycaster.setFromCamera(mouse, camera);
      const intersects = raycaster.intersectObjects(zoneGroup.children, false);

      if (intersects.length > 0) {
        const hitZone = intersects[0].object.userData.zone;
        if (hitZone) {
          handleSelectZone(hitZone);
        }
      }
    };

    const handleCanvasMouseMove = (event) => {
      const rect = renderer.domElement.getBoundingClientRect();
      mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

      raycaster.setFromCamera(mouse, camera);
      const intersects = raycaster.intersectObjects(zoneGroup.children, false);
      renderer.domElement.style.cursor = intersects.length > 0 ? 'pointer' : 'default';
    };

    renderer.domElement.addEventListener('click', handleCanvasClick);
    renderer.domElement.addEventListener('mousemove', handleCanvasMouseMove);

    // 10. Animation Loop (Smooth 60 FPS)
    let animId;
    const clock = new THREE.Clock();

    const animate = () => {
      animId = requestAnimationFrame(animate);
      const delta = clock.getDelta();
      const time = clock.getElapsedTime();

      // Smooth camera and controls target flight tween
      if (cameraTweenRef.current.active) {
        const spd = cameraTweenRef.current.speed || 0.05;
        camera.position.lerp(cameraTweenRef.current.targetPos, spd);
        if (cameraTweenRef.current.controlsTarget) {
          controls.target.lerp(cameraTweenRef.current.controlsTarget, spd);
        }
        if (camera.position.distanceTo(cameraTweenRef.current.targetPos) < 1.2) {
          cameraTweenRef.current.active = false;
        }
      }

      controls.update();

      // Subtle organic rotation when autoRotate is OFF and no zone is being inspected
      if (!autoRotate && !activeZoneRef.current) {
        neuronCloud.rotation.y = Math.sin(time * 0.15) * 0.04;
        tractMesh.rotation.y = Math.sin(time * 0.15) * 0.04;
      }

      // Action Potential Photon Particle Flow
      if (pulseParticlesRef.current) {
        const { geo, splines, progress } = pulseParticlesRef.current;
        const posAttr = geo.attributes.position;
        const pArr = posAttr.array;
        const pSpeed = waveStateRef.current.active ? 1.35 : 0.45;

        for (let k = 0; k < progress.length; k++) {
          progress[k] = (progress[k] + delta * pSpeed) % 1.0;
          const pt = splines[k].getPoint(progress[k]);
          pArr[k * 3] = pt.x;
          pArr[k * 3 + 1] = pt.y;
          pArr[k * 3 + 2] = pt.z;
        }
        posAttr.needsUpdate = true;
      }

      // Update 3D Zone Beacon Rings (Billboard orientation & Pulsing Scale)
      const currentZone = activeZoneRef.current;
      zoneGroup.children.forEach((mesh) => {
        mesh.lookAt(camera.position);
        const isMatch = currentZone && mesh.userData.zone?.id === currentZone.id;
        if (isMatch) {
          const osc = 1.0 + 0.22 * Math.sin(time * 7.5);
          mesh.scale.set(osc, osc, osc);
          if (mesh.material) mesh.material.opacity = 0.96;
        } else {
          mesh.scale.set(1.0, 1.0, 1.0);
          if (mesh.material) mesh.material.opacity = currentZone ? 0.25 : 0.72;
        }
      });

      // Soliton Wavefront Depolarization & Local Zone Spotlight
      if (neuronPointsRef.current) {
        const curCols = neuronPointsRef.current.geo.attributes.color.array;
        const baseCols = neuronBaseColors;
        const nPositions = neuronPositions;

        // 1. Global Soliton Wavefront Sweep
        if (waveStateRef.current.active) {
          waveStateRef.current.progress += delta * waveStateRef.current.speed;
          const prog = waveStateRef.current.progress;
          setPulsePct(Math.min(100, Math.round(prog * 100)));

          if (prog >= 1.0) {
            waveStateRef.current.active = false;
            setPulseActive(false);
            setPulsePct(0);
          }

          const sweepZ = 135 - prog * 270;

          for (let n = 0; n < neuronCount; n++) {
            const zVal = nPositions[n * 3 + 2];
            const distToWave = Math.abs(zVal - sweepZ);

            if (distToWave < 32) {
              const ignite = 1.0 - distToWave / 32;
              curCols[n * 3] = baseCols[n * 3] + ignite * (1.0 - baseCols[n * 3]);
              curCols[n * 3 + 1] = baseCols[n * 3 + 1] + ignite * (1.0 - baseCols[n * 3 + 1]);
              curCols[n * 3 + 2] = baseCols[n * 3 + 2] + ignite * (1.0 - baseCols[n * 3 + 2]);
            } else {
              curCols[n * 3] = THREE.MathUtils.lerp(curCols[n * 3], baseCols[n * 3], delta * 4.5);
              curCols[n * 3 + 1] = THREE.MathUtils.lerp(curCols[n * 3 + 1], baseCols[n * 3 + 1], delta * 4.5);
              curCols[n * 3 + 2] = THREE.MathUtils.lerp(curCols[n * 3 + 2], baseCols[n * 3 + 2], delta * 4.5);
            }
          }
        }

        // 2. Local Zone Depolarization (Spotlight around active zone center)
        if (currentZone) {
          const zCenter = currentZone.center;
          const zColor = new THREE.Color(currentZone.color);
          const glow = 0.5 + 0.5 * Math.sin(time * 8.0);

          for (let n = 0; n < neuronCount; n++) {
            const dx = nPositions[n * 3] - zCenter.x;
            const dy = nPositions[n * 3 + 1] - zCenter.y;
            const dz = nPositions[n * 3 + 2] - zCenter.z;
            const distSq = dx * dx + dy * dy + dz * dz;

            if (distSq < 2200) { // Radius ~47
              const factor = 1.0 - Math.sqrt(distSq) / 47.0;
              curCols[n * 3] = THREE.MathUtils.lerp(curCols[n * 3], zColor.r + 0.25 * glow, factor * 0.45);
              curCols[n * 3 + 1] = THREE.MathUtils.lerp(curCols[n * 3 + 1], zColor.g + 0.25 * glow, factor * 0.45);
              curCols[n * 3 + 2] = THREE.MathUtils.lerp(curCols[n * 3 + 2], zColor.b + 0.25 * glow, factor * 0.45);
            }
          }
        }

        neuronGeo.attributes.color.needsUpdate = true;
      }

      renderer.render(scene, camera);
    };

    animate();

    // 11. Responsive Resize
    const handleResize = () => {
      if (!mount) return;
      const w = mount.clientWidth;
      const h = mount.clientHeight;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    window.addEventListener('resize', handleResize);

    // 12. Clean Resource Disposal
    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener('resize', handleResize);
      renderer.domElement.removeEventListener('wheel', handleDomWheel);
      renderer.domElement.removeEventListener('click', handleCanvasClick);
      renderer.domElement.removeEventListener('mousemove', handleCanvasMouseMove);
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
  }, [autoRotate, handleSelectZone]);

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
          padding: '12px 20px',
          background: 'linear-gradient(180deg, rgba(2, 4, 10, 0.98) 0%, rgba(2, 4, 10, 0.85) 75%, rgba(2, 4, 10, 0) 100%)',
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
            <SciFiCognitivePulseBurstIcon size={18} color="#00f3ff" />
            <h2
              style={{
                margin: 0,
                fontSize: '0.96rem',
                color: '#ffffff',
                fontFamily: 'Rajdhani, sans-serif',
                letterSpacing: '1.8px',
                fontWeight: 800,
                textShadow: '0 0 10px rgba(0, 243, 255, 0.5)',
              }}
            >
              HOLOGRAPHIC COGNITIVE CONNECTOME 3D • BẢN ĐỒ NÃO BỘ TIỂU BẢO BẢO
            </h2>
          </div>
          <div style={{ fontSize: '0.72rem', color: '#cbd5e1', fontFamily: 'Share Tech Mono', marginTop: '2px', letterSpacing: '0.5px' }}>
            Chuẩn DTI Tractography Quốc Tế (RGB = XYZ) • 10,800 Cortical Neurons • Soliton Wave
            {typeof freeEnergy === 'number' && ` • F=${freeEnergy.toFixed(3)}`}
            {typeof totalPulses === 'number' && ` • Pulses: ${totalPulses}`}
          </div>
        </div>

        {/* Right Controls: Presets, AutoRotate, Fullscreen & Trigger Pulse */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap', pointerEvents: 'auto' }}>
          {/* Preset Camera Views */}
          <div style={{ display: 'flex', background: 'rgba(0, 0, 0, 0.75)', borderRadius: '4px', border: '1px solid rgba(0, 243, 255, 0.25)', overflow: 'hidden' }}>
            <button
              type="button"
              onClick={() => applyCameraPreset('perspective')}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '5px',
                padding: '5px 9px',
                fontSize: '0.70rem',
                fontFamily: 'Share Tech Mono',
                background: activePreset === 'perspective' && !activeZone ? 'rgba(0, 243, 255, 0.3)' : 'transparent',
                color: activePreset === 'perspective' && !activeZone ? '#00f3ff' : '#cbd5e1',
                border: 'none',
                cursor: 'pointer',
              }}
            >
              <SciFiPerspectiveEyeIcon size={12} color={activePreset === 'perspective' && !activeZone ? '#00f3ff' : '#94a3b8'} />
              <span>Toàn Cảnh 3D</span>
            </button>
            <button
              type="button"
              onClick={() => applyCameraPreset('lateral')}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '5px',
                padding: '5px 9px',
                fontSize: '0.70rem',
                fontFamily: 'Share Tech Mono',
                background: activePreset === 'lateral' ? 'rgba(0, 243, 255, 0.3)' : 'transparent',
                color: activePreset === 'lateral' ? '#00f3ff' : '#cbd5e1',
                border: 'none',
                borderLeft: '1px solid rgba(0, 243, 255, 0.15)',
                cursor: 'pointer',
              }}
            >
              <SciFiSagittalLateralIcon size={12} color={activePreset === 'lateral' ? '#00f3ff' : '#94a3b8'} />
              <span>Bán Cầu Ngang</span>
            </button>
            <button
              type="button"
              onClick={() => applyCameraPreset('top')}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '5px',
                padding: '5px 9px',
                fontSize: '0.70rem',
                fontFamily: 'Share Tech Mono',
                background: activePreset === 'top' ? 'rgba(0, 243, 255, 0.3)' : 'transparent',
                color: activePreset === 'top' ? '#00f3ff' : '#cbd5e1',
                border: 'none',
                borderLeft: '1px solid rgba(0, 243, 255, 0.15)',
                cursor: 'pointer',
              }}
            >
              <SciFiAxialTopIcon size={12} color={activePreset === 'top' ? '#00f3ff' : '#94a3b8'} />
              <span>Từ Trên Đỉnh</span>
            </button>
            <button
              type="button"
              onClick={() => applyCameraPreset('frontal')}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '5px',
                padding: '5px 9px',
                fontSize: '0.70rem',
                fontFamily: 'Share Tech Mono',
                background: activePreset === 'frontal' ? 'rgba(0, 243, 255, 0.3)' : 'transparent',
                color: activePreset === 'frontal' ? '#00f3ff' : '#cbd5e1',
                border: 'none',
                borderLeft: '1px solid rgba(0, 243, 255, 0.15)',
                cursor: 'pointer',
              }}
            >
              <SciFiCoronalFrontIcon size={12} color={activePreset === 'frontal' ? '#00f3ff' : '#94a3b8'} />
              <span>Mặt Trước</span>
            </button>
          </div>

          {/* Auto-Rotate Toggle */}
          <button
            type="button"
            onClick={() => setAutoRotate(!autoRotate)}
            style={{
              padding: '5px 11px',
              fontSize: '0.70rem',
              fontFamily: 'Share Tech Mono',
              fontWeight: 600,
              background: autoRotate ? 'rgba(0, 255, 157, 0.25)' : 'rgba(0, 0, 0, 0.75)',
              color: autoRotate ? '#00ff9d' : '#cbd5e1',
              border: `1px solid ${autoRotate ? 'rgba(0, 255, 157, 0.6)' : 'rgba(0, 243, 255, 0.25)'}`,
              borderRadius: '3px',
              cursor: 'pointer',
            }}
          >
            {autoRotate ? 'Xoay 360° [BẬT]' : 'Xoay 360° [TẮT]'}
          </button>

          {/* Zoom Buttons */}
          <div style={{ display: 'flex', gap: '2px' }}>
            <button
              type="button"
              title="Phóng to (Ctrl + Cuộn chuột)"
              onClick={() => handleZoom(0.85)}
              style={{
                padding: '5px 9px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: 'rgba(0, 0, 0, 0.75)',
                border: '1px solid rgba(0, 243, 255, 0.25)',
                borderRadius: '3px 0 0 3px',
                cursor: 'pointer',
              }}
            >
              <SciFiZoomInIcon size={14} color="#00f3ff" />
            </button>
            <button
              type="button"
              title="Thu nhỏ (Ctrl + Cuộn chuột)"
              onClick={() => handleZoom(1.15)}
              style={{
                padding: '5px 9px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: 'rgba(0, 0, 0, 0.75)',
                border: '1px solid rgba(0, 243, 255, 0.25)',
                borderRadius: '0',
                cursor: 'pointer',
              }}
            >
              <SciFiZoomOutIcon size={14} color="#00f3ff" />
            </button>
            <button
              type="button"
              title="Đặt lại góc nhìn toàn cảnh"
              onClick={resetToOverview}
              style={{
                padding: '5px 9px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: 'rgba(0, 0, 0, 0.75)',
                border: '1px solid rgba(0, 243, 255, 0.25)',
                borderRadius: '0 3px 3px 0',
                cursor: 'pointer',
              }}
            >
              <SciFiSyncRefreshLoopIcon size={14} color="#00f3ff" />
            </button>
          </div>

          {/* Fullscreen Toggle */}
          <button
            type="button"
            title="Toàn màn hình"
            onClick={toggleFullscreen}
            style={{
              padding: '5px 9px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              background: 'rgba(0, 0, 0, 0.75)',
              border: '1px solid rgba(0, 243, 255, 0.25)',
              borderRadius: '3px',
              cursor: 'pointer',
            }}
          >
            {isFullscreen ? (
              <SciFiFullscreenExitIcon size={15} color="#00ff9d" />
            ) : (
              <SciFiFullscreenExpandIcon size={15} color="#00f3ff" />
            )}
          </button>

          {/* Soliton Wave Status Badge */}
          <div
            style={{
              padding: '5px 9px',
              fontSize: '0.70rem',
              fontFamily: 'Share Tech Mono',
              borderRadius: '3px',
              background: pulseActive ? 'rgba(255, 0, 85, 0.25)' : 'rgba(0, 243, 255, 0.12)',
              border: `1px solid ${pulseActive ? '#ff0055' : 'rgba(0, 243, 255, 0.35)'}`,
              color: pulseActive ? '#ff0055' : '#00f3ff',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            <span
              style={{
                width: '6px',
                height: '6px',
                borderRadius: '50%',
                background: pulseActive ? '#ff0055' : '#00ff9d',
                boxShadow: `0 0 8px ${pulseActive ? '#ff0055' : '#00ff9d'}`,
              }}
            />
            {pulseActive ? `SÓNG KHỬ CỰC: ${pulsePct}%` : 'CONNECTOME: SẴN SÀNG'}
          </div>

          {/* Action Potential Trigger Button */}
          <button
            type="button"
            onClick={fireActionPotential}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '7px',
              padding: '6px 14px',
              fontSize: '0.74rem',
              fontFamily: 'Share Tech Mono',
              fontWeight: 700,
              background: 'linear-gradient(135deg, rgba(0, 243, 255, 0.35), rgba(189, 0, 255, 0.35))',
              color: '#ffffff',
              border: '1px solid #00f3ff',
              borderRadius: '3px',
              cursor: 'pointer',
              boxShadow: '0 0 16px rgba(0, 243, 255, 0.5)',
              transition: 'all 0.2s ease',
            }}
          >
            <SciFiCognitivePulseBurstIcon size={16} color="#00f3ff" />
            <span>KÍCH HOẠT XUNG THẦN KINH</span>
          </button>
        </div>
      </div>

      {/* ── Active Cognitive Zone Holographic Inspector HUD ───────────────── */}
      {activeZone && (
        <div
          style={{
            position: 'absolute',
            top: 72,
            left: 20,
            width: '380px',
            maxWidth: 'calc(100% - 40px)',
            background: 'rgba(2, 5, 14, 0.98)',
            backdropFilter: 'blur(20px)',
            border: `1.5px solid ${activeZone.color}`,
            borderRadius: '6px',
            padding: '14px 18px',
            boxShadow: `0 20px 50px rgba(0,0,0,0.95), 0 0 30px ${activeZone.color}44, inset 0 0 20px ${activeZone.color}15`,
            zIndex: 15,
            fontFamily: 'Share Tech Mono',
            animation: 'fadeIn 0.25s ease',
          }}
        >
          {/* Header & Close / Reset Button */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px', borderBottom: '1px solid rgba(255, 255, 255, 0.1)', paddingBottom: '8px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <SciFiCognitivePulseBurstIcon size={18} color={activeZone.color} />
              <span
                style={{
                  color: '#ffffff',
                  fontFamily: 'Rajdhani, sans-serif',
                  fontWeight: 800,
                  fontSize: '1.05rem',
                  letterSpacing: '1.5px',
                  textShadow: `0 0 12px ${activeZone.color}`,
                }}
              >
                {activeZone.name}
              </span>
            </div>
            <button
              type="button"
              onClick={resetToOverview}
              title="Đóng bảng và trở về toàn cảnh"
              style={{
                background: 'rgba(255, 255, 255, 0.05)',
                border: '1px solid rgba(255, 255, 255, 0.2)',
                borderRadius: '3px',
                color: '#cbd5e1',
                padding: '4px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                cursor: 'pointer',
                transition: 'all 0.15s ease',
              }}
            >
              <SciFiCyberCloseCancelIcon size={15} color="#cbd5e1" />
            </button>
          </div>

          {/* Subtitle & Role */}
          <div style={{ color: '#cbd5e1', fontSize: '0.78rem', fontWeight: 600, marginBottom: '8px' }}>
            {activeZone.role} • <span style={{ color: activeZone.color, fontWeight: 700 }}>{activeZone.tensor}</span>
          </div>

          {/* Biological Description */}
          <div style={{ color: '#e2e8f0', fontSize: '0.74rem', lineHeight: '1.5', marginBottom: '12px' }}>
            {activeZone.desc}
          </div>

          {/* Live Neuro-Telemetry 3 Micro-Cards Grid */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(3, 1fr)',
              gap: '8px',
              marginBottom: '12px',
            }}
          >
            {/* Card 1: Membrane Voltage */}
            <div
              style={{
                background: 'rgba(0, 0, 0, 0.65)',
                padding: '8px 10px',
                borderRadius: '4px',
                border: '1px solid rgba(0, 255, 157, 0.25)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '4px', color: '#94a3b8', fontSize: '0.68rem', fontWeight: 700 }}>
                <SciFiMembraneVoltageIcon size={13} color="#00ff9d" />
                <span>ĐIỆN THẾ MÀNG</span>
              </div>
              <div style={{ color: '#00ff9d', fontWeight: 800, fontSize: '0.88rem', marginTop: '4px' }}>
                {activeZone.metrics.potential}
              </div>
            </div>

            {/* Card 2: Firing Rate */}
            <div
              style={{
                background: 'rgba(0, 0, 0, 0.65)',
                padding: '8px 10px',
                borderRadius: '4px',
                border: '1px solid rgba(0, 243, 255, 0.25)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '4px', color: '#94a3b8', fontSize: '0.68rem', fontWeight: 700 }}>
                <SciFiSynapticFrequencyIcon size={13} color="#00f3ff" />
                <span>TẦN SỐ XUNG</span>
              </div>
              <div style={{ color: '#00f3ff', fontWeight: 800, fontSize: '0.88rem', marginTop: '4px' }}>
                {activeZone.metrics.firingRate}
              </div>
            </div>

            {/* Card 3: Neurochemistry */}
            <div
              style={{
                background: 'rgba(0, 0, 0, 0.65)',
                padding: '8px 10px',
                borderRadius: '4px',
                border: '1px solid rgba(255, 215, 0, 0.25)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '4px', color: '#94a3b8', fontSize: '0.68rem', fontWeight: 700 }}>
                <SciFiNeuroChemistryFlaskIcon size={13} color="#ffd700" />
                <span>HÓA THẦN KINH</span>
              </div>
              <div
                style={{
                  color: '#ffd700',
                  fontWeight: 800,
                  fontSize: '0.80rem',
                  marginTop: '4px',
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                }}
                title={activeZone.metrics.keyChemical}
              >
                {activeZone.metrics.keyChemical}
              </div>
            </div>
          </div>

          {/* Action Buttons: Deep Brain Stimulation & Reset */}
          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              type="button"
              onClick={fireActionPotential}
              style={{
                flex: 1,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '6px',
                padding: '8px 12px',
                fontSize: '0.76rem',
                fontFamily: 'Rajdhani, sans-serif',
                fontWeight: 700,
                letterSpacing: '0.8px',
                background: `linear-gradient(135deg, ${activeZone.color}40, rgba(0, 243, 255, 0.3))`,
                color: '#ffffff',
                border: `1px solid ${activeZone.color}`,
                borderRadius: '4px',
                cursor: 'pointer',
                textAlign: 'center',
                boxShadow: `0 0 12px ${activeZone.color}55`,
                transition: 'all 0.2s ease',
              }}
            >
              <SciFiDeepBrainStimulationIcon size={16} color="#ffffff" />
              <span>KÍCH THÍCH SÂU (DBS)</span>
            </button>
            <button
              type="button"
              onClick={resetToOverview}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '5px',
                padding: '8px 12px',
                fontSize: '0.74rem',
                fontFamily: 'Share Tech Mono',
                fontWeight: 600,
                background: 'rgba(255, 255, 255, 0.08)',
                color: '#cbd5e1',
                border: '1px solid rgba(255, 255, 255, 0.2)',
                borderRadius: '4px',
                cursor: 'pointer',
                transition: 'all 0.2s ease',
              }}
            >
              <SciFiOverviewHomeIcon size={14} color="#cbd5e1" />
              <span>TOÀN CẢNH</span>
            </button>
          </div>
        </div>
      )}

      {/* ── 3D Canvas Mounting Point ────────────────────────────────────────── */}
      <div ref={mountRef} style={{ width: '100%', height: '100%' }} />

      {/* ── Bottom HUD Footer & Zone Chips ──────────────────────────────────── */}
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
            background: 'rgba(2, 4, 10, 0.94)',
            padding: '8px 14px',
            borderRadius: '4px',
            border: '1px solid rgba(0, 243, 255, 0.3)',
            boxShadow: '0 8px 24px rgba(0,0,0,0.6)',
            display: 'flex',
            flexDirection: 'column',
            gap: '4px',
            pointerEvents: 'auto',
          }}
        >
          <div style={{ color: '#00f3ff', fontWeight: 700, letterSpacing: '1px', fontSize: '0.70rem' }}>
            CHUẨN MÃ HÓA HƯỚNG TRỤC THẦN KINH DTI (HCP FA):
          </div>
          <div style={{ display: 'flex', gap: '14px', flexWrap: 'wrap', fontSize: '0.68rem', color: '#cbd5e1' }}>
            <span style={{ color: '#ff3366', display: 'inline-flex', alignItems: 'center', gap: '4px', fontWeight: 600 }}>
              ● Trục X (Đỏ): Liên bán cầu (Corpus Callosum)
            </span>
            <span style={{ color: '#00ff9d', display: 'inline-flex', alignItems: 'center', gap: '4px', fontWeight: 600 }}>
              ● Trục Y (Xanh lá): Trước - Sau (Frontal-Occipital)
            </span>
            <span style={{ color: '#00f3ff', display: 'inline-flex', alignItems: 'center', gap: '4px', fontWeight: 600 }}>
              ● Trục Z (Xanh lam): Trên - Dưới (Projection)
            </span>
          </div>
        </div>

        {/* Cognitive Zones Interactive Chips */}
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', pointerEvents: 'auto' }}>
          {COGNITIVE_ZONES.map((zone) => {
            const isSelected = activeZone?.id === zone.id;
            return (
              <div
                key={zone.id}
                onClick={() => handleSelectZone(zone)}
                title={`Bấm để focus cận cảnh vào ${zone.name}`}
                style={{
                  background: isSelected ? `${zone.color}33` : 'rgba(2, 5, 14, 0.92)',
                  border: `1.5px solid ${isSelected ? zone.color : 'rgba(255, 255, 255, 0.2)'}`,
                  boxShadow: isSelected ? `0 0 16px ${zone.color}77, inset 0 0 10px ${zone.color}44` : 'none',
                  padding: '7px 13px',
                  borderRadius: '4px',
                  cursor: 'pointer',
                  textAlign: 'center',
                  transition: 'all 0.2s cubic-bezier(0.4, 0, 0.2, 1)',
                  transform: isSelected ? 'translateY(-2px)' : 'none',
                }}
              >
                <div style={{ color: isSelected ? '#ffffff' : zone.color, fontWeight: 700, fontSize: '0.70rem', letterSpacing: '0.5px' }}>
                  {zone.name}
                </div>
                <div style={{ color: isSelected ? zone.color : '#94a3b8', fontSize: '0.64rem', marginTop: '2px' }}>
                  {zone.tensor}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
