"use client";

// 4-tap court calibration: grab a frame from the chosen video in the browser and let the user click the
// 4 outer court corners. Returns taps in source-video pixels (near-left, near-right, far-right, far-left).
import { useEffect, useRef, useState } from "react";

const ORDER = ["near-left", "near-right", "far-right", "far-left"] as const;
const COLORS = ["#22c55e", "#3b82f6", "#f59e0b", "#ef4444"];

interface Props {
  file: File;
  onChange: (taps: [number, number][] | null) => void;
}

export default function CourtTapper({ file, onChange }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const [frame, setFrame] = useState<ImageBitmap | HTMLCanvasElement | null>(null);
  const [taps, setTaps] = useState<[number, number][]>([]);
  const [error, setError] = useState<string | null>(null);

  // Decode one frame (~1 s in) from the local file.
  useEffect(() => {
    setTaps([]);
    setFrame(null);
    setError(null);
    onChange(null);
    const url = URL.createObjectURL(file);
    const v = document.createElement("video");
    v.muted = true;
    v.preload = "auto";
    v.src = url;
    const fail = () => setError("Your browser can't preview this video format (e.g. HEVC/.mov). You can still analyse it without calibration.");
    v.onerror = fail;
    v.onloadedmetadata = () => {
      v.currentTime = Math.min(1, (v.duration || 2) / 2);
    };
    v.onseeked = () => {
      const c = document.createElement("canvas");
      c.width = v.videoWidth;
      c.height = v.videoHeight;
      const ctx = c.getContext("2d");
      if (!ctx || !c.width) return fail();
      ctx.drawImage(v, 0, 0);
      setSize({ w: c.width, h: c.height });
      setFrame(c);
    };
    return () => URL.revokeObjectURL(url);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file]);

  // Draw frame + taps + court outline.
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
      ctx.strokeStyle = "#facc15";
      ctx.lineWidth = 3 * s;
      ctx.stroke();
      if (taps.length === 4) {
        ctx.fillStyle = "rgba(250,204,21,0.15)";
        ctx.fill();
      }
    }
    taps.forEach(([x, y], i) => {
      ctx.beginPath();
      ctx.arc(x, y, 9 * s, 0, Math.PI * 2);
      ctx.fillStyle = COLORS[i];
      ctx.fill();
      ctx.strokeStyle = "white";
      ctx.lineWidth = 2 * s;
      ctx.stroke();
      ctx.font = `600 ${18 * s}px system-ui`;
      ctx.fillStyle = "white";
      ctx.fillText(ORDER[i], x + 12 * s, y - 10 * s);
    });
  }, [frame, size, taps]);

  const click = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!size || taps.length >= 4) return;
    const r = e.currentTarget.getBoundingClientRect();
    const pt: [number, number] = [
      Math.round(((e.clientX - r.left) / r.width) * size.w),
      Math.round(((e.clientY - r.top) / r.height) * size.h),
    ];
    const next = [...taps, pt];
    setTaps(next);
    onChange(next.length === 4 ? next : null);
  };

  const reset = () => {
    setTaps([]);
    onChange(null);
  };

  if (error) return <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-700 dark:text-amber-300">{error}</div>;
  if (!frame) return <div className="animate-pulse py-8 text-center text-sm text-muted">Reading a frame from the video…</div>;

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
        {taps.length < 4 ? (
          <span>
            Click the <b style={{ color: COLORS[taps.length] }}>{ORDER[taps.length]}</b> corner of the court
            <span className="text-muted"> ({taps.length}/4, outer doubles lines, &quot;near&quot; = closest to the camera)</span>
          </span>
        ) : (
          <span className="text-emerald-500">✓ Court calibrated with 4 taps</span>
        )}
        {taps.length > 0 && <button type="button" className="btn-ghost ml-auto py-1 text-xs" onClick={reset}>Reset taps</button>}
      </div>
      <canvas ref={canvasRef} onClick={click} className={`w-full rounded-lg ${taps.length < 4 ? "cursor-crosshair" : ""}`} />
    </div>
  );
}
