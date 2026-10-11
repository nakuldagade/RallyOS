"use client";

// The Smart Court inside a match's own section: the 3D court of the detected sport, the shots and players of this match once they are
// available, and the court's specifications, all in one place. If the shots cannot be shown to this visitor (a match that belongs
// to its players and coaches), the court and its specifications are still shown, empty.
import Link from "next/link";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { emptyScene } from "@/lib/court3d";
import type { MatchJSON, SportConfig } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { Loading } from "@/components/ui";
import CourtSpecs from "@/components/court3d/CourtSpecs";
import Scene3DPanel from "@/components/court3d/Scene3DPanel";

export function summaryOf(m: MatchJSON) {
  const auto = (m.calibration as unknown as { auto?: { quality?: string } }).auto;
  const cal = m.calibration as unknown as { taps_px?: [number, number][]; focal_px?: number; camera_position_m?: number[]; method?: string; reprojection_error_px?: number | null; note?: string };
  const h = (m.calibration as unknown as { homography?: number[][] }).homography;
  return {
    sport: m.sport, sport_confidence: m.sport_confidence ?? null, sport_source: (m as unknown as { sport_source?: string }).sport_source ?? "",
    calibrated: !!cal.method && cal.method !== "none" && !!h, method: cal.method ?? null, quality: auto?.quality ?? (cal.method === "4-tap" ? "corners given" : null),
    reprojection_error_px: cal.reprojection_error_px ?? null, focal_px: cal.focal_px ?? null, camera_position_m: cal.camera_position_m ?? null,
    corners_px: cal.taps_px ?? null, note: cal.note ?? null, video: { fps: m.video.fps, width: m.video.width, height: m.video.height },
  };
}

export default function MatchSmartCourt({ match, sport, time, mock }: { match: MatchJSON; sport: SportConfig; time: number; mock?: boolean }) {
  const { user } = useAuth();
  const scene = useApi(() => (mock ? Promise.reject(new Error("the sample match has no stored tracking")) : api.matchScene3d(match.match_id)), [match.match_id, user?.id]);
  const summary = summaryOf(match);
  const specs = <div className="mt-5 border-t border-border pt-4"><h3 className="mb-3 text-sm font-semibold">Court specifications</h3><CourtSpecs cfg={sport} summary={summary} /></div>;
  if (scene.loading) return <Loading label="Building the 3D court from this match…" />;
  if (scene.error || !scene.data) {
    const restricted = /log in|belongs/i.test(scene.error ?? "");
    return (
      <><Scene3DPanel role={user?.role ?? "viewer"} now={emptyScene(sport, match.match_id)}
        topRight={
          <div className="card p-4 text-sm">
            <p>{restricted ? "The shots, players and heatmaps of this match are for its players and their coaches. The court it was played on is shown here." : `The shots could not be shown: ${scene.error}. The court is shown here.`}</p>
            {restricted && !user && <Link href="/login" className="btn-primary mt-3 inline-block">Log in</Link>}
          </div>} />{specs}</>
    );
  }
  return <><Scene3DPanel role={user?.role ?? "viewer"} now={scene.data} follow={{ time }} height="h-[min(58vh,560px)] min-h-[340px]" />{specs}</>;
}

export function SmartCourtLink() {
  return <Link href="/courts" className="text-xs text-accent">Open in Smart Courts →</Link>;
}
