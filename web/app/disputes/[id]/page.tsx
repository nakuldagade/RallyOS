"use client";

// FAIR-PLAY REPLAY: clip, landing point + uncertainty ellipse, IN/OUT probability, SHA-256 badge.
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { api, mediaUrl } from "@/lib/api";
import { fmtTime, pct, shortHash } from "@/lib/format";
import { pointSegDist } from "@/lib/geometry";
import { BADMINTON } from "@/lib/sports";
import type { SportConfig } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { Badge, Card, ConfidenceBar, ErrorBox, Loading, PageHeader } from "@/components/ui";
import MiniCourt from "@/components/court/MiniCourt";

export default function DisputePage() {
  const { id } = useParams<{ id: string }>();
  const dispute = useApi(() => api.dispute(id), [id]);
  const [sport, setSport] = useState<SportConfig>(BADMINTON);
  const [clipOk, setClipOk] = useState(true);
  const d = dispute.data;

  useEffect(() => {
    if (!d) return;
    api.match(d.match_id).then((m) => api.sport(m.data.sport)).then(setSport).catch(() => setSport(BADMINTON));
  }, [d]);

  const nearest = useMemo(() => {
    const c = d?.event?.court;
    if (!c) return null;
    let best = { id: "", dist: Infinity };
    for (const l of sport.court.lines) {
      if (l.id === "net") continue;
      const dist = pointSegDist(c, l.p1, l.p2);
      if (dist < best.dist) best = { id: l.id, dist };
    }
    return best;
  }, [d, sport]);

  if (dispute.loading) return <Loading />;
  if (dispute.error || !d) return <ErrorBox message={dispute.error ?? "Dispute not found"} onRetry={dispute.reload} />;

  const ev = d.event;
  const c = ev?.court;
  const [a, b, angle] = ev?.ellipse_m ?? [0.1, 0.1, 0];
  const tooClose = d.call.toUpperCase().startsWith("TOO CLOSE"); // the pipeline decides the call
  const callColor = tooClose ? "#f59e0b" : d.call === "OUT" ? "#f43f5e" : "#22c55e";
  const clip = mediaUrl(d.clip_url);

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader title="Fair-Play Replay" subtitle={<>Close call {d.id} in <Link className="text-accent" href={`/matches/${d.match_id}${ev ? `?t=${ev.t}` : ""}`}>{d.match_id}</Link>{ev ? ` at ${fmtTime(ev.t)}` : ""}</>} />

      <div className="grid gap-4 lg:grid-cols-[1fr_380px]">
        <div className="space-y-4">
          <Card title="Replay clip (6 s, slow motion, trajectory drawn)">
            {clip && clipOk ? (
              <video src={clip} controls playsInline className="w-full rounded-lg bg-black" onError={() => setClipOk(false)} />
            ) : (
              <div className="grid aspect-video place-items-center rounded-lg border border-dashed border-border text-center text-sm text-muted">
                <div>
                  The review clip hasn&apos;t been rendered yet (mock data).<br />
                  The pipeline writes it to <code>{d.clip_url ?? "media/<match>/<dispute>.mp4"}</code>.
                </div>
              </div>
            )}
          </Card>
          <div className="grid gap-4 sm:grid-cols-2">
            <Card title="Full court">
              <MiniCourt sport={sport} className="mx-auto h-[300px] w-full" highlightLines={nearest ? [nearest.id] : []}
                dots={c ? [{ x: c[0], y: c[1], color: callColor }] : []} />
            </Card>
            <Card title="Zoom: landing + uncertainty">
              {c ? (
                <MiniCourt sport={sport} className="mx-auto h-[300px] w-full" focus={{ x: c[0], y: c[1], r: Math.max(0.5, a * 5) }}
                  highlightLines={nearest ? [nearest.id] : []}
                  ellipse={{ x: c[0], y: c[1], a, b, angle, color: callColor }} dots={[{ x: c[0], y: c[1], color: callColor }]} />
              ) : <div className="text-sm text-muted">No landing position.</div>}
            </Card>
          </div>
        </div>

        <div className="space-y-4">
          <Card>
            <div className="label">Call</div>
            <div className="mt-1 text-5xl font-bold" style={{ color: callColor }}>{tooClose ? "TOO CLOSE" : d.call}</div>
            <div className="mt-1 text-sm text-muted">{tooClose ? `Too close to call (${pct(d.prob)})` : `${pct(d.prob)} probability`}</div>
            <div className="mt-3"><ConfidenceBar value={d.prob} tone={tooClose ? "amber" : d.call === "OUT" ? "red" : "accent"} /></div>
            <p className="mt-4 text-xs text-muted">Decision support, not a decision. The probability combines detection noise, calibration error and interpolated frames into the uncertainty ellipse.</p>
          </Card>
          <Card title="Evidence">
            <dl className="space-y-2 text-sm">
              {c && <div className="flex justify-between"><dt className="text-muted">Landing point</dt><dd className="tabular-nums">x {c[0].toFixed(2)} m, y {c[1].toFixed(2)} m</dd></div>}
              {nearest && <div className="flex justify-between"><dt className="text-muted">Nearest line</dt><dd className="tabular-nums">{nearest.id} · {(nearest.dist * 100).toFixed(0)} cm</dd></div>}
              <div className="flex justify-between"><dt className="text-muted">Uncertainty ellipse</dt><dd className="tabular-nums">±{(a * 100).toFixed(0)} × ±{(b * 100).toFixed(0)} cm</dd></div>
              {ev && <div className="flex justify-between"><dt className="text-muted">Event confidence</dt><dd>{pct(ev.confidence)}</dd></div>}
              <div className="flex justify-between"><dt className="text-muted">Status</dt><dd><Badge tone="amber">{d.status}</Badge></dd></div>
            </dl>
          </Card>
          <Card title="Verified match record">
            <div className="text-xs text-muted">SHA-256 of the source video and event log</div>
            <code className="mt-1 block break-all text-xs">{shortHash(d.sha256)}</code>
            <p className="mt-2 text-xs text-muted">Anyone can re-hash the video later to check the record wasn&apos;t edited.</p>
          </Card>
        </div>
      </div>
    </div>
  );
}
