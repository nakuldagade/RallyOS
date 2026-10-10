"use client";

// A player's history and full analysis over every analysed match: the heatmap of where they stood (summed over all matches),
// how the latest match compares with the earlier ones, the trend of each metric, their best shots, and the match-by-match
// history. Everything comes from GET /v1/players/{id}/analysis; nothing is filled in here when a match could not measure it.
import Link from "next/link";
import { useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtTime } from "@/lib/format";
import { BADMINTON } from "@/lib/sports";
import type { AnalysisMatch, MetricValues, PlayerAnalysis as Analysis, SportConfig } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { Badge, Card, ErrorBox, Loading, Stat } from "@/components/ui";
import MiniCourt from "@/components/court/MiniCourt";
import PlayerChat from "@/components/player/PlayerChat";

const tooltipStyle = { background: "rgb(var(--card))", border: "1px solid rgb(var(--border))", borderRadius: 8 };
const TREND_ORDER: { key: keyof MetricValues; label: string; unit: string }[] = [
  { key: "avg_return_to_base_s", label: "Return to base", unit: "s (lower is better)" },
  { key: "split_step_pct", label: "Split-step", unit: "% of opponent shots" },
  { key: "fastest_shot_kmh", label: "Fastest shot", unit: "km/h at the racket" },
  { key: "best_shot_score", label: "Best-shot score", unit: "out of 100" },
  { key: "distance_per_min", label: "Distance covered", unit: "m per minute" },
  { key: "top_speed_mps", label: "Top movement speed", unit: "m/s" },
];
const OUTCOME: Record<string, string> = { winner: "won the point", forced_error: "forced an error", kept_going: "kept the rally going", unknown: "outcome not seen", error: "lost the point" };

function fmtDate(iso: string) {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso.slice(0, 10) : d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

function Trend({ a, k, label, unit }: { a: Analysis; k: keyof MetricValues; label: string; unit: string }) {
  const rows = (a.trends[k] ?? []).map((p) => ({ n: `#${p.i}`, v: p.value }));
  const have = rows.filter((r) => r.v != null).length;
  return (
    <div className="rounded-lg border border-border p-3">
      <div className="flex items-baseline justify-between"><span className="text-sm font-medium">{label}</span><span className="text-[11px] text-muted">{unit}</span></div>
      {have < 2 ? <p className="py-6 text-center text-xs text-muted">{have === 0 ? "not measured in these matches" : "needs a second match with this measured"}</p> : (
        <div className="h-28">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={rows} margin={{ left: -22, right: 6, top: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--border))" />
              <XAxis dataKey="n" tick={{ fill: "rgb(var(--muted))", fontSize: 10 }} />
              <YAxis tick={{ fill: "rgb(var(--muted))", fontSize: 10 }} domain={["auto", "auto"]} />
              <Tooltip contentStyle={tooltipStyle} />
              <Line type="monotone" dataKey="v" stroke="rgb(var(--accent))" strokeWidth={2} dot={{ r: 3 }} connectNulls isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

export default function PlayerAnalysis({ playerId }: { playerId: string }) {
  const { user, ready } = useAuth();
  const analysis = useApi(() => (user ? api.playerAnalysis(playerId) : Promise.reject(new Error("log in"))), [playerId, user?.id]);
  const sport = useApi(() => (analysis.data ? api.sport(analysis.data.player.sport) : Promise.resolve(undefined as SportConfig | undefined)), [analysis.data?.player.sport]);
  const [view, setView] = useState<"all" | "earlier" | "latest">("all");

  if (!ready) return <Loading />;
  if (!user) {
    return (
      <Card title="History and full analysis">
        <p className="text-sm text-muted">Log in to see a player&apos;s history and analysis: a player sees their own, a coach sees the players on their roster.</p>
        <Link href="/login" className="btn-primary mt-3 inline-block">Log in</Link>
      </Card>
    );
  }
  if (analysis.loading) return <Loading label="Building the analysis from every analysed match…" />;
  if (analysis.error || !analysis.data) {
    return <ErrorBox message={analysis.error ?? "No analysis"} onRetry={analysis.reload} />;
  }
  const a = analysis.data;
  const s = a.summary;
  const court = sport.data ?? { ...BADMINTON, court: { ...BADMINTON.court, length: a.heatmap.court.length, width: a.heatmap.court.width } };
  const grid = view === "all" ? a.heatmap.all : view === "earlier" ? a.heatmap.earlier : a.heatmap.latest;
  const zones = Object.entries(a.zones).sort((x, y) => y[1] - x[1]);
  const mix = Object.entries(a.shot_mix).sort((x, y) => y[1] - x[1]);
  const mixMax = Math.max(1, ...mix.map(([, n]) => n));

  if (s.matches === 0) {
    return (
      <Card title="History and full analysis">
        <p className="text-sm">No analysed match is linked to {a.player.name} yet, so there is no history to show (and nothing is made up).</p>
        <p className="mt-2 text-sm text-muted">Analyse a match (upload a video or record live), then open the match and say who played: it joins this history straight away.</p>
        <div className="mt-3 flex gap-2"><Link href="/upload" className="btn-primary">Analyse a match</Link><Link href="/capture" className="btn-ghost">Record live</Link></div>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        <Stat label="Matches analysed" value={s.matches} hint={`${s.analysed_minutes} min of play`} />
        <Stat label="Won / lost" value={`${s.wins} / ${s.losses}`} hint="where the score was seen" />
        <Stat label="Hits" value={s.hits} />
        <Stat label="Distance" value={`${s.distance_m} m`} hint="all matches" />
        <Stat label="Tracked" value={`${Math.round(s.frames_tracked / 25)} s`} hint="of court position" />
      </div>

      <PlayerChat playerId={playerId} name={a.player.name} />

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
        <Card title="Where you play: heatmap of every analysed match"
          actions={<div className="flex gap-1 text-xs">
            {([["all", "All matches"], ["earlier", "Earlier"], ["latest", "Latest"]] as const).map(([k, label]) => (
              <button key={k} onClick={() => setView(k)} disabled={k !== "all" && !a.heatmap[k]}
                className={`rounded-md px-2 py-1 ${view === k ? "bg-accent text-accent-fg" : "border border-border disabled:opacity-40"}`}>{label}</button>
            ))}
          </div>}>
          {grid ? <MiniCourt sport={court} heat={{ cell: a.heatmap.cell, grid }} className="mx-auto h-[420px] w-full" /> : <p className="py-10 text-center text-sm text-muted">No court positions for this view.</p>}
          <p className="mt-2 text-xs text-muted">
            Time spent at each spot, summed over every match and drawn in your own half (a far-side player&apos;s positions are turned round so matches from either end add up). Brighter means more time.
            {a.heatmap.frames ? ` Built from ${a.heatmap.frames.toLocaleString()} tracked frames.` : ""}
          </p>
        </Card>
        <div className="space-y-4">
          <Card title="Time by zone">
            {zones.length ? <ul className="space-y-1.5 text-sm">{zones.slice(0, 6).map(([z, f]) => (
              <li key={z} className="flex items-center gap-2"><span className="w-28 capitalize text-muted">{z.replace("-", " ")}</span>
                <div className="h-2 flex-1 rounded bg-fg/10"><div className="h-2 rounded bg-accent" style={{ width: `${Math.round(f * 100)}%` }} /></div>
                <span className="w-9 text-right tabular-nums">{Math.round(f * 100)}%</span></li>))}</ul> : <p className="text-sm text-muted">Zones need a calibrated court.</p>}
          </Card>
          <Card title="Shots used">
            {mix.length ? <ul className="space-y-1.5 text-sm">{mix.map(([k, n]) => (
              <li key={k} className="flex items-center gap-2"><span className="w-16 capitalize text-muted">{k}</span>
                <div className="h-2 flex-1 rounded bg-fg/10"><div className="h-2 rounded bg-sky-500" style={{ width: `${(100 * n) / mixMax}%` }} /></div>
                <span className="w-6 text-right tabular-nums">{n}</span></li>))}</ul> : <p className="text-sm text-muted">No shot types matched a rule in these matches.</p>}
          </Card>
        </div>
      </div>

      <Card title="Past vs current: the latest match against your earlier ones">
        {a.compare.length === 0 ? <p className="text-sm text-muted">With one analysed match there is nothing to compare yet. After the next one, each metric shows whether it got better or worse.</p> : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-muted"><tr><th className="py-2">Metric</th><th>Earlier (average)</th><th>Latest</th><th>Change</th><th></th></tr></thead>
                <tbody className="divide-y divide-border">
                  {a.compare.map((c) => (
                    <tr key={c.metric}>
                      <td className="py-2">{c.label}</td>
                      <td className="tabular-nums">{c.earlier} {c.unit}<span className="ml-1 text-[11px] text-muted">({c.n_earlier} match{c.n_earlier === 1 ? "" : "es"})</span></td>
                      <td className="tabular-nums font-medium">{c.latest} {c.unit}</td>
                      <td className="tabular-nums">{c.change_pct > 0 ? "+" : ""}{c.change_pct}%</td>
                      <td><Badge tone={c.verdict === "better" ? "green" : c.verdict === "worse" ? "red" : "neutral"}>{c.verdict === "changed" ? "changed" : c.verdict}</Badge></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {a.insights.length > 0 && <ul className="mt-3 list-disc space-y-1 pl-5 text-sm">{a.insights.map((i) => <li key={i.metric}>{i.text}</li>)}</ul>}
            <p className="mt-2 text-xs text-muted">Differences between single matches are noisy (a short clip, a different opponent): read a change as a pointer, and look at the trend below.</p>
          </>
        )}
      </Card>

      <Card title="How each metric has moved, match by match">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{TREND_ORDER.map((t) => <Trend key={t.key} a={a} k={t.key} label={t.label} unit={t.unit} />)}</div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Best shots (the outcome first, then the technique)">
          {a.best_shots.length === 0 ? <p className="text-sm text-muted">No shot could be rated yet.</p> : (
            <ul className="divide-y divide-border">
              {a.best_shots.map((b, i) => (
                <li key={`${b.match_id}-${b.t}-${i}`} className="py-2 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium capitalize">{b.shot ?? "shot"} <span className="text-muted">· {OUTCOME[b.outcome] ?? b.outcome}</span></span>
                    <span className="tabular-nums">{b.score}/100</span>
                  </div>
                  <div className="text-xs text-muted">{b.why}</div>
                  <Link href={`/matches/${b.match_id}?t=${b.t}`} className="text-xs text-accent">Watch at {fmtTime(b.t)} →</Link>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-xs text-muted">A shot that won the point always ranks above one that lost it; speed is only one part of technique.</p>
        </Card>
        <Card title="Match history">
          <ul className="divide-y divide-border">
            {[...a.matches].reverse().map((m: AnalysisMatch) => (
              <li key={m.match_id} className="py-2 text-sm">
                <div className="flex items-center justify-between gap-2">
                  <Link href={`/matches/${m.match_id}`} className="font-medium text-accent">vs {m.opponent}</Link>
                  <span className="flex items-center gap-2">{m.result && <Badge tone={m.result === "won" ? "green" : "red"}>{m.result}</Badge>}<span className="text-xs text-muted">{fmtDate(m.date)}</span></span>
                </div>
                <div className="mt-0.5 text-xs text-muted">
                  {Math.round(m.duration_s)} s · {m.hits ?? 0} hits
                  {m.metrics.avg_return_to_base_s != null ? ` · return ${m.metrics.avg_return_to_base_s} s` : ""}
                  {m.metrics.fastest_shot_kmh != null ? ` · fastest ${m.metrics.fastest_shot_kmh} km/h` : ""}
                </div>
              </li>
            ))}
          </ul>
        </Card>
      </div>
      <p className="text-xs text-muted">{a.data_note}</p>
    </div>
  );
}
