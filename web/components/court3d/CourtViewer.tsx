"use client";

// The 3D court: a court built from the sport's own YAML (size in metres, every line, the net, the walls of squash and padel,
// the table top of table tennis, the colours), the players as walking figures that follow their tracked positions and swing at
// each of their shots, the shuttle / ball of every visible layer moving along its path, and a heatmap on the floor. Pause, scrub
// and slow motion are controlled by the page; this component owns the animation clock and the scene. Colour is the only thing
// that tells layers apart. The figures are not captured poses: they move along the measured foot positions with a procedural
// walk cycle, and the racket arm swings when a shot of theirs is hit.
import { useEffect, useRef } from "react";
import type { MutableRefObject } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { positionAt, shuttleAt } from "@/lib/court3d";
import type { Layer3D, Scene3DData } from "@/lib/court3d";

export type CameraPreset = "behind" | "top" | "side" | "broadcast";

export interface ViewerHandle {
  seek: (t: number) => void;
  setPreset: (p: CameraPreset) => void;
}

interface Props {
  handle?: MutableRefObject<ViewerHandle | null>;     // a prop, not a ref: next/dynamic does not forward refs
  sport: string;
  court: Scene3DData["court"];
  objectSize?: number;                                // the ball / shuttle's real size in metres (drawn a little larger so it can be seen)
  layers: Layer3D[];
  duration: number;
  playing: boolean;
  speed: number;
  loop: boolean;
  showPaths: boolean;
  onTime?: (t: number) => void;
  onEnded?: () => void;
  className?: string;
}

const DEFAULT_SURFACE = { out: "#14452f", inner: "#1d6b46", line: "#ffffff" };

function disposeTree(o: THREE.Object3D) {
  o.traverse((c) => {
    const m = c as THREE.Mesh;
    m.geometry?.dispose?.();
    const mat = m.material as THREE.Material | THREE.Material[] | undefined;
    (Array.isArray(mat) ? mat : mat ? [mat] : []).forEach((x) => { (x as THREE.MeshBasicMaterial).map?.dispose?.(); x.dispose(); });
  });
}

function nameSprite(text: string, color: string): THREE.Sprite {
  const c = document.createElement("canvas");
  c.width = 256; c.height = 64;
  const g = c.getContext("2d")!;
  g.font = "600 30px sans-serif";
  g.textAlign = "center"; g.textBaseline = "middle";
  g.fillStyle = "rgba(10,14,22,0.75)";
  g.fillRect(8, 8, 240, 48);
  g.strokeStyle = color; g.lineWidth = 4; g.strokeRect(8, 8, 240, 48);
  g.fillStyle = "#fff";
  g.fillText(text.slice(0, 16), 128, 33);
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(c), depthTest: false, transparent: true }));
  s.scale.set(1.6, 0.4, 1);
  s.renderOrder = 10;
  return s;
}

function heatTexture(grid: number[][], color: string): THREE.CanvasTexture {
  const rows = grid.length, cols = grid[0]?.length ?? 0;
  const c = document.createElement("canvas");
  c.width = Math.max(1, cols * 8); c.height = Math.max(1, rows * 8);
  const g = c.getContext("2d")!;
  const col = new THREE.Color(color);
  const rgb = `${Math.round(col.r * 255)},${Math.round(col.g * 255)},${Math.round(col.b * 255)}`;
  for (let r = 0; r < rows; r++) {
    for (let k = 0; k < cols; k++) {
      const v = grid[r][k];
      if (v < 0.03) continue;
      g.fillStyle = `rgba(${rgb},${(0.18 + 0.7 * Math.pow(v, 0.8)).toFixed(3)})`;
      g.fillRect(k * 8, (rows - 1 - r) * 8, 8, 8);            // row 0 is the near baseline: the bottom of the picture
    }
  }
  const t = new THREE.CanvasTexture(c);
  t.magFilter = THREE.LinearFilter;
  return t;
}

// ---- a figure that walks and swings -----------------------------------------------------------------------------------------

interface Figure {
  group: THREE.Group;
  body: THREE.Group;                                   // everything that bobs
  legL: THREE.Group; legR: THREE.Group; armL: THREE.Group; armR: THREE.Group;
}

function limb(len: number, r: number, mat: THREE.Material): THREE.Group {
  const pivot = new THREE.Group();
  const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r * 0.85, len, 10), mat);
  m.position.y = -len / 2;
  pivot.add(m);
  return pivot;
}

function makeFigure(color: string, ghost: boolean, label: string): Figure {
  const mat = new THREE.MeshStandardMaterial({ color, roughness: 0.6, transparent: ghost, opacity: ghost ? 0.5 : 1 });
  const dark = new THREE.MeshStandardMaterial({ color: new THREE.Color(color).multiplyScalar(0.45), roughness: 0.7, transparent: ghost, opacity: ghost ? 0.5 : 1 });
  const skin = new THREE.MeshStandardMaterial({ color: "#e8c39e", roughness: 0.8, transparent: ghost, opacity: ghost ? 0.5 : 1 });
  const group = new THREE.Group();
  const body = new THREE.Group();
  group.add(body);
  const hips = new THREE.Group();
  hips.position.y = 0.92;
  body.add(hips);
  const legL = limb(0.9, 0.075, dark), legR = limb(0.9, 0.075, dark);
  legL.position.x = -0.1; legR.position.x = 0.1;
  hips.add(legL, legR);
  const torso = new THREE.Mesh(new THREE.BoxGeometry(0.42, 0.58, 0.24), mat);
  torso.position.y = 0.3;
  hips.add(torso);
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.115, 14, 10), skin);
  head.position.y = 0.75;
  hips.add(head);
  const shoulder = new THREE.Group();
  shoulder.position.y = 0.52;
  hips.add(shoulder);
  const armL = limb(0.62, 0.05, mat), armR = limb(0.62, 0.05, mat);
  armL.position.x = -0.27; armR.position.x = 0.27;
  shoulder.add(armL, armR);
  // the racket: a handle continuing the arm and an oval head
  const handle = new THREE.Mesh(new THREE.CylinderGeometry(0.014, 0.014, 0.35, 8), new THREE.MeshStandardMaterial({ color: "#222" }));
  handle.position.y = -0.62 - 0.17;
  const frame = new THREE.Mesh(new THREE.TorusGeometry(0.12, 0.012, 8, 20), new THREE.MeshStandardMaterial({ color: "#111" }));
  frame.scale.set(0.8, 1.15, 1);
  frame.position.y = -0.62 - 0.35 - 0.14;
  const strings = new THREE.Mesh(new THREE.CircleGeometry(0.115, 20), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.35, side: THREE.DoubleSide }));
  strings.scale.set(0.8, 1.15, 1);
  strings.position.copy(frame.position);
  armR.add(handle, frame, strings);
  const sprite = nameSprite(label, color);
  sprite.position.y = 2.25;
  group.add(sprite);
  return { group, body, legL, legR, armL, armR };
}

const smooth = (x: number) => x * x * (3 - 2 * x);

/** Right-arm angle (radians about x, 0 = hanging, more negative = raised forward / overhead) at u in [0, 1] of a swing around the contact at 0.5. */
function swingAngle(u: number, overhead: boolean): number {
  const keys: [number, number][] = overhead ? [[0, -0.2], [0.3, -2.5], [0.5, -3.0], [0.75, -1.2], [1, -0.2]] : [[0, -0.2], [0.3, -1.0], [0.5, -1.5], [0.75, -0.9], [1, -0.2]];
  for (let i = 1; i < keys.length; i++) {
    if (u <= keys[i][0]) {
      const [u0, a0] = keys[i - 1], [u1, a1] = keys[i];
      return a0 + (a1 - a0) * smooth((u - u0) / (u1 - u0));
    }
  }
  return keys[keys.length - 1][1];
}

const OVERHEAD = new Set(["smash", "clear", "drop", "serve"]);
const SWING_S = 0.7;

const CourtViewer = function CourtViewer(props: Props) {
  const mount = useRef<HTMLDivElement>(null);
  const live = useRef(props);
  live.current = props;
  const api = useRef<{ seek: (t: number) => void; preset: (p: CameraPreset) => void; rebuild: () => void } | null>(null);

  useEffect(() => {
    if (props.handle) props.handle.current = { seek: (t) => api.current?.seek(t), setPreset: (p) => api.current?.preset(p) };
  }, [props.handle]);

  // the scene lives for the life of the component; layers and the court are rebuilt when they change
  useEffect(() => {
    const el = mount.current!;
    const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    el.appendChild(renderer.domElement);
    renderer.domElement.style.display = "block";
    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#0b1220");
    const camera = new THREE.PerspectiveCamera(45, 1, 0.05, 400);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.maxPolarAngle = Math.PI / 2 - 0.03;
    scene.add(new THREE.HemisphereLight("#dbe8ff", "#1b2433", 1.05));
    const sun = new THREE.DirectionalLight("#ffffff", 1.4);
    sun.position.set(8, 20, 12);
    scene.add(sun);

    let courtGroup: THREE.Group | null = null;
    let layerGroup: THREE.Group | null = null;
    type Dyn = {
      layer: Layer3D; shuttle: THREE.Mesh; trail: THREE.Mesh[]; fig: Figure | null; label: string;
      bright: { line: THREE.Line; flight: Layer3D["flights"][0] }[]; hits: { t: number; overhead: boolean }[]; cum: number[];
    };
    let dynamic: Dyn[] = [];
    let time = 0;
    let lastReport = 0;
    let raf = 0;
    let last = performance.now();
    let courtKey = "";

    const planeZ = () => live.current.court.view3d?.plane_height_m ?? 0;
    const toWorld = (x: number, y: number, z: number, c = live.current.court) => new THREE.Vector3(x - c.width / 2, z, c.length / 2 - y);

    const preset = (p: CameraPreset) => {
      const { length: L, width: W } = live.current.court;
      const span = Math.max(L, W) + (planeZ() > 0 ? 3 : 0);
      const walled = !!live.current.court.view3d?.wall_color;      // a camera outside walls looks over them, from higher up
      const pos: Record<CameraPreset, [number, number, number]> = {
        behind: [0, span * (walled ? 0.8 : 0.42) + planeZ(), L / 2 + span * (walled ? 0.7 : 0.55)],
        top: [0, span * 1.25, 0.01],
        side: [W / 2 + span * 0.85, span * 0.35, 0],
        broadcast: [W * 0.9 + 1, span * (walled ? 0.8 : 0.55) + planeZ(), L / 2 + span * 0.45],
      };
      camera.position.set(...pos[p]);
      controls.target.set(0, planeZ(), 0);
      controls.update();
    };

    const wallMesh = (w: NonNullable<Scene3DData["court"]["walls"]>[number], court: Scene3DData["court"], color: string, opacity: number): THREE.Group | null => {
      const m = /^([xy])=([\d.]+)$/.exec(w.plane ?? "");
      if (!m) return null;
      const axis = m[1], v = Number(m[2]);
      const { length: L, width: W } = court;
      const lineTop = Math.max(0, ...((w.lines ?? []).flatMap((l) => [l.p1[1], l.p2[1]])));
      const hAt = (along: number): number => {                               // wall height at a position along it
        if (w.height_m != null) return w.height_m;
        if (axis === "x" && w.out_line_from_m != null && w.out_line_to_m != null) return w.out_line_to_m + (w.out_line_from_m - w.out_line_to_m) * (along / L);   // squash side wall slopes to the back
        if (w.out_line_m != null) return w.out_line_m;
        return lineTop || 3;
      };
      const [a0, a1] = axis === "y" ? [0, W] : (w.y_range ?? [0, L]);
      const g = new THREE.Group();
      const n = 12;
      const pts: number[] = [];
      for (let i = 0; i <= n; i++) {
        const along = a0 + ((a1 - a0) * i) / n;
        const h = hAt(along);
        const bottom = axis === "y" ? toWorld(along, v, 0, court) : toWorld(v, along, 0, court);
        pts.push(bottom.x, 0, bottom.z, bottom.x, h, bottom.z);
      }
      const idx: number[] = [];
      for (let i = 0; i < n; i++) { const o = i * 2; idx.push(o, o + 1, o + 2, o + 1, o + 3, o + 2); }
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
      geo.setIndex(idx);
      geo.computeVertexNormals();
      g.add(new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color, transparent: true, opacity, side: THREE.DoubleSide, depthWrite: opacity > 0.7 })));
      for (const l of w.lines ?? []) {                                       // squash's tin, service and out lines on the front wall
        const h = l.p1[1];
        const pa = axis === "y" ? toWorld(l.p1[0], v, h, court) : toWorld(v, l.p1[0], h, court);
        const pb = axis === "y" ? toWorld(l.p2[0], v, h, court) : toWorld(v, l.p2[0], h, court);
        const lm = new THREE.Mesh(new THREE.BoxGeometry(pa.distanceTo(pb), 0.04, 0.02), new THREE.MeshBasicMaterial({ color: "#c0262d" }));
        lm.position.copy(pa.clone().add(pb).multiplyScalar(0.5));
        g.add(lm);
      }
      return g;
    };

    const buildCourt = () => {
      const { court, sport } = live.current;
      const key = `${sport}:${court.length}:${court.width}:${court.lines.length}:${(court.walls ?? []).length}:${planeZ()}`;
      if (key === courtKey) return;
      courtKey = key;
      if (courtGroup) { scene.remove(courtGroup); disposeTree(courtGroup); }
      const view = court.view3d ?? {};
      const col = { ...DEFAULT_SURFACE, ...(view.surface ?? {}) };
      const { length: L, width: W } = court;
      const pz = planeZ();
      const g = new THREE.Group();
      const pad = Math.max(Math.max(L, W) * 0.22, pz > 0 ? 3 : 0);
      const out = new THREE.Mesh(new THREE.PlaneGeometry(W + 2 * pad, L + 2 * pad), new THREE.MeshStandardMaterial({ color: col.out, roughness: 0.95 }));
      out.rotation.x = -Math.PI / 2;
      g.add(out);
      if (pz > 0) {                                                          // a table: a slab on legs
        const slab = new THREE.Mesh(new THREE.BoxGeometry(W, 0.04, L), new THREE.MeshStandardMaterial({ color: col.inner, roughness: 0.5 }));
        slab.position.y = pz - 0.02;
        g.add(slab);
        if (view.legs) for (const [sx, sz] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) {
          const leg = new THREE.Mesh(new THREE.BoxGeometry(0.07, pz - 0.04, 0.07), new THREE.MeshStandardMaterial({ color: "#222" }));
          leg.position.set(sx * (W / 2 - 0.12), (pz - 0.04) / 2, sz * (L / 2 - 0.2));
          g.add(leg);
        }
      } else {
        const inner = new THREE.Mesh(new THREE.PlaneGeometry(W, L), new THREE.MeshStandardMaterial({ color: col.inner, roughness: 0.85 }));
        inner.rotation.x = -Math.PI / 2;
        inner.position.y = 0.004;
        g.add(inner);
      }
      const lineMat = new THREE.MeshBasicMaterial({ color: col.line });
      const lw = pz > 0 ? 0.02 : 0.05;
      for (const l of court.lines) {
        if (l.id === "net") continue;
        const a = toWorld(l.p1[0], l.p1[1], 0), b = toWorld(l.p2[0], l.p2[1], 0);
        const len = a.distanceTo(b);
        const m = new THREE.Mesh(new THREE.BoxGeometry(len + lw, 0.004, lw), lineMat);
        m.position.copy(a.clone().add(b).multiplyScalar(0.5));
        m.position.y = pz + 0.008;
        m.rotation.y = -Math.atan2(b.z - a.z, b.x - a.x);
        g.add(m);
      }
      const net = court.lines.find((l) => l.id === "net");
      if (net) {
        const hc = court.net.height_center ?? 1.0, hp = court.net.height_post ?? hc;
        const a = toWorld(net.p1[0], net.p1[1], 0), b = toWorld(net.p2[0], net.p2[1], 0);
        const over = court.net.overhang_m ?? 0;
        const len = a.distanceTo(b) + 2 * over;
        const cv = document.createElement("canvas");
        cv.width = 256; cv.height = 64;
        const cg = cv.getContext("2d")!;
        cg.fillStyle = "rgba(20,24,32,0.35)"; cg.fillRect(0, 0, 256, 64);
        cg.strokeStyle = "rgba(230,235,245,0.8)"; cg.lineWidth = 1.5;
        for (let i = 0; i <= 256; i += 8) { cg.beginPath(); cg.moveTo(i, 0); cg.lineTo(i, 64); cg.stroke(); }
        for (let j = 0; j <= 64; j += 8) { cg.beginPath(); cg.moveTo(0, j); cg.lineTo(256, j); cg.stroke(); }
        const tex = new THREE.CanvasTexture(cv);
        const mesh = new THREE.Mesh(new THREE.PlaneGeometry(len, hc), new THREE.MeshBasicMaterial({ map: tex, transparent: true, side: THREE.DoubleSide }));
        mesh.position.copy(a.clone().add(b).multiplyScalar(0.5));
        mesh.position.y = pz + hc / 2;
        mesh.rotation.y = -Math.atan2(b.z - a.z, b.x - a.x);
        g.add(mesh);
        const tape = new THREE.Mesh(new THREE.BoxGeometry(len, Math.max(0.012, hc * 0.04), 0.02), new THREE.MeshBasicMaterial({ color: "#f8fafc" }));
        tape.position.copy(mesh.position); tape.position.y = pz + hc; tape.rotation.y = mesh.rotation.y;
        g.add(tape);
        for (const p of [a, b]) {
          const post = new THREE.Mesh(new THREE.CylinderGeometry(Math.min(0.04, hp * 0.2), Math.min(0.04, hp * 0.2), hp + 0.02, 12), new THREE.MeshStandardMaterial({ color: "#1f2937" }));
          post.position.set(p.x, pz + (hp + 0.02) / 2, p.z);
          g.add(post);
        }
      }
      for (const w of court.walls ?? []) {
        if (!view.wall_color) break;                                        // a sport with no drawn walls (see view3d in its YAML)
        const wm = wallMesh(w, court, view.wall_color, view.wall_opacity ?? 0.3);
        if (wm) g.add(wm);
      }
      courtGroup = g;
      scene.add(g);
      preset("behind");
    };

    const buildLayers = () => {
      if (layerGroup) { scene.remove(layerGroup); disposeTree(layerGroup); }
      dynamic = [];
      const { court, layers, objectSize } = live.current;
      const lg = new THREE.Group();
      const ballR = Math.max(0.05, (objectSize ?? 0.065) * 1.6);
      layers.forEach((layer, li) => {
        if (!layer.visible) return;
        const color = new THREE.Color(layer.color);
        const bright: Dyn["bright"] = [];
        if (layer.showHeat && layer.heat) {
          const hm = new THREE.Mesh(new THREE.PlaneGeometry(court.width, layer.heat.grid.length * layer.heat.cell),
            new THREE.MeshBasicMaterial({ map: heatTexture(layer.heat.grid, layer.color), transparent: true, depthWrite: false }));
          hm.rotation.x = -Math.PI / 2;
          hm.position.set(0, 0.012 + li * 0.002, court.length / 2 - (layer.heat.grid.length * layer.heat.cell) / 2);
          hm.renderOrder = 2 + li;
          lg.add(hm);
        }
        for (const f of layer.flights) {
          const pts = f.samples.map((s) => toWorld(s[1], s[2], s[3]));
          const geo = new THREE.BufferGeometry().setFromPoints(pts);
          const dashed = f.kind === "estimate";
          const faint = dashed
            ? new THREE.Line(geo, new THREE.LineDashedMaterial({ color, dashSize: 0.18, gapSize: 0.12, transparent: true, opacity: layer.ghost ? 0.25 : 0.4 }))
            : new THREE.Line(geo, new THREE.LineBasicMaterial({ color, transparent: true, opacity: layer.ghost ? 0.22 : 0.35 }));
          if (dashed) faint.computeLineDistances();
          lg.add(faint);
          const hot = new THREE.Line(geo.clone(), new THREE.LineBasicMaterial({ color, transparent: true, opacity: layer.ghost ? 0.55 : 1 }));
          hot.geometry.setDrawRange(0, 0);
          hot.renderOrder = 4;
          lg.add(hot);
          bright.push({ line: hot, flight: f });
        }
        const shuttle = new THREE.Mesh(new THREE.SphereGeometry(layer.ghost ? ballR * 0.8 : ballR, 16, 12), new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.6 }));
        shuttle.visible = false;
        lg.add(shuttle);
        const trail: THREE.Mesh[] = [];
        for (let k = 0; k < 10; k++) {
          const m = new THREE.Mesh(new THREE.SphereGeometry(ballR * 0.55 * (1 - k / 14), 8, 6), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.5 * (1 - k / 10) }));
          m.visible = false;
          lg.add(m);
          trail.push(m);
        }
        let fig: Figure | null = null;
        const cum: number[] = [];
        if (layer.positions.length > 0) {
          fig = makeFigure(layer.color, !!layer.ghost, layer.label);
          lg.add(fig.group);
          let d = 0;
          layer.positions.forEach((p, i) => { if (i) d += Math.hypot(p[1] - layer.positions[i - 1][1], p[2] - layer.positions[i - 1][2]); cum.push(d); });
          cum.unshift(0);
          cum.length = layer.positions.length;
        }
        const hits = layer.flights.map((f) => ({ t: f.t0, overhead: OVERHEAD.has(f.shot ?? "") || f.peak_z > 2.0 }));
        dynamic.push({ layer, shuttle, trail, fig, label: layer.label, bright, hits, cum });
      });
      layerGroup = lg;
      scene.add(lg);
      update(time);
    };

    const animateFigure = (d: Dyn, t: number, w: THREE.Vector3) => {
      const f = d.fig!;
      const pos = d.layer.positions;
      // walking: how fast, and how far along the path (the phase of the stride is the distance walked)
      const p0 = positionAt(pos, t - 0.25), p1 = positionAt(pos, t + 0.25);
      const speed = p0 && p1 ? Math.hypot(p1[0] - p0[0], p1[1] - p0[1]) / 0.5 : 0;
      let walked = 0;
      if (d.cum.length > 1) {
        const i = Math.max(0, pos.findIndex((q) => q[0] > t) - 1);
        const j = Math.min(i + 1, pos.length - 1);
        const u = pos[j][0] > pos[i][0] ? Math.min(1, Math.max(0, (t - pos[i][0]) / (pos[j][0] - pos[i][0]))) : 0;
        walked = d.cum[i] + (d.cum[j] - d.cum[i]) * u;
      }
      const amp = Math.min(1, speed / 2.5) * 0.75;
      const ph = (walked / 0.85) * Math.PI;
      f.legL.rotation.x = Math.sin(ph) * amp;
      f.legR.rotation.x = -Math.sin(ph) * amp;
      f.armL.rotation.x = -Math.sin(ph) * amp * 0.6;
      f.body.position.y = Math.abs(Math.cos(ph)) * 0.05 * Math.min(1, speed / 2.5);
      f.body.rotation.x = Math.min(0.25, speed * 0.05);                             // leans into a run
      // facing the net, a little toward where it is going when it moves fast
      const net = new THREE.Vector3(0, 0, 0);
      let yaw = Math.atan2(net.x - w.x, net.z - w.z);
      if (speed > 1.5 && p0 && p1) yaw += Math.max(-0.6, Math.min(0.6, Math.atan2(p1[0] - p0[0], -(p1[1] - p0[1])) * 0.15));
      f.group.rotation.y = yaw;
      // the racket arm: at rest it hangs a little forward, and it swings around each contact of this player's shots
      let arm = -0.25;
      for (const h of d.hits) {
        if (Math.abs(t - h.t) <= SWING_S / 2) { arm = swingAngle((t - (h.t - SWING_S / 2)) / SWING_S, h.overhead); break; }
      }
      f.armR.rotation.x = arm;
    };

    const update = (t: number) => {
      const pz = planeZ();
      for (const d of dynamic) {
        const p = positionAt(d.layer.positions, t);
        if (p && d.fig) {
          const w = toWorld(p[0], p[1], 0);
          d.fig.group.position.set(w.x, 0, w.z);
          animateFigure(d, t, w);
        }
        for (const b of d.bright) {
          const n = b.flight.samples.length;
          const upto = t < b.flight.t0 ? 0 : t >= b.flight.t1 ? n : Math.max(1, b.flight.samples.findIndex((s) => s[0] > t));
          b.line.geometry.setDrawRange(0, upto <= 0 ? 0 : upto);
          b.line.visible = live.current.showPaths || (t >= b.flight.t0 && t <= b.flight.t1 + 0.6);
        }
        const s = shuttleAt(d.layer.flights, t);
        d.shuttle.visible = !!s;
        d.trail.forEach((m) => { m.visible = false; });
        if (s) {
          d.shuttle.position.copy(toWorld(s.at[0], s.at[1], s.at[2]));
          for (let k = 0; k < d.trail.length; k++) {
            const sm = s.flight.samples[s.index - 1 - k * 2];
            if (!sm) break;
            d.trail[k].position.copy(toWorld(sm[1], sm[2], sm[3]));
            d.trail[k].visible = true;
          }
        }
      }
      void pz;
    };

    const resize = () => {
      const w = el.clientWidth || 800, h = el.clientHeight || 450;
      renderer.setSize(w, h, false);
      renderer.domElement.style.width = "100%";
      renderer.domElement.style.height = "100%";
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    resize();

    const loop = (now: number) => {
      raf = requestAnimationFrame(loop);
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      const p = live.current;
      if (p.playing) {
        time += dt * p.speed;
        if (time >= p.duration) {
          if (p.loop && p.duration > 0) time = 0;
          else { time = p.duration; p.onEnded?.(); }
        }
      }
      update(time);
      if (now - lastReport > 66) { lastReport = now; p.onTime?.(time); }
      controls.update();
      renderer.render(scene, camera);
    };

    api.current = { seek: (t) => { time = Math.max(0, t); update(time); live.current.onTime?.(time); }, preset, rebuild: () => { buildCourt(); buildLayers(); } };
    buildCourt();
    buildLayers();
    raf = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      controls.dispose();
      if (courtGroup) disposeTree(courtGroup);
      if (layerGroup) disposeTree(layerGroup);
      renderer.dispose();
      el.removeChild(renderer.domElement);
      api.current = null;
    };
  }, []);

  // anything that changes what is drawn rebuilds it (the animation clock is kept)
  const key = JSON.stringify(props.layers.map((l) => [l.id, l.visible, l.showHeat, l.color, l.ghost, l.flights.length, l.positions.length])) +
    `|${props.sport}|${props.court.length}|${props.court.width}|${props.court.view3d?.plane_height_m ?? 0}|${(props.court.walls ?? []).length}`;
  useEffect(() => { api.current?.rebuild(); }, [key]);   // eslint-disable-line react-hooks/exhaustive-deps

  return <div ref={mount} className={props.className} />;
};

export default CourtViewer;
