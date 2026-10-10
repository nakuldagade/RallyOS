// How each rally ended: landing -> call -> suggested winner, or why no call was made.
import Link from "next/link";
import { fmtTime, pct } from "@/lib/format";
import type { MatchJSON } from "@/lib/types";
import { Badge } from "@/components/ui";

const REASON: Record<string, string> = {
  landing_in: "Landed IN",
  landing_out: "Landed OUT",
  too_close: "Too close to call",
  net_fault: "Didn't cross the net",
  clip_ended: "Clip ended before the landing",
  landing_implausible: "Shuttle lost in the air (no landing seen)",
  landing_hidden_by_net: "Shuttle lost against the net",
  landing_uncalibrated: "Landing seen, but no court calibration",
  shuttle_lost: "Shuttle not tracked after the last hit",
};

export default function RallyOutcomes({ match, onSeek }: { match: MatchJSON; onSeek: (t: number) => void }) {
  const name = (tid?: number | null) => match.players.find((p) => p.track_id === tid)?.name ?? `Player ${tid}`;
  if (!match.rallies.length) return <p className="text-sm text-muted">No rallies found.</p>;
  return (
    <div className="space-y-2">
      {match.rallies.map((r) => {
        const land = match.events.find((e) => e.type === "landing" && e.rally_idx === r.idx);
        const reason = r.end_reason ?? "";
        const called = r.winner_track_id != null;
        return (
          <div key={r.idx} className="rounded-lg border border-border p-2.5 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <button className="font-medium hover:text-accent" onClick={() => onSeek(land?.t ?? r.t_start)}>
                Rally {r.idx + 1} · {fmtTime(r.t_start)}–{fmtTime(r.t_end)} · {r.hits} hits
              </button>
              {r.score_after && <span className="font-mono tabular-nums">{r.score_after}</span>}
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
              <Badge tone={reason === "landing_in" ? "green" : reason === "landing_out" ? "red" : called ? "amber" : "neutral"}>
                {REASON[reason] ?? (reason || "unknown")}
              </Badge>
              {land?.call && <Badge tone="blue" title="Probability from the uncertainty ellipse">{land.call} {pct(land.call_prob ?? 0)}</Badge>}
              {called && <Badge title="Suggested from where it landed and the call; confirm the score to make it count">winner: {name(r.winner_track_id)} ({pct(r.winner_confidence ?? 0)})</Badge>}
              {r.hitter_conflict && <Badge tone="amber" title="The last detected hitter is on the landing side: a final hit was probably missed">hitter conflict</Badge>}
              {land?.dispute_id && <Link href={`/disputes/${land.dispute_id}`} className="text-xs text-accent">Fair-Play Replay →</Link>}
            </div>
            {!called && land?.note && <p className="mt-1 text-xs text-muted">No call: {land.note}.</p>}
          </div>
        );
      })}
    </div>
  );
}
