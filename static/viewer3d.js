// viewer3d.js — parametric 3D rocket model driven by the same design
// parameters used by the physics backend. Exposes window.RocketViewer.

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const SCALE = 0.1; // mm -> scene units (i.e. scene units are cm)

let scene, camera, renderer, controls, container;
let rocketGroup = null;
let bodyMat, finMat, wireframeOn = false;
let currentRadius = 60; // scene units, used for camera framing

function noseProfilePoints(type, L, R, segments = 28) {
  // Returns [{x_mm, r_mm}, ...] from tip (x=0) to base (x=L).
  const pts = [];
  for (let i = 0; i <= segments; i++) {
    const x = (L * i) / segments;
    const u = x / L;
    let r;
    switch (type) {
      case 'conical':
        r = R * u;
        break;
      case 'parabolic':
        r = R * (2 * u - u * u);
        break;
      case 'elliptical':
        r = R * Math.sqrt(Math.max(0, 1 - (1 - u) * (1 - u)));
        break;
      case 'ogive':
      default: {
        const rho = (R * R + L * L) / (2 * R);
        r = Math.sqrt(Math.max(0, rho * rho - (L - x) * (L - x))) - (rho - R);
        break;
      }
    }
    pts.push({ x, r: Math.max(0, r) });
  }
  return pts;
}

function clearRocket() {
  if (rocketGroup) {
    scene.remove(rocketGroup);
    rocketGroup.traverse(obj => {
      if (obj.geometry) obj.geometry.dispose();
    });
    rocketGroup = null;
  }
}

function buildRocket(body, fin) {
  // body: {diameter_mm, nose_length_mm, nose_type}
  // fin:  {root_chord_mm, tip_chord_mm, span_mm, sweep_mm, thickness_mm, count, position_from_nose_mm}
  clearRocket();

  const bodyR_mm = body.diameter_mm / 2;
  const tailStub_mm = body.diameter_mm * 0.5;
  const totalLen_mm = Math.max(
    fin.position_from_nose_mm + fin.root_chord_mm + tailStub_mm,
    body.nose_length_mm + body.diameter_mm * 4
  );

  const sceneY = (fromNoseMM) => (totalLen_mm / 2 - fromNoseMM) * SCALE;

  const group = new THREE.Group();

  // ---- nose cone (lathe revolve) ----
  const profile = noseProfilePoints(body.nose_type, body.nose_length_mm, bodyR_mm);
  const latheePts = profile.map(p => new THREE.Vector2(Math.max(0.0001, p.r * SCALE), sceneY(p.x)));
  const noseGeo = new THREE.LatheGeometry(latheePts, 40);
  const noseMesh = new THREE.Mesh(noseGeo, bodyMat);
  group.add(noseMesh);

  // ---- body tube ----
  const bodyTopY = sceneY(body.nose_length_mm);
  const bodyBottomY = sceneY(totalLen_mm);
  const bodyLen = bodyTopY - bodyBottomY;
  const bodyGeo = new THREE.CylinderGeometry(bodyR_mm * SCALE, bodyR_mm * SCALE, bodyLen, 40, 1, true);
  const bodyMesh = new THREE.Mesh(bodyGeo, bodyMat);
  bodyMesh.position.y = (bodyTopY + bodyBottomY) / 2;
  group.add(bodyMesh);

  // simple end cap at the tail so it doesn't look hollow
  const capGeo = new THREE.CircleGeometry(bodyR_mm * SCALE, 40);
  const capMesh = new THREE.Mesh(capGeo, bodyMat);
  capMesh.rotation.x = Math.PI / 2;
  capMesh.position.y = bodyBottomY;
  group.add(capMesh);

  // ---- fins ----
  const bodyR_scene = bodyR_mm * SCALE;
  const spanScene = fin.span_mm * SCALE;
  const thickScene = Math.max(0.03, fin.thickness_mm * SCALE);

  const shape = new THREE.Shape();
  const yRootLE = sceneY(fin.position_from_nose_mm);
  const yRootTE = sceneY(fin.position_from_nose_mm + fin.root_chord_mm);
  const yTipLE = sceneY(fin.position_from_nose_mm + fin.sweep_mm);
  const yTipTE = sceneY(fin.position_from_nose_mm + fin.sweep_mm + fin.tip_chord_mm);

  shape.moveTo(bodyR_scene, yRootLE);
  shape.lineTo(bodyR_scene, yRootTE);
  shape.lineTo(bodyR_scene + spanScene, yTipTE);
  shape.lineTo(bodyR_scene + spanScene, yTipLE);
  shape.closePath();

  const finGeo = new THREE.ExtrudeGeometry(shape, { depth: thickScene, bevelEnabled: false });
  finGeo.translate(0, 0, -thickScene / 2);

  for (let i = 0; i < fin.count; i++) {
    const finMesh = new THREE.Mesh(finGeo, finMat);
    finMesh.rotation.y = (i * 2 * Math.PI) / fin.count;
    group.add(finMesh);
  }

  scene.add(group);
  rocketGroup = group;

  currentRadius = Math.max(bodyR_scene + spanScene, totalLen_mm * SCALE * 0.55);
  return { totalLen_mm, bodyR_scene };
}

function frameCamera(totalLen_mm) {
  const halfLen = (totalLen_mm * SCALE) / 2;
  const dist = Math.max(currentRadius * 3.2, halfLen * 2.4);
  camera.position.set(dist * 0.55, dist * 0.35, dist * 0.75);
  controls.target.set(0, 0, 0);
  camera.near = dist / 500;
  camera.far = dist * 50;
  camera.updateProjectionMatrix();
  controls.update();
}

function setView(preset) {
  if (!rocketGroup) return;
  const dist = camera.position.length() || currentRadius * 3;
  switch (preset) {
    case 'front':
      camera.position.set(0, 0, dist);
      break;
    case 'side':
      camera.position.set(dist, 0, 0);
      break;
    case 'top':
      camera.position.set(0, dist, 0.0001);
      break;
    case 'iso':
    default:
      camera.position.set(dist * 0.55, dist * 0.35, dist * 0.75);
      break;
  }
  controls.target.set(0, 0, 0);
  controls.update();
}

function toggleWireframe() {
  wireframeOn = !wireframeOn;
  bodyMat.wireframe = wireframeOn;
  finMat.wireframe = wireframeOn;
  return wireframeOn;
}

function setAutoRotate(on) {
  controls.autoRotate = on;
  controls.autoRotateSpeed = 2.2;
}

function resize() {
  if (!container || !renderer || !camera) return;
  const w = container.clientWidth;
  const h = container.clientHeight;
  if (w === 0 || h === 0) return;
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  renderer.setSize(w, h);
}

function animate() {
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);
}

function init(canvasContainer) {
  container = canvasContainer;

  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0a1622);
  scene.fog = new THREE.Fog(0x0a1622, 400, 1600);

  camera = new THREE.PerspectiveCamera(38, container.clientWidth / Math.max(1, container.clientHeight), 0.1, 5000);
  camera.position.set(140, 90, 200);

  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(container.clientWidth, container.clientHeight);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  container.appendChild(renderer.domElement);

  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.screenSpacePanning = true;
  controls.minDistance = 5;
  controls.maxDistance = 3000;
  controls.target.set(0, 0, 0);

  // lighting: hemisphere for soft ambient fill + one key light for form
  const hemi = new THREE.HemisphereLight(0x9fd0e0, 0x0a1622, 0.9);
  scene.add(hemi);
  const key = new THREE.DirectionalLight(0xffffff, 1.4);
  key.position.set(120, 180, 90);
  scene.add(key);
  const rim = new THREE.DirectionalLight(0x45d9c9, 0.5);
  rim.position.set(-150, 60, -120);
  scene.add(rim);

  // reference grid "pad" beneath the rocket
  const grid = new THREE.GridHelper(600, 30, 0x234158, 0x16293b);
  grid.position.y = -80;
  scene.add(grid);

  bodyMat = new THREE.MeshStandardMaterial({ color: 0x9fb4c8, metalness: 0.55, roughness: 0.38 });
  finMat = new THREE.MeshStandardMaterial({ color: 0xff7a45, metalness: 0.3, roughness: 0.45 });

  window.addEventListener('resize', resize);
  new ResizeObserver(resize).observe(container);

  animate();
}

function update(bodyParams, finParams) {
  if (!scene) return;
  const { totalLen_mm } = buildRocket(bodyParams, finParams);
  frameCamera(totalLen_mm);
}

function resetView() {
  if (!rocketGroup) return;
  setView('iso');
}

window.RocketViewer = { init, update, resetView, setView, toggleWireframe, setAutoRotate, resize };
