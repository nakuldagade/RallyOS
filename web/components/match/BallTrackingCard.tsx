// Where the shuttle track came from and how good it is, stated honestly.
import { pct } from "@/lib/format";
import type { BallStats } from "@/lib/types";
import { Badge, ConfidenceBar } from "@/components/ui";

const TRACKER_LABEL: Record<string, string> = {
  racketvision: "RacketVision TrackNetV3 plug-in",
  geometric: "Geometric tracker (motion + linking)",
};

export default function BallTrackingCard({ ball, calibrated }: { ball: BallStats; calibrated: boolean }) {
  const ref = ball.reference_metrics;
  return (
    <div className="space-y-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{TRACKER_LABEL[ball.tracker] ?? ball.tracker}</span>
        {ball.tracker === "racketvision"
          ? <Badge tone="green" title="Pretrained weights used as released; nothing trained or fine-tuned">inference only</Badge>
          : <Badge tone="green" title="Motion, size and brightness rules; no trained ball detector">no training</Badge>}
      </div>
      <div>
        <div className="mb-1 flex justify-between text-xs text-muted">
          <span>Shuttle found in {ball.detected_frames} / {ball.frames} frames</span>
          <span>{pct(ball.detected_pct)}</span>
        </div>
        <ConfidenceBar value={ball.detected_pct} />
      </div>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
        <dt className="text-muted">Gap-filled frames</dt><dd className="text-right tabular-nums">{ball.interpolated_frames} (flagged)</dd>
        <dt className="text-muted">Longest gap</dt><dd className="text-right tabular-nums">{ball.longest_gap_s} s</dd>
        {ball.mean_conf != null && (<><dt className="text-muted">Mean confidence</dt><dd className="text-right tabular-nums">{pct(ball.mean_conf)}</dd></>)}
        {ball.hit_candidates != null && (<><dt className="text-muted">Hit candidates</dt><dd className="text-right tabular-nums">{ball.hit_candidates}</dd></>)}
      </dl>
      {ref && (
        <div className="rounded-lg border border-border p-2.5">
          <div className="label mb-1">Reference accuracy</div>
          <div className="flex flex-wrap gap-1.5">
            {ref.precision != null && <Badge>precision {pct(ref.precision)}</Badge>}
            {ref.recall != null && <Badge>recall {pct(ref.recall)}</Badge>}
            {ref.f1 != null && <Badge>F1 {ref.f1.toFixed(2)}</Badge>}
            {ref.mean_dist != null && <Badge>±{ref.mean_dist.toFixed(1)} px @512×288</Badge>}
          </div>
          {ball.reference_note && <p className="mt-1.5 text-[11px] text-muted">{ball.reference_note}</p>}
        </div>
      )}
      <p className="text-[11px] text-muted">
        Hit candidates come from sudden changes in the shuttle&apos;s path; with a soundtrack, audio onsets confirm them and add hits hidden in tracking gaps.
        {calibrated
          ? " Shuttle speeds and landing calls are not computed yet, so none are shown."
          : " No court calibration on this clip, so positions are in video pixels: no speeds, landing calls or player sides are claimed."}
      </p>
    </div>
  );
}
