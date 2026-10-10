"use client";

// One player: rating and its history, style fingerprint, the full analysis over every analysed match, suggested opponents.
// Used by /me (the logged-in player's own dashboard) and /players/[id] (a coach opening someone on their roster, or anyone
// opening a profile).
import Link from "next/link";
import type { ReactNode } from "react";
import { CartesianGrid, Line, LineChart, PolarAngleAxis, PolarGrid, Radar, RadarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { Badge, Card, ErrorBox, Loading, PageHeader, Stat } from "@/components/ui";
import PlayerAnalysis from "@/components/player/PlayerAnalysis";

const STYLE_AXES = ["Attack", "Defence", "Net play", "Endurance"];
const tooltipStyle = { background: "rgb(var(--card))", border: "1px solid rgb(var(--border))", borderRadius: 8 };

export default function PlayerProfile({ id, title, actions }: { id: string; title?: string; actions?: ReactNode }) {
  const player = useApi(() => api.player(id), [id]);
  const trends = useApi(() => api.trends(id), [id]);
  const suggestions = useApi(() => api.matchmaking(id), [id]);

  if (player.loading) return <Loading />;
  if (player.error || !player.data) return <ErrorBox message={player.error ?? "Player not found"} onRetry={player.reload} />;
  const p = player.data;
  const rated = trends.data?.rating_history ?? [];
  const history = rated.map((h) => ({ date: h.at.slice(5, 10), rating: Math.round(h.rating), verified: h.evidence_level === "video_verified" }));
  const first = history[0]?.rating;
  const sample = rated.length > 0 && !rated.some((h) => h.match_id);
  const style = (p.style_vec ?? []).map((v, i) => ({ axis: STYLE_AXES[i] ?? `#${i}`, value: Math.round(v * 100) }));

  return (
    <div className="mx-auto max-w-6xl space-y-4">
      <PageHeader title={title ?? p.name} subtitle={`${p.name} · ${p.sport} · ${p.id}`}
        actions={<div className="flex gap-2">{actions}<Link href={`/play?a=${p.id}`} className="btn-primary">Find an opponent</Link></div>} />
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Verified rating" value={Math.round(p.rating)} hint={`± ${Math.round(p.rd * 2)} (95%)`} />
        <Stat label="Change" value={first !== undefined ? `${p.rating - first >= 0 ? "+" : ""}${Math.round(p.rating - first)}` : "—"} hint="over the history shown" />
        <Stat label="Rating deviation" value={Math.round(p.rd)} hint="lower = more certain" />
        <Stat label="Volatility" value={p.vol.toFixed(3)} />
      </div>
      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <Card title="Rating history" actions={sample ? <Badge tone="amber" title="The rating curve comes from the seed data, not from analysed matches">sample curve</Badge> : undefined}>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={history} margin={{ left: -10, right: 10, top: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--border))" />
                <XAxis dataKey="date" tick={{ fill: "rgb(var(--muted))", fontSize: 12 }} />
                <YAxis domain={["dataMin - 20", "dataMax + 20"]} tick={{ fill: "rgb(var(--muted))", fontSize: 12 }} />
                <Tooltip contentStyle={tooltipStyle} />
                <Line type="monotone" dataKey="rating" stroke="rgb(var(--accent))" strokeWidth={2.5} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card title="Style fingerprint">
          {style.length ? (
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <RadarChart data={style} outerRadius="72%">
                  <PolarGrid stroke="rgb(var(--border))" />
                  <PolarAngleAxis dataKey="axis" tick={{ fill: "rgb(var(--muted))", fontSize: 12 }} />
                  <Radar dataKey="value" stroke="rgb(var(--accent))" fill="rgb(var(--accent))" fillOpacity={0.35} />
                </RadarChart>
              </ResponsiveContainer>
            </div>
          ) : <div className="text-sm text-muted">No style data yet.</div>}
        </Card>
      </div>

      <PlayerAnalysis playerId={id} />

      <Card title="Suggested opponents (similar rating, nearby, complementary style)">
        {suggestions.loading ? <Loading /> : suggestions.error ? <ErrorBox message={suggestions.error} /> : (
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {suggestions.data?.map((s) => (
              <Link key={s.player_id} href={`/play?a=${p.id}&b=${s.player_id}`} className="rounded-lg border border-border p-3 transition hover:border-accent">
                <div className="flex items-center justify-between">
                  <span className="font-medium">{s.name}</span>
                  <span className="tabular-nums text-sm">{Math.round(s.rating)}</span>
                </div>
                <div className="mt-1 flex flex-wrap gap-1.5 text-xs">
                  <Badge>{s.distance_km} km</Badge>
                  <Badge tone="blue">style gap {Math.round(s.style_complement * 100)}%</Badge>
                  <Badge tone="green">match {Math.round(s.score * 100)}</Badge>
                </div>
              </Link>
            ))}
            {suggestions.data?.length === 0 && <div className="text-sm text-muted">No one in range right now.</div>}
          </div>
        )}
      </Card>
    </div>
  );
}
