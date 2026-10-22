// Rack builder: a 42 U rack in 3D with drag & drop mounting (snap), blinking LEDs and visible cabling.
import * as THREE from "three";
import { store } from "./store.js";
import { canPlaceItems } from "./rules.js";

const U_H = 0.0445;       // height of one rack unit in metres
const Y0 = 0.09;          // bottom of U1
const FRONT_Z = 0.25;
const RACK_U = 42;
const centerY = (uStart, u) => Y0 + (uStart - 1 + u / 2) * U_H;

const CAT_COLOR = {
  server_cpu: "#2b3a55", server_storage: "#3a4150", server_gpu: "#42305f", switch_tor: "#1f5252",
  pdu: "#5a4220", ups: "#5a2230", patch_panel: "#4a4f57", cable_mgmt: "#2b2f36", blank: "#14171c",
};

function spec(hw) {
  const a = hw.attrs;
  const parts = [];
  if (a.cpu) parts.push(`${a.cpu} cpu units`);
  if (a.storage_tb) parts.push(`${a.storage_tb} TB`);
  if (a.gpu) parts.push(`${a.gpu} gpu units`);
  if (hw.ports) parts.push(`${hw.ports} ports`);
  if (a.max_w) parts.push(`${(a.max_w / 1000).toFixed(1)} kW`);
  if (a.ups_w) parts.push(`${(a.ups_w / 1000).toFixed(0)} kW backup`);
  if (hw.power_w) parts.push(`${hw.power_w} W`);
  return parts.join(" | ");
}

const texCache = new Map();
function frontTexture(hw) {
  if (texCache.has(hw.code)) return texCache.get(hw.code);
  const u = hw.u_height, W = 1024, H = 128 * u;
  const c = document.createElement("canvas");
  c.width = W; c.height = H;
  const g = c.getContext("2d");
  g.fillStyle = CAT_COLOR[hw.category] || "#333";
  g.fillRect(0, 0, W, H);
  g.fillStyle = "rgba(255,255,255,.14)"; g.fillRect(0, 0, W, 4);
  g.fillStyle = "rgba(0,0,0,.4)"; g.fillRect(0, H - 4, W, 4);
  g.fillStyle = "#15181d"; g.fillRect(0, 0, 28, H); g.fillRect(W - 28, 0, 28, H);
  g.fillStyle = "#9aa4b2";
  for (let i = 0; i < u; i++) for (const x of [14, W - 14]) { g.beginPath(); g.arc(x, i * 128 + 64, 6, 0, Math.PI * 2); g.fill(); }
  if (hw.category !== "blank") {
    g.fillStyle = "#f0f6fc"; g.font = "bold 34px system-ui, sans-serif"; g.textBaseline = "middle";
    g.fillText(hw.name, 52, Math.min(H / 2 - 14, 64 - 14));
    g.fillStyle = "rgba(240,246,252,.65)"; g.font = "24px system-ui, sans-serif";
    g.fillText(spec(hw), 52, Math.min(H / 2 + 22, 64 + 22));
  }
  decor(g, hw, W, H);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  texCache.set(hw.code, tex);
  return tex;
}

function decor(g, hw, W, H) {
  const x0 = 500, x1 = W - 60;
  g.fillStyle = "rgba(0,0,0,.45)";
  switch (hw.category) {
    case "server_cpu":
      for (let r = 0; r < hw.u_height * 3; r++) for (let i = 0; i < 20; i++) g.fillRect(x0 + i * 22, 16 + r * 34, 12, 20);
      break;
    case "server_storage": {
      const rows = hw.u_height >= 4 ? 4 : 2, cols = 6;
      const bw = (x1 - x0) / cols - 8, bh = (H - 40) / rows - 8;
      for (let r = 0; r < rows; r++) for (let i = 0; i < cols; i++) {
        g.fillRect(x0 + i * (bw + 8), 20 + r * (bh + 8), bw, bh);
        g.fillStyle = "#58a6ff"; g.fillRect(x0 + i * (bw + 8) + 6, 24 + r * (bh + 8), 8, 5); g.fillStyle = "rgba(0,0,0,.45)";
      }
      break;
    }
    case "server_gpu": {
      const n = hw.u_height >= 4 ? 4 : 2, r = Math.min(H / 2 - 14, 52);
      for (let i = 0; i < n; i++) {
        const cx = x0 + 60 + i * ((x1 - x0 - 60) / Math.max(1, n - 1)), cy = H / 2;
        g.beginPath(); g.arc(cx, cy, r, 0, Math.PI * 2); g.fill();
        g.strokeStyle = "#7ee787"; g.lineWidth = 2; g.beginPath(); g.arc(cx, cy, r - 6, 0, Math.PI * 2); g.stroke();
      }
      break;
    }
    case "switch_tor": {
      const perRow = 24, rows = Math.ceil(hw.ports / perRow);
      for (let r = 0; r < rows; r++) for (let i = 0; i < Math.min(perRow, hw.ports - r * perRow); i++)
        g.fillRect(x0 + i * 20, (rows === 1 ? 50 : 24 + r * 44), 15, 22);
      break;
    }
    case "pdu":
      for (let i = 0; i < 8; i++) { g.beginPath(); g.arc(x0 + 30 + i * 50, 64, 15, 0, Math.PI * 2); g.fill(); }
      break;
    case "ups":
      g.fillStyle = "#0b3d1d"; g.fillRect(x0, 28, 200, H - 56);
      g.fillStyle = "#3fb950"; g.font = "bold 40px monospace"; g.fillText("100 %", x0 + 40, H / 2);
      break;
    case "patch_panel":
      for (let i = 0; i < 24; i++) { g.beginPath(); g.arc(x0 + 12 + i * 20, 64, 7, 0, Math.PI * 2); g.fill(); }
      break;
    case "cable_mgmt":
      g.strokeStyle = "rgba(255,255,255,.25)"; g.lineWidth = 3;
      for (let i = 0; i < 18; i++) { g.beginPath(); g.moveTo(x0 + i * 26, 24); g.lineTo(x0 + i * 26, 104); g.stroke(); }
      break;
    default:
  }
}

function numberTexture() {
  const c = document.createElement("canvas");
  c.width = 64; c.height = RACK_U * 24;
  const g = c.getContext("2d");
  g.fillStyle = "#0e1218"; g.fillRect(0, 0, 64, c.height);
  g.font = "13px monospace"; g.textBaseline = "middle"; g.textAlign = "center";
  for (let n = 1; n <= RACK_U; n++) {
    const y = c.height - (n - 0.5) * 24;
    g.fillStyle = n % 5 === 0 ? "#e6edf3" : "#6b7787";
    g.fillText(String(n), 32, y);
    g.fillStyle = "#2a3342"; g.fillRect(0, c.height - n * 24, 64, 1);
  }
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

function backTexture() {
  const c = document.createElement("canvas");
  c.width = 32; c.height = RACK_U * 16;
  const g = c.getContext("2d");
  g.fillStyle = "#0a0d12"; g.fillRect(0, 0, 32, c.height);
  g.fillStyle = "#161c26";
  for (let n = 0; n < RACK_U; n++) g.fillRect(0, n * 16 + 15, 32, 1);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

const matCache = new Map();
function frontMaterial(hw) {
  if (!matCache.has(hw.code)) matCache.set(hw.code, new THREE.MeshStandardMaterial({ map: frontTexture(hw), roughness: 0.5, metalness: 0.3 }));
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

  scene.add(new THREE.AmbientLight(0xa8b4cc, 0.9));
  const key = new THREE.DirectionalLight(0xffffff, 1.2);
  key.position.set(1.5, 3, 4);
  scene.add(key);
  const fill = new THREE.PointLight(0x4ea1ff, 0.6, 6);
  fill.position.set(-1.5, 1.2, 1.5);
  scene.add(fill);

  const floor = new THREE.Mesh(new THREE.PlaneGeometry(10, 10), new THREE.MeshStandardMaterial({ color: 0x10151d, roughness: 0.95 }));
  floor.rotation.x = -Math.PI / 2;
  scene.add(floor);
  scene.add(new THREE.GridHelper(10, 40, 0x1f2937, 0x151b25));

  // Rack frame
  const frame = new THREE.Group();
  const frameMat = new THREE.MeshStandardMaterial({ color: 0x1a1f28, metalness: 0.7, roughness: 0.4 });
  const height = RACK_U * U_H + 2 * (Y0 - 0.01);
  for (const x of [-0.255, 0.255]) {
    const post = new THREE.Mesh(new THREE.BoxGeometry(0.04, height, 0.6), frameMat);
    post.position.set(x, height / 2 + 0.0, 0);
    frame.add(post);
  }
  for (const y of [0.04, height - 0.04 + 0.0]) {
    const plate = new THREE.Mesh(new THREE.BoxGeometry(0.55, 0.08, 0.62), frameMat);
    plate.position.set(0, y, 0);
    frame.add(plate);
  }
  const numbers = new THREE.Mesh(new THREE.PlaneGeometry(0.03, RACK_U * U_H), new THREE.MeshBasicMaterial({ map: numberTexture() }));
  numbers.position.set(-0.228, Y0 + (RACK_U * U_H) / 2, FRONT_Z + 0.002);
  frame.add(numbers);
  const back = new THREE.Mesh(new THREE.PlaneGeometry(0.47, RACK_U * U_H), new THREE.MeshBasicMaterial({ map: backTexture() }));
  back.position.set(0, Y0 + (RACK_U * U_H) / 2, -0.28);
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
