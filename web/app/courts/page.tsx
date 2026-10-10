"use client";

// Smart Courts: the 3D court. A coach sees the players of their roster in a match, colour-coded, and picks which to show and
// compare; a player sees their own matches, themselves and the opponent they faced, and compares a previous match with a current
// one. Pause, scrub, slow motion, heatmaps, figures that move. The court is chosen from the sport the analysis detected.
// (There is no booking here any more.)
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Scene3DData } from "@/lib/court3d";
import { sportLabel } from "@/lib/sports";
import { useApi } from "@/lib/useApi";
import { Badge, Card, ErrorBox, Loading, PageHeader } from "@/components/ui";
import Scene3DPanel from "@/components/court3d/Scene3DPanel";

const METRIC_ROWS: { key: string; label: string; unit: string; better: "lower" | "higher" }[] = [
  { key: "avg_return_to_base_s", label: "Return to base", unit: "s", better: "lower" },
  { key: "split_step_pct", label: "Split-step", unit: "%", better: "higher" },
  { key: "fastest_shot_kmh", label: "Fastest shot (at the racket)", unit: "km/h", better: "higher" },
  { key: "distance_per_min", label: "Distance covered", unit: "m/min", better: "higher" },
  { key: "best_shot_score", label: "Best-shot score", unit: "/100", better: "higher" },
];

function Compare({ playerId, nowId, beforeId }: { playerId: string; nowId: string; beforeId: string }) {
  const a = useApi(() => api.playerAnalysis(playerId), [playerId]);
  if (a.loading) return <Loading />;
  const now = a.data?.matches.find((m) => m.match_id === nowId), before = a.data?.matches.find((m) => m.match_id === beforeId);
  if (!now || !before) return <p className="text-sm text-muted">These matches are not in your analysed history yet.</p>;
  return (
    <table className="w-full text-sm">
      <thead className="text-left text-xs text-muted"><tr><th className="py-1.5">Metric</th><th>Previous</th><th>Current</th><th></th></tr></thead>
      <tbody className="divide-y divide-border">
        {METRIC_ROWS.map((r) => {
          const p = (before.metrics as unknown as Record<string, number | null>)[r.key], c = (now.metrics as unknown as Record<string, number | null>)[r.key];
          const delta = p != null && c != null ? c - p : null;
          const good = delta == null || delta === 0 ? null : r.better === "lower" ? delta < 0 : delta > 0;
          return (
            <tr key={r.key}>
              <td className="py-1.5">{r.label}</td>
              <td className="tabular-nums">{p ?? "—"} {p != null ? r.unit : ""}</td>
              <td className="tabular-nums font-medium">{c ?? "—"} {c != null ? r.unit : ""}</td>
              <td>{good == null ? null : <Badge tone={good ? "green" : "red"}>{good ? "better" : "worse"}</Badge>}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function Viewer3D({ role, playerId }: { role: "coach" | "player"; playerId: string | null }) {
  const list = useApi(() => api.courts3dMatches(), []);
  const [nowId, setNowId] = useState("");
  const [beforeId, setBeforeId] = useState("");
  const now = useApi(() => (nowId ? api.courts3dScene(nowId) : Promise.resolve(undefined)), [nowId]);
  const before = useApi(() => (beforeId ? api.courts3dScene(beforeId) : Promise.resolve(undefined)), [beforeId]);

  useEffect(() => { if (list.data?.length && !nowId) setNowId(list.data[0].match_id); }, [list.data, nowId]);
  useEffect(() => { setBeforeId(""); }, [nowId]);

  if (list.loading) return <Loading />;
  if (list.error) return <ErrorBox message={list.error} onRetry={list.reload} />;
  const matches = list.data ?? [];
  if (matches.length === 0) {
    return (
      <Card title="No match to show yet">
        <p className="text-sm">{role === "coach" ? "None of the matches analysed so far has a player from your roster in it." : "No analysed match is linked to you yet."}</p>
        <p className="mt-2 text-sm text-muted">Analyse a match (upload or record live), open it and say who played: it appears here, with the shots as 3D paths and a heatmap.</p>
        <div className="mt-3 flex gap-2"><Link href="/upload" className="btn-primary">Analyse a match</Link><Link href="/capture" className="btn-ghost">Record live</Link></div>
      </Card>
    );
  }
  const sc = now.data;
  const sameSport = matches.filter((m) => sc && m.sport === sc.sport && m.match_id !== sc.match_id);
  const date = (d: string) => new Date(d).toLocaleDateString(undefined, { day: "numeric", month: "short" });
  return (
    <Scene3DPanel role={role} now={sc} before={before.data} loading={now.loading}
      topRight={
        <Card title="Match">
          <select className="input w-full" value={nowId} onChange={(e) => setNowId(e.target.value)}>
            {matches.map((m) => <option key={m.match_id} value={m.match_id}>{date(m.date)} · {m.players.map((p) => p.name).join(" vs ")} · {sportLabel(m.sport)}</option>)}
          </select>
          {sc && <p className="mt-2 text-xs text-muted">Court: {sportLabel(sc.sport)} (the sport the analysis detected).</p>}
          <label className="label mb-1 mt-3 block">{role === "player" ? "Compare with a previous match" : "Compare with another match"}</label>
          <select className="input w-full" value={beforeId} onChange={(e) => setBeforeId(e.target.value)}>
            <option value="">none</option>
            {sameSport.map((m) => <option key={m.match_id} value={m.match_id}>{date(m.date)} · {m.players.map((p) => p.name).join(" vs ")}</option>)}
          </select>
          {before.error && <p className="mt-2 text-xs text-rose-500">{before.error}</p>}
        </Card>
      }
      bottomRight={role === "player" && playerId ? (beforeId && nowId
        ? <Card title="Performance: previous vs current"><Compare playerId={playerId} nowId={nowId} beforeId={beforeId} /></Card>
        : <Card><p className="text-sm text-muted">Pick a previous match above to draw it next to this one and compare the numbers.</p></Card>) : undefined} />
  );
}

const COURT_SPORTS = ["tennis", "badminton", "table_tennis", "squash", "pickleball", "padel"];

/** A court with nothing on it, for a visitor who has not logged in: any of the six sports. */
function Preview() {
  const [sport, setSport] = useState("tennis");
  const cfg = useApi(() => api.sport(sport), [sport]);
  const body = () => {
    if (cfg.loading) return <Loading />;
    if (cfg.error || !cfg.data) return <ErrorBox message={cfg.error ?? "No court"} onRetry={cfg.reload} />;
    const c = cfg.data as unknown as { sport: string; court: Scene3DData["court"]; net: Scene3DData["court"]["net"]; walls?: Scene3DData["court"]["walls"]; view3d?: Scene3DData["court"]["view3d"]; projectile?: { size_m?: number } };
    const empty: Scene3DData = {
      match_id: "preview", date: "", sport: c.sport, fps: 25, duration_s: 1, object_size_m: c.projectile?.size_m,
      court: { length: c.court.length, width: c.court.width, lines: c.court.lines, net: c.net ?? {}, walls: c.walls, view3d: c.view3d },
      players: [], flights: [], positions: {}, heat: {}, notes: { heights: "", positions: "" },
    };
    return <Scene3DPanel role="viewer" now={empty} />;
  };
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-1.5 text-sm">
        <span className="mr-1 text-muted">Court</span>
        {COURT_SPORTS.map((k) => (
          <button key={k} onClick={() => setSport(k)} className={`rounded-lg px-3 py-1.5 ${sport === k ? "bg-accent text-accent-fg" : "border border-border"}`}>{sportLabel(k)}</button>
        ))}
      </div>
      {body()}
    </div>
  );
}

export default function SmartCourts() {
  const { user, ready } = useAuth();
  return (
    <div className="mx-auto max-w-7xl space-y-4">
      <PageHeader title="Smart Courts" subtitle="Your matches in 3D: shot paths you can pause and slow down, players that move, colour-coded on the court, and where they stood." />
      {!ready ? <Loading /> : !user ? (
        <>
          <Preview />
          <Card><p className="text-sm">These are the courts, empty. <Link href="/login" className="text-accent">Log in</Link> to see your matches on it: a coach sees the players on their roster, a player sees their own matches (themselves and the opponent they faced) and can compare a previous match with a current one. The court follows the sport the analysis detected.</p></Card>
        </>
      ) : <Viewer3D role={user.role} playerId={user.player_id} />}
    </div>
  );
}
