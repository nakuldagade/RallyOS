import Link from "next/link";
import { fmtTime } from "@/lib/format";
import type { Insight, MatchJSON } from "@/lib/types";
import { Badge } from "@/components/ui";

function resolve(stats: unknown, id: string): unknown {
  return id.split(".").reduce<unknown>((cur, k) => (cur && typeof cur === "object" ? (cur as Record<string, unknown>)[k] : undefined), stats);
}

export default function InsightCard({ insight, match }: { insight: Insight; match?: MatchJSON }) {
  const player = match?.players.find((p) => p.track_id === insight.player_track_id);
  return (
    <div className="card p-4">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        {player && (
          <span className="flex items-center gap-1.5 text-xs font-medium">
            <span className="h-2 w-2 rounded-full" style={{ background: player.color ?? "#94a3b8" }} /> {player.name}
          </span>
        )}
        {insight.grounded !== false && <Badge tone="green" title="Every number is checked against the stats JSON">grounded</Badge>}
      </div>
      <p className="text-sm leading-relaxed">{insight.text}</p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {insight.stat_ids.map((s) => {
          const v = match ? resolve(match.stats, s) : undefined;
          return (
            <code key={s} className="rounded bg-fg/5 px-1.5 py-0.5 text-[11px] text-muted" title="Cited stat">
              {s}{v !== undefined && typeof v !== "object" ? ` = ${String(v)}` : ""}
            </code>
          );
        })}
      </div>
      {match && insight.clip_t.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {insight.clip_t.map((t) => (
            <Link key={t} href={`/matches/${match.match_id}?t=${t}`} className="btn-ghost py-1 text-xs">▶ Watch {fmtTime(t)}</Link>
          ))}
        </div>
      )}
    </div>
  );
}
