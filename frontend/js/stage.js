// One shared WebGL renderer; views (globe, room, rack) take turns rendering into it.
import * as THREE from "three";

export const stage = {
  renderer: null,
  view: null,
  clock: new THREE.Clock(),
  time: 0,
};

export function initStage(canvas) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  stage.renderer = renderer;
  const resize = () => {
    renderer.setSize(window.innerWidth, window.innerHeight, false);
    if (stage.view) stage.view.resize(window.innerWidth, window.innerHeight);
  };
  window.addEventListener("resize", resize);
  resize();
  const loop = () => {
    requestAnimationFrame(loop);
    const dt = Math.min(0.1, stage.clock.getDelta());
    stage.time += dt;
    if (stage.view) {
      stage.view.update(dt, stage.time);
      renderer.render(stage.view.scene, stage.view.camera);
    }
  };
  loop();
}

// Switch the active view. Views implement: scene, camera, update(dt, t), resize(w, h), activate(), deactivate().
export function setStageView(view) {
  if (stage.view === view) return;
  if (stage.view && stage.view.deactivate) stage.view.deactivate();
  stage.view = view;
  if (view.activate) view.activate();
  view.resize(window.innerWidth, window.innerHeight);
}

// Simple damped orbit controller for a camera around a target (drag = rotate, wheel = zoom).
export class Orbit {
  constructor(camera, dom, opts = {}) {
    this.camera = camera;
    this.dom = dom;
    this.target = new THREE.Vector3(...(opts.target || [0, 0, 0]));
    this.yaw = opts.yaw ?? 0;
    this.pitch = opts.pitch ?? 0.3;
    this.dist = opts.dist ?? 4;
    this.minDist = opts.minDist ?? 1.5;
    this.maxDist = opts.maxDist ?? 8;
    this.minPitch = opts.minPitch ?? -1.4;
    this.maxPitch = opts.maxPitch ?? 1.4;
    this.vYaw = 0; this.vPitch = 0;
    this.dragging = false;
    this.moved = 0;      // pixels moved during the last drag, used to tell click from drag
    this.enabled = false;
    this._down = (e) => {
      if (!this.enabled || e.button !== 0) return;
      this.dragging = true; this.moved = 0; this.lx = e.clientX; this.ly = e.clientY;
    };
    this._move = (e) => {
      if (!this.dragging) return;
      const dx = e.clientX - this.lx, dy = e.clientY - this.ly;
      this.lx = e.clientX; this.ly = e.clientY;
      this.moved += Math.abs(dx) + Math.abs(dy);
      const k = 0.005 * Math.min(1, this.dist / 3);
      this.vYaw = -dx * k; this.vPitch = dy * k;
      this.yaw += this.vYaw; this.pitch += this.vPitch;
    };
    this._up = () => { this.dragging = false; };
    this._wheel = (e) => {
      if (!this.enabled) return;
      e.preventDefault();
      this.dist = Math.min(this.maxDist, Math.max(this.minDist, this.dist * (1 + Math.sign(e.deltaY) * 0.1)));
    };
    dom.addEventListener("pointerdown", this._down);
    window.addEventListener("pointermove", this._move);
    window.addEventListener("pointerup", this._up);
    dom.addEventListener("wheel", this._wheel, { passive: false });
  }

  get wasDrag() { return this.moved > 6; }

  update(dt) {
    if (!this.dragging) {
      this.yaw += this.vYaw; this.pitch += this.vPitch;
      const damp = Math.pow(0.0005, dt);
      this.vYaw *= damp; this.vPitch *= damp;
    }
    this.pitch = Math.min(this.maxPitch, Math.max(this.minPitch, this.pitch));
    const cp = Math.cos(this.pitch);
    this.camera.position.set(
      this.target.x + this.dist * cp * Math.sin(this.yaw),
      this.target.y + this.dist * Math.sin(this.pitch),
      this.target.z + this.dist * cp * Math.cos(this.yaw),
    );
    this.camera.lookAt(this.target);
  }
}
