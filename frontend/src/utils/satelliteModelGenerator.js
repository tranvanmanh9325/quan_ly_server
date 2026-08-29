import * as THREE from 'three';

/**
 * Photorealistic 3D Spacecraft Generator with NASA 3-Point Space Lighting & 3D Attitude Dynamics.
 * 
 * Generates high-fidelity satellites with:
 * - Kapton Gold MLI Foil with metallic specular highlights
 * - Deep-Blue Silicon Solar Array Wafers with silver busbars
 * - Chrome Parabolic High-Gain Dish Antenna
 * - Star Trackers & Optical Earth-Observation Baffles
 * - 4-Quadrant RCS Thruster Pods
 * - Magnetometer / Space Truss Boom
 * 
 * Includes updateSatellite3DTransform with 28° natural pitch offset, slow axial drift, and solar array tracking.
 */

let sharedKaptonMaterial = null;
let sharedSolarMaterial = null;
let sharedMetalDarkMaterial = null;
let sharedMetalChromeMaterial = null;
let sharedBeaconGeo = null;

// Reusable Geometry Singletons
let sharedBodyGeo = null;
let sharedPlateGeo = null;
let sharedYokeGeo = null;
let sharedFrameGeo = null;
let sharedCellGeo = null;
let sharedCellEdgeGeo = null;
let sharedGimbalGeo = null;
let sharedDishGeo = null;
let sharedFeedGeo = null;
let sharedBaffleGeo = null;
let sharedNozzleGeo = null;
let sharedMastGeo = null;
let sharedMagHeadGeo = null;

// Reusable Material Caches by Hex Color
const beaconMaterialCache = new Map();
const lineMaterialCache = new Map();

function getOrCreateBeaconMaterial(hexColor) {
  if (!beaconMaterialCache.has(hexColor)) {
    beaconMaterialCache.set(hexColor, new THREE.MeshBasicMaterial({ color: new THREE.Color(hexColor) }));
  }
  return beaconMaterialCache.get(hexColor);
}

function getOrCreateLineMaterial(hexColor) {
  if (!lineMaterialCache.has(hexColor)) {
    lineMaterialCache.set(
      hexColor,
      new THREE.LineBasicMaterial({
        color: new THREE.Color(hexColor),
        transparent: true,
        opacity: 0.75,
      })
    );
  }
  return lineMaterialCache.get(hexColor);
}

// Pre-allocated Vector3 / Matrix4 / Quaternion buffers for ZERO Garbage Collection
const _satPos = new THREE.Vector3();
const _targetLook = new THREE.Vector3(0, 0, 0);
const _upVector = new THREE.Vector3(0, 1, 0);
const _pitchAxis = new THREE.Vector3(1, 0, 0);
const _yawAxis = new THREE.Vector3(0, 1, 0);
const _rotMatrix = new THREE.Matrix4();
const _pitchQuat = new THREE.Quaternion();
const _yawQuat = new THREE.Quaternion();
const _combinedQuat = new THREE.Quaternion();

/**
 * Generates procedural Kapton gold foil bump & color texture on HTML5 Canvas.
 */
function createKaptonCanvasTexture(size = 512) {
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  if (!ctx) return new THREE.Texture();

  // Base amber gold foil color
  ctx.fillStyle = '#e8a115';
  ctx.fillRect(0, 0, size, size);

  const imgData = ctx.getImageData(0, 0, size, size);
  const data = imgData.data;

  // Multi-frequency noise for sharp foil wrinkle facets
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const idx = (y * size + x) * 4;
      const n1 = Math.sin(x * 0.08 + Math.cos(y * 0.06) * 4.0);
      const n2 = Math.cos(y * 0.12 + Math.sin(x * 0.10) * 3.0);
      const n3 = Math.sin((x + y) * 0.04) * Math.cos((x - y) * 0.05);
      const wrinkle = (n1 * 0.4 + n2 * 0.4 + n3 * 0.2) * 45;

      data[idx] = Math.min(255, Math.max(160, data[idx] + wrinkle));
      data[idx + 1] = Math.min(210, Math.max(100, data[idx + 1] + wrinkle * 0.8));
      data[idx + 2] = Math.min(80, Math.max(10, data[idx + 2] + wrinkle * 0.3));
    }
  }
  ctx.putImageData(imgData, 0, 0);

  // Gold thermal tape seams (grid lines)
  ctx.strokeStyle = 'rgba(255, 235, 120, 0.45)';
  ctx.lineWidth = 2.5;
  const step = size / 8;
  for (let i = 0; i <= size; i += step) {
    ctx.beginPath();
    ctx.moveTo(i, 0);
    ctx.lineTo(i, size);
    ctx.stroke();

    ctx.beginPath();
    ctx.moveTo(0, i);
    ctx.lineTo(size, i);
    ctx.stroke();
  }

  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  return texture;
}

/**
 * Generates photorealistic deep-blue solar array texture with silicon wafers & silver busbars.
 */
function createSolarPanelCanvasTexture(width = 512, height = 256) {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d');
  if (!ctx) return new THREE.Texture();

  // Deep space navy blue substrate
  ctx.fillStyle = '#060e22';
  ctx.fillRect(0, 0, width, height);

  const cols = 6;
  const rows = 3;
  const cellW = width / cols;
  const cellH = height / rows;
  const pad = 3;

  for (let c = 0; c < cols; c++) {
    for (let r = 0; r < rows; r++) {
      const x = c * cellW + pad;
      const y = r * cellH + pad;
      const w = cellW - pad * 2;
      const h = cellH - pad * 2;

      // Individual silicon wafer gradient with anti-reflective coating
      const grad = ctx.createLinearGradient(x, y, x + w, y + h);
      grad.addColorStop(0, '#102a52');
      grad.addColorStop(0.5, '#0b1d3a');
      grad.addColorStop(1, '#050d1c');
      ctx.fillStyle = grad;

      // Draw wafer with chamfered 45-degree corners
      const corner = 4;
      ctx.beginPath();
      ctx.moveTo(x + corner, y);
      ctx.lineTo(x + w - corner, y);
      ctx.lineTo(x + w, y + corner);
      ctx.lineTo(x + w, y + h - corner);
      ctx.lineTo(x + w - corner, y + h);
      ctx.lineTo(x + corner, y + h);
      ctx.lineTo(x, y + h - corner);
      ctx.lineTo(x, y + corner);
      ctx.closePath();
      ctx.fill();

      // Silver micro contact fingers
      ctx.strokeStyle = 'rgba(170, 210, 255, 0.25)';
      ctx.lineWidth = 1;
      const fingerStep = 6;
      for (let fy = y + 3; fy < y + h - 3; fy += fingerStep) {
        ctx.beginPath();
        ctx.moveTo(x + 2, fy);
        ctx.lineTo(x + w - 2, fy);
        ctx.stroke();
      }

      // Silver main busbars (dual conductors)
      ctx.strokeStyle = 'rgba(235, 245, 255, 0.85)';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(x + w * 0.33, y + 1);
      ctx.lineTo(x + w * 0.33, y + h - 1);
      ctx.moveTo(x + w * 0.67, y + 1);
      ctx.lineTo(x + w * 0.67, y + h - 1);
      ctx.stroke();
    }
  }

  const texture = new THREE.CanvasTexture(canvas);
  return texture;
}

/**
 * Initializes shared materials & geometries once (Singleton)
 */
function initPhotorealisticResources() {
  if (sharedKaptonMaterial) return;

  const kaptonTex = createKaptonCanvasTexture(512);
  const solarTex = createSolarPanelCanvasTexture(512, 256);

  // High-performance PBR materials with high specular reflectivity
  sharedKaptonMaterial = new THREE.MeshStandardMaterial({
    map: kaptonTex,
    color: 0xffb703,
    metalness: 0.92,
    roughness: 0.22,
    bumpMap: kaptonTex,
    bumpScale: 0.04,
  });

  sharedSolarMaterial = new THREE.MeshStandardMaterial({
    map: solarTex,
    color: 0x103768,
    metalness: 0.85,
    roughness: 0.12,
    bumpMap: solarTex,
    bumpScale: 0.02,
    side: THREE.DoubleSide,
  });

  sharedMetalDarkMaterial = new THREE.MeshStandardMaterial({
    color: 0x1e2430,
    metalness: 0.85,
    roughness: 0.35,
  });

  sharedMetalChromeMaterial = new THREE.MeshStandardMaterial({
    color: 0xf1f5f9,
    metalness: 0.98,
    roughness: 0.08,
  });

  // Shared Geometries
  const bodyRadius = 0.55;
  const bodyHeight = 1.1;
  sharedBodyGeo = new THREE.CylinderGeometry(bodyRadius, bodyRadius, bodyHeight, 6);
  sharedPlateGeo = new THREE.CylinderGeometry(bodyRadius * 1.04, bodyRadius * 1.04, 0.04, 6);
  sharedYokeGeo = new THREE.CylinderGeometry(0.04, 0.04, 0.5, 8);
  sharedFrameGeo = new THREE.BoxGeometry(1.6, 0.7, 0.03);
  sharedCellGeo = new THREE.PlaneGeometry(1.54, 0.66);
  sharedCellEdgeGeo = new THREE.EdgesGeometry(sharedCellGeo);
  sharedGimbalGeo = new THREE.CylinderGeometry(0.08, 0.12, 0.16, 12);

  // Parabolic dish curve
  const dishPoints = [];
  for (let i = 0; i <= 14; i++) {
    const t = i / 14;
    const x = t * 0.55;
    const y = t * t * 0.22;
    dishPoints.push(new THREE.Vector2(x, y));
  }
  sharedDishGeo = new THREE.LatheGeometry(dishPoints, 16);
  sharedFeedGeo = new THREE.ConeGeometry(0.06, 0.16, 8);
  sharedBaffleGeo = new THREE.CylinderGeometry(0.05, 0.08, 0.22, 8);
  sharedNozzleGeo = new THREE.ConeGeometry(0.04, 0.09, 6, 1, true);
  sharedMastGeo = new THREE.CylinderGeometry(0.018, 0.018, 1.0, 6);
  sharedMagHeadGeo = new THREE.SphereGeometry(0.07, 8, 8);
  sharedBeaconGeo = new THREE.SphereGeometry(0.06, 6, 6);
}

/**
 * Creates a photorealistic 3D Spacecraft Group for react-globe.gl
 * @param {Object} sat - Satellite config object
 * @param {number} scale - Global scale multiplier (default: 1.0)
 * @returns {THREE.Group}
 */
export function createSatellite3DObject(sat, scale = 1.4) {
  initPhotorealisticResources();

  const satellite = new THREE.Group();
  satellite.name = `PhotorealisticSat_${sat.id}`;

  const hexColor = sat.color || '#00ff9d';
  const beaconMat = getOrCreateBeaconMaterial(hexColor);
  const neonLineMat = getOrCreateLineMaterial(hexColor);

  // 1. MAIN CHASSIS (Hexagonal Prism in Gold Kapton MLI Foil)
  const bodyMesh = new THREE.Mesh(sharedBodyGeo, sharedKaptonMaterial);
  satellite.add(bodyMesh);

  // Top & Bottom Equipment Plates (Dark Aerospace Aluminum)
  const topPlate = new THREE.Mesh(sharedPlateGeo, sharedMetalDarkMaterial);
  topPlate.position.y = 0.57;
  satellite.add(topPlate);

  const bottomPlate = topPlate.clone();
  bottomPlate.position.y = -0.57;
  satellite.add(bottomPlate);

  // 2. DUAL ARTICULATED SOLAR WINGS (Left & Right with Bezel & Silicon Cells)
  const createSolarWing = (direction, name) => {
    const wingGroup = new THREE.Group();
    wingGroup.name = name;

    // Articulated Hinge / Yoke connecting wing to main chassis
    const yoke = new THREE.Mesh(sharedYokeGeo, sharedMetalDarkMaterial);
    yoke.rotation.z = Math.PI / 2;
    yoke.position.x = direction * 0.25;
    wingGroup.add(yoke);

    // Bezel Frame
    const frame = new THREE.Mesh(sharedFrameGeo, sharedMetalDarkMaterial);
    frame.position.x = direction * (0.5 + 0.8);
    wingGroup.add(frame);

    // Front Photovoltaic Silicon Wafer Face
    const cellFront = new THREE.Mesh(sharedCellGeo, sharedSolarMaterial);
    cellFront.position.set(direction * (0.5 + 0.8), 0, 0.017);
    wingGroup.add(cellFront);

    // Back Solar Face
    const cellBack = cellFront.clone();
    cellBack.rotation.y = Math.PI;
    cellBack.position.z = -0.017;
    wingGroup.add(cellBack);

    // Neon Frame Accent on outer perimeter (Shared Geometry & Material)
    const neonFrame = new THREE.LineSegments(sharedCellEdgeGeo, neonLineMat);
    neonFrame.position.copy(cellFront.position);
    wingGroup.add(neonFrame);

    return wingGroup;
  };

  satellite.add(createSolarWing(1, 'SolarWing_Right'));
  satellite.add(createSolarWing(-1, 'SolarWing_Left'));

  // 3. HIGH-GAIN PARABOLIC DISH ANTENNA (With Gimbal & Feed Horn)
  const dishGroup = new THREE.Group();
  dishGroup.position.set(0, 0.62, 0);

  // Gimbal Mount Base
  const gimbal = new THREE.Mesh(sharedGimbalGeo, sharedMetalDarkMaterial);
  dishGroup.add(gimbal);

  // Parabolic Dish Reflector
  const dishMesh = new THREE.Mesh(sharedDishGeo, sharedMetalChromeMaterial);
  dishMesh.position.y = 0.2;
  dishMesh.rotation.x = -Math.PI / 5; // Angled Earth transmission
  dishGroup.add(dishMesh);

  // Feed Horn in center of dish
  const feedMesh = new THREE.Mesh(sharedFeedGeo, sharedMetalChromeMaterial);
  feedMesh.position.set(0, 0.42, 0.14);
  feedMesh.rotation.x = Math.PI - Math.PI / 5;
  dishGroup.add(feedMesh);

  satellite.add(dishGroup);

  // 4. STAR TRACKERS & OPTICAL PAYLOAD SENSORS
  const tracker1 = new THREE.Mesh(sharedBaffleGeo, sharedMetalDarkMaterial);
  tracker1.position.set(0.3, 0.25, 0.45);
  tracker1.rotation.x = Math.PI / 4;
  satellite.add(tracker1);

  const tracker2 = tracker1.clone();
  tracker2.position.set(-0.3, 0.25, 0.45);
  tracker2.rotation.x = Math.PI / 4;
  satellite.add(tracker2);

  // 5. ATTITUDE CONTROL (4-QUADRANT RCS THRUSTER PODS)
  const rcsOffsets = [
    [0.48, 0.35, 0.32],
    [-0.48, 0.35, 0.32],
    [0.48, -0.35, -0.32],
    [-0.48, -0.35, -0.32],
  ];

  rcsOffsets.forEach(([x, y, z]) => {
    const rcsPod = new THREE.Group();
    rcsPod.position.set(x, y, z);

    const n1 = new THREE.Mesh(sharedNozzleGeo, sharedMetalDarkMaterial);
    n1.rotation.z = Math.PI / 2;
    rcsPod.add(n1);

    const n2 = new THREE.Mesh(sharedNozzleGeo, sharedMetalDarkMaterial);
    n2.rotation.x = Math.PI / 2;
    rcsPod.add(n2);

    satellite.add(rcsPod);
  });

  // 6. MAGNETOMETER / SPACE TRUSS BOOM
  const boomGroup = new THREE.Group();
  boomGroup.position.set(0, -0.62, 0);

  const mast = new THREE.Mesh(sharedMastGeo, sharedMetalChromeMaterial);
  mast.position.y = -0.5;
  boomGroup.add(mast);

  const magHead = new THREE.Mesh(sharedMagHeadGeo, sharedMetalDarkMaterial);
  magHead.position.y = -1.0;
  boomGroup.add(magHead);

  satellite.add(boomGroup);

  // 7. ACTIVE TELEMETRY BEACON LED
  const beaconMesh = new THREE.Mesh(sharedBeaconGeo, beaconMat);
  beaconMesh.position.set(0, 0.58, 0.45);
  satellite.add(beaconMesh);

  // Apply Global Scale
  satellite.scale.set(scale, scale, scale);
  return satellite;
}

/**
 * Updates satellite position and 3D Attitude Transform (28° Pitch Offset + Slow Axial Drift + Solar Tracking)
 * @param {THREE.Group} obj - 3D Satellite Group
 * @param {Object} sat - Satellite config object
 * @param {Object} coords - Cartesian coordinates {x, y, z}
 * @param {boolean} isSelected - Is currently selected by user
 * @param {THREE.PointLight} targetLight - Target spotlight
 */
export function updateSatellite3DTransform(obj, sat, coords, isSelected = false, targetLight = null) {
  if (!obj || !coords) return;

  const nowSec = performance.now() / 1000;

  // 1. POSITION COORDINATES
  _satPos.set(coords.x, coords.y, coords.z);
  obj.position.copy(_satPos);

  // 2. NATURAL 3D ATTITUDE (PITCH OFFSET + AXIAL DRIFT)
  // Step 2.1: Base orientation towards Earth center
  _rotMatrix.lookAt(_satPos, _targetLook, _upVector);
  _combinedQuat.setFromRotationMatrix(_rotMatrix);

  // Step 2.2: Natural Pitch Offset (28° tilt so camera sees top dish, body facets & wing thickness)
  const pitchAngle = THREE.MathUtils.degToRad(28);
  _pitchQuat.setFromAxisAngle(_pitchAxis, pitchAngle);
  _combinedQuat.multiply(_pitchQuat);

  // Step 2.3: Slow Axial Drift (0.18 rad/s rotation around main axis for dynamic metallic sheen)
  const driftSpeed = 0.18;
  const yawAngle = (nowSec * driftSpeed + (sat.id.charCodeAt(0) || 0)) % (Math.PI * 2);
  _yawQuat.setFromAxisAngle(_yawAxis, yawAngle);
  _combinedQuat.multiply(_yawQuat);

  // Apply final Quaternion to spacecraft
  obj.quaternion.copy(_combinedQuat);

  // 3. SUN-POINTING SOLAR ARRAY TRACKING
  const wingLeft = obj.getObjectByName('SolarWing_Left');
  const wingRight = obj.getObjectByName('SolarWing_Right');
  if (wingLeft && wingRight) {
    const sunAngle = Math.sin(nowSec * 0.4 + (coords.x * 0.01)) * 0.35;
    wingLeft.rotation.x = sunAngle;
    wingRight.rotation.x = sunAngle;
  }

  // 4. SELECTED TARGET CINEMATIC LIGHTING
  if (isSelected && targetLight) {
    targetLight.position.set(coords.x * 1.05, coords.y * 1.05, coords.z * 1.05);
    targetLight.intensity = 2.8 + Math.sin(nowSec * 4.0) * 0.6;
  }
}
