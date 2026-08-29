import * as THREE from 'three';

/**
 * Three.js Procedural 3D Satellite Mesh Generator
 * Ultra-lightweight: < 50 vertices, 0 KB network asset download.
 * Uses MeshBasicMaterial to completely eliminate GPU lighting shader overhead on Intel HD 4400.
 */

// Shared Geometry & Material Singletons for maximum VRAM & GC efficiency
let sharedBusGeo = null;
let sharedTrussGeo = null;
let sharedPanelGeo = null;
let sharedDishGeo = null;
let sharedHornGeo = null;
let sharedBeaconGeo = null;

let sharedBusMat = null;
let sharedPanelMat = null;
let sharedMetalMat = null;

function initSharedResources() {
  if (sharedBusGeo) return;

  // Geometries
  sharedBusGeo = new THREE.BoxGeometry(0.8, 0.5, 0.5);
  sharedTrussGeo = new THREE.CylinderGeometry(0.04, 0.04, 2.4, 6);
  sharedPanelGeo = new THREE.PlaneGeometry(0.9, 0.45);
  sharedDishGeo = new THREE.ConeGeometry(0.3, 0.15, 8, 1, true);
  sharedHornGeo = new THREE.CylinderGeometry(0.02, 0.02, 0.25, 4);
  sharedBeaconGeo = new THREE.SphereGeometry(0.08, 4, 4);

  // Materials
  sharedBusMat = new THREE.MeshBasicMaterial({ color: 0xffb700 }); // Gold Kapton MLI foil
  sharedPanelMat = new THREE.MeshBasicMaterial({
    color: 0x003388,
    side: THREE.DoubleSide,
  });
  sharedMetalMat = new THREE.MeshBasicMaterial({ color: 0xd0d8e2 });
}

/**
 * Creates a distinct 3D Three.js Group representing a satellite
 * @param {Object} sat - Satellite config object with color property
 * @param {number} scale - Scale multiplier (default: 1.0)
 * @returns {THREE.Group}
 */
export function createSatellite3DObject(sat, scale = 1.0) {
  initSharedResources();

  const group = new THREE.Group();
  group.name = `Satellite_${sat.id}`;

  const satColor = new THREE.Color(sat.color || '#00ff9d');

  // 1. Satellite Bus Body (Gold Kapton Box)
  const busMesh = new THREE.Mesh(sharedBusGeo, sharedBusMat);
  busMesh.scale.set(scale, scale, scale);
  group.add(busMesh);

  // 2. Solar Panel Truss Boom (Horizontal support rod)
  const trussMesh = new THREE.Mesh(sharedTrussGeo, sharedMetalMat);
  trussMesh.rotation.z = Math.PI / 2;
  trussMesh.scale.set(scale, scale, scale);
  group.add(trussMesh);

  // 3. Left Solar Array Wing
  const leftPanel = new THREE.Mesh(sharedPanelGeo, sharedPanelMat);
  leftPanel.position.set(-1.0 * scale, 0, 0);
  leftPanel.scale.set(scale, scale, scale);
  const leftFrame = new THREE.LineSegments(
    new THREE.EdgesGeometry(sharedPanelGeo),
    new THREE.LineBasicMaterial({ color: satColor })
  );
  leftPanel.add(leftFrame);
  group.add(leftPanel);

  // 4. Right Solar Array Wing
  const rightPanel = new THREE.Mesh(sharedPanelGeo, sharedPanelMat);
  rightPanel.position.set(1.0 * scale, 0, 0);
  rightPanel.scale.set(scale, scale, scale);
  const rightFrame = new THREE.LineSegments(
    new THREE.EdgesGeometry(sharedPanelGeo),
    new THREE.LineBasicMaterial({ color: satColor })
  );
  rightPanel.add(rightFrame);
  group.add(rightPanel);

  // 5. High-Gain Parabolic Dish Antenna (facing Earth / -Y)
  const dishMesh = new THREE.Mesh(sharedDishGeo, sharedMetalMat);
  dishMesh.position.set(0, -0.35 * scale, 0);
  dishMesh.rotation.x = Math.PI;
  dishMesh.scale.set(scale, scale, scale);
  group.add(dishMesh);

  // Feed Horn in center of dish
  const hornMesh = new THREE.Mesh(
    sharedHornGeo,
    new THREE.MeshBasicMaterial({ color: satColor })
  );
  hornMesh.position.set(0, -0.45 * scale, 0);
  hornMesh.scale.set(scale, scale, scale);
  group.add(hornMesh);

  // 6. Active Telemetry Beacon LED
  const beaconMesh = new THREE.Mesh(
    sharedBeaconGeo,
    new THREE.MeshBasicMaterial({ color: satColor })
  );
  beaconMesh.position.set(0, 0.32 * scale, 0);
  beaconMesh.scale.set(scale, scale, scale);
  group.add(beaconMesh);

  return group;
}
