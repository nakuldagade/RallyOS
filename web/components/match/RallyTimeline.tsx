"use client";

// Rally timeline: rally segments, hit onsets (height = confidence), landings, playhead. Click to seek.
import { fmtTime, pct } from "@/lib/format";
import type { MatchEvent, PlayerRef, Rally } from "@/lib/types";

interface Props {
  duration: number;
  rallies: Rally[];
  events: MatchEvent[];
  players: PlayerRef[];
  time: number;
  onSeek: (t: number) => void;
}

export default function RallyTimeline({ duration, rallies, events, players, time, onSeek }: Props) {
  const color = (tid?: number | null) => players.find((p) => p.track_id === tid)?.color ?? "#94a3b8";
  const name = (tid?: number | null) => players.find((p) => p.track_id === tid)?.name ?? "—";
  const x = (t: number) => (t / duration) * 1000;

  const click = (e: React.MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    onSeek(((e.clientX - r.left) / r.width) * duration);
  };

  return (
    <div>
      <svg viewBox="0 0 1000 90" preserveAspectRatio="none" className="h-24 w-full cursor-pointer select-none" onClick={click}
        role="img" aria-label="Rally timeline">
        <rect x={0} y={0} width={1000} height={90} fill="rgb(var(--fg) / 0.04)" />
        {rallies.map((r) => (
          <rect key={r.idx} x={x(r.t_start)} y={52} width={Math.max(2, x(r.t_end) - x(r.t_start))} height={14} rx={2}
            fill={color(r.winner_track_id)} opacity={0.75}>
            <title>{`Rally ${r.idx + 1}: ${r.hits} hits, won by ${name(r.winner_track_id)}`}</title>
          </rect>
        ))}
        {events.filter((e) => e.type === "hit").map((e) => (
          <rect key={e.id} x={x(e.t) - 1} y={48 - 40 * e.confidence} width={2.2} height={40 * e.confidence} fill="#22c55e" opacity={0.9}>
            <title>{`${fmtTime(e.t)} hit · ${e.shot ?? ""} · ${name(e.track_id)} · conf ${pct(e.confidence)}`}</title>
          </rect>
        ))}
        {events.filter((e) => e.type !== "hit").map((e) => (
          <circle key={e.id} cx={x(e.t)} cy={78} r={4} fill={e.call === "OUT" ? "#f43f5e" : "#facc15"}>
            <title>{`${fmtTime(e.t)} ${e.type} ${e.call ?? ""} ${e.call_prob ? pct(e.call_prob) : ""}`}</title>
          </circle>
        ))}
        <line x1={x(time)} x2={x(time)} y1={0} y2={90} stroke="rgb(var(--fg))" strokeWidth={2} vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="mt-1 flex justify-between text-[11px] text-muted">
        <span>0:00</span>
        <span>green bars = hit onsets (audio + vision, height = confidence) · yellow = landings</span>
        <span>{fmtTime(duration)}</span>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {rallies.map((r) => (
          <button key={r.idx} onClick={() => onSeek(r.t_start)}
            className={`rounded-lg border px-2.5 py-1.5 text-left text-xs transition hover:bg-fg/5 ${
              time >= r.t_start && time <= r.t_end ? "border-accent" : "border-border"}`}>
            <div className="font-medium">Rally {r.idx + 1} · {r.hits} hits</div>
            <div className="text-muted">
              {fmtTime(r.t_start)}–{fmtTime(r.t_end)} · <span style={{ color: color(r.winner_track_id) }}>{name(r.winner_track_id)}</span>
              {" "}({pct(r.confidence)}) {r.score_after && `· ${r.score_after}`}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
