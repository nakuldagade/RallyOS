"use client";

// The matches as a summary strip plus a filterable grid of cards.
import Link from "next/link";
import { useMemo, useState } from "react";
import { sportLabel } from "@/lib/sports";
import type { MatchSummary } from "@/lib/types";

const SPORT_COLOR: Record<string, string> = {
  badminton: "bg-emerald-500", tennis: "bg-lime-500", table_tennis: "bg-sky-500",
  pickleball: "bg-amber-500", padel: "bg-violet-500", squash: "bg-rose-500",
};

function length(s?: number | null) {
  if (!s) return "—";
  const m = Math.floor(s / 60), r = Math.round(s % 60);
  return m ? `${m} min ${r} s` : `${r} s`;
}

function Card({ m }: { m: MatchSummary }) {
  const unassigned = m.players.length === 0 || m.players.some((p) => /^(near|far) player$/i.test(p));
  const title = m.title || (m.players.length ? m.players.join(" vs ") : "Untitled match");
  const games = m.games.filter((g) => g.some((x) => x > 0));
  const verified = m.evidence_level === "video_verified";
  return (
    <article className="card group flex flex-col overflow-hidden transition hover:-translate-y-0.5 hover:border-accent/60 hover:shadow-md">
      <div className={`h-1 ${SPORT_COLOR[m.sport] ?? "bg-accent"}`} />
      <div className="flex flex-1 flex-col gap-4 p-4">
        <div className="flex items-center justify-between gap-2 text-xs">
          <span className="font-medium uppercase tracking-wide text-muted">{sportLabel(m.sport)}{m.synthetic && <span className="ml-2 rounded bg-amber-500/15 px-1.5 py-0.5 normal-case tracking-normal text-amber-600 dark:text-amber-400" title="A simulated match, not real video">Sample data</span>}</span>
          <span className={verified ? "text-emerald-500" : "text-muted"} title={verified ? "Video verified" : "Analysed from video; scores are suggestions until a person confirms them"}>
            {verified ? "● Verified" : "○ Analysed"}
          </span>
        </div>

        <Link href={`/matches/${m.match_id}`} className="block min-w-0">
          <h3 className="truncate text-lg font-semibold leading-tight group-hover:text-accent" title={title}>{title}</h3>
          <p className="mt-1 text-xs text-muted">
            {unassigned ? <span className="text-amber-500">Players not assigned</span> : "Players assigned"} · <span className="font-mono">{m.match_id}</span>
          </p>
        </Link>

        <div className="rounded-lg bg-fg/5 px-3 py-2.5">
          {games.length ? (
            <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 font-mono text-base font-semibold tabular-nums">
              {games.map((g, i) => <span key={i}>{g.join(" – ")}</span>)}
            </div>
          ) : <div className="text-sm text-muted">Score not available for this clip</div>}
        </div>

        <dl className="grid grid-cols-3 gap-2 text-sm">
          <div><dt className="text-xs text-muted">Rallies</dt><dd className="font-semibold tabular-nums">{m.rallies}</dd></div>
          <div><dt className="text-xs text-muted">Length</dt><dd className="font-semibold tabular-nums">{length(m.duration_s)}</dd></div>
          <div><dt className="text-xs text-muted">Tracker</dt><dd className="font-semibold">{m.ball_tracker === "racketvision" ? "RacketVision" : "Geometric"}</dd></div>
        </dl>

        <div className="mt-auto flex gap-2">
          <Link href={`/matches/${m.match_id}`} className="btn-primary flex-1">Open match</Link>
          <Link href={`/matches/${m.match_id}#smart-court`} className="btn-ghost" title="3D Smart Court: shot paths, moving players, heatmaps">3D</Link>
          <Link href={`/matches/${m.match_id}/report`} className="btn-ghost" title="Evidence-linked coach report">Report</Link>
        </div>
      </div>
    </article>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="card px-4 py-3">
      <div className="label">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
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
  const minutes = matches.reduce((t, m) => t + (m.duration_s ?? 0), 0) / 60;
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Matches analysed" value={String(matches.length)} />
        <Kpi label="Rallies" value={String(matches.reduce((t, m) => t + m.rallies, 0))} />
        <Kpi label="Video analysed" value={`${minutes.toFixed(1)} min`} />
        <Kpi label="Sports" value={String(sports.length)} />
      </div>

      <div className="flex flex-wrap items-center gap-2">
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
      ) : <div className="card p-8 text-center text-sm text-muted">No match fits these filters.</div>}
    </div>
  );
}
