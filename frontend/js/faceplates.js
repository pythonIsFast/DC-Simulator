// Procedurally drawn front panels and rack parts (no external textures, no licensing issues).
// Proportions follow a real 19" rack: 482 mm wide, 44.5 mm per rack unit -> about 10.8 : 1 per U.
import * as THREE from "three";

export const PX_W = 2048;           // texture width for a device front
export const PX_U = 189;            // texture height per rack unit
const RACK_U = 42;

function canvas(w, h) {
  const c = document.createElement("canvas");
  c.width = w; c.height = h;
  return [c, c.getContext("2d")];
}

function toTexture(c, repeat) {
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 8;
  if (repeat) { t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(...repeat); }
  return t;
}

// ---------------------------------------------------------------- drawing helpers

function brushedMetal(g, W, H, light, dark) {
  const grad = g.createLinearGradient(0, 0, 0, H);
  grad.addColorStop(0, light); grad.addColorStop(0.5, dark); grad.addColorStop(1, light);
  g.fillStyle = grad;
  g.fillRect(0, 0, W, H);
  g.fillStyle = "rgba(255,255,255,.035)";
  for (let y = 0; y < H; y += 3) g.fillRect(0, y, W, 1);
  g.fillStyle = "rgba(255,255,255,.18)"; g.fillRect(0, 0, W, 3);   // top edge highlight
  g.fillStyle = "rgba(0,0,0,.55)"; g.fillRect(0, H - 3, W, 3);      // bottom edge shadow
}

function rackEars(g, W, H, u) {
  for (const x of [0, W - 70]) {
    const grad = g.createLinearGradient(x, 0, x + 70, 0);
    grad.addColorStop(0, "#9aa3af"); grad.addColorStop(0.5, "#c5ccd6"); grad.addColorStop(1, "#8b939f");
    g.fillStyle = grad;
    g.fillRect(x, 0, 70, H);
    g.fillStyle = "rgba(0,0,0,.5)";
    g.fillRect(x + (x === 0 ? 69 : 0), 0, 1, H);
    for (let i = 0; i < u; i++) {   // mounting slot per rack unit
      g.fillStyle = "#0d0f12";
      g.beginPath(); g.roundRect(x + 22, i * PX_U + PX_U / 2 - 13, 26, 26, 8); g.fill();
    }
  }
}

function led(g, x, y, r, color) {
  const glow = g.createRadialGradient(x, y, 0, x, y, r * 3);
  glow.addColorStop(0, color); glow.addColorStop(0.35, color); glow.addColorStop(1, "rgba(0,0,0,0)");
  g.globalAlpha = 0.55; g.fillStyle = glow; g.fillRect(x - r * 3, y - r * 3, r * 6, r * 6);
  g.globalAlpha = 1; g.fillStyle = color; g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.fill();
}

function slotGrille(g, x, y, w, h, slotW = 22, gap = 12, slotH = 0.55) {
  g.fillStyle = "#07090c";
  g.fillRect(x, y, w, h);
  g.fillStyle = "#2c3139";
  for (let cx = x + 6; cx < x + w - slotW; cx += slotW + gap) {
    for (let cy = y + 8; cy < y + h - 12; cy += 20) {
      g.beginPath(); g.roundRect(cx, cy, slotW, 20 * slotH + 2, 4); g.fill();
    }
  }
}

function hexMesh(g, x, y, w, h) {
  g.fillStyle = "#050608"; g.fillRect(x, y, w, h);
  g.fillStyle = "#222831";
  const r = 7;
  for (let row = 0, cy = y + r + 4; cy < y + h - r; row++, cy += r * 1.8) {
    for (let cx = x + r + 4 + (row % 2) * r; cx < x + w - r; cx += r * 2.1) {
      g.beginPath(); g.arc(cx, cy, r * 0.62, 0, Math.PI * 2); g.fill();
    }
  }
}

function bay(g, x, y, w, h, ledColor) {
  g.fillStyle = "#0a0c0f"; g.fillRect(x, y, w, h);
  const grad = g.createLinearGradient(x, y, x, y + h);
  grad.addColorStop(0, "#3b414b"); grad.addColorStop(1, "#23272e");
  g.fillStyle = grad; g.fillRect(x + 3, y + 3, w - 6, h - 6);
  g.fillStyle = "#11141a"; g.fillRect(x + 8, y + h * 0.38, w - 16, h * 0.24);   // handle recess
  g.fillStyle = "#8f98a5"; g.fillRect(x + 8, y + h * 0.4, w - 40, 5);            // release latch
  led(g, x + w - 14, y + 11, 3, ledColor);
}

function sfp(g, x, y, w, h) {
  g.fillStyle = "#b8c0cc"; g.fillRect(x, y, w, h);
  g.fillStyle = "#0b0d10"; g.fillRect(x + 3, y + 4, w - 6, h - 8);
  g.fillStyle = "#4a515c"; g.fillRect(x + 6, y + h - 12, w - 12, 5);
}

function rj45(g, x, y, w, h) {
  g.fillStyle = "#9aa2ae"; g.fillRect(x, y, w, h);
  g.fillStyle = "#0b0d10"; g.fillRect(x + 2, y + 3, w - 4, h - 6);
  g.fillStyle = "#c9a227";
  for (let i = 0; i < 6; i++) g.fillRect(x + 4 + i * ((w - 8) / 6), y + h - 9, 2, 5);
}

function label(g, text, x, y, size = 26) {
  g.font = `600 ${size}px system-ui, sans-serif`;
  const w = g.measureText(text).width + 24;
  g.fillStyle = "rgba(10,12,16,.72)";
  g.beginPath(); g.roundRect(x, y - size, w, size + 14, 6); g.fill();
  g.fillStyle = "#cfd6df";
  g.textBaseline = "alphabetic";
  g.fillText(text, x + 12, y);
}

function powerButton(g, x, y) {
  g.fillStyle = "#0b0d10"; g.beginPath(); g.arc(x, y, 24, 0, Math.PI * 2); g.fill();
  g.strokeStyle = "#7f8a99"; g.lineWidth = 3; g.beginPath(); g.arc(x, y, 15, -1.2, 4.35); g.stroke();
  g.beginPath(); g.moveTo(x, y - 18); g.lineTo(x, y - 4); g.stroke();
}

// ---------------------------------------------------------------- device faces

const PAINT = {
  server_cpu: ["#3a4049", "#262a31"], server_storage: ["#3a4049", "#262a31"], server_gpu: ["#2a2f36", "#15181d"],
  switch_tor: ["#2a2d33", "#15171b"], pdu: ["#23262c", "#101216"], ups: ["#2d3138", "#1a1d22"],
  fan_panel: ["#272b31", "#14161a"], patch_panel: ["#2a2d33", "#16181c"], cable_mgmt: ["#33373e", "#20232a"], blank: ["#1b1e23", "#101215"],
};

const texCache = new Map();
export function frontTexture(hw) {
  if (texCache.has(hw.code)) return texCache.get(hw.code);
  const u = hw.u_height, W = PX_W, H = PX_U * u;
  const [c, g] = canvas(W, H);
  const [light, dark] = PAINT[hw.category] || ["#333", "#222"];
  brushedMetal(g, W, H, light, dark);
  rackEars(g, W, H, u);
  const x0 = 110, x1 = W - 110;           // usable area between the ears
  const cy = H / 2;
  const cat = hw.category;

  if (cat === "server_cpu") {
    powerButton(g, x0 + 40, PX_U / 2);
    led(g, x0 + 100, PX_U / 2 - 14, 5, "#34d058"); led(g, x0 + 100, PX_U / 2 + 14, 5, "#58a6ff");
    slotGrille(g, x0 + 170, 20, 1020, H - 40, 22, 12, u > 1 ? 0.7 : 0.55);
    // right side: two 2.5" drive bays per U on dual servers, otherwise USB and label tag
    const bays = Math.min(8, Math.max(2, u * 4));
    for (let i = 0; i < bays; i++) bay(g, 1340 + (i % 4) * 130, 16 + Math.floor(i / 4) * (PX_U - 4), 120, PX_U - 28, i % 3 ? "#34d058" : "#f0883e");
    g.fillStyle = "#e6e9ee"; g.fillRect(x1 - 10, 28, 60, 26);                       // pull-out service tag
    label(g, hw.name, x0 + 170, H - 14, 24);
  } else if (cat === "server_storage") {
    const rows = Math.max(1, u >= 4 ? 4 : u), cols = 12;
    const bw = (x1 - x0 - 140) / cols, bh = (H - 30) / rows;
    for (let r = 0; r < rows; r++) for (let i = 0; i < cols; i++)
      bay(g, x0 + 140 + i * bw + 2, 15 + r * bh + 2, bw - 4, bh - 4, (r + i) % 7 === 0 ? "#f0883e" : "#34d058");
    powerButton(g, x0 + 40, 70); led(g, x0 + 100, 70, 5, "#34d058");
    label(g, hw.name, x0 + 6, H - 14, 22);
  } else if (cat === "server_gpu") {
    const blocks = u >= 4 ? 4 : 2, bw = (x1 - x0 - 200) / blocks;
    for (let i = 0; i < blocks; i++) hexMesh(g, x0 + 190 + i * bw + 6, 18, bw - 12, H - 36);
    g.fillStyle = "#76b900"; g.fillRect(x0 + 160, 18, 6, H - 36);                   // accent stripe
    powerButton(g, x0 + 60, PX_U / 2); led(g, x0 + 60, PX_U / 2 + 50, 5, "#76b900");
    label(g, hw.name, x0 + 190, H - 14, 24);
  } else if (cat === "switch_tor") {
    const perRow = Math.min(24, hw.ports), rows = Math.ceil(hw.ports / perRow);
    const pw = Math.min(58, (x1 - x0 - 380) / perRow - 6), ph = rows === 1 ? 70 : 60;
    for (let r = 0; r < rows; r++) for (let i = 0; i < Math.min(perRow, hw.ports - r * perRow); i++) {
      const x = x0 + 300 + i * (pw + 6), y = rows === 1 ? 70 : 26 + r * (ph + 20) + (r ? 4 : 0);
      sfp(g, x, y, pw, ph);
      led(g, x + pw / 2, y - 10, 3, (i + r) % 5 ? "#34d058" : "#f0883e");
    }
    rj45(g, x0 + 40, 60, 56, 50); rj45(g, x0 + 110, 60, 56, 50);
    label(g, hw.name, x0 + 6, H - 14, 22);
  } else if (cat === "pdu") {
    const n = 12;
    for (let i = 0; i < n; i++) {
      const x = x0 + 330 + i * 100;
      g.fillStyle = "#0a0b0d"; g.beginPath(); g.roundRect(x, 56, 80, 74, 8); g.fill();
      g.fillStyle = "#3b3f47";
      for (const dx of [18, 40, 62]) g.fillRect(x + dx - 4, 72, 8, 28);
    }
    g.fillStyle = "#06240f"; g.fillRect(x0 + 40, 50, 150, 80);                         // display
    g.fillStyle = "#34d058"; g.font = "700 46px monospace"; g.textBaseline = "middle"; g.fillText("3.2A", x0 + 56, 90);
    g.fillStyle = "#c0392b"; g.fillRect(x0 + 215, 54, 56, 72);                         // breaker
    g.fillStyle = "#e5e7eb"; g.fillRect(x0 + 225, 62, 36, 22);
  } else if (cat === "ups") {
    g.fillStyle = "#06151f"; g.fillRect(x0 + 40, 24, 420, H - 48);
    g.fillStyle = "#58a6ff"; g.font = "700 54px monospace"; g.textBaseline = "middle"; g.fillText("ONLINE 100%", x0 + 60, PX_U / 2);
    for (let i = 0; i < 5; i++) { g.fillStyle = "#34d058"; g.fillRect(x0 + 60 + i * 76, PX_U + 8 > H ? H - 30 : PX_U / 2 + 40, 60, 16); }
    for (let i = 0; i < 4; i++) { g.fillStyle = "#4a515c"; g.beginPath(); g.arc(x0 + 560 + i * 70, PX_U / 2, 22, 0, Math.PI * 2); g.fill(); }
    slotGrille(g, x0 + 900, 24, 800, H - 48, 20, 12, 0.5);
    label(g, hw.name, x0 + 40, H - 12, 22);
  } else if (cat === "fan_panel") {
    const n = 8, step = (x1 - x0) / n;
    for (let i = 0; i < n; i++) {
      const fx = x0 + step * (i + 0.5);
      g.fillStyle = "#050607"; g.beginPath(); g.arc(fx, cy, 74, 0, Math.PI * 2); g.fill();
      g.strokeStyle = "#2f353d"; g.lineWidth = 3;
      for (let r = 20; r <= 70; r += 17) { g.beginPath(); g.arc(fx, cy, r, 0, Math.PI * 2); g.stroke(); }
      for (let a = 0; a < 6; a++) { g.beginPath(); g.moveTo(fx, cy); g.lineTo(fx + Math.cos(a * 1.047) * 72, cy + Math.sin(a * 1.047) * 72); g.stroke(); }
    }
  } else if (cat === "patch_panel") {
    for (let r = 0; r < 2; r++) for (let i = 0; i < 24; i++) {
      const x = x0 + 60 + i * 76, y = 22 + r * 82;
      rj45(g, x, y, 56, 46);
      g.fillStyle = "#e5e7eb"; g.font = "600 16px system-ui"; g.textBaseline = "alphabetic"; g.fillText(String(r * 24 + i + 1), x + 16, y + 62);
    }
  } else if (cat === "cable_mgmt") {
    g.fillStyle = "#14161a"; g.fillRect(x0, 40, x1 - x0, H - 80);
    g.fillStyle = "#3d424b";
    for (let x = x0 + 10; x < x1 - 20; x += 34) g.fillRect(x, 44, 22, H - 88);
  } else {   // blanking panel
    g.fillStyle = "rgba(255,255,255,.05)"; g.fillRect(x0, 40, x1 - x0, 4);
    for (const x of [x0 + 30, x1 - 30]) { g.fillStyle = "#050607"; g.beginPath(); g.arc(x, cy, 8, 0, Math.PI * 2); g.fill(); }
  }
  const tex = toTexture(c);
  texCache.set(hw.code, tex);
  return tex;
}

// ---------------------------------------------------------------- rack parts

// Rack rail with square mounting holes (three per rack unit) and U numbers.
export function railTexture() {
  const [c, g] = canvas(64, RACK_U * 48);
  g.fillStyle = "#14171c"; g.fillRect(0, 0, 64, c.height);
  for (let n = 0; n < RACK_U; n++) {
    const y = c.height - (n + 1) * 48;
    g.fillStyle = "#050607";
    for (const dy of [6, 22, 38]) g.fillRect(34, y + dy, 14, 8);
    g.fillStyle = n % 5 === 4 ? "#e6edf3" : "#6b7787";
    g.font = "bold 15px monospace"; g.textBaseline = "middle"; g.fillText(String(n + 1), 4, y + 24);
    g.fillStyle = "#2a3140"; g.fillRect(0, y, 64, 1);
  }
  return toTexture(c);
}

// Perforated sheet metal (used for side panels and the room's rack doors).
export function perforatedTexture(opaque = false, repeat = [1, 1]) {
  const [c, g] = canvas(256, 256);
  g.fillStyle = "#101318"; g.fillRect(0, 0, 256, 256);
  g.fillStyle = opaque ? "#030405" : "#000000";
  for (let y = 8; y < 256; y += 16) for (let x = 8 + ((y / 16) % 2) * 8; x < 256; x += 16) { g.beginPath(); g.arc(x, y, 4, 0, Math.PI * 2); g.fill(); }
  return toTexture(c, repeat);
}

export function backTexture() {
  const [c, g] = canvas(32, RACK_U * 16);
  g.fillStyle = "#06080b"; g.fillRect(0, 0, 32, c.height);
  g.fillStyle = "#12161d";
  for (let n = 0; n < RACK_U; n++) g.fillRect(0, n * 16 + 15, 32, 1);
  return toTexture(c);
}
