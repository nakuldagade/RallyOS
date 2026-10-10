"use client";

// MATCH VISION: video + canvas overlay, live mini-court, score, rally timeline, stats tabs.
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { fmtTime, pct, shortHash, speed } from "@/lib/format";
import { BADMINTON, heatmap, sportLabel, zoneRect, zoneTime } from "@/lib/sports";
import type { Score, SportConfig, TrackFrame } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { Badge, Card, ErrorBox, Loading, MockBanner } from "@/components/ui";
import MiniCourt, { type CourtDot, type CourtRect } from "@/components/court/MiniCourt";
import ZoneSummary, { type PlayerZones } from "@/components/court/ZoneSummary";
import CalibratePanel from "@/components/match/CalibratePanel";
import VideoOverlay from "@/components/video/VideoOverlay";
import RallyTimeline from "@/components/match/RallyTimeline";
import RallyOutcomes from "@/components/match/RallyOutcomes";
import Scoreboard from "@/components/match/Scoreboard";
import StatCards from "@/components/match/StatCards";
import ShotMix from "@/components/match/ShotMix";
import InsightCard from "@/components/coach/InsightCard";
import AudioCard from "@/components/match/AudioCard";
import BallTrackingCard from "@/components/match/BallTrackingCard";

type Tab = "stats" | "shots" | "events" | "insights";

function MatchVision() {
  const { id } = useParams<{ id: string }>();
  const params = useSearchParams();
  const match = useApi(() => api.match(id), [id]);
  const tracks = useApi(() => api.tracks(id), [id]);
  const [sport, setSport] = useState<SportConfig>(BADMINTON);
  const [time, setTime] = useState(0);
  const [frame, setFrame] = useState<TrackFrame | null>(null);
  const [seek, setSeek] = useState<{ t: number; n: number }>();
  const [tab, setTab] = useState<Tab>("stats");
  const [heatMode, setHeatMode] = useState<string>("");   // "" | "live:<track>" | "full:<track>"

  const m = match.data?.data;
  const tr = tracks.data?.data ?? null;

  useEffect(() => {
    if (!m) return;
    api.sport(m.sport).then(setSport).catch(() => setSport(BADMINTON));
  }, [m]);

  useEffect(() => {
    const t = parseFloat(params.get("t") ?? "");
    if (!isNaN(t)) setSeek({ t, n: Date.now() });
  }, [params]);

  const fps = m?.video.fps || tr?.fps || 25;
  const upto = Math.floor(time * fps);
  const [heatKind, heatTid] = heatMode ? [heatMode.split(":")[0], parseInt(heatMode.split(":")[1])] : ["", null];
  const heat = useMemo(
    () => (tr && heatTid !== null ? heatmap(tr, heatTid, sport, 0.5, heatKind === "live" ? upto : undefined) : null),
    [tr, heatTid, heatKind, sport, heatKind === "live" ? upto : 0], // eslint-disable-line react-hooks/exhaustive-deps
  );
  const zoneRows: PlayerZones[] = useMemo(() => {
    if (!tr || !m) return [];
    return m.players.filter((p) => p.side === "near" || p.side === "far").map((p) => ({
      player: p,
      live: zoneTime(tr, p.track_id, p.side as "near" | "far", sport, upto),
      whole: zoneTime(tr, p.track_id, p.side as "near" | "far", sport),
    }));
  }, [tr, m, sport, upto]);
  const zoneBoxes: CourtRect[] = zoneRows.flatMap(({ player, live }) => {
    const r = live[0] ? zoneRect(live[0].zone, sport, player.side as "near" | "far") : null;
    return r ? [{ ...r, color: player.color ?? "#94a3b8", label: `${Math.round(live[0].pct * 100)}%` }] : [];
  });

  if (match.loading) return <Loading label="Loading match…" />;
  if (match.error || !m) return <ErrorBox message={match.error ?? "Match not found"} onRetry={match.reload} />;

  const goto = (t: number) => setSeek({ t, n: Date.now() });
  const color = (tid?: number | null) => m.players.find((p) => p.track_id === tid)?.color ?? "#94a3b8";
  const name = (tid?: number | null) => m.players.find((p) => p.track_id === tid)?.name ?? "—";

  const dots: CourtDot[] = [
    ...m.events.filter((e) => e.type === "landing" && e.court).map((e) => ({
      x: e.court![0], y: e.court![1], color: e.call === "OUT" ? "#f43f5e" : "#facc15", hollow: true,
      title: `${e.call ?? "landing"} ${e.call_prob ? pct(e.call_prob) : ""} at ${fmtTime(e.t)}`,
      onClick: () => goto(e.t),
    })),
    ...(frame?.players ?? []).filter((p) => p.court).map((p) => ({
      x: p.court![0], y: p.court![1], color: color(p.track_id), label: name(p.track_id),
    })),
  ];

  const calibrated = m.calibration.method !== "none";
  const setScore = (s: Score) => match.setData({ ...match.data!, data: { ...m, score: { ...m.score, ...s } } });

  return (
    <div className="mx-auto max-w-7xl">
      {match.data?.mock && <MockBanner />}
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="label">{sportLabel(m.sport)} · {m.match_id}</div>
          <h1 className="text-2xl font-semibold tracking-tight">{m.title || m.players.map((p) => p.name).join(" vs ") || m.match_id}</h1>
          <div className="mt-2 flex flex-wrap gap-2">
            {m.sport_confidence != null && <Badge tone="green">{sportLabel(m.sport)} detected · {pct(m.sport_confidence)} fit</Badge>}
            {m.calibration.method === "4-tap" && <Badge tone="green" title="Court calibrated from 4 tapped corners">court: 4-tap calibration</Badge>}
            <Badge tone="blue" title="SHA-256 of the source video: tamper-evident match record">SHA-256 {shortHash(m.video.sha256)}</Badge>
            <Badge>{m.video.fps} fps · {m.video.width}×{m.video.height}</Badge>
            {m.stats.ball?.tracker === "racketvision" && <Badge tone="amber" title="Shuttle positions from the pretrained RacketVision tracker (inference only)">ball: RacketVision plug-in</Badge>}
          </div>
        </div>
        <Link href={`/matches/${m.match_id}/report`} className="btn-primary">AI coach report →</Link>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_340px]">
        <div className="min-w-0 space-y-4">
          <VideoOverlay match={m} tracks={tr} lines={sport.court.lines} courtSize={sport.court} seek={seek}
            onTime={(t, f) => { setTime(t); setFrame(f); }} />
          <Card title="Rally timeline">
            <RallyTimeline duration={m.video.duration_s} rallies={m.rallies} events={m.events} players={m.players} time={time} onSeek={goto} />
          </Card>
        </div>

        <div className="space-y-4">
          {m.stats.ball && (
            <Card title="Ball tracking">
              <BallTrackingCard ball={m.stats.ball} calibrated={calibrated} />
            </Card>
          )}
          {m.stats.audio && (
            <Card title="Hits heard from audio">
              <AudioCard audio={m.stats.audio} />
            </Card>
          )}
          <Card title="Score">
            {m.players.length ? (
              <Scoreboard matchId={m.match_id} score={m.score} players={m.players} canConfirm={!match.data?.mock} onConfirmed={setScore} />
            ) : (
              <p className="text-sm text-muted">No players tracked in this clip yet, so there is no score. Players, pose and scoring appear once the player stage runs.</p>
            )}
          </Card>
          {m.rallies.some((r) => r.end_reason) && (
            <Card title="How each rally ended">
              <RallyOutcomes match={m} onSeek={goto} />
            </Card>
          )}
          {calibrated ? (
          <Card title="Top-down view" actions={
            <select className="input py-1 text-xs" value={heatMode} onChange={(e) => setHeatMode(e.target.value)}>
              <option value="">Live positions</option>
              {m.players.map((p) => <option key={`l${p.track_id}`} value={`live:${p.track_id}`}>Live heatmap: {p.name}</option>)}
              {m.players.map((p) => <option key={`f${p.track_id}`} value={`full:${p.track_id}`}>Whole-clip heatmap: {p.name}</option>)}
            </select>}>
            <MiniCourt sport={sport} dots={dots} heat={heat} rects={zoneBoxes} className="mx-auto h-[360px] w-full" />
            <p className="mt-2 text-xs text-muted">
              Hollow yellow rings are landings (click to jump).
              {heat ? (heatKind === "live" ? ` Heatmap builds up as the video plays (to ${fmtTime(time)}).` : " Heatmap of the whole clip from tracked foot positions.") : ""}
            </p>
            <ZoneSummary rows={zoneRows} timeLabel={`up to ${fmtTime(time)}`} />
            {!match.data?.mock && <div className="mt-3 flex justify-end"><CalibratePanel match={m} onDone={() => { match.reload(); tracks.reload(); }} /></div>}
          </Card>
          ) : (
            <Card title="Top-down view">
              <p className="mb-3 text-sm text-muted">Court not calibrated for this clip, so there are no court positions, heatmaps, line calls or score. Tap the 4 court corners to add them.</p>
              {!match.data?.mock && <CalibratePanel match={m} onDone={() => { match.reload(); tracks.reload(); }} />}
            </Card>
          )}
          {m.disputes.length > 0 && (
            <Card title="Close calls">
              <div className="space-y-2">
                {m.disputes.map((d) => (
                  <Link key={d.id} href={`/disputes/${d.id}`} className="flex items-center justify-between rounded-lg border border-border p-2.5 text-sm hover:bg-fg/5">
                    <span>Fair-Play Replay · {d.id}</span>
                    <Badge tone={d.call === "OUT" ? "red" : "green"}>{d.call} {pct(d.prob)}</Badge>
                  </Link>
                ))}
              </div>
            </Card>
          )}
        </div>
      </div>

      <Card className="mt-4">
        <div className="mb-4 flex gap-1 border-b border-border">
          {(["stats", "shots", "events", "insights"] as Tab[]).map((t) => (
            <button key={t} onClick={() => setTab(t)}
              className={`-mb-px border-b-2 px-3 py-2 text-sm capitalize ${tab === t ? "border-accent font-medium" : "border-transparent text-muted"}`}>
              {t}
            </button>
          ))}
        </div>
        {tab === "stats" && <StatCards match={m} />}
        {tab === "shots" && <ShotMix match={m} />}
        {tab === "events" && (
          <div className="overflow-x-auto">
            <p className="mb-2 text-xs text-muted">*Speed is the average horizontal speed to the next contact or landing, shown only when both ends are known; it is a lower bound of the shuttle&apos;s peak speed. Hover a dash to see why there is none.</p>
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted">
                <tr><th className="py-2">Time</th><th>Type</th><th>Player</th><th>Shot / call</th><th title="Average horizontal speed from this contact to the next contact or landing, with an error band. The shuttle's real peak speed is higher (it also travels up and down and slows down), so treat this as a lower bound.">Avg speed*</th><th>Confidence</th><th>Source</th></tr>
              </thead>
              <tbody>
                {m.events.map((e) => (
                  <tr key={e.id} onClick={() => goto(e.t)} className="cursor-pointer border-t border-border hover:bg-fg/5">
                    <td className="py-2 font-mono tabular-nums">{fmtTime(e.t)}</td>
                    <td>{e.type}</td>
                    <td>{e.track_id ? name(e.track_id) : "—"}</td>
                    <td>{e.shot ?? (e.call ? `${e.call} (${pct(e.call_prob)})` : e.note ? <span className="text-xs text-muted">no call</span> : "—")}</td>
                    <td className="tabular-nums" title={e.speed_kmh != null ? `Average horizontal speed, ${e.speed_basis}; a lower bound of the shuttle's peak speed` : (e.speed_why_not ?? undefined)}>
                      {speed(e.speed_kmh, e.speed_err_pct)}
                      {e.speed_kmh == null && e.speed_why_not ? <span className="ml-1 text-[10px] text-muted">n/a</span> : null}
                    </td>
                    <td className="tabular-nums">{pct(e.confidence)}{e.interpolated ? " · interpolated" : ""}</td>
                    <td className="text-muted">{e.source?.join(" + ") ?? "vision"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {tab === "insights" && (
          <div className="grid gap-3 md:grid-cols-2">
            {m.insights.length ? m.insights.map((i, k) => <InsightCard key={k} insight={i} match={m} />) : (
              <div className="text-sm text-muted">No insights in this match file. Open the coach report.</div>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}

export default function MatchPage() {
  return (
    <Suspense fallback={<Loading />}>
      <MatchVision />
    </Suspense>
  );
}
