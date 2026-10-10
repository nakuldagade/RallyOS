"use client";

// The matches as a filterable grid of cards: sport, players, score, verification, length and quick actions.
import Link from "next/link";
import { useMemo, useState } from "react";
import { fmtTime } from "@/lib/format";
import { sportLabel } from "@/lib/sports";
import type { MatchSummary } from "@/lib/types";
import { Badge } from "@/components/ui";

function Card({ m }: { m: MatchSummary }) {
  const title = m.title || m.players.join(" vs ") || m.match_id;
  const verified = m.evidence_level === "video_verified";
  return (
    <div className="card flex flex-col gap-3 p-4 transition hover:border-accent/60">
      <div className="flex items-start justify-between gap-2">
        <Badge tone="blue">{sportLabel(m.sport)}</Badge>
        {verified ? <Badge tone="green">video verified</Badge> : <Badge tone="amber">{m.evidence_level.replace(/_/g, " ")}</Badge>}
      </div>
      <Link href={`/matches/${m.match_id}`} className="min-w-0">
        <div className="truncate text-base font-semibold leading-snug" title={title}>{title}</div>
        <div className="mt-0.5 truncate text-xs text-muted">{m.match_id}</div>
      </Link>
      <div className="font-mono text-lg tabular-nums">
        {m.games.length ? m.games.map((g) => g.join("–")).join("   ") : <span className="text-sm text-muted">no score yet</span>}
      </div>
      <dl className="grid grid-cols-3 gap-2 border-t border-border pt-3 text-xs">
        <div><dt className="text-muted">Rallies</dt><dd className="font-medium tabular-nums">{m.rallies}</dd></div>
        <div><dt className="text-muted">Length</dt><dd className="font-medium tabular-nums">{m.duration_s ? fmtTime(m.duration_s) : "—"}</dd></div>
        <div><dt className="text-muted">Ball</dt><dd className="font-medium">{m.ball_tracker === "racketvision" ? "RacketVision" : "geometric"}</dd></div>
      </dl>
      <div className="mt-auto flex gap-2">
        <Link href={`/matches/${m.match_id}`} className="btn-primary flex-1 py-1.5 text-center text-xs">Open match</Link>
        <Link href={`/matches/${m.match_id}#smart-court`} className="btn-ghost py-1.5 text-xs" title="3D Smart Court: shot paths, moving players, heatmaps">3D court</Link>
        <Link href={`/matches/${m.match_id}/report`} className="btn-ghost py-1.5 text-xs">Report</Link>
      </div>
    </div>
  );
}

export default function MatchList({ matches }: { matches: MatchSummary[] }) {
  const [q, setQ] = useState("");
  const [sport, setSport] = useState("");
  const [sort, setSort] = useState<"recent" | "rallies" | "length">("recent");
  const sports = useMemo(() => [...new Set(matches.map((m) => m.sport))], [matches]);
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const rows = matches.filter((m) => (!sport || m.sport === sport) &&
      (!needle || `${m.title ?? ""} ${m.players.join(" ")} ${m.match_id}`.toLowerCase().includes(needle)));
    if (sort === "rallies") return [...rows].sort((a, b) => b.rallies - a.rallies);
    if (sort === "length") return [...rows].sort((a, b) => (b.duration_s ?? 0) - (a.duration_s ?? 0));
    return rows;
  }, [matches, q, sport, sort]);

  if (!matches.length) return <div className="text-sm text-muted">No matches yet. Upload one, or run <code>python -m api.seed</code>.</div>;
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <input className="input min-w-48 flex-1" placeholder="Search by player, title or id…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select className="input w-auto" value={sport} onChange={(e) => setSport(e.target.value)} aria-label="Sport">
          <option value="">All sports</option>
          {sports.map((s) => <option key={s} value={s}>{sportLabel(s)}</option>)}
        </select>
        <select className="input w-auto" value={sort} onChange={(e) => setSort(e.target.value as typeof sort)} aria-label="Sort">
          <option value="recent">Newest first</option>
          <option value="rallies">Most rallies</option>
          <option value="length">Longest</option>
        </select>
        <span className="text-xs text-muted">{shown.length} of {matches.length}</span>
      </div>
      {shown.length ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{shown.map((m) => <Card key={m.match_id} m={m} />)}</div>
      ) : <div className="text-sm text-muted">No match fits these filters.</div>}
    </div>
  );
}
