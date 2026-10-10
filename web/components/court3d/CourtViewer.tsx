"use client";

// The 3D court: a court built from the sport's own YAML (lines, net height, size in metres), the players and the shuttle / ball
// of every visible layer moving along their paths, and a heatmap on the floor. Pause, scrub and slow motion are controlled by
// the page; this component owns the animation clock and the scene. Colour is the only thing that tells layers apart.
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

const SURFACE: Record<string, { out: string; inner: string; line: string }> = {
  tennis: { out: "#2f6b4f", inner: "#2b5f95", line: "#ffffff" },       // a hard court: blue inside the lines, green around
  badminton: { out: "#14452f", inner: "#1d6b46", line: "#ffffff" },
  pickleball: { out: "#2f4f6b", inner: "#3b7a57", line: "#ffffff" },
  padel: { out: "#1f5a8f", inner: "#2b6cb0", line: "#ffffff" },
  squash: { out: "#7a5b3a", inner: "#b08a5b", line: "#c0262d" },
  table_tennis: { out: "#1b2b3c", inner: "#14507d", line: "#ffffff" },
};

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
  c.width = cols * 8; c.height = rows * 8;
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

export default function CourtViewer(props: Props) {
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
    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 400);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.maxPolarAngle = Math.PI / 2 - 0.03;
    scene.add(new THREE.HemisphereLight("#dbe8ff", "#1b2433", 1.05));
    const sun = new THREE.DirectionalLight("#ffffff", 1.4);
    sun.position.set(8, 20, 12);
    scene.add(sun);

    let courtGroup: THREE.Group | null = null;
    let layerGroup: THREE.Group | null = null;
    let dynamic: { layer: Layer3D; shuttle: THREE.Mesh; trail: THREE.Mesh[]; player: THREE.Group; bright: { line: THREE.Line; flight: Layer3D["flights"][0] }[] }[] = [];
    let time = 0;
    let lastReport = 0;
    let raf = 0;
    let last = performance.now();
    let courtKey = "";

    const toWorld = (x: number, y: number, z: number, c = live.current.court) => new THREE.Vector3(x - c.width / 2, z, c.length / 2 - y);

    const preset = (p: CameraPreset) => {
      const { length: L, width: W } = live.current.court;
      const span = Math.max(L, W);
      const pos: Record<CameraPreset, [number, number, number]> = {
        behind: [0, span * 0.42, L / 2 + span * 0.55],
        top: [0, span * 1.25, 0.01],
        side: [W / 2 + span * 0.85, span * 0.35, 0],
        broadcast: [W * 0.9, span * 0.55, L / 2 + span * 0.45],
      };
      camera.position.set(...pos[p]);
      controls.target.set(0, 0, 0);
      controls.update();
    };

    const buildCourt = () => {
      const { court, sport } = live.current;
      const key = `${sport}:${court.length}:${court.width}:${court.lines.length}`;
      if (key === courtKey) return;
      courtKey = key;
      if (courtGroup) { scene.remove(courtGroup); disposeTree(courtGroup); }
      const col = SURFACE[sport] ?? SURFACE.badminton;
      const { length: L, width: W } = court;
      const g = new THREE.Group();
      const pad = Math.max(L, W) * 0.22;
      const out = new THREE.Mesh(new THREE.PlaneGeometry(W + 2 * pad, L + 2 * pad), new THREE.MeshStandardMaterial({ color: col.out, roughness: 0.95 }));
      out.rotation.x = -Math.PI / 2;
      g.add(out);
      const inner = new THREE.Mesh(new THREE.PlaneGeometry(W, L), new THREE.MeshStandardMaterial({ color: col.inner, roughness: 0.85 }));
      inner.rotation.x = -Math.PI / 2;
      inner.position.y = 0.004;
      g.add(inner);
      const lineMat = new THREE.MeshBasicMaterial({ color: col.line });
      for (const l of court.lines) {
        if (l.id === "net") continue;
        const a = toWorld(l.p1[0], l.p1[1], 0), b = toWorld(l.p2[0], l.p2[1], 0);
        const len = a.distanceTo(b);
        const m = new THREE.Mesh(new THREE.BoxGeometry(len + 0.05, 0.004, 0.05), lineMat);
        m.position.copy(a.clone().add(b).multiplyScalar(0.5));
        m.position.y = 0.008;
        m.rotation.y = -Math.atan2(b.z - a.z, b.x - a.x);
        g.add(m);
      }
      const net = court.lines.find((l) => l.id === "net");
      if (net) {
        const hc = court.net.height_center ?? 1.0, hp = court.net.height_post ?? hc;
        const a = toWorld(net.p1[0], net.p1[1], 0), b = toWorld(net.p2[0], net.p2[1], 0);
        const len = a.distanceTo(b);
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
        mesh.position.y = hc / 2;
        mesh.rotation.y = -Math.atan2(b.z - a.z, b.x - a.x);
        g.add(mesh);
        const tape = new THREE.Mesh(new THREE.BoxGeometry(len, 0.04, 0.03), new THREE.MeshBasicMaterial({ color: "#f8fafc" }));
        tape.position.copy(mesh.position); tape.position.y = hc; tape.rotation.y = mesh.rotation.y;
        g.add(tape);
        for (const p of [a, b]) {
          const post = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.04, hp + 0.05, 12), new THREE.MeshStandardMaterial({ color: "#1f2937" }));
          post.position.set(p.x, (hp + 0.05) / 2, p.z);
          g.add(post);
        }
      }
      courtGroup = g;
      scene.add(g);
      preset("behind");
    };

    const buildLayers = () => {
      if (layerGroup) { scene.remove(layerGroup); disposeTree(layerGroup); }
      dynamic = [];
      const { court, layers } = live.current;
      const lg = new THREE.Group();
      layers.forEach((layer, li) => {
        if (!layer.visible) return;
        const color = new THREE.Color(layer.color);
        const bright: { line: THREE.Line; flight: Layer3D["flights"][0] }[] = [];
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
          faint.name = `faint:${li}`;
          lg.add(faint);
          const hot = new THREE.Line(geo.clone(), new THREE.LineBasicMaterial({ color, transparent: true, opacity: layer.ghost ? 0.55 : 1 }));
          hot.geometry.setDrawRange(0, 0);
          hot.renderOrder = 4;
          lg.add(hot);
          bright.push({ line: hot, flight: f });
        }
        const shuttle = new THREE.Mesh(new THREE.SphereGeometry(layer.ghost ? 0.1 : 0.13, 16, 12), new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.6 }));
        shuttle.visible = false;
        lg.add(shuttle);
        const trail: THREE.Mesh[] = [];
        for (let k = 0; k < 10; k++) {
          const m = new THREE.Mesh(new THREE.SphereGeometry(0.07 * (1 - k / 14), 8, 6), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.5 * (1 - k / 10) }));
          m.visible = false;
          lg.add(m);
          trail.push(m);
        }
        const player = new THREE.Group();
        const body = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.26, 1.3, 16), new THREE.MeshStandardMaterial({ color, transparent: layer.ghost, opacity: layer.ghost ? 0.45 : 1 }));
        body.position.y = 0.75;
        const head = new THREE.Mesh(new THREE.SphereGeometry(0.17, 16, 12), new THREE.MeshStandardMaterial({ color, transparent: layer.ghost, opacity: layer.ghost ? 0.45 : 1 }));
        head.position.y = 1.65;
        const label = nameSprite(layer.label, layer.color);
        label.position.y = 2.3;
        player.add(body, head, label);
        player.visible = layer.positions.length > 0;
        lg.add(player);
        dynamic.push({ layer, shuttle, trail, player, bright });
      });
      layerGroup = lg;
      scene.add(lg);
      update(time);
    };

    const update = (t: number) => {
      for (const d of dynamic) {
        const p = positionAt(d.layer.positions, t);
        if (p) {
          const w = toWorld(p[0], p[1], 0);
          d.player.position.set(w.x, 0, w.z);
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
    `|${props.sport}|${props.court.length}|${props.court.width}`;
  useEffect(() => { api.current?.rebuild(); }, [key]);   // eslint-disable-line react-hooks/exhaustive-deps

  return <div ref={mount} className={props.className} />;
}
