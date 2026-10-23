// Datacenter room view: open racks with their real devices (instanced per hardware type), status lights, heatmap floor.
import * as THREE from "three";
import { Orbit, applyEnvironment, fitCamera } from "./stage.js";
import { perforatedTexture, frontTexture, railTexture, backTexture } from "./faceplates.js";
import { store } from "./store.js";
import { createPeople } from "./people.js";
import { kw } from "./util.js";

const COLS = 5;
const MAX_SLOTS = 20;
export const slotPos = (s) => ({ x: ((s % COLS) - 2) * 1.0, z: (Math.floor(s / COLS) - 1.5) * 1.8 });
const ROOM_W = 7, ROOM_D = 8.4;
// Same rack dimensions as the rack view (19" rack, 44.5 mm per unit).
const U_H = 0.0445, Y0 = 0.09, RACK_U = 42;
const RACK_H = RACK_U * U_H + 2 * (Y0 - 0.01);
const centerY = (uStart, u) => Y0 + (uStart - 1 + u / 2) * U_H;

function floorTexture() {
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const g = c.getContext("2d");
  g.fillStyle = "#171e29"; g.fillRect(0, 0, 128, 128);
  g.strokeStyle = "#232d3c"; g.lineWidth = 3; g.strokeRect(0, 0, 128, 128);
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(ROOM_W, ROOM_D);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

const COLD = new THREE.Color(0x5fa8ff), WARM = new THREE.Color(0xf2c14e), HOT = new THREE.Color(0xf0453a);
const OFF = new THREE.Color(0x2a2d35), EMPTY = new THREE.Color(0x6b7482);
function heatColor(f, out) {
  f = Math.max(0, Math.min(1, f));
  return f < 0.5 ? out.copy(COLD).lerp(WARM, f * 2) : out.copy(WARM).lerp(HOT, (f - 0.5) * 2);
}

export function createRoomView(canvas, tooltip, handlers) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x070a10);
  scene.fog = new THREE.Fog(0x070a10, 12, 26);
  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
  const orbit = new Orbit(camera, canvas, { target: [0, 0.9, 0], dist: 7.5, minDist: 2.2, maxDist: 15, pitch: 0.75, yaw: 0.35, minPitch: 0.15, maxPitch: 1.35 });

  applyEnvironment(scene);
  scene.add(new THREE.AmbientLight(0x8899bb, 0.25));
  const key = new THREE.DirectionalLight(0xfff4e6, 1.8);
  key.position.set(4, 9, 5);
  key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048);
  Object.assign(key.shadow.camera, { left: -6, right: 6, top: 6, bottom: -6, near: 1, far: 25 });
  key.shadow.bias = -0.0005;
  scene.add(key);

  const floor = new THREE.Mesh(new THREE.PlaneGeometry(ROOM_W, ROOM_D), new THREE.MeshStandardMaterial({ map: floorTexture(), roughness: 0.38, metalness: 0.3 }));
  floor.rotation.x = -Math.PI / 2;
  floor.receiveShadow = true;
  scene.add(floor);
  const wallMat = new THREE.MeshStandardMaterial({ color: 0x1b2433, roughness: 1 });
  const back = new THREE.Mesh(new THREE.PlaneGeometry(ROOM_W, 3.2), wallMat);
  back.position.set(0, 1.6, -ROOM_D / 2);
  const left = new THREE.Mesh(new THREE.PlaneGeometry(ROOM_D, 3.2), wallMat);
  left.rotation.y = Math.PI / 2; left.position.set(-ROOM_W / 2, 1.6, 0);
  scene.add(back, left);

  // Heatmap overlay on the floor
  const hmCanvas = document.createElement("canvas");
  hmCanvas.width = 256; hmCanvas.height = Math.round(256 * ROOM_D / ROOM_W);
  const hmTex = new THREE.CanvasTexture(hmCanvas);
  const heatmap = new THREE.Mesh(new THREE.PlaneGeometry(ROOM_W, ROOM_D), new THREE.MeshBasicMaterial({ map: hmTex, transparent: true, opacity: 0.95, depthWrite: false }));
  heatmap.rotation.x = -Math.PI / 2; heatmap.position.y = 0.02; heatmap.visible = false;
  scene.add(heatmap);

  // Racks (instanced), status LEDs (instanced), empty slots (instanced)
  // The racks themselves are open frames with real devices (built in rebuild()). This invisible volume only receives clicks.
  const rackMesh = new THREE.InstancedMesh(new THREE.BoxGeometry(0.64, RACK_H, 0.66), new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false }), MAX_SLOTS);
  const heatMesh = new THREE.InstancedMesh(new THREE.BoxGeometry(0.02, 1.9, 0.02), new THREE.MeshBasicMaterial(), MAX_SLOTS);
  const ledMesh = new THREE.InstancedMesh(new THREE.BoxGeometry(0.46, 0.04, 0.02), new THREE.MeshBasicMaterial(), MAX_SLOTS);
  const contents = new THREE.Group();   // frames and devices, rebuilt when the racks change
  scene.add(contents);
  const darkMetal = new THREE.MeshStandardMaterial({ color: 0x1b2028, metalness: 0.85, roughness: 0.38 });
  const sideMat = new THREE.MeshStandardMaterial({ color: 0x20252d, metalness: 0.6, roughness: 0.5 });
  const perfMat = new THREE.MeshStandardMaterial({ map: perforatedTexture(true, [3, 12]), metalness: 0.5, roughness: 0.6, side: THREE.DoubleSide });
  const railMat = new THREE.MeshStandardMaterial({ map: railTexture(), metalness: 0.6, roughness: 0.5 });
  const backMat = new THREE.MeshBasicMaterial({ map: backTexture() });
  const postGeo = new THREE.BoxGeometry(0.03, RACK_H, 0.03);
  const panelGeo = new THREE.PlaneGeometry(0.6, RACK_H);
  const railGeo = new THREE.PlaneGeometry(0.03, RACK_U * U_H);
  const backGeo = new THREE.PlaneGeometry(0.47, RACK_U * U_H);
  const topGeo = new THREE.BoxGeometry(0.56, 0.03, 0.6);
  const plinthGeo = new THREE.BoxGeometry(0.58, 0.07, 0.62);
  const deviceGeo = new Map();     // rack units -> geometry
  const deviceMats = new Map();    // hardware code -> materials
  const WHITE = new THREE.Color(0xffffff), DIM = new THREE.Color(0x4a4d55);

  function geoFor(u) {
    if (!deviceGeo.has(u)) deviceGeo.set(u, new THREE.BoxGeometry(0.46, u * U_H - 0.003, 0.5));
    return deviceGeo.get(u);
  }
  function matsFor(hw) {
    if (!deviceMats.has(hw.code)) {
      const front = new THREE.MeshStandardMaterial({ map: frontTexture(hw), roughness: 0.42, metalness: 0.55 });
      deviceMats.set(hw.code, [sideMat, sideMat, sideMat, sideMat, front, sideMat]);
    }
    return deviceMats.get(hw.code);
  }

  // Frame of one rack: rails, perforated side panels, top, plinth and back panel.
  function addFrame(x, z) {
    const g = new THREE.Group();
    g.position.set(x, 0, z);
    for (const sx of [-0.256, 0.256]) for (const sz of [0.27, -0.27]) {
      const post = new THREE.Mesh(postGeo, darkMetal);
      post.position.set(sx, RACK_H / 2, sz);
      g.add(post);
    }
    for (const sx of [-0.256, 0.256]) {
      const rail = new THREE.Mesh(railGeo, railMat);
      rail.position.set(sx, Y0 + (RACK_U * U_H) / 2, 0.2851);
      g.add(rail);
    }
    for (const side of [-1, 1]) {
      const panel = new THREE.Mesh(panelGeo, perfMat);
      panel.rotation.y = Math.PI / 2;
      panel.position.set(side * 0.272, RACK_H / 2, 0);
      g.add(panel);
    }
    const top = new THREE.Mesh(topGeo, darkMetal);
    top.position.y = RACK_H;
    const plinth = new THREE.Mesh(plinthGeo, darkMetal);
    plinth.position.y = 0.06;
    const back = new THREE.Mesh(backGeo, backMat);
    back.position.set(0, Y0 + (RACK_U * U_H) / 2, -0.26);
    g.add(top, plinth, back);
    contents.add(g);
  }

  // All devices of the same hardware type are one InstancedMesh (few draw calls even with hundreds of devices).
  function rebuildContents() {
    for (const child of [...contents.children]) if (child.isInstancedMesh) child.dispose();
    contents.clear();
    const byCode = new Map();
    for (const r of racks) {
      const p = slotPos(r.slot);
      addFrame(p.x, p.z);
      for (const it of r.items) {
        if (!store.hw.byCode[it.code]) continue;
        if (!byCode.has(it.code)) byCode.set(it.code, []);
        byCode.get(it.code).push({ p, it, r });
      }
    }
    for (const [code, list] of byCode) {
      const hw = store.hw.byCode[code];
      const mesh = new THREE.InstancedMesh(geoFor(hw.u_height), matsFor(hw), list.length);
      list.forEach(({ p, it, r }, i) => {
        tmpM.makeTranslation(p.x, centerY(it.u_start, hw.u_height), p.z);
        mesh.setMatrixAt(i, tmpM);
        mesh.setColorAt(i, r.online ? WHITE : DIM);   // offline racks look dark
      });
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      mesh.instanceMatrix.needsUpdate = true;
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
      contents.add(mesh);
    }
  }
  const slotMesh = new THREE.InstancedMesh(new THREE.PlaneGeometry(0.6, 0.9), new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.22, side: THREE.DoubleSide }), MAX_SLOTS);
  for (const m of [rackMesh, ledMesh, slotMesh, heatMesh]) { m.instanceMatrix.setUsage(THREE.DynamicDrawUsage); m.count = 0; scene.add(m); }
  const cracGroup = new THREE.Group();
  scene.add(cracGroup);
  const people = createPeople(scene, slotPos);

  let dc = null;
  let racks = [];          // rack json per rack instance
  let emptySlots = [];     // slot numbers per slot instance
  let hover = null;        // {type, index}
  let util = 0;
  const tmpM = new THREE.Matrix4(), tmpC = new THREE.Color();
  const ray = new THREE.Raycaster(), ndc = new THREE.Vector2();

  function rebuild() {
    hover = null;
    racks = dc ? dc.racks : [];
    const used = new Set(racks.map((r) => r.slot));
    emptySlots = [];
    for (let s = 0; s < (dc ? dc.max_racks : 0); s++) if (!used.has(s)) emptySlots.push(s);
    rackMesh.count = ledMesh.count = heatMesh.count = racks.length;
    slotMesh.count = emptySlots.length;
    racks.forEach((r, i) => {
      const p = slotPos(r.slot);
      tmpM.makeTranslation(p.x, RACK_H / 2, p.z);
      rackMesh.setMatrixAt(i, tmpM);
      tmpM.makeTranslation(p.x, RACK_H + 0.04, p.z + 0.24);
      ledMesh.setMatrixAt(i, tmpM);
      let color;
      if (r.items.length === 0) color = tmpC.copy(EMPTY);
      else if (!r.online) color = tmpC.copy(OFF);
      else color = heatColor(r.stats.heat_w / 9000, tmpC);
      tmpM.makeTranslation(p.x + 0.31, 1.0, p.z + 0.27);
      heatMesh.setMatrixAt(i, tmpM);
      heatMesh.setColorAt(i, color);
    });
    emptySlots.forEach((s, i) => {
      const p = slotPos(s);
      tmpM.makeRotationX(-Math.PI / 2).setPosition(p.x, 0.03, p.z);
      slotMesh.setMatrixAt(i, tmpM);
      slotMesh.setColorAt(i, tmpC.set(0x2dd4bf));
    });
    for (const m of [rackMesh, slotMesh]) m.instanceMatrix.needsUpdate = true;
    if (slotMesh.instanceColor) slotMesh.instanceColor.needsUpdate = true;
    ledMesh.instanceMatrix.needsUpdate = true;
    heatMesh.instanceMatrix.needsUpdate = true;
    if (heatMesh.instanceColor) heatMesh.instanceColor.needsUpdate = true;

    rebuildContents();

    // Cooling units along the back wall
    cracGroup.clear();
    const n = dc ? Math.max(1, Math.round(dc.cooling_kw / 40)) : 0;
    for (let i = 0; i < n; i++) {
      const crac = new THREE.Mesh(new THREE.BoxGeometry(0.9, 1.9, 0.6), new THREE.MeshStandardMaterial({ color: 0x3a4a63, roughness: 0.6, metalness: 0.3 }));
      crac.position.set((i - (n - 1) / 2) * 1.1, 0.95, -ROOM_D / 2 + 0.4);
      const vent = new THREE.Mesh(new THREE.PlaneGeometry(0.7, 0.5), new THREE.MeshBasicMaterial({ color: 0x66ccff }));
      vent.position.set(0, 0.5, 0.31);
      crac.add(vent);
      cracGroup.add(crac);
    }
    drawHeatmap();
  }

  function drawHeatmap() {
    const g = hmCanvas.getContext("2d");
    g.clearRect(0, 0, hmCanvas.width, hmCanvas.height);
    g.globalCompositeOperation = "lighter";
    for (const r of racks) {
      if (!r.online || r.stats.heat_w <= 0) continue;
      const p = slotPos(r.slot);
      const cx = ((p.x + ROOM_W / 2) / ROOM_W) * hmCanvas.width;
      const cy = ((p.z + ROOM_D / 2) / ROOM_D) * hmCanvas.height;
      const rad = 38;
      const a = Math.min(0.9, r.stats.heat_w / 9000);
      const grad = g.createRadialGradient(cx, cy, 0, cx, cy, rad);
      grad.addColorStop(0, `rgba(255,${Math.round(150 - 120 * a)},20,${a})`);
      grad.addColorStop(1, "rgba(255,80,0,0)");
      g.fillStyle = grad;
      g.fillRect(cx - rad, cy - rad, rad * 2, rad * 2);
    }
    g.globalCompositeOperation = "source-over";
    hmTex.needsUpdate = true;
  }

  function pick(ev) {
    const rect = canvas.getBoundingClientRect();
    ndc.set(((ev.clientX - rect.left) / rect.width) * 2 - 1, -((ev.clientY - rect.top) / rect.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    const hits = ray.intersectObjects([rackMesh, slotMesh], false);
    if (!hits.length) return null;
    const h = hits[0];
    return h.object === rackMesh ? { type: "rack", index: h.instanceId } : { type: "slot", index: h.instanceId };
  }

  function setHover(next) {
    if (hover && hover.type === "slot") { slotMesh.setColorAt(hover.index, tmpC.set(0x2dd4bf)); slotMesh.instanceColor.needsUpdate = true; }
    hover = next;
    if (hover && hover.type === "slot") { slotMesh.setColorAt(hover.index, tmpC.set(0xffffff)); slotMesh.instanceColor.needsUpdate = true; }
    canvas.style.cursor = hover ? "pointer" : "";
  }

  function showTooltip(ev) {
    if (!hover || orbit.dragging) { tooltip.hidden = true; return; }
    tooltip.hidden = false;
    tooltip.style.left = ev.clientX + 14 + "px";
    tooltip.style.top = ev.clientY + 14 + "px";
    if (hover.type === "slot") {
      tooltip.textContent = "Empty slot: click to install a rack";
    } else {
      const r = racks[hover.index];
      tooltip.textContent = `${r.name}: ${r.online ? "online" : r.offline_text || "offline"} | ${kw(r.stats.load_w)} | ${r.stats.used_u}/42 U`;
    }
  }

  const onMove = (ev) => {
    if (!view.active) return;
    setHover(orbit.dragging ? null : pick(ev));
    showTooltip(ev);
  };
  const onClick = (ev) => {
    if (!view.active || orbit.wasDrag) return;
    const p = pick(ev);
    if (!p) return;
    if (p.type === "rack") handlers.onRack(racks[p.index]);
    else handlers.onSlot(emptySlots[p.index]);
  };
  canvas.addEventListener("pointermove", onMove);
  canvas.addEventListener("click", onClick);

  const view = {
    scene, camera, active: false,
    setDatacenter(next) { dc = next; util = next ? next.util : 0; rebuild(); },
    setHeatmap(on) { heatmap.visible = on; },
    setUtil(u) { util = u; },
    setPeople(data) { people.setData(data); },
    update(dt, t) {
      orbit.update(dt);
      people.update(dt, t);
      // Status LEDs: green blink speed follows utilization, red = offline, amber = overload
      for (let i = 0; i < racks.length; i++) {
        const r = racks[i];
        if (r.items.length === 0) tmpC.set(0x333a46);
        else if (!r.online) tmpC.set(Math.sin(t * 6 + i) > 0 ? 0xff3b30 : 0x400000);
        else if (r.stats.overload) tmpC.set(0xe3b341);
        else tmpC.set(Math.sin(t * (3 + util * 14) + i * 1.7) > -0.3 ? 0x3fb950 : 0x0f3a1a);
        ledMesh.setColorAt(i, tmpC);
      }
      if (ledMesh.instanceColor) ledMesh.instanceColor.needsUpdate = true;
    },
    resize(w, h) { fitCamera(camera, w, h); },
    activate() { view.active = true; orbit.enabled = true; },
    deactivate() { view.active = false; orbit.enabled = false; tooltip.hidden = true; setHover(null); },
  };
  return view;
}
