/* ============================================================
   HERO-SCENE.JS — ambient 3D backdrop for the landing hero
   ============================================================
   Loaded only on pages with a `#hero-scene-mount` element (see
   index.html). Mirrors the same visual language as the
   procedural_art.py generation engine (soft organic shapes,
   brand/accent gradient lighting) so the chrome and the actual
   generated art feel like they come from the same place.

   Degrades gracefully: if WebGL isn't available, or the person
   prefers reduced motion, this simply doesn't mount anything —
   the CSS `.gradient-mesh-bg` animated backdrop (enhance.css)
   is a complete visual on its own underneath it.
   ============================================================ */

import * as THREE from '/static/js/vendor/three.module.min.js';

(function () {
  'use strict';

  const mount = document.getElementById('hero-scene-mount');
  if (!mount) return;

  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'low-power' });
  } catch (e) {
    return; // no WebGL — CSS gradient-mesh backdrop already covers it
  }

  const styles = getComputedStyle(document.documentElement);
  const brand = new THREE.Color(styles.getPropertyValue('--brand-500').trim() || '#4c6ef5');
  const accent = new THREE.Color(styles.getPropertyValue('--accent-500').trim() || '#845ef7');

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
  camera.position.set(0, 0, 11);

  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  mount.appendChild(renderer.domElement);

  // ---- Lighting: real shading, not flat/emissive shapes ----
  scene.add(new THREE.AmbientLight(0xffffff, 0.35));
  const keyLight = new THREE.PointLight(brand, 26, 40);
  keyLight.position.set(6, 5, 8);
  scene.add(keyLight);
  const rimLight = new THREE.PointLight(accent, 22, 40);
  rimLight.position.set(-7, -4, 6);
  scene.add(rimLight);

  // ---- A small cluster of softly-lit organic/geometric forms ----
  const group = new THREE.Group();
  scene.add(group);

  const geometries = [
    new THREE.IcosahedronGeometry(1.5, 1),
    new THREE.TorusKnotGeometry(1, 0.32, 128, 16),
    new THREE.IcosahedronGeometry(1, 0),
    new THREE.SphereGeometry(1.1, 32, 32),
    new THREE.OctahedronGeometry(1.2, 0),
  ];

  const meshes = [];
  const count = 5;
  for (let i = 0; i < count; i++) {
    const geo = geometries[i % geometries.length];
    const mat = new THREE.MeshStandardMaterial({
      color: i % 2 === 0 ? brand : accent,
      roughness: 0.35,
      metalness: 0.15,
      transparent: true,
      opacity: 0.85,
    });
    const mesh = new THREE.Mesh(geo, mat);
    const angle = (i / count) * Math.PI * 2;
    const radius = 3.4 + (i % 2) * 1.1;
    mesh.position.set(Math.cos(angle) * radius, Math.sin(angle) * radius * 0.6, (i % 3) * -1.2);
    const scale = 0.55 + Math.random() * 0.5;
    mesh.scale.setScalar(scale);
    mesh.userData.baseY = mesh.position.y;
    mesh.userData.floatSpeed = 0.4 + Math.random() * 0.4;
    mesh.userData.floatOffset = Math.random() * Math.PI * 2;
    mesh.userData.spinSpeed = (Math.random() - 0.5) * 0.25;
    group.add(mesh);
    meshes.push(mesh);
  }

  let targetRotX = 0;
  let targetRotY = 0;
  mount.addEventListener('pointermove', (e) => {
    const rect = mount.getBoundingClientRect();
    const px = (e.clientX - rect.left) / rect.width - 0.5;
    const py = (e.clientY - rect.top) / rect.height - 0.5;
    targetRotY = px * 0.5;
    targetRotX = py * 0.3;
  });

  function resize() {
    const w = mount.clientWidth || 1;
    const h = mount.clientHeight || 1;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  window.addEventListener('resize', resize);
  resize();

  const clock = new THREE.Clock();
  let running = true;
  document.addEventListener('visibilitychange', () => {
    running = document.visibilityState === 'visible';
    if (running) animate();
  });

  function animate() {
    if (!running) return;
    const t = clock.getElapsedTime();

    meshes.forEach((m) => {
      m.position.y = m.userData.baseY + Math.sin(t * m.userData.floatSpeed + m.userData.floatOffset) * 0.35;
      m.rotation.x += m.userData.spinSpeed * 0.01;
      m.rotation.y += m.userData.spinSpeed * 0.014;
    });

    group.rotation.y += (targetRotY - group.rotation.y) * 0.04;
    group.rotation.x += (targetRotX - group.rotation.x) * 0.04;

    renderer.render(scene, camera);
    requestAnimationFrame(animate);
  }
  animate();
})();
