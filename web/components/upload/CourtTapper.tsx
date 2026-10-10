"use client";

// Court calibration on one video frame. The court is found automatically (Court Fingerprint: line detection +
// sport templates, no training); the 4 corners can be dragged if any is off, or tapped by hand when nothing is
// found. Returns corners in source-video pixels (near-left, near-right, far-right, far-left).
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { sportLabel } from "@/lib/sports";
import type { CourtDetection } from "@/lib/types";
import { Badge } from "@/components/ui";

const ORDER = ["near-left", "near-right", "far-right", "far-left"] as const;
const COLORS = ["#22c55e", "#3b82f6", "#f59e0b", "#ef4444"];

type Pt = [number, number];

interface Props {
  file?: File | null;       // a local file chosen for upload...
  src?: string | null;      // ...or the stored video of an existing match
  sport?: string;           // "auto" tries every sport; otherwise only this sport's template
  onChange: (taps: Pt[] | null) => void;
  onDetected?: (d: CourtDetection | null) => void;   // lets the page use the detected sport
}

export default function CourtTapper({ file, src, sport = "auto", onChange, onDetected }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const [frame, setFrame] = useState<HTMLCanvasElement | null>(null);
  const [taps, setTaps] = useState<Pt[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [detecting, setDetecting] = useState(false);
  const [det, setDet] = useState<CourtDetection | null>(null);
  const [drag, setDrag] = useState<number | null>(null);
  const runId = useRef(0);

  // Decode one frame (~1 s in) from the local file or the stored video.
  useEffect(() => {
    setTaps([]);
    setFrame(null);
    setError(null);
    setDet(null);
    onChange(null);
    onDetected?.(null);
    if (!file && !src) return;
    // React (dev) mounts effects twice: the first run is cleaned up while its video is still loading.
    // A cancelled run must stay silent, otherwise its error event shows "can't preview" on the first upload.
    let cancelled = false;
    const url = file ? URL.createObjectURL(file) : src!;
    const v = document.createElement("video");
    v.muted = true;
    v.preload = "auto";
    v.playsInline = true;
    const fail = () => {
      if (!cancelled) setError("Your browser can't preview this video format (e.g. HEVC/.mov). The court is then searched for automatically while analysing.");
    };
    v.onerror = fail;
    v.onloadedmetadata = () => {
      if (!cancelled) v.currentTime = Math.min(1, (v.duration || 2) / 2);
    };
    v.onseeked = () => {
      if (cancelled) return;
      const c = document.createElement("canvas");
      c.width = v.videoWidth;
      c.height = v.videoHeight;
      const ctx = c.getContext("2d");
      if (!ctx || !c.width) return fail();
      ctx.drawImage(v, 0, 0);
      setSize({ w: c.width, h: c.height });
      setFrame(c);
    };
    v.src = url;
    return () => {
      cancelled = true;
      v.onerror = v.onloadedmetadata = v.onseeked = null;
      v.removeAttribute("src");
      if (file) URL.revokeObjectURL(url);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file, src]);

  const detect = useCallback(async () => {
    if (!frame) return;
    const id = ++runId.current;
    setDetecting(true);
    setDet(null);
    setTaps([]);
    onChange(null);
    onDetected?.(null);
    try {
      const blob = await new Promise<Blob | null>((res) => frame.toBlob(res, "image/jpeg", 0.9));
      if (!blob) throw new Error("could not encode the frame");
      const d = await api.detectCourt(blob, sport);
      if (id !== runId.current) return;                 // a newer run (or a reset) superseded this one
      setDet(d);
      onDetected?.(d.found ? d : null);
      if (d.found && d.corners_px && d.width && size) {
        const k = size.w / d.width;
        const pts = d.corners_px.map(([x, y]) => [Math.round(x * k), Math.round(y * k)] as Pt);
        setTaps(pts);
        onChange(pts);
      }
    } catch (e) {
      if (id === runId.current) setDet({ found: false, message: e instanceof Error ? e.message : String(e) });
    } finally {
      if (id === runId.current) setDetecting(false);
    }
  }, [frame, sport, size, onChange, onDetected]);

  // Auto-detect as soon as the frame is ready, and again when the chosen sport changes.
  useEffect(() => {
    if (frame && size) detect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [frame, sport]);

  // Draw frame + court outline + handles.
  useEffect(() => {
    const c = canvasRef.current;
    if (!c || !frame || !size) return;
    c.width = size.w;
    c.height = size.h;
    const ctx = c.getContext("2d")!;
    ctx.drawImage(frame, 0, 0);
    const s = size.w / 1280;
    if (taps.length > 1) {
      ctx.beginPath();
      taps.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
      if (taps.length === 4) ctx.closePath();
      ctx.strokeStyle = det?.quality === "check" ? "#f59e0b" : "#facc15";
      ctx.lineWidth = 3 * s;
      ctx.stroke();
      if (taps.length === 4) {
        ctx.fillStyle = "rgba(250,204,21,0.12)";
        ctx.fill();
      }
    }
    taps.forEach(([x, y], i) => {
      ctx.beginPath();
      ctx.arc(x, y, (drag === i ? 13 : 10) * s, 0, Math.PI * 2);
      ctx.fillStyle = COLORS[i];
      ctx.fill();
      ctx.strokeStyle = "white";
      ctx.lineWidth = 2 * s;
      ctx.stroke();
      ctx.font = `600 ${18 * s}px system-ui`;
      ctx.fillStyle = "white";
      ctx.fillText(ORDER[i], x + 14 * s, y - 12 * s);
    });
  }, [frame, size, taps, drag, det]);

  const toFrame = (e: React.PointerEvent<HTMLCanvasElement>): Pt => {
    const r = e.currentTarget.getBoundingClientRect();
    return [
      Math.max(0, Math.min(size!.w, Math.round(((e.clientX - r.left) / r.width) * size!.w))),
      Math.max(0, Math.min(size!.h, Math.round(((e.clientY - r.top) / r.height) * size!.h))),
    ];
  };

  const nearest = (p: Pt): number | null => {
    const reach = (size!.w / 1280) * 28;
    let best: number | null = null;
    let bd = reach;
    taps.forEach(([x, y], i) => {
      const d = Math.hypot(x - p[0], y - p[1]);
      if (d < bd) { bd = d; best = i; }
    });
    return best;
  };

  const down = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!size || detecting) return;
    const p = toFrame(e);
    const hit = taps.length ? nearest(p) : null;
    if (hit !== null) {                                  // grab a corner to move it
      e.currentTarget.setPointerCapture(e.pointerId);
      setDrag(hit);
    } else if (taps.length < 4) {                        // otherwise add the next corner by hand
      const next = [...taps, p];
      setTaps(next);
      onChange(next.length === 4 ? next : null);
    }
  };

  const move = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (drag === null || !size) return;
    const p = toFrame(e);
    setTaps((t) => t.map((q, i) => (i === drag ? p : q)));
  };

  const up = () => {
    if (drag === null) return;
    setDrag(null);
    if (taps.length === 4) onChange(taps);
  };

  const manualReset = () => {
    runId.current++;                                     // cancel any detection still running
    setDetecting(false);
    setDet(null);
    setTaps([]);
    onChange(null);
    onDetected?.(null);
  };

  if (error) return <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-700 dark:text-amber-300">{error}</div>;
  if (!frame) return <div className="animate-pulse py-8 text-center text-sm text-muted">Reading a frame from the video…</div>;

  const found = det?.found && taps.length === 4;
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
        {detecting ? (
          <span className="animate-pulse text-muted">Finding the court lines…</span>
        ) : found ? (
          det!.quality === "high" ? (
            <span className="flex flex-wrap items-center gap-2 text-emerald-600 dark:text-emerald-400">
              ✓ Court found automatically
              <Badge tone="green" title="Heuristic from how well the template's lines land on line pixels, not a probability">
                {sportLabel(det!.sport ?? "")} · fit {Math.round((det!.precision ?? 0) * 100)}%
              </Badge>
            </span>
          ) : (
            <span className="flex flex-wrap items-center gap-2 text-amber-700 dark:text-amber-300">
              Court found, but part of it may be hidden (net, banners or players): check the corners
              <Badge tone="amber">{sportLabel(det!.sport ?? "")} · fit {Math.round((det!.precision ?? 0) * 100)}%</Badge>
            </span>
          )
        ) : taps.length < 4 ? (
          <span>
            {det && !det.found ? <span className="text-amber-700 dark:text-amber-300">No court found automatically. </span> : null}
            Click the <b style={{ color: COLORS[taps.length] }}>{ORDER[taps.length]}</b> corner of the court
            <span className="text-muted"> ({taps.length}/4, outer doubles lines, &quot;near&quot; = closest to the camera)</span>
          </span>
        ) : (
          <span className="text-emerald-500">✓ Court set with 4 corners</span>
        )}
        <span className="ml-auto flex gap-2">
          <button type="button" className="btn-ghost py-1 text-xs" disabled={detecting} onClick={detect}>Auto-detect again</button>
          {(taps.length > 0 || det) && <button type="button" className="btn-ghost py-1 text-xs" onClick={manualReset}>Clear (tap by hand)</button>}
        </span>
      </div>
      {found && <p className="mb-2 text-xs text-muted">Drag any corner to adjust it. The outline should sit on the outer court lines.</p>}
      <canvas ref={canvasRef} onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up}
        className={`w-full touch-none rounded-lg ${drag !== null ? "cursor-grabbing" : taps.length < 4 ? "cursor-crosshair" : "cursor-grab"}`} />
    </div>
  );
}
