"use client";

// The 3D court with its controls, shared by the Smart Courts page and the 3D view on a match's own page: play / pause / scrub /
// slow motion, camera presets, a checkbox per player (and per heatmap), a second (previous) match drawn lighter, and the venue
// model of the sport. The caller decides which match(es) to load and who may see them.
import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { Layer3D, Scene3DData } from "@/lib/court3d";
import { fmtTime } from "@/lib/format";
import { Badge, Card, Loading } from "@/components/ui";
import type { CameraPreset, ViewerHandle } from "@/components/court3d/CourtViewer";
import VenueModel from "@/components/court3d/VenueModel";

const CourtViewer = dynamic(() => import("@/components/court3d/CourtViewer"), { ssr: false, loading: () => <Loading label="Loading the 3D court…" /> });

const SPEEDS = [1, 0.5, 0.25, 0.1];
const PRESETS: { id: CameraPreset; label: string }[] = [{ id: "behind", label: "Behind baseline" }, { id: "broadcast", label: "Broadcast" }, { id: "side", label: "Side" }, { id: "top", label: "Top-down" }];

export function layersOf(s: Scene3DData, tag: "now" | "compare", on: Record<string, boolean>, heat: Record<string, boolean>): Layer3D[] {
  return s.players.map((p) => {
    const id = `${tag}:${s.match_id}:${p.track_id}`;
    return {
      id, label: tag === "compare" ? `${p.name} (before)` : p.name, color: p.color, ghost: tag === "compare",
      flights: s.flights.filter((f) => f.track_id === p.track_id), positions: s.positions[String(p.track_id)] ?? [], heat: s.heat[String(p.track_id)] ?? null,
      visible: on[id] ?? true, showHeat: heat[id] ?? false,
    };
  });
}

interface Props {
  now?: Scene3DData;
  before?: Scene3DData;
  role: "coach" | "player" | "viewer";
  loading?: boolean;
  topRight?: ReactNode;                              // match pickers
  bottomRight?: ReactNode;                           // e.g. the previous-vs-current numbers
  follow?: { time: number };                         // the match page's video clock: the 3D court can follow it
  height?: string;
}

export default function Scene3DPanel({ now, before, role, loading, topRight, bottomRight, follow, height = "h-[min(62vh,620px)] min-h-[360px]" }: Props) {
  const [tab, setTab] = useState<"court" | "venue">("court");
  const [on, setOn] = useState<Record<string, boolean>>({});
  const [heat, setHeat] = useState<Record<string, boolean>>({});
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [loop, setLoop] = useState(true);
  const [paths, setPaths] = useState(true);
  const [time, setTime] = useState(0);
  const [following, setFollowing] = useState(true);
  const viewer = useRef<ViewerHandle>(null);

  const layers = useMemo(() => [
    ...(now ? layersOf(now, "now", on, heat) : []),
    ...(before ? layersOf(before, "compare", on, heat) : []),
  ], [now, before, on, heat]);
  const duration = useMemo(() => {
    const ends = [now, before].filter(Boolean).map((s) => Math.max(s!.duration_s ?? 0, ...s!.flights.map((f) => f.t1), ...Object.values(s!.positions).map((p) => p[p.length - 1]?.[0] ?? 0)));
    return Math.max(1, ...ends);
  }, [now, before]);

  useEffect(() => {                                   // follow the video of the match page
    if (follow && following) { setPlaying(false); viewer.current?.seek(follow.time); }
  }, [follow?.time, following]);                      // eslint-disable-line react-hooks/exhaustive-deps

  const shown = layers.filter((l) => l.visible);
  const flightsShown = shown.reduce((n, l) => n + l.flights.length, 0);
  const estimates = shown.reduce((n, l) => n + l.flights.filter((f) => f.kind === "estimate").length, 0);
  const nearest = shown.reduce((n, l) => n + l.flights.filter((f) => f.placement === "nearest").length, 0);
  const guessed = shown.reduce((n, l) => n + l.flights.filter((f) => f.placement === "base").length, 0);
  const sport = now?.sport ?? "tennis";

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
      <div className="min-w-0 space-y-3">
        <div className="flex gap-1 text-sm">
          {([["court", "3D court (your data)"], ["venue", "Venue model (Sketchfab)"]] as const).map(([k, l]) => (
            <button key={k} onClick={() => setTab(k)} className={`rounded-lg px-3 py-1.5 ${tab === k ? "bg-accent text-accent-fg" : "border border-border"}`}>{l}</button>
          ))}
        </div>
        {tab === "venue" ? <Card><VenueModel sport={sport} /></Card> : (
          <>
            <div className="relative overflow-hidden rounded-xl border border-border bg-[#0b1220]">
              {now ? (
                <CourtViewer handle={viewer} className={`${height} w-full`} sport={now.sport} court={now.court} objectSize={now.object_size_m} layers={layers} duration={duration}
                  playing={playing} speed={speed} loop={loop} showPaths={paths} onTime={setTime} onEnded={() => setPlaying(false)} />
              ) : <div className="grid h-[420px] place-items-center"><Loading label={loading ? "Loading the match…" : "Nothing to show"} /></div>}
              <div className="absolute left-3 top-3 flex flex-wrap gap-1.5">
                {PRESETS.map((p) => <button key={p.id} onClick={() => viewer.current?.setPreset(p.id)} className="rounded-md bg-black/50 px-2 py-1 text-xs text-white hover:bg-black/70">{p.label}</button>)}
              </div>
              <div className="absolute bottom-2 right-3 text-[11px] text-white/60">drag to orbit · scroll to zoom · right-drag to pan</div>
            </div>

            <Card>
              <div className="flex flex-wrap items-center gap-3">
                <button className="btn-primary w-24" onClick={() => { if (!playing && time >= duration - 0.01) viewer.current?.seek(0); setFollowing(false); setPlaying(!playing); }}>{playing ? "Pause" : "Play"}</button>
                <div className="flex items-center gap-1 text-xs">
                  <span className="mr-1 text-muted">Speed</span>
                  {SPEEDS.map((s) => <button key={s} onClick={() => setSpeed(s)} className={`rounded-md px-2 py-1 ${speed === s ? "bg-accent text-accent-fg" : "border border-border"}`}>{s === 1 ? "1×" : `${s}×`}</button>)}
                </div>
                <label className="flex items-center gap-1.5 text-xs"><input type="checkbox" checked={loop} onChange={(e) => setLoop(e.target.checked)} /> Loop</label>
                <label className="flex items-center gap-1.5 text-xs"><input type="checkbox" checked={paths} onChange={(e) => setPaths(e.target.checked)} /> Show every path</label>
                {follow && <label className="flex items-center gap-1.5 text-xs" title="Moves with the video above; untick to play the 3D court on its own"><input type="checkbox" checked={following} onChange={(e) => setFollowing(e.target.checked)} /> Follow the video</label>}
                <span className="ml-auto tabular-nums text-sm text-muted">{fmtTime(time)} / {fmtTime(duration)}</span>
              </div>
              <input type="range" min={0} max={duration} step={0.01} value={Math.min(time, duration)} className="mt-3 w-full"
                onChange={(e) => { setPlaying(false); setFollowing(false); viewer.current?.seek(Number(e.target.value)); }} aria-label="Match time" />
              <p className="mt-2 text-xs text-muted">
                Pause at any moment to see where the shuttle / ball and the players were; slow motion shows a fast shot. The figures follow the tracked foot positions and swing at each of their shots
                (a walk cycle and a swing, not captured poses). Solid paths are shots whose flight a drag law explains; dashed ones are gravity-only estimates ({estimates} of {flightsShown} shown). Every hit has a path; where a player was not tracked at that moment the path starts or ends at their nearest tracked position ({nearest}) or, if they were not tracked at all, at their side's base position ({guessed}), so those paths show where a shot could have gone, not where it did.
                One camera does not measure height: the heights are reconstructed.
              </p>
            </Card>
          </>
        )}
      </div>

      <div className="space-y-3">
        {topRight}
        {now && (
          <Card title={role === "coach" ? "Players: choose who to show and compare" : "Players"}>
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
              Each person has one colour, and their shuttle / ball is drawn in it. {before ? "The previous match is drawn lighter." : ""}
              {role === "player" ? " You and the opponent you faced are shown, in your own matches only." : ""}
            </p>
            {flightsShown === 0 && layers.length > 0 && <div className="mt-2"><Badge tone="amber">no shot of this match could be placed on the court</Badge></div>}
          </Card>
        )}
        {bottomRight}
      </div>
    </div>
  );
}
