"use client";

// Live dashboard: top-down court with the players, a running score suggestion, hit / rally counters, the processing lag,
// the calibration quality, the chunk strip and the latest events. Everything computed during the match is provisional
// and says so; "finalised" replaces it with the full-match result.
import { fmtTime, num, pct } from "@/lib/format";
import { lagTone, type ChunkRow, type LiveState } from "@/lib/live";
import { sportLabel } from "@/lib/sports";
import type { SportConfig } from "@/lib/types";
import { Badge, Card } from "@/components/ui";
import MiniCourt, { type CourtDot } from "@/components/court/MiniCourt";

const COLORS = ["#3b82f6", "#ef4444"];
const CHUNK_ICON: Record<ChunkRow["state"], string> = {
  recording: "●", buffered: "◌", uploading: "↑", received: "…", processed: "✓", failed: "!",
};
const CHUNK_TONE: Record<ChunkRow["state"], string> = {
  recording: "bg-rose-500/20 text-rose-600 dark:text-rose-400 animate-pulse",
  buffered: "bg-amber-500/20 text-amber-700 dark:text-amber-400",
  uploading: "bg-sky-500/20 text-sky-700 dark:text-sky-400 animate-pulse",
  received: "bg-amber-500/15 text-amber-700 dark:text-amber-400",
  processed: "bg-emerald-500/20 text-emerald-600 dark:text-emerald-400",
  failed: "bg-rose-500/30 text-rose-700 dark:text-rose-300",
};

export function Provisional() {
  return <Badge tone="amber" title="Computed while the match is still being played; recomputed over the whole match when it ends">provisional</Badge>;
}

export function LagBadge({ lag }: { lag: LiveState["lag"] }) {
  if (!lag) return <Badge>lag: waiting</Badge>;
  const tone = lagTone(lag.lag_s);
  return (
    <Badge tone={tone} title={`How far behind the camera the results are. Average ${num(lag.avg_latency_s, 1)} s, worst ${num(lag.max_lag_s, 1)} s. Target: under 10 s.`}>
      lag {num(lag.lag_s, 1)} s{tone === "green" ? "" : " · falling behind"}
    </Badge>
  );
}

export function CalibrationBadge({ cal }: { cal: LiveState["calibration"] }) {
  if (!cal) return <Badge>court: looking…</Badge>;
  if (cal.quality === "high") return <Badge tone="green" title={cal.note ?? undefined}>court found{cal.sport ? ` · ${sportLabel(cal.sport)}` : ""}{cal.precision ? ` · fit ${pct(cal.precision)}` : ""}</Badge>;
  if (cal.quality === "check") return <Badge tone="amber" title={cal.note ?? "Part of the court may be hidden: check the corners"}>court: check the corners</Badge>;
  return <Badge tone="red" title={cal.note ?? undefined}>no court: positions, calls and score unavailable</Badge>;
}

export function ChunkStrip({ chunks, seconds }: { chunks: ChunkRow[]; seconds: number }) {
  if (!chunks.length) return <p className="text-sm text-muted">No chunks yet. A chunk is cut every {seconds} s automatically.</p>;
  return (
    <div>
      <div className="flex flex-wrap gap-1.5">
        {chunks.slice(-24).map((c) => (
          <div key={c.seq} className={`grid h-9 w-9 place-items-center rounded-md text-sm font-medium ${CHUNK_TONE[c.state]}`}
            title={`chunk ${c.seq}: ${fmtTime(c.t0)}–${fmtTime(c.t1)} · ${c.state}${c.process_s != null ? ` · ${num(c.process_s, 1)} s to analyse` : ""}${c.reduced_quality ? " · reduced quality" : ""}`}>
            {CHUNK_ICON[c.state]}
          </div>
        ))}
      </div>
      <p className="mt-1.5 text-[11px] text-muted">● recording · ◌ buffered (offline) · ↑ uploading · … waiting to be analysed · ✓ analysed · ! failed. Hover a chunk for its timing.</p>
    </div>
  );
}

export default function LiveDashboard({ live, sport }: { live: LiveState; sport: SportConfig }) {
  const names = new Map(live.players.map((p) => [p.track_id, p]));
  const dots: CourtDot[] = [];
  for (const p of live.position?.players ?? []) {
    if (!p.court) continue;
    const meta = names.get(p.track_id);
    dots.push({ x: p.court[0], y: p.court[1], color: meta?.color ?? COLORS[(p.track_id - 1) % 2], label: meta?.name ?? `P${p.track_id}` });
  }
  for (const e of live.events.slice(-12)) {
    if (!e.court) continue;
    if (e.type === "landing") dots.push({ x: e.court[0], y: e.court[1], color: e.call === "OUT" ? "#f43f5e" : e.call === "IN" ? "#22c55e" : "#f59e0b", hollow: true, title: `landing ${e.call ?? ""} at ${fmtTime(e.t)}` });
    else dots.push({ x: e.court[0], y: e.court[1], color: "#facc15", hollow: true, title: `hit at ${fmtTime(e.t)}` });
  }
  const st = live.stats;
  const closed = live.rallies.length;
  const recent = live.events.slice(-8).reverse();
  const done = live.status === "done";
  const courtFound = !!live.calibration && (live.calibration.quality === "high" || live.calibration.quality === "check");
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <CalibrationBadge cal={live.calibration} />
        <LagBadge lag={live.lag} />
        {live.status === "finalising" && <Badge tone="blue">finalising the match…</Badge>}
        {done && <Badge tone="green">match finalised</Badge>}
        {live.chunks.some((c) => c.reduced_quality) && <Badge tone="amber" title="The analysis fell behind, so some stretches were analysed with fewer frames">reduced quality in places</Badge>}
        {!done && live.status !== "idle" && <Provisional />}
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
        {courtFound ? (
          <Card title="Live court" actions={<span className="text-xs text-muted">{live.position ? `at ${fmtTime(live.position.t)}` : "waiting for the first chunk"}</span>}>
            <MiniCourt sport={sport} dots={dots} className="mx-auto h-[380px] w-full" />
            <p className="mt-2 text-xs text-muted">
              Filled dots: players now. Hollow dots: recent hits (yellow) and landings (green IN, red OUT, amber too close). The shuttle is tracked in video pixels
              {live.ballTrail.length ? ` (${live.ballTrail.length} recent positions)` : ""}; its court position needs the height, which one camera cannot measure.
            </p>
          </Card>
        ) : (
          <Card title="Finding the court">
            <p className="text-sm text-muted">
              {live.calibration ? "No court could be found in the picture yet, so there are no court positions, calls or score. Point the camera so all four corners of the court are visible, or mark the corners before recording."
                : "The live court appears here as soon as the court is detected in the first chunk."}
            </p>
          </Card>
        )}

        <div className="space-y-4">
          <Card title={<span className="flex items-center gap-2">Score suggestion {!done && <Provisional />}</span>}>
            <div className="text-3xl font-semibold tabular-nums">{st?.score?.suggested ?? st?.score?.score_str ?? "—"}</div>
            <p className="mt-1 text-xs text-muted">
              Counted from the start of the stream, only for rallies whose landing has been seen; a person confirms the score when the match ends.
            </p>
          </Card>
          <Card title="Rallies and hits">
            <div className="grid grid-cols-3 gap-2 text-center">
              <div><div className="text-2xl font-semibold tabular-nums">{st?.rallies ?? closed}</div><div className="text-xs text-muted">rallies closed</div></div>
              <div><div className="text-2xl font-semibold tabular-nums">{st?.hits ?? live.events.filter((e) => e.type === "hit").length}</div><div className="text-xs text-muted">hits</div></div>
              <div><div className="text-2xl font-semibold tabular-nums">{live.chunks.filter((c) => c.state === "processed").length}</div><div className="text-xs text-muted">chunks analysed</div></div>
            </div>
            {st?.per_player && Object.keys(st.per_player).length > 0 && (
              <ul className="mt-3 space-y-1 border-t border-border pt-2 text-xs">
                {Object.entries(st.per_player).map(([tid, v]) => (
                  <li key={tid} className="flex justify-between">
                    <span className="text-muted">{names.get(Number(tid))?.name ?? `Player ${tid}`}</span>
                    <span className="tabular-nums">{v.distance_m != null ? `${num(Number(v.distance_m), 0)} m covered` : "—"}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>

      <Card title="Chunks"><ChunkStrip chunks={live.chunks} seconds={live.chunkSeconds} /></Card>

      <Card title="Latest events" actions={!done ? <Provisional /> : undefined}>
        {recent.length === 0 ? <p className="text-sm text-muted">Nothing yet.</p> : (
          <ul className="divide-y divide-border text-sm">
            {recent.map((e) => (
              <li key={e.id} className="flex items-center gap-3 py-1.5">
                <span className="w-14 font-mono tabular-nums text-muted">{fmtTime(e.t)}</span>
                <span className="w-16">{e.type}</span>
                <span className="flex-1">
                  {e.type === "landing" ? (e.call ? `${e.call} (${pct(e.call_prob ?? 0)})` : e.note ? "no call" : "—") : (names.get(e.track_id ?? -1)?.name ?? (e.track_id ? `Player ${e.track_id}` : "unattributed"))}
                  {e.shot ? <span className="ml-2 text-muted">{e.shot}</span> : null}
                </span>
                <span className="text-xs tabular-nums text-muted">{pct(e.confidence)}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
