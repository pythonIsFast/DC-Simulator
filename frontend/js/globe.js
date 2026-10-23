// 3D globe with a procedurally drawn earth (Natural Earth land polygons, public domain).
import * as THREE from "three";
import { Orbit, fitCamera } from "./stage.js";

export function latLonToVec3(lat, lon, r = 1) {
  const la = (lat * Math.PI) / 180, lo = (lon * Math.PI) / 180;
  return new THREE.Vector3(r * Math.cos(la) * Math.cos(lo), r * Math.sin(la), -r * Math.cos(la) * Math.sin(lo));
}

// Decode a quantized TopoJSON land object into polygons: [[ring, hole, ...], ...], ring = [[lon, lat], ...].
function decodeLand(topo) {
  const [sx, sy] = topo.transform.scale;
  const [tx, ty] = topo.transform.translate;
  const arcs = topo.arcs.map((arc) => {
    let x = 0, y = 0;
    return arc.map(([dx, dy]) => { x += dx; y += dy; return [x * sx + tx, y * sy + ty]; });
  });
  const ring = (indices) => {
    const pts = [];
    for (const i of indices) {
      const a = i >= 0 ? arcs[i] : arcs[~i].slice().reverse();
      pts.push(...(pts.length ? a.slice(1) : a));
    }
    return pts;
  };
  const polys = [];
  for (const g of topo.objects.land.geometries) {
    if (g.type === "Polygon") polys.push(g.arcs.map(ring));
    else if (g.type === "MultiPolygon") for (const p of g.arcs) polys.push(p.map(ring));
  }
  return polys;
}

function drawEarthTexture(polys) {
  const W = 4096, H = 2048;
  const canvas = document.createElement("canvas");
  canvas.width = W; canvas.height = H;
  const ctx = canvas.getContext("2d");
  const sea = ctx.createLinearGradient(0, 0, 0, H);
  sea.addColorStop(0, "#0d3b73"); sea.addColorStop(0.5, "#1257a0"); sea.addColorStop(1, "#0d3b73");
  ctx.fillStyle = sea;
  ctx.fillRect(0, 0, W, H);

  // Faint graticule
  ctx.strokeStyle = "rgba(120,170,230,.12)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let lon = -180; lon <= 180; lon += 15) { const x = ((lon + 180) / 360) * W; ctx.moveTo(x, 0); ctx.lineTo(x, H); }
  for (let lat = -90; lat <= 90; lat += 15) { const y = ((90 - lat) / 180) * H; ctx.moveTo(0, y); ctx.lineTo(W, y); }
  ctx.stroke();

  const path = () => {
    ctx.beginPath();
    for (const poly of polys) {
      for (const ring of poly) {
        ring.forEach(([lon, lat], i) => {
          const x = ((lon + 180) / 360) * W, y = ((90 - lat) / 180) * H;
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        });
        ctx.closePath();
      }
    }
  };
  path();
  const land = ctx.createLinearGradient(0, 0, 0, H);
  land.addColorStop(0, "#f2f7ff"); land.addColorStop(0.15, "#4f9a68"); land.addColorStop(0.5, "#62b36a");
  land.addColorStop(0.85, "#4f9a68"); land.addColorStop(1, "#f2f7ff");
  ctx.fillStyle = land;
  ctx.fill("evenodd");
  ctx.lineWidth = 2;
  ctx.strokeStyle = "rgba(220,255,230,.5)";
  ctx.stroke();
  return canvas;
}

function makeStars() {
  const n = 1500;
  const pos = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    const v = new THREE.Vector3().randomDirection().multiplyScalar(30 + Math.random() * 30);
    pos.set([v.x, v.y, v.z], i * 3);
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  return new THREE.Points(geo, new THREE.PointsMaterial({ color: 0xffffff, size: 0.12, sizeAttenuation: true, transparent: true, opacity: 0.8 }));
}

export function createGlobeView(canvas, labelsRoot, onPick) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x05080d);
  const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 200);
  const orbit = new Orbit(camera, canvas, { dist: 3.4, minDist: 1.7, maxDist: 6, pitch: 0.5, yaw: 0.2, minPitch: -1.3, maxPitch: 1.3 });

  scene.add(makeStars());
  const globe = new THREE.Mesh(
    new THREE.SphereGeometry(1, 96, 64),
    new THREE.MeshStandardMaterial({ color: 0x4a6a8a, roughness: 0.85, metalness: 0 }),
  );
  scene.add(globe);

  fetch("vendor/land-110m.json").then((r) => r.json()).then((topo) => {
    const tex = new THREE.CanvasTexture(drawEarthTexture(decodeLand(topo)));
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.anisotropy = 8;
    globe.material.map = tex;
    globe.material.color.set(0xffffff);
    globe.material.needsUpdate = true;
  }).catch(() => { /* keep the plain sphere if the land data is missing */ });

  scene.add(new THREE.Mesh(
    new THREE.SphereGeometry(1.12, 64, 48),
    new THREE.ShaderMaterial({
      vertexShader: "varying vec3 vN; void main(){ vN = normalize(normalMatrix * normal); gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
      fragmentShader: "varying vec3 vN; void main(){ float i = pow(max(0.0, 0.72 - dot(vN, vec3(0.0, 0.0, 1.0))), 3.0); gl_FragColor = vec4(0.3, 0.6, 1.0, 1.0) * i; }",
      blending: THREE.AdditiveBlending, side: THREE.BackSide, transparent: true, depthWrite: false,
    }),
  ));
  scene.add(new THREE.AmbientLight(0xffffff, 0.75));
  const sun = new THREE.DirectionalLight(0xffffff, 1.3);
  scene.add(sun);

  const markers = new THREE.Group();
  const arcs = new THREE.Group();
  scene.add(markers, arcs);

  const labels = new Map();   // regionId -> {el, pos, marker, ring}
  let selectedId = null;
  let focus = null;           // {yaw, pitch, dist}
  let idle = 0;

  function ensureRegions(regions) {
    if (labels.size === regions.length) return;
    labels.forEach((l) => l.el.remove());
    labels.clear();
    markers.clear();
    for (const r of regions) {
      const pos = latLonToVec3(r.lat, r.lon, 1.006);
      const el = document.createElement("div");
      el.className = "region-label";
      el.textContent = r.name;
      el.addEventListener("pointerdown", orbit._down);  // a drag that starts on a label still rotates the globe
      el.addEventListener("click", () => { if (!orbit.wasDrag) onPick(r.id); });
      labelsRoot.append(el);
      const dot = new THREE.Mesh(new THREE.SphereGeometry(0.011, 12, 12), new THREE.MeshBasicMaterial({ color: 0x9fb3c8 }));
      dot.position.copy(pos);
      const ring = new THREE.Mesh(new THREE.RingGeometry(0.02, 0.026, 32), new THREE.MeshBasicMaterial({ color: 0x9fb3c8, transparent: true, opacity: 0.8, side: THREE.DoubleSide }));
      ring.position.copy(pos);
      ring.lookAt(pos.clone().multiplyScalar(2));
      markers.add(dot, ring);
      labels.set(r.id, { el, pos, dot, ring, region: r });
    }
  }

  function rebuildArcs(state) {
    arcs.clear();
    const ids = [...new Set(state.datacenters.map((d) => d.region_id))];
    for (let i = 0; i < ids.length; i++) {
      for (let j = i + 1; j < ids.length; j++) {
        const a = labels.get(ids[i]), b = labels.get(ids[j]);
        if (!a || !b) continue;
        const mid = a.pos.clone().add(b.pos).normalize().multiplyScalar(1 + 0.25 * a.pos.angleTo(b.pos));
        const pts = new THREE.QuadraticBezierCurve3(a.pos, mid, b.pos).getPoints(48);
        arcs.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts),
          new THREE.LineBasicMaterial({ color: 0x2dd4bf, transparent: true, opacity: 0.7 })));
      }
    }
  }

  const view = {
    scene, camera,
    setData(state) {
      ensureRegions(state.regions);
      const mine = new Set(state.datacenters.map((d) => d.region_id));
      for (const [id, l] of labels) {
        const hasEvent = l.region.events && l.region.events.length > 0;
        const dcCount = state.datacenters.filter((d) => d.region_id === id).length;
        l.el.className = "region-label" + (mine.has(id) ? " mine" : "") + (hasEvent ? " event" : "") + (id === selectedId ? " selected" : "");
        l.el.textContent = l.region.name + (dcCount ? ` (${dcCount})` : "");
        l.region = state.regions.find((r) => r.id === id) || l.region;
        const color = hasEvent ? 0xfbbf24 : mine.has(id) ? 0x2dd4bf : 0x9fb3c8;
        l.dot.material.color.setHex(color);
        l.ring.material.color.setHex(color);
      }
      rebuildArcs(state);
    },
    select(regionId) {
      selectedId = regionId;
      for (const [id, l] of labels) l.el.classList.toggle("selected", id === regionId);
    },
    focusRegion(regionId) {
      const l = labels.get(regionId);
      if (!l) return;
      const v = l.pos.clone().normalize();
      focus = { yaw: Math.atan2(v.x, v.z), pitch: Math.asin(v.y) * 0.9, dist: 2.3 };
    },
    update(dt, t) {
      idle += dt;
      if (orbit.dragging) { idle = 0; focus = null; }
      if (focus) {
        const k = 1 - Math.pow(0.001, dt);
        let dy = focus.yaw - orbit.yaw;
        dy = Math.atan2(Math.sin(dy), Math.cos(dy));
        orbit.yaw += dy * k;
        orbit.pitch += (focus.pitch - orbit.pitch) * k;
        orbit.dist += (focus.dist - orbit.dist) * k;
        if (Math.abs(dy) < 0.002) focus = null;
      } else if (idle > 6 && selectedId === null) {
        orbit.yaw += dt * 0.04;
      }
      orbit.update(dt);
      sun.position.copy(camera.position).add(new THREE.Vector3(2, 2, 1));
      const w = window.innerWidth, h = window.innerHeight;
      const camDir = camera.position.clone().normalize();
      for (const l of labels.values()) {
        const facing = l.pos.clone().normalize().dot(camDir) > 0.2;
        const p = l.pos.clone().project(camera);
        l.el.style.display = facing ? "" : "none";
        l.el.style.left = ((p.x * 0.5 + 0.5) * w).toFixed(1) + "px";
        l.el.style.top = ((-p.y * 0.5 + 0.5) * h).toFixed(1) + "px";
        const pulse = 1 + 0.35 * Math.sin(t * 3 + l.pos.x * 10);
        l.ring.scale.setScalar(pulse);
        l.ring.material.opacity = 0.9 - 0.4 * (pulse - 0.65);
      }
    },
    resize(w, h) { fitCamera(camera, w, h); },
    activate() { orbit.enabled = true; labelsRoot.hidden = false; idle = 0; },
    deactivate() { orbit.enabled = false; labelsRoot.hidden = true; },
  };
  return view;
}
