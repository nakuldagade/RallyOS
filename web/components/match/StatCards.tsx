import { num, pct } from "@/lib/format";
import type { MatchJSON, PlayerStats } from "@/lib/types";
import { Stat } from "@/components/ui";

type Metric = { label: string; value: string; hint?: string };

/** Only the metrics the pipeline actually produced for this player. */
function playerMetrics(s: PlayerStats): Metric[] {
  const out: Metric[] = [];
  if (s.distance_m != null) out.push({ label: "Distance", value: `${num(s.distance_m, 0)} m`, hint: "from court positions" });
  if (typeof s.top_speed_mps === "number") out.push({ label: "Top speed", value: `${num(s.top_speed_mps)} m/s`, hint: "movement" });
  if (s.avg_return_to_base_s != null) {
    out.push({ label: "Return to base", value: `${num(s.avg_return_to_base_s, 2)} s`,
      hint: s.pulled_away_n != null ? `after ${s.pulled_away_n} shots that pulled them away; back in time ${pct(s.returned_pct ?? 0)}` : "avg after each shot" });
  } else if (s.stayed_central_n) {
    out.push({ label: "Return to base", value: "stayed central", hint: `${s.stayed_central_n} shots hit from base, none pulled them away` });
  }
  if (s.split_step_n != null && s.split_step_detected != null) {
    out.push({ label: "Split-step", value: `${s.split_step_detected} of ${s.split_step_n}`,
      hint: "opponent shots, from ankle lift: a guide, not a count" });
  } else if (s.split_step_pct != null) out.push({ label: "Split-step", value: pct(s.split_step_pct), hint: "of opponent shots" });
  if (s.fatigue?.enough_data && s.fatigue.return_change_pct != null) {
    out.push({ label: "Recovery over the match", value: `${s.fatigue.return_change_pct > 0 ? "+" : ""}${s.fatigue.return_change_pct}%`,
      hint: `${num(s.fatigue.first_third_return_s, 2)} s → ${num(s.fatigue.last_third_return_s, 2)} s, first to last third` });
  } else if (s.fatigue) {
    out.push({ label: "Fatigue trend", value: "not enough play", hint: s.fatigue.note ?? "needs more shots" });
  }
  if (s.fastest_shot_kmh) out.push({ label: "Fastest shot", value: `≈ ${s.fastest_shot_kmh} km/h`, hint: "average horizontal speed: a lower bound" });
  if (s.avg_smash_kmh) out.push({ label: "Avg smash", value: `≈ ${s.avg_smash_kmh} km/h`, hint: "event-timing estimate" });
  if (typeof s.hits === "number") out.push({ label: "Hits", value: String(s.hits), hint: "vision-only candidates" });
  if (typeof s.tracked_pct === "number") out.push({ label: "Tracked", value: pct(s.tracked_pct), hint: "of sampled frames" });
  if (Array.isArray(s.coverage_m)) out.push({ label: "Court coverage", value: `${s.coverage_m[0]} × ${s.coverage_m[1]} m`, hint: "width × length" });
  return out;
}

export default function StatCards({ match }: { match: MatchJSON }) {
  const m = match.stats.match ?? {};
  const per = match.stats.per_player ?? {};
  const pipe = match.stats.pipeline;
  return (
    <div className="space-y-4">
      {pipe && (
        <div className="rounded-lg border border-border bg-fg/[0.03] p-3 text-xs text-muted">
          Processed on <b>{pipe.device}</b> in {pipe.processing_s} s
          {pipe.players_backend ? <> · players: {pipe.players_backend}</> : null}
          {pipe.players_skipped_reason ? <> · players skipped: {pipe.players_skipped_reason}</> : null}
          {pipe.static_people_ignored?.length ? <> · ignored {pipe.static_people_ignored.length} static {pipe.static_people_ignored.length === 1 ? "person" : "people"} (umpires / line judges / spectators)</> : null}
          {pipe.ignored_detections && Object.keys(pipe.ignored_detections).length ? (
            <> · filtered detections: {Object.entries(pipe.ignored_detections).map(([r, n]) => `${n} ${r}`).join(", ")}</>
          ) : null}
          {pipe.not_computed?.length ? <> · <span className="text-amber-600 dark:text-amber-400">not computed yet: {pipe.not_computed.join(", ")}</span></> : null}
        </div>
      )}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat label="Rallies" value={m.rallies ?? match.rallies.length} />
        <Stat label="Avg rally length" value={`${num(m.avg_rally_hits)} hits`} />
        <Stat label="Longest rally" value={`${m.longest_rally_hits ?? "—"} hits`} />
        <Stat label="Calibration error" value={`${num(match.calibration.reprojection_error_px)} px`} hint={`${match.calibration.method} calibration`} />
      </div>
      {match.players.map((p) => {
        const s = per[String(p.track_id)];
        return (
          <div key={p.track_id}>
            <div className="mb-2 flex items-center gap-2 text-sm font-medium">
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: p.color ?? "#94a3b8" }} /> {p.name}
            </div>
            {s ? (
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {playerMetrics(s).map((m) => <Stat key={m.label} label={m.label} value={m.value} hint={m.hint} />)}
              </div>
            ) : (
              <div className="rounded-lg border border-dashed border-border p-3 text-xs text-muted">
                Not computed for this player yet. Approximate stats are only shown when the pipeline produced them.
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
