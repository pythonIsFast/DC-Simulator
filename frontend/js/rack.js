// Rack builder: a 42 U rack in 3D with drag & drop mounting (snap), blinking LEDs and visible cabling.
import * as THREE from "three";
import { store } from "./store.js";
import { canPlaceItems } from "./rules.js";
import { frontTexture, railTexture, perforatedTexture, backTexture } from "./faceplates.js";
import { applyEnvironment } from "./stage.js";

const U_H = 0.0445;       // height of one rack unit in metres
const Y0 = 0.09;          // bottom of U1
const FRONT_Z = 0.25;
const RACK_U = 42;
const centerY = (uStart, u) => Y0 + (uStart - 1 + u / 2) * U_H;


const matCache = new Map();
function frontMaterial(hw) {
  if (!matCache.has(hw.code)) matCache.set(hw.code, new THREE.MeshStandardMaterial({ map: frontTexture(hw), roughness: 0.42, metalness: 0.55 }));
  return matCache.get(hw.code);
}

const easeOutBack = (t) => 1 + 2.70158 * Math.pow(t - 1, 3) + 1.70158 * Math.pow(t - 1, 2);

export function createRackView(canvas, tooltip, handlers) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x070a10);
  scene.fog = new THREE.Fog(0x070a10, 6, 14);
  const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 50);
  const target = new THREE.Vector3(0.5, 1.0, 0);
  const camDist = 3.5;
  let camYaw = 0, camPitch = 0.05, wantYaw = 0, wantPitch = 0.05;

  applyEnvironment(scene);                       // reflections for the metal parts
  scene.add(new THREE.AmbientLight(0x8fa0bf, 0.18));
  const key = new THREE.DirectionalLight(0xfff4e6, 2.2);
  key.position.set(1.8, 3.2, 3.5);
  key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048);
  key.shadow.camera.left = -1.6; key.shadow.camera.right = 1.6; key.shadow.camera.top = 2.4; key.shadow.camera.bottom = -0.3;
  key.shadow.camera.near = 0.5; key.shadow.camera.far = 9;
  key.shadow.bias = -0.0004; key.shadow.normalBias = 0.01;
  scene.add(key);
  const fill = new THREE.PointLight(0x5aa9ff, 8, 6);
  fill.position.set(-1.6, 1.2, 1.8);
  scene.add(fill);

  const floor = new THREE.Mesh(new THREE.PlaneGeometry(12, 12), new THREE.MeshStandardMaterial({ color: 0x151a22, roughness: 0.32, metalness: 0.35 }));
  floor.rotation.x = -Math.PI / 2;
  floor.receiveShadow = true;
  scene.add(floor);

  // Rack frame: four rails with square holes, perforated side panels, plinth with casters
  const frame = new THREE.Group();
  const frameMat = new THREE.MeshStandardMaterial({ color: 0x1b2028, metalness: 0.85, roughness: 0.38 });
  const height = RACK_U * U_H + 2 * (Y0 - 0.01);
  const uSpan = RACK_U * U_H, uMid = Y0 + uSpan / 2;
  const rail = railTexture();
  for (const x of [-0.256, 0.256]) {
    for (const z of [0.27, -0.27]) {
      const post = new THREE.Mesh(new THREE.BoxGeometry(0.03, height, 0.03), frameMat);
      post.position.set(x, height / 2, z);
      post.castShadow = true;
      frame.add(post);
    }
    const face = new THREE.Mesh(new THREE.PlaneGeometry(0.03, uSpan), new THREE.MeshStandardMaterial({ map: rail, metalness: 0.6, roughness: 0.5 }));
    face.position.set(x, uMid, 0.27 + 0.0151);
    frame.add(face);
  }
  for (const side of [-1, 1]) {
    const panel = new THREE.Mesh(new THREE.PlaneGeometry(0.6, height), new THREE.MeshStandardMaterial({ map: perforatedTexture(true, [3, 12]), metalness: 0.5, roughness: 0.6, side: THREE.DoubleSide }));
    panel.rotation.y = Math.PI / 2;
    panel.position.set(side * 0.272, height / 2, 0);
    panel.receiveShadow = true;
    frame.add(panel);
  }
  const top = new THREE.Mesh(new THREE.BoxGeometry(0.56, 0.03, 0.6), frameMat);
  top.position.set(0, height, 0);
  const plinth = new THREE.Mesh(new THREE.BoxGeometry(0.58, 0.07, 0.62), frameMat);
  plinth.position.set(0, 0.06, 0);
  frame.add(top, plinth);
  for (const x of [-0.25, 0.25]) for (const z of [-0.27, 0.27]) {
    const caster = new THREE.Mesh(new THREE.CylinderGeometry(0.022, 0.022, 0.02, 16), new THREE.MeshStandardMaterial({ color: 0x0a0b0d, roughness: 0.8 }));
    caster.position.set(x, 0.01, z);
    frame.add(caster);
  }
  const back = new THREE.Mesh(new THREE.PlaneGeometry(0.47, uSpan), new THREE.MeshBasicMaterial({ map: backTexture() }));
  back.position.set(0, uMid, -0.26);
  frame.add(back);
  scene.add(frame);

  const itemsGroup = new THREE.Group();
  const cablesGroup = new THREE.Group();
  scene.add(itemsGroup, cablesGroup);

  // LEDs (instanced) are rebuilt with the items
  let ledMesh = null;
  let leds = [];
  const ledGeo = new THREE.BoxGeometry(0.008, 0.008, 0.004);
  const ledMat = new THREE.MeshBasicMaterial();

  // Ghost for the mounting preview
  const ghost = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.45, depthWrite: false }));
  ghost.visible = false;
  scene.add(ghost);
  const selectBox = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(1, 1, 1)), new THREE.LineBasicMaterial({ color: 0xffd33d }));
  selectBox.visible = false;
  scene.add(selectBox);

  const sideMat = new THREE.MeshStandardMaterial({ color: 0x20252d, metalness: 0.6, roughness: 0.5 });
  const geoCache = new Map();
  const itemGeo = (u) => {
    if (!geoCache.has(u)) geoCache.set(u, new THREE.BoxGeometry(0.46, u * U_H - 0.003, 0.5));
    return geoCache.get(u);
  };

  let rack = null, dc = null;
  let knownIds = new Set();
  let knownRackId = null;
  let selectedId = null;
  let meshById = new Map();
  let anims = [];
  let drag = null;          // {item, mesh, startU, moved}
  let hoverId = null;
  const view = { scene, camera, active: false, dragCode: null };

  const ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
  const frontPlane = new THREE.Plane(new THREE.Vector3(0, 0, 1), -FRONT_Z);
  const hit = new THREE.Vector3();

  function setNdc(ev) {
    const r = canvas.getBoundingClientRect();
    ndc.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
  }

  // U (continuous) under the pointer, or null when the ray misses the front plane.
  function uUnderPointer(ev) {
    setNdc(ev);
    if (!ray.ray.intersectPlane(frontPlane, hit)) return null;
    return (hit.y - Y0) / U_H;
  }

  function snapU(uf, height) {
    return Math.max(1, Math.min(RACK_U - height + 1, Math.round(uf - height / 2) + 1));
  }

  // Mirrors the server rules (racks.placement_error) for instant visual feedback.
  function canPlace(hw, uStart, ignoreId) {
    return !!rack && canPlaceItems(rack.items, hw, uStart, ignoreId);
  }

  function showGhost(hw, uStart, valid) {
    ghost.visible = true;
    ghost.scale.set(0.46, hw.u_height * U_H - 0.003, 0.5);
    ghost.position.set(0, centerY(uStart, hw.u_height), 0.02);
    ghost.material.color.set(valid ? 0x3fb950 : 0xf85149);
  }

  function clearGhost() { ghost.visible = false; }

  function selectItem(id) {
    selectedId = id;
    const m = id != null ? meshById.get(id) : null;
    if (m) {
      const hw = store.hw.byCode[m.userData.item.code];
      selectBox.visible = true;
      selectBox.scale.set(0.47, hw.u_height * U_H, 0.51);
      selectBox.position.copy(m.position);
    } else {
      selectBox.visible = false;
    }
    handlers.onSelect(m ? m.userData.item : null);
  }

  function buildItems(animate) {
    itemsGroup.clear();
    meshById = new Map();
    leds = [];
    for (const item of rack.items) {
      const hw = store.hw.byCode[item.code];
      const front = frontMaterial(hw);
      const mesh = new THREE.Mesh(itemGeo(hw.u_height), [sideMat, sideMat, sideMat, sideMat, front, sideMat]);
      mesh.position.set(0, centerY(item.u_start, hw.u_height), 0);
      mesh.userData.item = item;
      mesh.castShadow = true; mesh.receiveShadow = true;
      itemsGroup.add(mesh);
      meshById.set(item.id, mesh);
      if (animate && !knownIds.has(item.id)) {
        mesh.position.z = 0.7;
        anims.push({ mesh, t: 0, dur: 0.38, z0: 0.7 });
      }
      addLeds(item, hw, mesh.position.y);
    }
    ledMesh = new THREE.InstancedMesh(ledGeo, ledMat, Math.max(1, leds.length));
    ledMesh.count = leds.length;
    ledMesh.setColorAt(0, new THREE.Color(0));
    leds.forEach((l, i) => {
      ledMesh.setMatrixAt(i, new THREE.Matrix4().makeTranslation(l.x, l.y, FRONT_Z + 0.003));
    });
    ledMesh.instanceMatrix.needsUpdate = true;
    itemsGroup.add(ledMesh);
  }

  function addLeds(item, hw, y) {
    const server = hw.category.startsWith("server_");
    if (server || hw.category === "ups") {
      leds.push({ x: 0.2, y: y + 0.008, kind: "power", item });
      leds.push({ x: 0.185, y: y + 0.008, kind: "act", item, phase: Math.random() * 6 });
      if (hw.u_height > 1) leds.push({ x: 0.17, y: y + 0.008, kind: "act", item, phase: Math.random() * 6 });
    } else if (hw.category === "switch_tor") {
      const n = Math.min(24, hw.ports);
      for (let i = 0; i < n; i++) leds.push({ x: -0.06 + i * 0.0105, y: y - 0.011, kind: "port", item, index: i, phase: Math.random() * 6 });
      leds.push({ x: 0.2, y: y + 0.008, kind: "power", item });
    } else if (hw.category === "pdu") {
      leds.push({ x: 0.2, y: y + 0.008, kind: "power", item });
    }
  }

  function buildCables() {
    cablesGroup.traverse((o) => { if (o.geometry) o.geometry.dispose(); });
    cablesGroup.clear();
    const st = rack.stats;
    const byCat = (cat) => rack.items.filter((i) => store.hw.byCode[i.code].category === cat);
    const tors = byCat("switch_tor"), pdus = byCat("pdu");
    const servers = rack.items.filter((i) => store.hw.byCode[i.code].category.startsWith("server_"))
      .sort((a, b) => a.u_start - b.u_start);
    const yOf = (i) => centerY(i.u_start, store.hw.byCode[i.code].u_height);
    const addCable = (pts, color) => {
      const curve = new THREE.CatmullRomCurve3(pts.map((p) => new THREE.Vector3(...p)), false, "catmullrom", 0.3);
      cablesGroup.add(new THREE.Mesh(new THREE.TubeGeometry(curve, 20, 0.0032, 6),
        new THREE.MeshStandardMaterial({ color, roughness: 0.6 })));
    };
    const netColors = [0x39c5cf, 0x2f81f7];
    const pwrColors = [0xf0883e, 0xda3633];
    servers.forEach((s, n) => {
      const y = yOf(s);
      const lane = 0.29 + (n % 10) * 0.006, zOut = 0.29 + (n % 10) * 0.004;
      if (st.connected_ids.includes(s.id)) {
        tors.forEach((t, k) => {
          const yt = yOf(t);
          addCable([[0.22, y - 0.004 * k, FRONT_Z + 0.004], [lane, y, zOut], [lane, (y + yt) / 2, zOut + 0.01], [lane, yt, zOut], [0.22, yt, FRONT_Z + 0.004]], netColors[k % 2]);
        });
      }
      pdus.forEach((p, k) => {
        const yp = yOf(p);
        const x = -0.29 - (n % 10) * 0.006 - k * 0.002;
        addCable([[-0.22, y + 0.004 * k, FRONT_Z + 0.004], [x, y, zOut], [x, (y + yp) / 2, zOut + 0.01], [x, yp, zOut], [-0.22, yp, FRONT_Z + 0.004]], pwrColors[k % 2]);
      });
    });
  }

  view.setRack = (nextRack, nextDc) => {
    const sameRack = rack && nextRack && rack.id === nextRack.id;
    rack = nextRack;
    dc = nextDc;
    if (!rack) return;
    buildItems(sameRack && knownRackId === rack.id);
    buildCables();
    knownIds = new Set(rack.items.map((i) => i.id));
    knownRackId = rack.id;
    if (selectedId != null && !meshById.has(selectedId)) selectedId = null;
    selectItem(selectedId);
  };
  view.setDc = (nextDc) => { dc = nextDc; };
  view.isDragging = () => drag !== null;
  view.select = (id) => selectItem(id);
  view.selected = () => selectedId;

  // ---- interaction: existing items (pointer drag)
  function pickItem(ev) {
    setNdc(ev);
    const hits = ray.intersectObjects([...meshById.values()], false);
    return hits.length ? hits[0].object : null;
  }

  canvas.addEventListener("pointerdown", (ev) => {
    if (!view.active || ev.button !== 0) return;
    const mesh = pickItem(ev);
    if (!mesh) { selectItem(null); return; }
    const item = mesh.userData.item;
    selectItem(item.id);
    const hw = store.hw.byCode[item.code];
    drag = { item, hw, mesh, moved: false, startU: item.u_start, sx: ev.clientX, sy: ev.clientY };
    canvas.setPointerCapture?.(ev.pointerId);
  });

  canvas.addEventListener("pointermove", (ev) => {
    if (!view.active) return;
    // camera parallax
    wantYaw = ((ev.clientX / window.innerWidth) - 0.5) * 0.5;
    wantPitch = 0.05 + (0.5 - ev.clientY / window.innerHeight) * 0.15;
    if (drag) {
      if (!drag.moved && Math.hypot(ev.clientX - drag.sx, ev.clientY - drag.sy) < 5) return;
      drag.moved = true;
      const uf = uUnderPointer(ev);
      if (uf === null) return;
      drag.u = snapU(uf, drag.hw.u_height);
      if (!drag.cloned) { drag.mesh.material = drag.mesh.material.slice(); drag.mesh.material[4] = drag.mesh.material[4].clone(); drag.cloned = true; }
      drag.mesh.material[4].transparent = true; drag.mesh.material[4].opacity = 0.5;
      showGhost(drag.hw, drag.u, canPlace(drag.hw, drag.u, drag.item.id));
      return;
    }
    const m = pickItem(ev);
    hoverId = m ? m.userData.item.id : null;
    canvas.style.cursor = m ? "grab" : "";
    if (m) {
      const hw = store.hw.byCode[m.userData.item.code];
      tooltip.hidden = false;
      tooltip.style.left = ev.clientX + 14 + "px";
      tooltip.style.top = ev.clientY + 14 + "px";
      tooltip.textContent = `${hw.name} | U${m.userData.item.u_start}${hw.u_height > 1 ? "-" + (m.userData.item.u_start + hw.u_height - 1) : ""}`;
    } else {
      tooltip.hidden = true;
    }
  });

  window.addEventListener("pointerup", (ev) => {
    if (!drag) return;
    const d = drag;
    drag = null;
    clearGhost();
    if (d.cloned) view.setRack(rack, dc); // rebuild meshes to drop the temporary transparent clone
    if (d.moved && d.u != null && d.u !== d.startU && canPlace(d.hw, d.u, d.item.id)) {
      handlers.onMove(d.item.id, d.u);
    } else if (d.moved) {
      handlers.onInvalid?.();
    }
  });

  // ---- interaction: dragging a catalog entry onto the canvas (HTML5 drag & drop)
  canvas.addEventListener("dragover", (ev) => {
    if (!view.active || !view.dragCode) return;
    ev.preventDefault();
    const hw = store.hw.byCode[view.dragCode];
    const uf = uUnderPointer(ev);
    if (uf === null) return;
    const u = snapU(uf, hw.u_height);
    showGhost(hw, u, canPlace(hw, u, null));
    canvas.classList.add("dropping");
  });
  canvas.addEventListener("dragleave", () => { clearGhost(); canvas.classList.remove("dropping"); });
  canvas.addEventListener("drop", (ev) => {
    ev.preventDefault();
    canvas.classList.remove("dropping");
    clearGhost();
    if (!view.dragCode) return;
    const hw = store.hw.byCode[view.dragCode];
    const uf = uUnderPointer(ev);
    if (uf === null) return;
    const u = snapU(uf, hw.u_height);
    if (canPlace(hw, u, null)) handlers.onInstall(hw.code, u);
    else handlers.onInvalid?.();
    view.dragCode = null;
  });

  view.update = (dt, t) => {
    // camera: gentle parallax around the rack
    camYaw += (wantYaw - camYaw) * Math.min(1, dt * 4);
    camPitch += (wantPitch - camPitch) * Math.min(1, dt * 4);
    camera.position.set(
      target.x + camDist * Math.sin(camYaw) * Math.cos(camPitch),
      target.y + camDist * Math.sin(camPitch),
      target.z + camDist * Math.cos(camYaw) * Math.cos(camPitch),
    );
    camera.lookAt(target);

    // mount animation (slide in with overshoot)
    anims = anims.filter((a) => {
      a.t += dt;
      const k = Math.min(1, a.t / a.dur);
      a.mesh.position.z = a.z0 * (1 - easeOutBack(k));
      return k < 1;
    });

    // LEDs: blink rate follows datacenter utilization; offline racks go red/dark
    if (ledMesh && rack) {
      const util = dc ? dc.util : 0;
      const online = rack.online;
      const connected = new Set(rack.stats.connected_ids);
      const col = new THREE.Color();
      for (let i = 0; i < leds.length; i++) {
        const l = leds[i];
        if (!online) {
          col.set(l.kind === "power" ? (Math.sin(t * 5) > 0 ? 0xff3b30 : 0x300000) : 0x000000);
        } else if (l.kind === "power") {
          col.set(0x3fb950);
        } else if (l.kind === "port") {
          const used = l.index < rack.stats.ports_used;
          col.set(used ? (Math.sin(t * (4 + util * 20) + l.phase) > -0.2 ? 0xe3b341 : 0x3a2e08) : 0x151515);
        } else {
          const ok = connected.has(l.item.id) || !store.hw.byCode[l.item.code].category.startsWith("server_");
          col.set(!ok ? 0xff3b30 : Math.sin(t * (3 + util * 22) + l.phase) > -0.2 ? 0x58a6ff : 0x0b1c33);
        }
        ledMesh.setColorAt(i, col);
      }
      if (ledMesh.instanceColor) ledMesh.instanceColor.needsUpdate = true;
    }
    if (selectedId != null && meshById.get(selectedId)) {
      selectBox.position.copy(meshById.get(selectedId).position);
    }
  };

  view.resize = (w, h) => { camera.aspect = w / h; camera.updateProjectionMatrix(); };
  view.activate = () => { view.active = true; };
  view.deactivate = () => { view.active = false; tooltip.hidden = true; clearGhost(); drag = null; };
  view.clearDrag = () => { view.dragCode = null; clearGhost(); canvas.classList.remove("dropping"); };
  void hoverId;
  return view;
}
