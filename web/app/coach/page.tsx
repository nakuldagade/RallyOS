"use client";

// Coach dashboard: the players on this coach's roster, who is improving, who needs attention, one click to the full analysis.
// Players are sent to their own dashboard; logged-out visitors to the login.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { homeFor, useAuth } from "@/lib/auth";
import type { CoachRow } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { Badge, Card, ErrorBox, Loading, PageHeader, Stat } from "@/components/ui";

function PlayerCard({ r, onRemove }: { r: CoachRow; onRemove: () => void }) {
  const l = r.latest;
  return (
    <div className="card p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <Link href={`/players/${r.player_id}`} className="text-lg font-semibold text-accent">{r.name}</Link>
          <div className="text-xs text-muted">
            rating {Math.round(r.rating)} ± {Math.round(r.rd * 2)}
            {r.rating_change != null ? ` · ${r.rating_change >= 0 ? "+" : ""}${r.rating_change}` : ""}
            {r.rating_is_sample ? " (sample curve)" : ""}
          </div>
        </div>
        <div className="flex flex-col items-end gap-1">
          <Badge tone={r.matches ? "blue" : "neutral"}>{r.matches} match{r.matches === 1 ? "" : "es"} analysed</Badge>
          {r.attention.length > 0 && <Badge tone="amber">{r.attention.length} to look at</Badge>}
        </div>
      </div>
      {l ? (
        <p className="mt-2 text-sm text-muted">
          Latest: vs {l.opponent}{l.result ? `, ${l.result}` : ""}
          {l.metrics.avg_return_to_base_s != null ? ` · return to base ${l.metrics.avg_return_to_base_s} s` : ""}
        </p>
      ) : <p className="mt-2 text-sm text-muted">No analysed match is linked to this player yet.</p>}
      {r.attention.length > 0 && (
        <div className="mt-2"><div className="label mb-1 text-amber-500">Needs attention</div>
          <ul className="list-disc space-y-0.5 pl-5 text-sm">{r.attention.map((a) => <li key={a.metric}>{a.text}</li>)}</ul></div>
      )}
      {r.improving.length > 0 && (
        <div className="mt-2"><div className="label mb-1 text-emerald-500">Improving</div>
          <ul className="list-disc space-y-0.5 pl-5 text-sm">{r.improving.map((a) => <li key={a.metric}>{a.text}</li>)}</ul></div>
      )}
      <div className="mt-3 flex gap-2">
        <Link href={`/players/${r.player_id}`} className="btn-primary py-1 text-xs">Full analysis and heatmap</Link>
        <button onClick={() => window.print()} className="btn-ghost py-1 text-xs">Print progress card</button>
        <button onClick={onRemove} className="btn-ghost py-1 text-xs text-rose-500">Remove</button>
      </div>
    </div>
  );
}

export default function CoachPage() {
  const { user, ready } = useAuth();
  const router = useRouter();
  const isCoach = ready && user?.role === "coach";
  useEffect(() => {
    if (ready && !user) router.replace("/login");
    else if (ready && user && user.role !== "coach") router.replace(homeFor(user));
  }, [ready, user, router]);

  const dash = useApi(() => (isCoach ? api.coachDashboard() : Promise.resolve(undefined)), [isCoach]);
  const players = useApi(() => api.players(), []);
  const [adding, setAdding] = useState("");
  const [err, setErr] = useState<string | null>(null);

  if (!isCoach) return <Loading />;
  if (dash.loading) return <Loading />;
  if (dash.error || !dash.data) return <ErrorBox message={dash.error ?? "No dashboard"} onRetry={dash.reload} />;
  const d = dash.data;
  const onRoster = new Set(d.players.map((p) => p.player_id));
  const candidates = (players.data ?? []).filter((p) => !onRoster.has(p.id));
  const act = async (fn: () => Promise<unknown>) => {
    setErr(null);
    try { await fn(); dash.reload(); setAdding(""); } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };

  return (
    <div className="mx-auto max-w-6xl space-y-4">
      <PageHeader title={`Coach dashboard · ${d.coach.name}`} subtitle="Your roster only. Open a player for their history, heatmap and match-by-match analysis." />
      <div className="grid grid-cols-3 gap-3">
        <Stat label="Players on your roster" value={d.totals.players} />
        <Stat label="Matches analysed" value={d.totals.matches} hint="across the roster" />
        <Stat label="Players to look at" value={d.totals.need_attention} hint="something got worse in their latest match" />
      </div>
      {err && <ErrorBox message={err} />}
      <div className="grid gap-4 md:grid-cols-2">
        {d.players.map((r) => <PlayerCard key={r.player_id} r={r} onRemove={() => act(() => api.removeFromRoster(r.player_id))} />)}
        {d.players.length === 0 && <Card title="Roster"><p className="text-sm text-muted">No players yet: add one below.</p></Card>}
      </div>
      <Card title="Add a player to your roster">
        <div className="flex flex-wrap items-center gap-2">
          <select className="input" value={adding} onChange={(e) => setAdding(e.target.value)}>
            <option value="">Choose a player…</option>
            {candidates.map((p) => <option key={p.id} value={p.id}>{p.name} ({Math.round(p.rating)})</option>)}
          </select>
          <button className="btn-primary" disabled={!adding} onClick={() => act(() => api.addToRoster(adding))}>Add</button>
        </div>
      </Card>
    </div>
  );
}
