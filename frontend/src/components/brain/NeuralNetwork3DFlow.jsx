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
 * NeuralNetwork3DFlow - Interactive 3D Neural Network Architecture & Synaptic Activation Flow
 * 
 * Recreates the exact visual paradigm requested by the user:
 * - Multi-stage neural pipeline: Input Embeddings -> Attention -> FeedForward -> Active Inference -> Workspace -> Cortex -> Dream -> Output Logits.
 * - Diamond biconvex synaptic fiber bundles connecting adjacent layers with multi-spectral colors.
 * - Blazing incandescent focal flare (white-hot core) at the first layer's activation bottleneck.
 * - Residual / Skip connection parabolic arcs looping high above and below non-adjacent layers.
 * - Real-time electrical photon pulse wave flowing from left to right along the synaptic splines.
 * - Monospace HUD layer labels floating above each stage with parameters and activation metrics.
 * - Interactive 3D camera (OrbitControls) with preset camera views (Pipeline side view, 3D perspective, Top-down).
 */

const LAYERS_CONFIG = [
  { id: 'input', name: 'L0: INPUT TOKENS', shape: 'stack', x: -440, nodes: 12, height: 160, params: '64x768', color: '#00f3ff' },
  { id: 'attn', name: 'L1: MULTI-HEAD ATTN', shape: 'plane', x: -280, nodes: 16, height: 210, params: '12.4k', color: '#00ff9d', hasFlare: true },
  { id: 'mlp', name: 'L2: SWIGLU / FFN', shape: 'plane', x: -140, nodes: 14, height: 180, params: '49.2k', color: '#ffd700' },
  { id: 'fep', name: 'L3: ACTIVE INFERENCE', shape: 'plane', x: -10, nodes: 12, height: 160, params: 'F=0.28', color: '#ff3366' },
  { id: 'gw', name: 'L4: GLOBAL WORKSPACE', shape: 'plane', x: 120, nodes: 10, height: 150, params: 'S=0.75', color: '#00f3ff' },
  { id: 'cortex', name: 'L5: VIRTUAL CORTEX', shape: 'plane', x: 240, nodes: 12, height: 160, params: '32GB mmap', color: '#bd00ff' },
  { id: 'dream', name: 'L6: DREAM ENGINE', shape: 'plane', x: 360, nodes: 10, height: 150, params: 'SWS/REM', color: '#00ff9d' },
  { id: 'output', name: 'L7: OUTPUT LOGITS', shape: 'stack', x: 470, nodes: 10, height: 140, params: 'Softmax', color: '#00f3ff' },
];

export default function NeuralNetwork3DFlow({
  onTriggerPulse,
  pulseTrigger = 0,
  telemetry = null,
}) {
  const mountRef = useRef(null);
  const containerRef = useRef(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [activePreset, setActivePreset] = useState('pipeline');
  const [autoRotate, setAutoRotate] = useState(false);

  // References for Three.js state
  const sceneRef = useRef(null);
  const cameraRef = useRef(null);
  const rendererRef = useRef(null);
  const controlsRef = useRef(null);
  const pulseWaveRef = useRef({ active: false, progress: 0, speed: 0.015 });
  const flareSpriteRef = useRef(null);
  const layerMeshesRef = useRef([]);
  const cameraTweenRef = useRef({ active: false, targetPos: new THREE.Vector3(10, 20, 680) });
  const pulseHudBarRef = useRef(null);
  const pulseHudTextRef = useRef(null);

  // Update autoRotate directly without destroying/recreating scene
  useEffect(() => {
    if (controlsRef.current) {
      controlsRef.current.autoRotate = autoRotate;
      controlsRef.current.autoRotateSpeed = 0.8;
    }
  }, [autoRotate]);

  // Create smooth radial glow sprite texture for incandescent focal flares
  const createGlowTexture = useCallback(() => {
    const canvas = document.createElement('canvas');
    canvas.width = 128;
    canvas.height = 128;
    const ctx = canvas.getContext('2d');
    const grad = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
    grad.addColorStop(0, 'rgba(255, 255, 255, 1.0)');
    grad.addColorStop(0.2, 'rgba(255, 240, 180, 0.85)');
    grad.addColorStop(0.5, 'rgba(0, 243, 255, 0.4)');
    grad.addColorStop(0.8, 'rgba(0, 255, 157, 0.1)');
    grad.addColorStop(1, 'rgba(0, 0, 0, 0)');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, 128, 128);
    return new THREE.CanvasTexture(canvas);
  }, []);

  // Set camera to preset angles with smooth flight interpolation
  const applyCameraPreset = useCallback((preset) => {
    if (!cameraRef.current || !controlsRef.current) return;
    setActivePreset(preset);
    const controls = controlsRef.current;
    controls.target.set(10, 0, 0);

    let targetPos = new THREE.Vector3(10, 20, 680);
    if (preset === 'pipeline') {
      targetPos = new THREE.Vector3(10, 20, 680);
    } else if (preset === 'perspective') {
      targetPos = new THREE.Vector3(380, 220, 520);
    } else if (preset === 'top') {
      targetPos = new THREE.Vector3(10, 750, 40);
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
    if (offset.length() > 150 && offset.length() < 1400) {
      camera.position.copy(controls.target).add(offset);
      controls.update();
    }
  }, []);

  // Trigger visual electrical pulse wave through the network
  const triggerVisualPulse = useCallback(() => {
    pulseWaveRef.current.active = true;
    pulseWaveRef.current.progress = 0;
    if (pulseHudTextRef.current) {
      pulseHudTextRef.current.innerText = 'PASS: L0 ➔ L7 [0%] • 1.21 GW POTENTIAL';
      pulseHudTextRef.current.style.color = '#00f3ff';
    }
    if (onTriggerPulse) onTriggerPulse();
  }, [onTriggerPulse]);

  // Expose global trigger for automated test verification
  useEffect(() => {
    window.__triggerBrainPulse = triggerVisualPulse;
    return () => {
      delete window.__triggerBrainPulse;
    };
  }, [triggerVisualPulse]);

  // Watch external pulseTrigger prop
  useEffect(() => {
    if (pulseTrigger > 0) {
      pulseWaveRef.current.active = true;
      pulseWaveRef.current.progress = 0;
      if (pulseHudTextRef.current) {
        pulseHudTextRef.current.innerText = 'PASS: L0 ➔ L7 [0%] • 1.21 GW POTENTIAL';
        pulseHudTextRef.current.style.color = '#00f3ff';
      }
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
    const height = mount.clientHeight || 500;

    // 1. Scene & Camera
    const scene = new THREE.Scene();
    sceneRef.current = scene;
    scene.background = new THREE.Color(0x060814);
    scene.fog = new THREE.FogExp2(0x060814, 0.0006);

    const camera = new THREE.PerspectiveCamera(45, width / height, 1, 3000);
    camera.position.set(10, 20, 680);
    cameraRef.current = camera;

    // 2. WebGL Renderer
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: 'high-performance' });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    mount.appendChild(renderer.domElement);
    rendererRef.current = renderer;

    // 3. OrbitControls
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.maxDistance = 1400;
    controls.minDistance = 150;
    controls.enableZoom = false; // Disable default wheel capture so the page scrolls freely
    controls.target.set(10, 0, 0);
    controlsRef.current = controls;

    // Ctrl + mouse wheel for precision 3D zooming without blocking normal page scrolling
    const handleDomWheel = (e) => {
      if (e.ctrlKey && cameraRef.current && controlsRef.current) {
        e.preventDefault();
        const factor = e.deltaY > 0 ? 1.08 : 0.92;
        const offset = cameraRef.current.position.clone().sub(controlsRef.current.target);
        offset.multiplyScalar(factor);
        if (offset.length() > 150 && offset.length() < 1400) {
          cameraRef.current.position.copy(controlsRef.current.target).add(offset);
          controlsRef.current.update();
        }
      }
    };
    renderer.domElement.addEventListener('wheel', handleDomWheel, { passive: false });

    // 4. Lighting
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.8);
    scene.add(ambientLight);

    const cyanPointLight = new THREE.PointLight(0x00f3ff, 2.5, 900);
    cyanPointLight.position.set(-320, 0, 100);
    scene.add(cyanPointLight);

    const pinkPointLight = new THREE.PointLight(0xff0055, 1.8, 800);
    pinkPointLight.position.set(200, 0, 100);
    scene.add(pinkPointLight);

    // 5. Build Neural Layers & Nodes
    const layerMeshes = [];
    const layerPositions = []; // Store node positions per layer for spline wiring
    const layerMetaList = [];

    LAYERS_CONFIG.forEach((cfg, lIdx) => {
      const nodeCoords = [];
      const layerNodes = [];
      const nodeCount = cfg.nodes;
      const layerGroup = new THREE.Group();
      layerGroup.position.set(cfg.x, 0, 0);

      // Layer Boundary Wireframe Box
      const planeGeo = new THREE.BoxGeometry(14, cfg.height, 48);
      const wireMat = new THREE.MeshBasicMaterial({
        color: new THREE.Color(cfg.color),
        wireframe: true,
        transparent: true,
        opacity: 0.22,
      });
      const planeMesh = new THREE.Mesh(planeGeo, wireMat);
      layerGroup.add(planeMesh);

      // Nodes inside the layer
      const nodeGeo = new THREE.BoxGeometry(6, cfg.shape === 'stack' ? 9 : 6, 6);
      for (let i = 0; i < nodeCount; i++) {
        const t = (i / (nodeCount - 1 || 1)) - 0.5;
        const y = t * (cfg.height - 18);
        const z = (Math.sin(i * 1.5) * 14);

        const nodeMat = new THREE.MeshBasicMaterial({
          color: new THREE.Color(cfg.color),
          transparent: true,
          opacity: 0.85,
        });
        const nodeMesh = new THREE.Mesh(nodeGeo, nodeMat);
        nodeMesh.position.set(0, y, z);
        layerGroup.add(nodeMesh);
        layerNodes.push(nodeMesh);

        nodeCoords.push(new THREE.Vector3(cfg.x, y, z));
      }

      // Add double sphere indicators above Layer 1 (matching user screenshot)
      if (lIdx === 1) {
        const indGeo = new THREE.SphereGeometry(4.5, 16, 16);
        const indMat = new THREE.MeshBasicMaterial({ color: 0xffffff });
        const ind1 = new THREE.Mesh(indGeo, indMat);
        ind1.position.set(-6, (cfg.height / 2) + 26, 0);
        const ind2 = new THREE.Mesh(indGeo, indMat);
        ind2.position.set(6, (cfg.height / 2) + 26, 0);
        layerGroup.add(ind1);
        layerGroup.add(ind2);
      }

      scene.add(layerGroup);
      layerMeshes.push(layerGroup);
      layerPositions.push(nodeCoords);
      layerMetaList.push({
        id: cfg.id,
        name: cfg.name,
        x: cfg.x,
        planeMesh,
        wireMat,
        nodes: layerNodes,
        baseColor: new THREE.Color(cfg.color),
      });
    });

    layerMeshesRef.current = layerMeshes;

    // 6. Build Diamond Biconvex Synaptic Fiber Bundles
    // Using single batched BufferGeometry with Vertex Colors for maximum 60FPS throughput
    const fiberPoints = [];
    const fiberColors = [];
    const palette = [
      new THREE.Color('#00ff9d'), // Neon Green
      new THREE.Color('#ffd700'), // Gold
      new THREE.Color('#ff8800'), // Amber
      new THREE.Color('#ff3366'), // Crimson
      new THREE.Color('#00f3ff'), // Cyan
    ];

    const allSplineCurves = [];

    for (let l = 0; l < layerPositions.length - 1; l++) {
      const fromNodes = layerPositions[l];
      const toNodes = layerPositions[l + 1];
      const midX = (LAYERS_CONFIG[l].x + LAYERS_CONFIG[l + 1].x) / 2;

      // Diamond biconvex bulge factor (first bundle is huge, others are proportional)
      const bulgeScale = l === 0 ? 1.45 : (l === 1 ? 1.25 : 1.05);

      // Connect sample pairs
      const density = l === 0 ? 28 : (l === 1 ? 22 : 16);

      for (let f = 0; f < fromNodes.length; f += (l === 0 ? 1 : 2)) {
        for (let t = 0; t < toNodes.length; t += (l === 0 ? 1 : 2)) {
          if ((f + t) % (density > 20 ? 1 : 2) !== 0) continue;

          const p0 = fromNodes[f];
          const p3 = toNodes[t];

          // Biconvex bulge: mid Y is pushed away from 0 to form diamond
          const avgY = (p0.y + p3.y) / 2;
          const bulgedY = avgY * bulgeScale + (Math.sin(f + t) * (l === 0 ? 32 : 16));
          const bulgedZ = ((p0.z + p3.z) / 2) * bulgeScale + (Math.cos(f * 2) * 18);

          // Cubic Bezier curve control points
          const p1 = new THREE.Vector3(midX - 25, bulgedY, bulgedZ);
          const p2 = new THREE.Vector3(midX + 25, bulgedY, bulgedZ);

          const curve = new THREE.CubicBezierCurve3(p0, p1, p2, p3);
          allSplineCurves.push(curve);

          const color = palette[(f * 3 + t * 5 + l) % palette.length];
          const segments = 12;
          const pts = curve.getPoints(segments);

          for (let p = 0; p < pts.length - 1; p++) {
            fiberPoints.push(pts[p].x, pts[p].y, pts[p].z);
            fiberPoints.push(pts[p + 1].x, pts[p + 1].y, pts[p + 1].z);

            // Shading: brighter at center
            const alpha = 0.5 + Math.sin((p / segments) * Math.PI) * 0.5;
            fiberColors.push(color.r * alpha, color.g * alpha, color.b * alpha);
            fiberColors.push(color.r * alpha, color.g * alpha, color.b * alpha);
          }
        }
      }
    }

    const fiberGeo = new THREE.BufferGeometry();
    fiberGeo.setAttribute('position', new THREE.Float32BufferAttribute(fiberPoints, 3));
    fiberGeo.setAttribute('color', new THREE.Float32BufferAttribute(fiberColors, 3));

    const fiberMat = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: 0.65,
      blending: THREE.AdditiveBlending,
    });
    const fiberMesh = new THREE.LineSegments(fiberGeo, fiberMat);
    scene.add(fiberMesh);

    // 7. Incandescent White-Hot Focal Flare (Center of Bundle 0 -> 1)
    const glowTex = createGlowTexture();
    const flareMat = new THREE.SpriteMaterial({
      map: glowTex,
      color: 0xffffff,
      transparent: true,
      opacity: 0.95,
      blending: THREE.AdditiveBlending,
    });
    const flareSprite = new THREE.Sprite(flareMat);
    const flareMidX = (LAYERS_CONFIG[0].x + LAYERS_CONFIG[1].x) / 2;
    flareSprite.position.set(flareMidX, 0, 0);
    flareSprite.scale.set(130, 240, 1);
    scene.add(flareSprite);
    flareSpriteRef.current = flareSprite;

    // Second smaller flare for Bundle 1 -> 2
    const flareMat2 = flareMat.clone();
    flareMat2.color = new THREE.Color('#ffe082');
    flareMat2.opacity = 0.7;
    const flareSprite2 = new THREE.Sprite(flareMat2);
    const flareMidX2 = (LAYERS_CONFIG[1].x + LAYERS_CONFIG[2].x) / 2;
    flareSprite2.position.set(flareMidX2, 0, 0);
    flareSprite2.scale.set(90, 170, 1);
    scene.add(flareSprite2);

    // 8. Residual / Skip Connections (Parabolic Arcs looping OVER & UNDER)
    const skipPoints = [];
    const skipColors = [];
    const skipPalette = [new THREE.Color('#00f3ff'), new THREE.Color('#ff007f'), new THREE.Color('#00ff9d')];

    // Define multi-layer skip jumps: [fromLayer, toLayer, archHeight, isOver]
    const skipJumps = [
      [1, 3, 155, true],   // L1 to L3 over
      [2, 4, 145, true],   // L2 to L4 over
      [3, 5, 135, true],   // L3 to L5 over
      [4, 6, 125, true],   // L4 to L6 over
      [1, 4, -145, false], // L1 to L4 under
      [2, 5, -135, false], // L2 to L5 under
      [3, 6, -125, false], // L3 to L6 under
    ];

    skipJumps.forEach(([fromIdx, toIdx, archH, isOver], sIdx) => {
      const fromCfg = LAYERS_CONFIG[fromIdx];
      const toCfg = LAYERS_CONFIG[toIdx];
      const startY = isOver ? (fromCfg.height / 2) : -(fromCfg.height / 2);
      const endY = isOver ? (toCfg.height / 2) : -(toCfg.height / 2);

      const p0 = new THREE.Vector3(fromCfg.x, startY, 0);
      const p3 = new THREE.Vector3(toCfg.x, endY, 0);
      const midX = (fromCfg.x + toCfg.x) / 2;
      const peakY = isOver ? (Math.max(startY, endY) + archH) : (Math.min(startY, endY) + archH);

      const p1 = new THREE.Vector3(midX - 30, peakY, isOver ? 20 : -20);
      const p2 = new THREE.Vector3(midX + 30, peakY, isOver ? 20 : -20);

      const arcCurve = new THREE.CubicBezierCurve3(p0, p1, p2, p3);
      const segments = 24;
      const arcPts = arcCurve.getPoints(segments);
      const c = skipPalette[sIdx % skipPalette.length];

      for (let p = 0; p < arcPts.length - 1; p++) {
        skipPoints.push(arcPts[p].x, arcPts[p].y, arcPts[p].z);
        skipPoints.push(arcPts[p + 1].x, arcPts[p + 1].y, arcPts[p + 1].z);
        skipColors.push(c.r, c.g, c.b);
        skipColors.push(c.r, c.g, c.b);
      }
    });

    const skipGeo = new THREE.BufferGeometry();
    skipGeo.setAttribute('position', new THREE.Float32BufferAttribute(skipPoints, 3));
    skipGeo.setAttribute('color', new THREE.Float32BufferAttribute(skipColors, 3));

    const skipMat = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: 0.85,
      blending: THREE.AdditiveBlending,
    });
    const skipMesh = new THREE.LineSegments(skipGeo, skipMat);
    scene.add(skipMesh);

    // 8b. High-Energy Traveling Shockwave Wavefront
    const shockwaveGroup = new THREE.Group();
    
    // Main inner glowing plasma cylinder
    const shockGeo = new THREE.CylinderGeometry(85, 85, 14, 32, 1, true);
    shockGeo.rotateZ(Math.PI / 2);
    const shockMat = new THREE.MeshBasicMaterial({
      color: 0x00f3ff,
      transparent: true,
      opacity: 0,
      blending: THREE.AdditiveBlending,
      side: THREE.DoubleSide,
    });
    const shockMesh = new THREE.Mesh(shockGeo, shockMat);
    shockwaveGroup.add(shockMesh);

    // Outer razor-sharp ionization ring
    const ringGeo = new THREE.RingGeometry(80, 96, 32);
    ringGeo.rotateY(Math.PI / 2);
    const ringMat = new THREE.MeshBasicMaterial({
      color: 0xffffff,
      transparent: true,
      opacity: 0,
      blending: THREE.AdditiveBlending,
      side: THREE.DoubleSide,
    });
    const ringMesh = new THREE.Mesh(ringGeo, ringMat);
    shockwaveGroup.add(ringMesh);

    // Dynamic point light carried by the shockwave wavefront
    const shockLight = new THREE.PointLight(0x00f3ff, 0, 450);
    shockwaveGroup.add(shockLight);

    shockwaveGroup.position.set(-480, 0, 0);
    scene.add(shockwaveGroup);

    // 9. Particle Wave Stream (Electrical Action Potential Packets)
    const particleCount = 180;
    const particlePositions = new Float32Array(particleCount * 3);
    const particleProgress = new Float32Array(particleCount);
    const particleCurves = [];

    for (let i = 0; i < particleCount; i++) {
      particleProgress[i] = Math.random();
      const randCurve = allSplineCurves[Math.floor(Math.random() * allSplineCurves.length)];
      particleCurves.push(randCurve);
      const pt = randCurve.getPoint(particleProgress[i]);
      particlePositions[i * 3] = pt.x;
      particlePositions[i * 3 + 1] = pt.y;
      particlePositions[i * 3 + 2] = pt.z;
    }

    const particleGeo = new THREE.BufferGeometry();
    particleGeo.setAttribute('position', new THREE.BufferAttribute(particlePositions, 3));

    const particleMat = new THREE.PointsMaterial({
      color: 0xffffff,
      size: 4.5,
      transparent: true,
      opacity: 0.9,
      blending: THREE.AdditiveBlending,
    });
    const particleSystem = new THREE.Points(particleGeo, particleMat);
    scene.add(particleSystem);

    // 10. Animation Loop
    let animId;
    let clock = new THREE.Clock();

    const animate = () => {
      animId = requestAnimationFrame(animate);

      const delta = clock.getDelta();
      const time = clock.getElapsedTime();

      // Controls damping
      controls.update();

      // Camera smooth flight interpolation
      if (cameraTweenRef.current?.active) {
        camera.position.lerp(cameraTweenRef.current.targetPos, delta * 6.0);
        if (camera.position.distanceTo(cameraTweenRef.current.targetPos) < 2) {
          camera.position.copy(cameraTweenRef.current.targetPos);
          cameraTweenRef.current.active = false;
        }
      }

      // Flare pulsation
      if (flareSpriteRef.current) {
        const baseScale = 130 + Math.sin(time * 5.0) * 12;
        const baseHeight = 240 + Math.cos(time * 4.0) * 18;
        flareSpriteRef.current.scale.set(baseScale, baseHeight, 1);
      }

      // Update particle stream along splines
      const positions = particleGeo.attributes.position.array;
      const isPulsingActive = pulseWaveRef.current.active;
      const streamSpeed = isPulsingActive ? 0.035 : 0.008;
      for (let i = 0; i < particleCount; i++) {
        particleProgress[i] = (particleProgress[i] + streamSpeed) % 1.0;
        const curve = particleCurves[i];
        if (curve) {
          const pt = curve.getPoint(particleProgress[i]);
          positions[i * 3] = pt.x;
          positions[i * 3 + 1] = pt.y;
          positions[i * 3 + 2] = pt.z;
        }
      }
      particleGeo.attributes.position.needsUpdate = true;

      // Handle SPECTACULAR NEURAL SHOCKWAVE SURGE
      if (typeof window !== 'undefined' && window.__holdPulseProgress !== undefined) {
        pulseWaveRef.current.active = true;
        pulseWaveRef.current.progress = window.__holdPulseProgress;
      }

      if (isPulsingActive) {
        if (typeof window === 'undefined' || window.__holdPulseProgress === undefined) {
          pulseWaveRef.current.progress += delta / 2.6; // ~2.6s sweep time across 8 layers
        }
        const progress = pulseWaveRef.current.progress;

        if (progress >= 1.0) {
          pulseWaveRef.current.active = false;
          pulseWaveRef.current.progress = 0;
          shockMat.opacity = 0;
          ringMat.opacity = 0;
          shockLight.intensity = 0;
          if (pulseHudBarRef.current) pulseHudBarRef.current.style.width = '0%';
          if (pulseHudTextRef.current) {
            pulseHudTextRef.current.innerText = 'MẠNG SẴN SÀNG • BẤM ĐỂ PHÓNG XUNG';
            pulseHudTextRef.current.style.color = 'rgba(224, 242, 254, 0.65)';
          }
        } else {
          // Current X coordinate along the pipeline (-480 to +490)
          const waveX = -480 + progress * 970;
          shockwaveGroup.position.x = waveX;

          // Wavefront breathing & opacity
          const waveFade = progress < 0.1 ? progress / 0.1 : (progress > 0.85 ? (1.0 - progress) / 0.15 : 1.0);
          shockMat.opacity = 0.85 * waveFade;
          ringMat.opacity = 0.95 * waveFade;
          shockLight.intensity = 5.0 * waveFade;

          // Dynamic spectral color shift
          if (progress < 0.3) {
            shockMat.color.setHex(0x00f3ff);
            shockLight.color.setHex(0x00f3ff);
          } else if (progress < 0.6) {
            shockMat.color.setHex(0xffffff);
            shockLight.color.setHex(0xffffff);
          } else if (progress < 0.8) {
            shockMat.color.setHex(0xffd700);
            shockLight.color.setHex(0xffd700);
          } else {
            shockMat.color.setHex(0x00ff9d);
            shockLight.color.setHex(0x00ff9d);
          }

          const pulseScale = 1.0 + Math.sin(time * 25.0) * 0.18;
          shockwaveGroup.scale.set(1, pulseScale, pulseScale);

          // Fiber line segments flash
          fiberMat.opacity = 0.65 + Math.sin(progress * Math.PI) * 0.35;

          // Camera micro-tremor in the first 350ms
          if (progress < 0.22) {
            const tremorMag = (1.0 - progress / 0.22) * 2.8;
            camera.position.x += (Math.random() - 0.5) * tremorMag;
            camera.position.y += (Math.random() - 0.5) * tremorMag;
          }

          // Incandescent flare burst when wave sweeps through L1 (-280)
          if (flareSpriteRef.current && Math.abs(waveX - (-280)) < 70) {
            const burstFactor = 1.0 - Math.abs(waveX - (-280)) / 70;
            flareSpriteRef.current.scale.set(130 + burstFactor * 140, 240 + burstFactor * 220, 1);
          }

          // Layer Ignition: check each layer
          layerMetaList.forEach((meta) => {
            const dist = Math.abs(waveX - meta.x);
            if (dist < 55) {
              const ignite = 1.0 - dist / 55;
              // Light up bounding wireframe
              meta.wireMat.opacity = 0.22 + ignite * 0.78;
              meta.wireMat.color.lerpColors(meta.baseColor, new THREE.Color(0xffffff), ignite * 0.9);

              // Expand and blaze all node cubes in this layer
              meta.nodes.forEach((node) => {
                const nodeScale = 1.0 + ignite * 1.5; // up to 2.5x
                node.scale.set(nodeScale, nodeScale, nodeScale);
                node.material.color.lerpColors(meta.baseColor, new THREE.Color(0xffffff), ignite * 0.9);
              });
            } else {
              // Smoothly decay back to normal
              meta.wireMat.opacity = THREE.MathUtils.lerp(meta.wireMat.opacity, 0.22, delta * 7);
              meta.wireMat.color.lerp(meta.baseColor, delta * 7);
              meta.nodes.forEach((node) => {
                node.scale.lerp(new THREE.Vector3(1, 1, 1), delta * 7);
                node.material.color.lerp(meta.baseColor, delta * 7);
              });
            }
          });

          // Update HUD progress bar in real-time
          const pct = Math.min(100, Math.round(progress * 100));
          if (pulseHudBarRef.current) {
            pulseHudBarRef.current.style.width = `${pct}%`;
          }
          if (pulseHudTextRef.current) {
            pulseHudTextRef.current.innerText = `PASS: L0 ➔ L7 [${pct}%] • 1.21 GW POTENTIAL`;
            pulseHudTextRef.current.style.color = '#00ff9d';
          }
        }
      } else {
        // Idle decay for all layers
        layerMetaList.forEach((meta) => {
          meta.wireMat.opacity = THREE.MathUtils.lerp(meta.wireMat.opacity, 0.22, delta * 8);
          meta.wireMat.color.lerp(meta.baseColor, delta * 8);
          meta.nodes.forEach((node) => {
            node.scale.lerp(new THREE.Vector3(1, 1, 1), delta * 8);
            node.material.color.lerp(meta.baseColor, delta * 8);
          });
        });
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

    // 12. Cleanup on Unmount
    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener('resize', handleResize);
      renderer.domElement.removeEventListener('wheel', handleDomWheel);
      controls.dispose();
      renderer.dispose();
      fiberGeo.dispose();
      fiberMat.dispose();
      skipGeo.dispose();
      skipMat.dispose();
      shockGeo.dispose();
      shockMat.dispose();
      ringGeo.dispose();
      ringMat.dispose();
      particleGeo.dispose();
      particleMat.dispose();
      glowTex.dispose();
      if (mount.contains(renderer.domElement)) {
        mount.removeChild(renderer.domElement);
      }
    };
  }, [createGlowTexture]);

  return (
    <div
      ref={containerRef}
      style={{
        width: '100%',
        height: isFullscreen ? '100vh' : '520px',
        background: '#060814',
        border: '1px solid rgba(0, 243, 255, 0.35)',
        borderRadius: '4px',
        position: 'relative',
        overflow: 'hidden',
        boxShadow: '0 8px 40px rgba(0, 243, 255, 0.12), inset 0 0 25px rgba(0, 243, 255, 0.05)',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* ── Top HUD Status Bar ───────────────────────────────────────── */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          padding: '10px 16px',
          background: 'linear-gradient(180deg, rgba(6, 12, 24, 0.88) 0%, rgba(6, 12, 24, 0) 100%)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          zIndex: 10,
          pointerEvents: 'none',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', pointerEvents: 'auto' }}>
          <SciFiCognitivePulseBurstIcon size={20} color="var(--accent-cyan)" />
          <div>
            <div
              style={{
                fontSize: '0.86rem',
                fontWeight: 700,
                color: '#ffffff',
                letterSpacing: '1.5px',
                fontFamily: 'Rajdhani, sans-serif',
              }}
            >
              VISUALIZER MẠNG NƠ-RON 3D • TIỂU BẢO BẢO SYNAPTIC PIPELINE
            </div>
            <div style={{ fontSize: '0.68rem', color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono' }}>
              8 Layers • 10k-Bit Biconvex Diamond Bundles • Residual Skip Arcs • F={telemetry?.active_inference?.free_energy ?? 0.28}
            </div>
          </div>
        </div>

        {/* Action Buttons & Real-Time Pulse HUD */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', pointerEvents: 'auto', flexWrap: 'wrap' }}>
          {/* Real-time Pulse Energy Bar */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              background: 'rgba(0,0,0,0.6)',
              padding: '3px 10px',
              borderRadius: '2px',
              border: '1px solid rgba(0, 243, 255, 0.25)',
            }}
          >
            <div
              ref={pulseHudTextRef}
              style={{
                fontSize: '0.68rem',
                fontFamily: 'Share Tech Mono, monospace',
                color: 'rgba(224, 242, 254, 0.65)',
                minWidth: '205px',
                textAlign: 'center',
              }}
            >
              MẠNG SẴN SÀNG • BẤM ĐỂ PHÓNG XUNG
            </div>
            <div
              style={{
                width: '75px',
                height: '5px',
                background: 'rgba(255, 255, 255, 0.1)',
                borderRadius: '2px',
                overflow: 'hidden',
              }}
            >
              <div
                ref={pulseHudBarRef}
                style={{
                  width: '0%',
                  height: '100%',
                  background: 'linear-gradient(90deg, #00f3ff, #00ff9d)',
                  boxShadow: '0 0 6px #00f3ff',
                  transition: 'width 0.05s linear',
                }}
              />
            </div>
          </div>

          {/* Preset Buttons */}
          <div style={{ display: 'flex', background: 'rgba(0,0,0,0.5)', padding: '2px', borderRadius: '3px', border: '1px solid rgba(0,243,255,0.2)' }}>
            <button
              type="button"
              onClick={() => applyCameraPreset('pipeline')}
              style={{
                padding: '4px 10px',
                fontSize: '0.7rem',
                fontFamily: 'Share Tech Mono',
                background: activePreset === 'pipeline' ? 'rgba(0, 243, 255, 0.25)' : 'transparent',
                color: activePreset === 'pipeline' ? '#00f3ff' : 'rgba(255,255,255,0.7)',
                border: 'none',
                cursor: 'pointer',
                borderRadius: '2px',
              }}
              title="Góc nhìn ngang Pipeline giống video mẫu"
            >
              Góc Ngang (Mẫu)
            </button>
            <button
              type="button"
              onClick={() => applyCameraPreset('perspective')}
              style={{
                padding: '4px 10px',
                fontSize: '0.7rem',
                fontFamily: 'Share Tech Mono',
                background: activePreset === 'perspective' ? 'rgba(0, 243, 255, 0.25)' : 'transparent',
                color: activePreset === 'perspective' ? '#00f3ff' : 'rgba(255,255,255,0.7)',
                border: 'none',
                cursor: 'pointer',
                borderRadius: '2px',
              }}
              title="Phối cảnh 3D có chiều sâu"
            >
              Phối Cảnh 3D
            </button>
            <button
              type="button"
              onClick={() => applyCameraPreset('top')}
              style={{
                padding: '4px 10px',
                fontSize: '0.7rem',
                fontFamily: 'Share Tech Mono',
                background: activePreset === 'top' ? 'rgba(0, 243, 255, 0.25)' : 'transparent',
                color: activePreset === 'top' ? '#00f3ff' : 'rgba(255,255,255,0.7)',
                border: 'none',
                cursor: 'pointer',
                borderRadius: '2px',
              }}
              title="Góc nhìn từ trên xuống"
            >
              Top-Down
            </button>
          </div>

          {/* Zoom In/Out Buttons */}
          <div style={{ display: 'flex', background: 'rgba(0,0,0,0.5)', padding: '2px', borderRadius: '3px', border: '1px solid rgba(0,243,255,0.2)' }}>
            <button
              type="button"
              onClick={() => handleZoom(0.85)}
              style={{
                padding: '4px 8px',
                background: 'transparent',
                color: '#00f3ff',
                border: 'none',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
              }}
              title="Phóng to 3D (Zoom In)"
            >
              <SciFiZoomInIcon size={13} color="#00f3ff" />
            </button>
            <button
              type="button"
              onClick={() => handleZoom(1.15)}
              style={{
                padding: '4px 8px',
                background: 'transparent',
                color: '#00f3ff',
                border: 'none',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
              }}
              title="Thu nhỏ 3D (Zoom Out)"
            >
              <SciFiZoomOutIcon size={13} color="#00f3ff" />
            </button>
          </div>

          {/* Auto-Rotate Toggle */}
          <button
            type="button"
            onClick={() => setAutoRotate(!autoRotate)}
            style={{
              padding: '4px 10px',
              fontSize: '0.7rem',
              fontFamily: 'Share Tech Mono',
              background: autoRotate ? 'rgba(0, 255, 157, 0.2)' : 'rgba(255, 255, 255, 0.06)',
              color: autoRotate ? '#00ff9d' : '#e0f2fe',
              border: `1px solid ${autoRotate ? '#00ff9d' : 'rgba(255, 255, 255, 0.2)'}`,
              cursor: 'pointer',
              borderRadius: '2px',
            }}
          >
            {autoRotate ? 'Xoay 360° [BẬT]' : 'Xoay 360° [TẮT]'}
          </button>

          {/* Trigger Pulse Surge Button */}
          <button
            type="button"
            onClick={triggerVisualPulse}
            style={{
              padding: '4px 12px',
              fontSize: '0.72rem',
              fontWeight: 700,
              fontFamily: 'Share Tech Mono',
              background: 'linear-gradient(135deg, rgba(0, 243, 255, 0.25), rgba(0, 255, 157, 0.3))',
              color: '#ffffff',
              border: '1px solid var(--accent-cyan)',
              cursor: 'pointer',
              borderRadius: '2px',
              boxShadow: '0 0 10px rgba(0, 243, 255, 0.3)',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            <SciFiCognitivePulseBurstIcon size={13} color="#ffffff" />
            <span>BẮN XUNG ĐIỆN</span>
          </button>

          {/* Fullscreen Toggle */}
          <button
            type="button"
            onClick={toggleFullscreen}
            style={{
              padding: '4px 8px',
              fontSize: '0.75rem',
              background: 'rgba(255, 255, 255, 0.08)',
              color: '#e0f2fe',
              border: '1px solid rgba(255, 255, 255, 0.2)',
              cursor: 'pointer',
              borderRadius: '2px',
              display: 'flex',
              alignItems: 'center',
            }}
            title={isFullscreen ? 'Thu nhỏ' : 'Toàn màn hình'}
          >
            {isFullscreen ? (
              <SciFiFullscreenExitIcon size={14} color="#e0f2fe" />
            ) : (
              <SciFiFullscreenExpandIcon size={14} color="#e0f2fe" />
            )}
          </button>
        </div>
      </div>

      {/* ── Three.js WebGL Mount Canvas ──────────────────────────────── */}
      <div ref={mountRef} style={{ width: '100%', height: '100%', cursor: 'grab' }} />

      {/* ── Overlay Layer Labels ────────────────────────────────────── */}
      <div
        style={{
          position: 'absolute',
          bottom: 12,
          left: 16,
          right: 16,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          pointerEvents: 'none',
          fontSize: '0.68rem',
          fontFamily: 'Share Tech Mono, monospace',
        }}
      >
        <div style={{ color: 'rgba(224, 242, 254, 0.65)', display: 'flex', gap: '16px' }}>
          <span>Chuột trái: <strong style={{ color: '#00f3ff' }}>Xoay 3D</strong></span>
          <span>Ctrl + Cuộn chuột: <strong style={{ color: '#00f3ff' }}>Phóng to/Thu nhỏ</strong></span>
          <span>Chuột phải: <strong style={{ color: '#00f3ff' }}>Di chuyển (Pan)</strong></span>
        </div>

        <div style={{ display: 'flex', gap: '14px', alignItems: 'center' }}>
          <span style={{ color: '#ff3366', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
            <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#ff3366', display: 'inline-block' }} />
            <span>Dây đỏ: Ức chế / Trọng số âm</span>
          </span>
          <span style={{ color: '#00ff9d', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
            <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#00ff9d', display: 'inline-block' }} />
            <span>Dây xanh lá: Hưng phấn / Trọng số dương</span>
          </span>
          <span style={{ color: '#ffd700', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
            <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#ffd700', display: 'inline-block' }} />
            <span>Dây vàng: Chùm kích hoạt cao</span>
          </span>
          <span style={{ color: '#00f3ff', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
            <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#00f3ff', display: 'inline-block' }} />
            <span>Vòng cung: Residual Skip Connections</span>
          </span>
        </div>
      </div>
    </div>
  );
}
