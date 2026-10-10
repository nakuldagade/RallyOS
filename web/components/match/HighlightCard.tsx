"use client";

// The best shot of the whole match as an ~8 s clip, on the match page.
import { mediaUrl } from "@/lib/api";
import { fmtTime } from "@/lib/format";
import { sportLabel } from "@/lib/sports";
import type { MatchJSON } from "@/lib/types";
import { Badge, Card } from "@/components/ui";

export const OUTCOME_LABEL: Record<string, string> = {
  winner: "won the point", forced_error: "forced an error", kept_going: "kept the rally going", unknown: "outcome not seen", error: "lost the point",
};

export default function HighlightCard({ match, onWatchFull }: { match: MatchJSON; onWatchFull: (t: number) => void }) {
  const h = match.highlight;
  if (!h) return null;
  const who = match.players.find((p) => p.track_id === h.track_id)?.name ?? `Player ${h.track_id}`;
  const src = mediaUrl(h.clip_url);
  return (
    <Card title="Highlight: the best shot of the match"
      actions={<button className="btn-ghost py-1 text-xs" onClick={() => onWatchFull(h.t)}>See it in the full replay ({fmtTime(h.t)}) →</button>}>
      <div className="grid items-start gap-4 md:grid-cols-[minmax(0,1.4fr)_1fr]">
        {src ? <video src={src} controls loop muted playsInline preload="metadata" className="w-full rounded-lg bg-black" /> : <p className="text-sm text-muted">The clip file is not available.</p>}
        <div className="space-y-2 text-sm">
          <div className="text-lg font-semibold capitalize">{who}: {h.shot ?? "shot"}</div>
          <div className="flex flex-wrap gap-2">
            <Badge tone={h.outcome === "winner" || h.outcome === "forced_error" ? "green" : h.outcome === "error" ? "red" : "neutral"}>{OUTCOME_LABEL[h.outcome] ?? h.outcome}</Badge>
            <Badge tone="blue" title="Outcome sets the band (won 80-100 ... lost 0-20); technique places the shot inside it">{h.score}/100</Badge>
            <Badge>{h.duration_s} s · {sportLabel(match.sport)}</Badge>
          </div>
          <p className="text-muted">{h.why}</p>
          {h.basis !== "outcome" && <p className="text-xs text-amber-500">No point-ending shot was seen in this match, so this is the best technique, not a point-winner.</p>}
          <p className="text-xs text-muted">Chosen by rules, not a trained model: what the shot achieved first, then placement, how far it moved the opponent, power and recovery. The clip has no sound.</p>
        </div>
      </div>
    </Card>
  );
}
