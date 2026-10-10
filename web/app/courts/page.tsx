"use client";

// Smart Courts: the 3D court. A coach sees the players of their roster in a match, colour-coded, and picks which to show and
// compare; a player sees only themselves and compares a previous match with a current one. Pause, scrub, slow motion, heatmaps.
// (There is no booking here any more.)
import Link from "next/link";
import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Layer3D, Scene3DData } from "@/lib/court3d";
import { fmtTime } from "@/lib/format";
import { sportLabel } from "@/lib/sports";
import type { SportConfig } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { Badge, Card, ErrorBox, Loading, PageHeader } from "@/components/ui";
import type { CameraPreset, ViewerHandle } from "@/components/court3d/CourtViewer";

const CourtViewer = dynamic(() => import("@/components/court3d/CourtViewer"), { ssr: false, loading: () => <Loading label="Loading the 3D court…" /> });

const SPEEDS = [1, 0.5, 0.25, 0.1];
const PRESETS: { id: CameraPreset; label: string }[] = [{ id: "behind", label: "Behind baseline" }, { id: "broadcast", label: "Broadcast" }, { id: "side", label: "Side" }, { id: "top", label: "Top-down" }];
const SKETCHFAB = "https://sketchfab.com/models/0ad5af25f6084d3f820c3f8dc36c58e8/embed";

function layersOf(s: Scene3DData, tag: "now" | "compare", on: Record<string, boolean>, heat: Record<string, boolean>): Layer3D[] {
  return s.players.map((p) => {
    const id = `${tag}:${s.match_id}:${p.track_id}`;
    return {
      id, label: tag === "compare" ? `${p.name} (before)` : p.name, color: p.color, ghost: tag === "compare",
      flights: s.flights.filter((f) => f.track_id === p.track_id), positions: s.positions[String(p.track_id)] ?? [], heat: s.heat[String(p.track_id)] ?? null,
      visible: on[id] ?? true, showHeat: heat[id] ?? false,
    };
  });
}

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
  const [on, setOn] = useState<Record<string, boolean>>({});
  const [heat, setHeat] = useState<Record<string, boolean>>({});
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [loop, setLoop] = useState(true);
  const [paths, setPaths] = useState(true);
  const [time, setTime] = useState(0);
  const viewer = useRef<ViewerHandle>(null);

  useEffect(() => {
    if (list.data?.length && !nowId) setNowId(list.data[0].match_id);
  }, [list.data, nowId]);
  useEffect(() => { setBeforeId(""); }, [nowId]);

  const layers = useMemo(() => [
    ...(now.data ? layersOf(now.data, "now", on, heat) : []),
    ...(before.data ? layersOf(before.data, "compare", on, heat) : []),
  ], [now.data, before.data, on, heat]);
  const duration = useMemo(() => {
    const ends = [now.data, before.data].filter(Boolean).map((s) => Math.max(s!.duration_s ?? 0, ...s!.flights.map((f) => f.t1), ...Object.values(s!.positions).map((p) => p[p.length - 1]?.[0] ?? 0)));
    return Math.max(1, ...ends);
  }, [now.data, before.data]);

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
  const flightsShown = layers.filter((l) => l.visible).reduce((n, l) => n + l.flights.length, 0);
  const estimates = layers.filter((l) => l.visible).reduce((n, l) => n + l.flights.filter((f) => f.kind === "estimate").length, 0);

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
      <div className="min-w-0 space-y-3">
        <div className="relative overflow-hidden rounded-xl border border-border bg-[#0b1220]">
          {sc ? (
            <CourtViewer handle={viewer} className="h-[min(62vh,620px)] min-h-[360px] w-full" sport={sc.sport} court={sc.court} layers={layers} duration={duration}
              playing={playing} speed={speed} loop={loop} showPaths={paths} onTime={setTime} onEnded={() => setPlaying(false)} />
          ) : <div className="grid h-[420px] place-items-center"><Loading label="Loading the match…" /></div>}
          <div className="absolute left-3 top-3 flex flex-wrap gap-1.5">
            {PRESETS.map((p) => <button key={p.id} onClick={() => viewer.current?.setPreset(p.id)} className="rounded-md bg-black/50 px-2 py-1 text-xs text-white hover:bg-black/70">{p.label}</button>)}
          </div>
          <div className="absolute bottom-2 right-3 text-[11px] text-white/60">drag to orbit · scroll to zoom · right-drag to pan</div>
        </div>

        <Card>
          <div className="flex flex-wrap items-center gap-3">
            <button className="btn-primary w-24" onClick={() => { if (!playing && time >= duration - 0.01) viewer.current?.seek(0); setPlaying(!playing); }}>{playing ? "Pause" : "Play"}</button>
            <div className="flex items-center gap-1 text-xs">
              <span className="mr-1 text-muted">Speed</span>
              {SPEEDS.map((s) => <button key={s} onClick={() => setSpeed(s)} className={`rounded-md px-2 py-1 ${speed === s ? "bg-accent text-accent-fg" : "border border-border"}`}>{s === 1 ? "1×" : `${s}×`}</button>)}
            </div>
            <label className="flex items-center gap-1.5 text-xs"><input type="checkbox" checked={loop} onChange={(e) => setLoop(e.target.checked)} /> Loop</label>
            <label className="flex items-center gap-1.5 text-xs"><input type="checkbox" checked={paths} onChange={(e) => setPaths(e.target.checked)} /> Show every path</label>
            <span className="ml-auto tabular-nums text-sm text-muted">{fmtTime(time)} / {fmtTime(duration)}</span>
          </div>
          <input type="range" min={0} max={duration} step={0.01} value={Math.min(time, duration)} className="mt-3 w-full"
            onChange={(e) => { setPlaying(false); viewer.current?.seek(Number(e.target.value)); }} aria-label="Match time" />
          <p className="mt-2 text-xs text-muted">
            Pause at any moment to see where the shuttle and the players were; slow motion shows a fast shot. Solid paths are shots whose flight a drag law explains;
            dashed ones are gravity-only estimates ({estimates} of {flightsShown} shown). One camera does not measure height: the heights are reconstructed.
          </p>
        </Card>
      </div>

      <div className="space-y-3">
        <Card title="Match">
          <select className="input w-full" value={nowId} onChange={(e) => setNowId(e.target.value)}>
            {matches.map((m) => <option key={m.match_id} value={m.match_id}>{new Date(m.date).toLocaleDateString(undefined, { day: "numeric", month: "short" })} · {m.players.map((p) => p.name).join(" vs ")} · {sportLabel(m.sport)}</option>)}
          </select>
          <label className="label mb-1 mt-3 block">{role === "player" ? "Compare with a previous match" : "Compare with another match"}</label>
          <select className="input w-full" value={beforeId} onChange={(e) => setBeforeId(e.target.value)}>
            <option value="">none</option>
            {sameSport.map((m) => <option key={m.match_id} value={m.match_id}>{new Date(m.date).toLocaleDateString(undefined, { day: "numeric", month: "short" })} · {m.players.map((p) => p.name).join(" vs ")}</option>)}
          </select>
          {before.error && <p className="mt-2 text-xs text-rose-500">{before.error}</p>}
        </Card>

        <Card title={role === "coach" ? "Players: choose who to show and compare" : "You and your opponent"}>
          <ul className="space-y-2">
            {layers.map((l) => (
              <li key={l.id} className="rounded-lg border border-border p-2.5">
                <label className="flex items-center gap-2 text-sm font-medium">
                  <input type="checkbox" checked={l.visible} onChange={(e) => setOn({ ...on, [l.id]: e.target.checked })} />
                  <span className="h-3 w-3 rounded-full" style={{ background: l.color, opacity: l.ghost ? 0.5 : 1 }} />
                  <span className="truncate">{l.label}</span>
                  <span className="ml-auto text-xs font-normal text-muted">{l.flights.length} shot{l.flights.length === 1 ? "" : "s"}</span>
                </label>
                <label className="mt-1.5 flex items-center gap-2 pl-6 text-xs text-muted">
                  <input type="checkbox" checked={l.showHeat} disabled={!l.heat} onChange={(e) => setHeat({ ...heat, [l.id]: e.target.checked })} />
                  Heatmap of where they stood{!l.heat ? " (not measured)" : ""}
                </label>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-muted">
            Each person has one colour, and their shuttle is drawn in it. {role === "player" ? "You and the opponent you faced are shown, in your own matches only: matches you were not in are never available to your account." : "A previous match is drawn lighter."}
          </p>
        </Card>

        {role === "player" && playerId && beforeId && nowId && (
          <Card title="Performance: previous vs current"><Compare playerId={playerId} nowId={nowId} beforeId={beforeId} /></Card>
        )}
        {role === "player" && !beforeId && <Card><p className="text-sm text-muted">Pick a previous match above to draw it next to this one and compare the numbers.</p></Card>}
      </div>
    </div>
  );
}

function Preview({ sport }: { sport: string }) {
  const cfg = useApi(() => api.sport(sport), [sport]);
  const viewer = useRef<ViewerHandle>(null);
  if (cfg.loading) return <Loading />;
  if (cfg.error || !cfg.data) return <ErrorBox message={cfg.error ?? "No court"} onRetry={cfg.reload} />;
  const c = cfg.data as SportConfig;
  return (
    <div className="relative overflow-hidden rounded-xl border border-border bg-[#0b1220]">
      <CourtViewer handle={viewer} className="h-[420px] w-full" sport={c.sport} court={{ length: c.court.length, width: c.court.width, lines: c.court.lines as never, net: c.net as never }}
        layers={[]} duration={1} playing={false} speed={1} loop={false} showPaths onTime={() => undefined} />
      <div className="absolute left-3 top-3 flex gap-1.5">
        {PRESETS.map((p) => <button key={p.id} onClick={() => viewer.current?.setPreset(p.id)} className="rounded-md bg-black/50 px-2 py-1 text-xs text-white hover:bg-black/70">{p.label}</button>)}
      </div>
    </div>
  );
}

export default function SmartCourts() {
  const { user, ready } = useAuth();
  const [tab, setTab] = useState<"viewer" | "model">("viewer");
  return (
    <div className="mx-auto max-w-7xl space-y-4">
      <PageHeader title="Smart Courts" subtitle="Your matches in 3D: shot paths you can pause and slow down, players colour-coded on the court, and where they stood."
        actions={<div className="flex gap-1 text-sm">
          {([["viewer", "3D court"], ["model", "Venue model (Sketchfab)"]] as const).map(([k, l]) => (
            <button key={k} onClick={() => setTab(k)} className={`rounded-lg px-3 py-1.5 ${tab === k ? "bg-accent text-accent-fg" : "border border-border"}`}>{l}</button>
          ))}
        </div>} />
      {tab === "model" ? (
        <Card title="Tennis court (PBR) by Tiko on Sketchfab">
          <div className="aspect-video w-full overflow-hidden rounded-lg bg-black">
            <iframe title="Tennis Court (PBR)" className="h-full w-full" frameBorder={0} allowFullScreen
              allow="autoplay; fullscreen; xr-spatial-tracking" src={SKETCHFAB} />
          </div>
          <p className="mt-2 text-xs text-muted">
            A model of a tennis venue to look around (it needs internet). Our shot paths and heatmaps are not drawn inside it: an embedded model cannot take our data, so the
            <button className="mx-1 text-accent" onClick={() => setTab("viewer")}>3D court</button>tab builds the court from the sport&apos;s own measurements instead, which is what makes the positions exact.
            Model: <a className="text-accent" href="https://sketchfab.com/3d-models/tennis-court-pbr-0ad5af25f6084d3f820c3f8dc36c58e8" target="_blank" rel="nofollow noreferrer">Tennis Court (PBR)</a> by
            {" "}<a className="text-accent" href="https://sketchfab.com/tikoavp" target="_blank" rel="nofollow noreferrer">Tiko</a> on <a className="text-accent" href="https://sketchfab.com" target="_blank" rel="nofollow noreferrer">Sketchfab</a>.
          </p>
        </Card>
      ) : !ready ? <Loading /> : !user ? (
        <>
          <Preview sport="tennis" />
          <Card><p className="text-sm">This is the tennis court. <Link href="/login" className="text-accent">Log in</Link> to see your matches on it: a coach sees the players on their roster, a player sees their own shots and can compare a previous match with a current one.</p></Card>
        </>
      ) : <Viewer3D role={user.role} playerId={user.player_id} />}
    </div>
  );
}
