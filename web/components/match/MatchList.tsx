import Link from "next/link";
import { fmtTime } from "@/lib/format";
import { sportLabel } from "@/lib/sports";
import type { MatchSummary } from "@/lib/types";
import { Badge } from "@/components/ui";

export default function MatchList({ matches }: { matches: MatchSummary[] }) {
  if (!matches.length) return <div className="text-sm text-muted">No matches yet. Upload one, or run <code>python -m api.seed</code>.</div>;
  return (
    <div className="divide-y divide-border">
      {matches.map((m) => (
        <Link key={m.match_id} href={`/matches/${m.match_id}`} className="flex flex-wrap items-center gap-3 py-3 transition hover:bg-fg/5">
          <div className="min-w-0 flex-1">
            <div className="font-medium">{m.title || m.players.join(" vs ") || m.match_id}</div>
            <div className="text-xs text-muted">
              {sportLabel(m.sport)} · {m.rallies} rallies analysed{m.duration_s ? ` · ${fmtTime(m.duration_s)}` : ""} · {m.match_id}
            </div>
          </div>
          <div className="font-mono text-sm tabular-nums">{m.games.length ? m.games.map((g) => g.join("–")).join("  ") : <span className="text-muted">no score</span>}</div>
          {m.ball_tracker === "racketvision" && <Badge tone="blue" title="Shuttle track from the pretrained RacketVision plug-in">RacketVision ball</Badge>}
          {m.evidence_level === "video_verified" ? <Badge tone="green">video verified</Badge> : <Badge tone="amber">{m.evidence_level}</Badge>}
        </Link>
      ))}
    </div>
  );
}
