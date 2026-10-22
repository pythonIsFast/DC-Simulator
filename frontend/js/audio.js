// Synthesized sound effects via the Web Audio API (no audio files, no licensing issues).
let ctx = null;
let master = null;
let muted = false;
try { muted = localStorage.getItem("dc_muted") === "1"; } catch { /* storage unavailable */ }

function ensure() {
  if (!ctx) {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return false;
    ctx = new AC();
    master = ctx.createGain();
    master.gain.value = muted ? 0 : 0.5;
    master.connect(ctx.destination);
  }
  if (ctx.state === "suspended") ctx.resume();
  return true;
}

// Browsers only allow audio after a user gesture.
export function unlockAudio() { ensure(); }
window.addEventListener("pointerdown", unlockAudio, { once: true });
window.addEventListener("keydown", unlockAudio, { once: true });

function tone({ freq, dur = 0.12, type = "sine", vol = 0.2, slide = 0, delay = 0 }) {
  if (!ensure() || muted) return;
  const t0 = ctx.currentTime + delay;
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(freq, t0);
  if (slide) osc.frequency.exponentialRampToValueAtTime(Math.max(20, freq + slide), t0 + dur);
  gain.gain.setValueAtTime(0.0001, t0);
  gain.gain.exponentialRampToValueAtTime(vol, t0 + 0.008);
  gain.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
  osc.connect(gain).connect(master);
  osc.start(t0);
  osc.stop(t0 + dur + 0.02);
}

let noiseBuffer = null;
function getNoise() {
  if (!noiseBuffer) {
    noiseBuffer = ctx.createBuffer(1, ctx.sampleRate * 2, ctx.sampleRate);
    const data = noiseBuffer.getChannelData(0);
    for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
  }
  return noiseBuffer;
}

function burst({ dur = 0.08, vol = 0.2, freq = 1200, q = 1, delay = 0 }) {
  if (!ensure() || muted) return;
  const t0 = ctx.currentTime + delay;
  const src = ctx.createBufferSource();
  src.buffer = getNoise();
  const filter = ctx.createBiquadFilter();
  filter.type = "bandpass";
  filter.frequency.value = freq;
  filter.Q.value = q;
  const gain = ctx.createGain();
  gain.gain.setValueAtTime(vol, t0);
  gain.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
  src.connect(filter).connect(gain).connect(master);
  src.start(t0);
  src.stop(t0 + dur + 0.02);
}

export const sfx = {
  click: () => tone({ freq: 520, dur: 0.05, type: "triangle", vol: 0.12 }),
  hover: () => tone({ freq: 760, dur: 0.03, type: "sine", vol: 0.04 }),
  // Heavy "clunk" when a server is mounted into the rack.
  mount: () => {
    tone({ freq: 140, dur: 0.14, type: "square", vol: 0.16, slide: -70 });
    burst({ dur: 0.06, vol: 0.25, freq: 2200, q: 2 });
    tone({ freq: 880, dur: 0.05, type: "triangle", vol: 0.07, delay: 0.05 });
  },
  unmount: () => {
    burst({ dur: 0.12, vol: 0.2, freq: 900, q: 1 });
    tone({ freq: 300, dur: 0.1, type: "sawtooth", vol: 0.08, slide: -150 });
  },
  build: () => {
    tone({ freq: 196, dur: 0.18, type: "triangle", vol: 0.2 });
    tone({ freq: 294, dur: 0.2, type: "triangle", vol: 0.2, delay: 0.09 });
    tone({ freq: 392, dur: 0.3, type: "triangle", vol: 0.2, delay: 0.18 });
  },
  cash: () => {
    tone({ freq: 1320, dur: 0.09, type: "sine", vol: 0.1 });
    tone({ freq: 1980, dur: 0.16, type: "sine", vol: 0.1, delay: 0.07 });
  },
  error: () => tone({ freq: 160, dur: 0.22, type: "sawtooth", vol: 0.14, slide: -50 }),
  alarm: () => {
    for (let i = 0; i < 3; i++) tone({ freq: 740, dur: 0.12, type: "square", vol: 0.1, delay: i * 0.2 });
  },
  milestone: () => {
    [523, 659, 784, 1047].forEach((f, i) => tone({ freq: f, dur: 0.28, type: "triangle", vol: 0.18, delay: i * 0.11 }));
    tone({ freq: 1568, dur: 0.6, type: "sine", vol: 0.12, delay: 0.5 });
  },
};

// Continuous fan noise whose loudness follows the load (0..1). level 0 = off.
let fan = null;
export function setFanLevel(level) {
  if (muted || level <= 0) {
    if (fan) fan.node.gain.setTargetAtTime(0, ctx.currentTime, 0.2);
    return;
  }
  if (!ensure()) return;
  if (!fan) {
    const src = ctx.createBufferSource();
    src.buffer = getNoise();
    src.loop = true;
    const filter = ctx.createBiquadFilter();
    filter.type = "lowpass";
    const gain = ctx.createGain();
    gain.gain.value = 0;
    src.connect(filter).connect(gain).connect(master);
    src.start();
    fan = { node: gain, filter };
  }
  const l = Math.min(1, level);
  fan.filter.frequency.setTargetAtTime(250 + 900 * l, ctx.currentTime, 0.3);
  fan.node.gain.setTargetAtTime(0.02 + 0.07 * l, ctx.currentTime, 0.3);
}

export function isMuted() { return muted; }
export function toggleMute() {
  muted = !muted;
  try { localStorage.setItem("dc_muted", muted ? "1" : "0"); } catch { /* ignore */ }
  if (master) master.gain.value = muted ? 0 : 0.5;
  if (muted && fan) fan.node.gain.setTargetAtTime(0, ctx.currentTime, 0.05);
  return muted;
}
