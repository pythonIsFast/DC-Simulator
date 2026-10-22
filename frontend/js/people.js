// Living datacenter room: employees walk around and work, construction sites grow, alarms and smoke on failures.
import * as THREE from "three";

const LANES = [-1.8, 0, 1.8, 3.6];     // free walking lanes in front of the rack rows
const EDGE_X = 2.9;                   // side corridors
const DESK = { x: -3.05, z: 3.6 };     // ops desk at the left wall
const ROLE_COLOR = { technician: 0xf28c28, admin: 0x2d6cdf, sales: 0x2b2f3a };
const REPAIR_REASONS = new Set(["pdu_failure", "switch_failure", "cable_fault", "tripped", "fire", "cyber_attack", "overload"]);
const SMOKE_REASONS = new Set(["fire", "tripped"]);

const mat = (color, rough = 0.8) => new THREE.MeshStandardMaterial({ color, roughness: rough });
const skin = [0xf1c9a5, 0xd9a57d, 0xa87850, 0x7a5233];

function makePerson(role, seed) {
  const g = new THREE.Group();
  const body = mat(ROLE_COLOR[role] ?? 0x555555);
  const pants = mat(role === "sales" ? 0x20232b : 0x30394a);
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.11, 14, 12), mat(skin[seed % skin.length], 0.6));
  head.position.y = 1.62;
  const torso = new THREE.Mesh(new THREE.BoxGeometry(0.34, 0.55, 0.2), body);
  torso.position.y = 1.2;
  g.add(head, torso);
  if (role === "technician") {   // hard hat and reflective stripe
    const hat = new THREE.Mesh(new THREE.SphereGeometry(0.125, 14, 8, 0, Math.PI * 2, 0, Math.PI / 2), mat(0xffd23f, 0.5));
    hat.position.y = 1.66;
    const stripe = new THREE.Mesh(new THREE.BoxGeometry(0.345, 0.06, 0.205), mat(0xe8f0f5, 0.4));
    stripe.position.y = 1.3;
    g.add(hat, stripe);
  }
  if (role === "sales") {        // tie
    const tie = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.3, 0.01), mat(0xc0392b));
    tie.position.set(0, 1.25, 0.106);
    g.add(tie);
  }
  const limb = (w, h, d, m) => new THREE.BoxGeometry(w, h, d);
  const legs = [-1, 1].map((s) => {
    const pivot = new THREE.Group();
    pivot.position.set(s * 0.09, 0.93, 0);
    const leg = new THREE.Mesh(limb(0.13, 0.9, 0.14), pants);
    leg.position.y = -0.45;
    pivot.add(leg);
    g.add(pivot);
    return pivot;
  });
  const arms = [-1, 1].map((s) => {
    const pivot = new THREE.Group();
    pivot.position.set(s * 0.22, 1.42, 0);
    const arm = new THREE.Mesh(limb(0.1, 0.5, 0.11), body);
    arm.position.y = -0.25;
    pivot.add(arm);
    g.add(pivot);
    return pivot;
  });
  g.traverse((o) => { if (o.isMesh) { o.castShadow = true; } });
  return { group: g, legs, arms };
}

// Route along the lanes: change lanes only through the side corridors (racks block the way).
function route(from, to) {
  if (Math.abs(from.z - to.z) < 0.25) return [{ x: to.x, z: to.z }];
  const edge = (from.x + to.x) / 2 >= 0 ? EDGE_X : -EDGE_X;
  return [{ x: edge, z: from.z }, { x: edge, z: to.z }, { x: to.x, z: to.z }];
}

export function createPeople(scene, slotPos) {
  const root = new THREE.Group();
  scene.add(root);

  // Ops desk with a monitor
  const desk = new THREE.Group();
  const deskTop = new THREE.Mesh(new THREE.BoxGeometry(0.7, 0.05, 1.6), mat(0x3a4050, 0.5));
  deskTop.position.y = 0.75;
  const screen = new THREE.Mesh(new THREE.BoxGeometry(0.04, 0.35, 0.6), new THREE.MeshBasicMaterial({ color: 0x4ea1ff }));
  screen.position.set(0.18, 1.0, 0);
  for (const dz of [-0.7, 0.7]) {
    const leg = new THREE.Mesh(new THREE.BoxGeometry(0.6, 0.75, 0.05), mat(0x2a2f3a));
    leg.position.set(0, 0.375, dz);
    desk.add(leg);
  }
  desk.add(deskTop, screen);
  desk.position.set(DESK.x - 0.1, 0, DESK.z);
  deskTop.castShadow = true;
  root.add(desk);

  // Construction site marker for a rack that is being built
  const site = new THREE.Group();
  const siteBox = new THREE.Mesh(new THREE.BoxGeometry(0.6, 2.0, 0.9), new THREE.MeshBasicMaterial({ color: 0x2dd4bf, transparent: true, opacity: 0.14, depthWrite: false }));
  const siteEdges = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(0.6, 2.0, 0.9)), new THREE.LineBasicMaterial({ color: 0x2dd4bf }));
  site.add(siteBox, siteEdges);
  site.visible = false;
  root.add(site);

  // Alarm beacons (a small fixed pool of lights) and smoke particles
  const beacons = [];
  for (let i = 0; i < 3; i++) {
    const light = new THREE.PointLight(0xff2a1a, 0, 3.5);
    const lamp = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.07, 0.1, 12), new THREE.MeshBasicMaterial({ color: 0xff2a1a }));
    lamp.visible = false;
    root.add(light, lamp);
    beacons.push({ light, lamp });
  }
  const SMOKE_N = 120;
  const smokePos = new Float32Array(SMOKE_N * 3);
  const smokeGeo = new THREE.BufferGeometry();
  smokeGeo.setAttribute("position", new THREE.BufferAttribute(smokePos, 3));
  const smoke = new THREE.Points(smokeGeo, new THREE.PointsMaterial({ color: 0x8b8f96, size: 0.3, transparent: true, opacity: 0.35, depthWrite: false }));
  smoke.frustumCulled = false;
  root.add(smoke);
  let smokeRacks = [];

  const people = new Map();   // employee id -> person
  let ctx = { employees: [], orders: [], racks: [], dcId: null };
  let beaconRacks = [];

  const rackFront = (slot) => { const p = slotPos(slot); return { x: p.x, z: p.z + 0.95 }; };
  const freeSlot = () => { const used = new Set(ctx.racks.map((r) => r.slot)); for (let s = 0; s < 20; s++) if (!used.has(s)) return s; return null; };

  function setJob(p, job, target) {
    const same = p.job === job && p.target && target && Math.abs(p.target.x - target.x) < 0.01 && Math.abs(p.target.z - target.z) < 0.01;
    if (same) return;
    p.job = job;
    p.target = target;
    p.path = target ? route({ x: p.group.position.x, z: p.group.position.z }, target) : [];
    p.state = "goto";
  }

  function assign() {
    const here = ctx.employees.filter((e) => e.status !== "working" || e.dc_id === ctx.dcId || e.dc_id == null).slice(0, 14);
    const ids = new Set(here.map((e) => e.id));
    for (const [id, p] of people) if (!ids.has(id)) { root.remove(p.group); people.delete(id); }
    const broken = ctx.racks.filter((r) => !r.online && r.items.length && REPAIR_REASONS.has(r.offline_reason));
    let repairIdx = 0;
    const slot = freeSlot();
    here.forEach((e, i) => {
      let p = people.get(e.id);
      if (!p) {
        const made = makePerson(e.role, e.id);
        const start = { x: -2 + (i % 5), z: LANES[i % LANES.length] };
        made.group.position.set(start.x, 0, start.z);
        root.add(made.group);
        p = { ...made, id: e.id, role: e.role, state: "wait", timer: Math.random() * 2, path: [], job: null, target: null, phase: Math.random() * 6 };
        people.set(e.id, p);
      }
      if (e.status === "working" && e.dc_id === ctx.dcId && e.order_kind === "new_rack" && slot !== null) {
        setJob(p, "build", { ...rackFront(slot), face: -Math.PI });
      } else if (e.status === "working" && e.dc_id === ctx.dcId && e.slot != null && (e.order_kind === "extend_rack" || e.order_kind === "add_redundancy")) {
        setJob(p, "build", { ...rackFront(e.slot), face: -Math.PI });   // working on an existing rack
      } else if (e.status === "working" && e.dc_id === ctx.dcId) {
        setJob(p, "build", { x: EDGE_X, z: -1.8, face: 0 });   // datacenter equipment work near the corridor
      } else if (e.role === "technician" && broken[repairIdx]) {
        const t = rackFront(broken[repairIdx++].slot);
        setJob(p, "repair", { ...t, face: -Math.PI });
      } else if (e.role === "admin" || e.role === "sales") {
        setJob(p, e.role === "admin" ? "type" : "call", { x: DESK.x + 0.55, z: DESK.z + (e.role === "admin" ? -0.4 : 0.4), face: -Math.PI / 2 });
      } else if (p.job !== "patrol") {
        p.job = "patrol"; p.target = null; p.path = []; p.state = "wait"; p.timer = 0;
      }
      p.group.visible = true;
    });
  }

  function patrolTarget() {
    const z = LANES[Math.floor(Math.random() * LANES.length)];
    return { x: -2.4 + Math.random() * 4.8, z };
  }

  function stepPerson(p, dt, t) {
    const g = p.group;
    const pos = g.position;
    let walking = false;
    if (p.state === "goto") {
      const next = p.path[0];
      if (!next) { p.state = p.job === "patrol" ? "wait" : "act"; p.timer = 1 + Math.random() * 3; if (p.target && p.target.face !== undefined) g.rotation.y = p.target.face; }
      else {
        const dx = next.x - pos.x, dz = next.z - pos.z;
        const dist = Math.hypot(dx, dz);
        const step = 1.15 * dt;
        if (dist <= step) { pos.x = next.x; pos.z = next.z; p.path.shift(); }
        else {
          pos.x += (dx / dist) * step; pos.z += (dz / dist) * step;
          const want = Math.atan2(dx, dz);
          let d = want - g.rotation.y;
          d = Math.atan2(Math.sin(d), Math.cos(d));
          g.rotation.y += d * Math.min(1, dt * 8);
          walking = true;
        }
      }
    } else if (p.state === "wait") {
      p.timer -= dt;
      if (p.timer <= 0) { p.target = patrolTarget(); p.path = route({ x: pos.x, z: pos.z }, p.target); p.state = "goto"; }
    }
    // animation
    const swing = walking ? Math.sin(t * 7 + p.phase) * 0.7 : 0;
    p.legs[0].rotation.x = swing; p.legs[1].rotation.x = -swing;
    p.arms[0].rotation.x = -swing * 0.8; p.arms[1].rotation.x = swing * 0.8;
    if (p.state === "act") {
      if (p.job === "build" || p.job === "repair") {          // hammering / working on a rack
        p.arms[1].rotation.x = -1.3 + Math.sin(t * 9 + p.phase) * 0.5;
        p.arms[0].rotation.x = -0.9;
      } else if (p.job === "type") {                          // typing
        p.arms[0].rotation.x = -1.1 + Math.sin(t * 12 + p.phase) * 0.12;
        p.arms[1].rotation.x = -1.1 + Math.sin(t * 12 + 1) * 0.12;
      } else if (p.job === "call") {                          // phone call
        p.arms[1].rotation.x = -2.5;
        p.arms[0].rotation.x = Math.sin(t * 2 + p.phase) * 0.1;
      }
    }
  }

  return {
    setData(next) {
      ctx = next;
      assign();
      // construction site
      const builder = ctx.orders.find((o) => o.status === "in_progress" && o.kind === "new_rack" && o.dc_id === ctx.dcId);
      const slot = freeSlot();
      site.visible = !!builder && slot !== null;
      if (site.visible) {
        const p = slotPos(slot);
        const f = Math.max(0.08, builder.progress / builder.total_ticks);
        site.position.set(p.x, 1.0 * f, p.z);
        site.scale.set(1, f, 1);
      }
      // alarms and smoke
      const offline = ctx.racks.filter((r) => !r.online && r.items.length && r.offline_reason && r.offline_reason !== "no_pdu");
      beaconRacks = offline.slice(0, beacons.length);
      smokeRacks = ctx.racks.filter((r) => !r.online && SMOKE_REASONS.has(r.offline_reason)).slice(0, 6);
      beacons.forEach((b, i) => {
        const r = beaconRacks[i];
        b.lamp.visible = !!r;
        if (r) { const p = slotPos(r.slot); b.lamp.position.set(p.x, 2.06, p.z); b.light.position.set(p.x, 2.4, p.z + 0.3); }
        else b.light.intensity = 0;
      });
    },
    update(dt, t) {
      for (const p of people.values()) stepPerson(p, dt, t);
      beacons.forEach((b, i) => { if (beaconRacks[i]) b.light.intensity = 10 + Math.sin(t * 8 + i) * 9;   // candela (physical light units) });
      site.children[0].material.opacity = 0.12 + Math.sin(t * 3) * 0.05;
      // smoke particles rise from smoking racks
      const n = smokeRacks.length ? SMOKE_N : 0;
      smokeGeo.setDrawRange(0, n);
      for (let i = 0; i < n; i++) {
        const rack = smokeRacks[i % smokeRacks.length];
        const o = slotPos(rack.slot);
        let y = smokePos[i * 3 + 1];
        if (y < 2.0 || y > 3.6) { smokePos[i * 3] = o.x + (Math.random() - 0.5) * 0.4; smokePos[i * 3 + 1] = 2.0 + Math.random() * 0.2; smokePos[i * 3 + 2] = o.z + (Math.random() - 0.5) * 0.5; y = smokePos[i * 3 + 1]; }
        smokePos[i * 3 + 1] = y + dt * (0.35 + (i % 5) * 0.06);
        smokePos[i * 3] += Math.sin(t + i) * dt * 0.05;
      }
      smokeGeo.attributes.position.needsUpdate = true;
    },
    dispose() { root.clear(); },
  };
}
