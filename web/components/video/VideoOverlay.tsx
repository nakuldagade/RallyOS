"use client";

// <video> + <canvas> overlay: players (bbox + pose), shuttle trail, court lines, hit/landing banners.
// If the source video is missing (mock / not yet processed) it renders tracks.json on a synthetic canvas.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { mediaUrl } from "@/lib/api";
import { fmtTime } from "@/lib/format";
import { applyH, courtToPx } from "@/lib/geometry";
import type { CourtLine, MatchJSON, TrackFrame, Tracks } from "@/lib/types";

const SKELETON: [number, number][] = [
  [5, 7], [7, 9], [6, 8], [8, 10], [5, 6], [5, 11], [6, 12], [11, 12],
  [11, 13], [13, 15], [12, 14], [14, 16], [0, 1], [0, 2], [1, 3], [2, 4],
];
const TRAIL = 24;

interface Props {
  match: MatchJSON;
  tracks: Tracks | null;
  lines: CourtLine[];
  courtSize: { length: number; width: number };
  seek?: { t: number; n: number };
  onTime?: (t: number, frame: TrackFrame | null) => void;
}

export default function VideoOverlay({ match, tracks, lines, courtSize, seek, onTime }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const src = mediaUrl(match.video.src);
  const [mode, setMode] = useState<"video" | "synthetic">(src ? "video" : "synthetic");
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [showIgnored, setShowIgnored] = useState(false);   // filtered-out people: off by default
  const [shown, setShown] = useState(0);
  const tRef = useRef(0);
  const playingRef = useRef(false);
  const speedRef = useRef(1);
  const onTimeRef = useRef(onTime);
  playingRef.current = playing;
  speedRef.current = speed;
  onTimeRef.current = onTime;

  const W = match.video.width;
  const H = match.video.height;
  const duration = match.video.duration_s;
  const fps = tracks?.fps ?? match.video.fps;
  const loopS = tracks ? tracks.frames.length / tracks.fps : 0;

  const c2p = useMemo(() => courtToPx(match, tracks), [match, tracks]);
  const colors = useMemo(() => new Map(match.players.map((p) => [p.track_id, p.color ?? "#22c55e"])), [match]);
  const names = useMemo(() => new Map(match.players.map((p) => [p.track_id, p.name])), [match]);

  const frameIndex = useCallback(
    (t: number): number | null => {
      if (!tracks?.frames.length) return null;
      const n = tracks.frames.length;
      const i = Math.round(t * fps);
      if (mode === "synthetic") return ((i % n) + n) % n; // mock tracks loop
      return i >= 0 && i < n ? i : null;
    },
    [tracks, fps, mode],
  );

  const draw = useCallback(
    (t: number) => {
      const ctx = canvasRef.current?.getContext("2d");
      if (!ctx) return;
      const s = W / 1920;
      ctx.clearRect(0, 0, W, H);
      if (mode === "synthetic") {
        const g = ctx.createLinearGradient(0, 0, 0, H);
        g.addColorStop(0, "#0a1220");
        g.addColorStop(1, "#0f2419");
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, W, H);
      }
      if (c2p) {
        if (mode === "synthetic") {
          const corners = [[0, 0], [courtSize.width, 0], [courtSize.width, courtSize.length], [0, courtSize.length]]
            .map(([x, y]) => applyH(c2p, x, y));
          ctx.beginPath();
          corners.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
          ctx.closePath();
          ctx.fillStyle = "rgba(34,120,74,0.55)";
          ctx.fill();
        }
        ctx.lineWidth = 3 * s;
        for (const l of lines) {
          const [x1, y1] = applyH(c2p, l.p1[0], l.p1[1]);
          const [x2, y2] = applyH(c2p, l.p2[0], l.p2[1]);
          ctx.strokeStyle = l.id === "net" ? "rgba(203,213,225,0.95)" : "rgba(255,255,255,0.8)";
          ctx.setLineDash(l.id === "net" ? [12 * s, 8 * s] : []);
          ctx.beginPath();
          ctx.moveTo(x1, y1);
          ctx.lineTo(x2, y2);
          ctx.stroke();
        }
        ctx.setLineDash([]);
      }

      const fi = frameIndex(t);
      let frame: TrackFrame | null = null;
      if (fi !== null && tracks) {
        frame = tracks.frames[fi];
        // shuttle trail (interpolated frames drawn hollow: lower confidence)
        for (let k = TRAIL; k >= 1; k--) {
          const b = tracks.frames[fi - k]?.ball;
          if (!b) continue;
          const a = 1 - k / TRAIL;
          ctx.beginPath();
          ctx.arc(b.px[0], b.px[1], (3 + 5 * a) * s, 0, Math.PI * 2);
          if (b.interp) {
            ctx.strokeStyle = `rgba(250,204,21,${a * 0.8})`;
            ctx.lineWidth = 2 * s;
            ctx.stroke();
          } else {
            ctx.fillStyle = `rgba(250,250,210,${a * 0.85})`;
            ctx.fill();
          }
        }
        if (showIgnored) {
          for (const o of frame.others ?? []) {     // detected but not a player: drawn faint so the filter is visible
            const [x1, y1, x2, y2] = o.bbox;
            ctx.setLineDash([8 * s, 6 * s]);
            ctx.strokeStyle = "rgba(203,213,225,0.7)";
            ctx.lineWidth = 2 * s;
            ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
            ctx.setLineDash([]);
            ctx.font = `500 ${16 * s}px system-ui, sans-serif`;
            const label = o.reason.startsWith("static") ? "ignored · official" : `ignored · ${o.reason}`;
            ctx.fillStyle = "rgba(15,23,42,0.75)";
            ctx.fillRect(x1, y1 - 22 * s, ctx.measureText(label).width + 10 * s, 20 * s);
            ctx.fillStyle = "rgba(226,232,240,0.95)";
            ctx.fillText(label, x1 + 5 * s, y1 - 7 * s);
          }
        }
        for (const p of frame.players) {
          const color = colors.get(p.track_id) ?? "#22c55e";
          const [x1, y1, x2, y2] = p.bbox;
          ctx.strokeStyle = color;
          ctx.lineWidth = 3 * s;
          ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
          if (p.kp) {
            ctx.lineWidth = 3.5 * s;
            for (const [a, b] of SKELETON) {
              const pa = p.kp[a];
              const pb = p.kp[b];
              if (!pa || !pb || pa[2] < 0.3 || pb[2] < 0.3) continue;
              ctx.beginPath();
              ctx.moveTo(pa[0], pa[1]);
              ctx.lineTo(pb[0], pb[1]);
              ctx.stroke();
            }
          }
          const label = names.get(p.track_id) ?? `#${p.track_id}`;
          ctx.font = `600 ${22 * s}px system-ui, sans-serif`;
          const tw = ctx.measureText(label).width;
          ctx.fillStyle = color;
          ctx.fillRect(x1, y1 - 30 * s, tw + 16 * s, 28 * s);
          ctx.fillStyle = "white";
          ctx.fillText(label, x1 + 8 * s, y1 - 9 * s);
        }
        const ball = frame.ball;
        if (ball) {
          ctx.beginPath();
          ctx.arc(ball.px[0], ball.px[1], 9 * s, 0, Math.PI * 2);
          ctx.fillStyle = ball.interp ? "rgba(250,204,21,0.5)" : "#fffbe6";
          ctx.shadowColor = "#fde68a";
          ctx.shadowBlur = 18 * s;
          ctx.fill();
          ctx.shadowBlur = 0;
        }
      }

      const ev = match.events.find((e) => Math.abs(e.t - t) < 0.35);
      if (ev) {
        const who = ev.track_id ? names.get(ev.track_id) : null;
        const text = [ev.type.toUpperCase(), ev.shot, who, ev.call && `${ev.call} ${Math.round((ev.call_prob ?? 0) * 100)}%`]
          .filter(Boolean).join(" · ");
        ctx.font = `700 ${30 * s}px system-ui, sans-serif`;
        const tw = ctx.measureText(text).width;
        ctx.fillStyle = ev.type === "landing" ? "rgba(250,204,21,0.92)" : "rgba(34,197,94,0.92)";
        ctx.fillRect(24 * s, 24 * s, tw + 32 * s, 48 * s);
        ctx.fillStyle = "#0b1220";
        ctx.fillText(text, 40 * s, 58 * s);
        if (ev.px) {
          ctx.beginPath();
          ctx.arc(ev.px[0], ev.px[1], 26 * s, 0, Math.PI * 2);
          ctx.strokeStyle = "#facc15";
          ctx.lineWidth = 4 * s;
          ctx.stroke();
        }
      }
      ctx.font = `${22 * s}px ui-monospace, monospace`;
      ctx.fillStyle = "rgba(255,255,255,0.75)";
      ctx.fillText(`${fmtTime(t)} / ${fmtTime(duration)}`, 24 * s, H - 24 * s);
      return frame;
    },
    [W, H, mode, c2p, lines, courtSize, frameIndex, tracks, colors, names, match.events, duration, showIgnored],
  );

  // Render loop: synthetic clock, or the <video> clock.
  useEffect(() => {
    let raf = 0;
    let last = performance.now();
    let lastEmit = 0;
    const tick = (now: number) => {
      const v = videoRef.current;
      if (mode === "synthetic") {
        if (playingRef.current) {
          tRef.current = Math.min(duration, tRef.current + ((now - last) / 1000) * speedRef.current);
          if (tRef.current >= duration) setPlaying(false);
        }
      } else if (v) {
        tRef.current = v.currentTime;
      }
      last = now;
      const frame = draw(tRef.current) ?? null;
      if (now - lastEmit > 66) {
        lastEmit = now;
        setShown(tRef.current);
        onTimeRef.current?.(tRef.current, frame);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [mode, draw, duration]);

  useEffect(() => {
    if (!seek) return;
    tRef.current = Math.max(0, Math.min(duration, seek.t));
    if (mode === "video" && videoRef.current) videoRef.current.currentTime = tRef.current;
  }, [seek, mode, duration]);

  useEffect(() => {
    if (videoRef.current) videoRef.current.playbackRate = speed;
  }, [speed]);

  const togglePlay = () => {
    const v = videoRef.current;
    if (mode === "video" && v) {
      if (v.paused) void v.play();
      else v.pause();
    } else {
      if (tRef.current >= duration) tRef.current = 0;
      setPlaying((p) => !p);
    }
  };

  const scrub = (t: number) => {
    tRef.current = t;
    if (mode === "video" && videoRef.current) videoRef.current.currentTime = t;
  };

  return (
    <div className="card overflow-hidden">
      <div className="relative w-full bg-black" style={{ aspectRatio: `${W} / ${H}` }}>
        {mode === "video" && src && (
          <video ref={videoRef} src={src} className="absolute inset-0 h-full w-full" playsInline muted
            onError={() => setMode("synthetic")} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} />
        )}
        <canvas ref={canvasRef} width={W} height={H} className="absolute inset-0 h-full w-full" onClick={togglePlay} />
      </div>
      <div className="flex flex-wrap items-center gap-3 border-t border-border px-3 py-2">
        <button onClick={togglePlay} className="btn-primary w-20 py-1.5">{playing ? "❚❚ Pause" : "▶ Play"}</button>
        <input type="range" min={0} max={duration} step={0.05} value={shown} onChange={(e) => scrub(parseFloat(e.target.value))}
          className="min-w-[120px] flex-1 accent-[rgb(var(--accent))]" aria-label="Seek" />
        <span className="font-mono text-xs tabular-nums text-muted">{fmtTime(shown)} / {fmtTime(duration)}</span>
        {tracks?.frames.some((f) => f.others?.length) && (
          <label className="flex items-center gap-1.5 text-xs text-muted">
            <input type="checkbox" checked={showIgnored} onChange={(e) => setShowIgnored(e.target.checked)} />
            show ignored people
          </label>
        )}
        <select value={speed} onChange={(e) => setSpeed(parseFloat(e.target.value))} className="input py-1 text-xs" aria-label="Playback speed">
          {[0.25, 0.5, 1, 2].map((v) => <option key={v} value={v}>{v}×</option>)}
        </select>
      </div>
      {mode === "synthetic" && (
        <div className="border-t border-border bg-amber-500/10 px-3 py-1.5 text-xs text-amber-700 dark:text-amber-300">
          No source video on the server, so this draws <code>tracks.json</code> on a synthetic {c2p ? "court" : "canvas (no court calibration)"}
          {tracks && loopS < duration - 0.5 ? ` (the tracks loop every ${loopS.toFixed(0)} s)` : ""}. Hollow shuttle dots are interpolated frames.
        </div>
      )}
    </div>
  );
}
