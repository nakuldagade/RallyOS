"use client";

// The specifications of the court the analysis detected: the sport and how sure the detection was, the court's measurements, net,
// walls, ball, what the camera calibration found, and whether the video meets the sport's capture advice. Everything is read from
// the sport's YAML and from what the analysis stored; nothing is typed in here.
import { sportLabel } from "@/lib/sports";
import type { CourtSummary, SportConfig } from "@/lib/types";
import { Badge } from "@/components/ui";

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return <div className="flex items-baseline justify-between gap-4 py-1.5"><dt className="shrink-0 text-muted">{k}</dt><dd className="min-w-0 text-right tabular-nums [overflow-wrap:anywhere]">{v}</dd></div>;
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="mb-4 break-inside-avoid"><h4 className="label mb-1">{title}</h4><dl className="divide-y divide-border text-sm">{children}</dl></section>;
}

export default function CourtSpecs({ cfg, summary, mockNote }: { cfg: SportConfig; summary?: Partial<CourtSummary> | null; mockNote?: string }) {
  const c = cfg.court;
  const lines = c.lines.filter((l) => l.id !== "net");
  const hasNet = c.lines.some((l) => l.id === "net");
  const table = cfg.view3d?.plane_height_m;
  const sc = cfg.scoring as Record<string, unknown>;
  const scoring = [sc.type && String(sc.type).replace(/_/g, " "), sc.points_to_win && `to ${sc.points_to_win}`, sc.win_by && `win by ${sc.win_by}`, sc.games_to_win && `best of ${Number(sc.games_to_win) * 2 - 1}`].filter(Boolean).join(", ");
  const v = summary?.video;
  const fps = v?.fps, minFps = cfg.capture?.min_fps, recFps = cfg.capture?.recommended_fps;
  const fpsTone = fps == null || minFps == null ? "neutral" : fps >= (recFps ?? minFps) ? "green" : fps >= minFps ? "amber" : "red";
  return (
    <div className="grid gap-x-10 gap-y-1 [grid-template-columns:repeat(auto-fill,minmax(260px,1fr))]">
      <Group title="Sport and detection">
        <Row k="Sport" v={<b>{cfg.display_name ?? sportLabel(cfg.sport)}</b>} />
        {summary && <Row k="How it was chosen" v={summary.sport_source ?? "—"} />}
        {summary?.sport_confidence != null && <Row k="Detection fit" v={`${Math.round(summary.sport_confidence * 100)}%`} />}
        {summary?.quality && <Row k="Court fit" v={<Badge tone={summary.quality === "check" ? "amber" : "green"}>{summary.quality}</Badge>} />}
      </Group>
      <Group title={table ? "Table and net" : "Court and net"}>
        <Row k={table ? "Table (length × width)" : "Court (length × width)"} v={`${c.length} × ${c.width} m`} />
        {table ? <Row k="Table top height" v={`${table} m above the floor`} /> : null}
        <Row k="Lines drawn" v={`${lines.length}`} />
        {hasNet && cfg.net && <Row k="Net height" v={`${cfg.net.height_center ?? "—"} m centre${cfg.net.height_post != null && cfg.net.height_post !== cfg.net.height_center ? `, ${cfg.net.height_post} m posts` : ""}`} />}
        {cfg.net?.overhang_m != null && <Row k="Net overhang" v={`${cfg.net.overhang_m} m each side`} />}
        {c.zones && <Row k="Zones" v={Object.entries(c.zones).map(([k, z]) => `${k}${z.y_from_net_m ? ` ${z.y_from_net_m[0]}–${z.y_from_net_m[1]} m` : ""}`).join(" · ")} />}
        {c.base_position && <Row k="Base position" v={`${c.base_position[0]}, ${c.base_position[1]} m`} />}
      </Group>
      {cfg.walls && cfg.walls.length > 0 && (
        <Group title="Walls">
          {cfg.walls.map((w) => (
            <Row key={w.id} k={w.id.replace(/_/g, " ")} v={[w.material, w.height_m != null ? `${w.height_m} m high` : w.out_line_m != null ? `out line ${w.out_line_m} m` : w.out_line_from_m != null ? `out line ${w.out_line_from_m}→${w.out_line_to_m} m` : null,
              w.lines?.length ? `${w.lines.length} marked lines` : null].filter(Boolean).join(", ") || w.plane} />
          ))}
        </Group>
      )}
      <Group title="Ball">
        <Row k={cfg.projectile.kind === "shuttle" ? "Shuttle" : "Ball"} v={`${(cfg.projectile.size_m * 100).toFixed(1)} cm`} />
        {cfg.projectile.motion_model && <Row k="Motion model" v={cfg.projectile.motion_model.replace(/_/g, " ") + (cfg.projectile.terminal_velocity_mps ? `, terminal velocity ${cfg.projectile.terminal_velocity_mps} m/s` : "")} />}
        <Row k="Bounces / walls" v={`${cfg.projectile.bounces ? "bounces" : "no bounce"}${cfg.projectile.wall_rebounds ? ", wall rebounds" : ""}`} />
        {cfg.projectile.speed_range_kmh && <Row k="Speed range" v={`${cfg.projectile.speed_range_kmh[0]}–${cfg.projectile.speed_range_kmh[1]} km/h`} />}
        {scoring && <Row k="Scoring" v={scoring} />}
      </Group>
      {summary && (
        <Group title="Camera calibration">
          <Row k="Calibrated" v={summary.calibrated ? "yes" : <span className="text-amber-500">no: tap the 4 corners</span>} />
          {summary.method && <Row k="Method" v={summary.method === "auto" ? "automatic (Court Fingerprint)" : summary.method === "4-tap" ? "from the four corners" : summary.method} />}
          {summary.reprojection_error_px != null && <Row k="Line fit error" v={`${summary.reprojection_error_px} px`} />}
          {summary.focal_px != null && <Row k="Focal length" v={`${Math.round(summary.focal_px)} px`} />}
          {summary.camera_position_m && <Row k="Camera position" v={summary.camera_position_m.map((x) => x.toFixed(1)).join(", ") + " m"} />}
          {summary.corners_px && <Row k="Corners (px)" v={summary.corners_px.map((p) => `${Math.round(p[0])},${Math.round(p[1])}`).join("  ")} />}
          {summary.note && <Row k="Note" v={<span className="text-amber-500">{summary.note}</span>} />}
        </Group>
      )}
      {v && (
        <Group title="Video against the capture advice">
          <Row k="Video" v={`${v.width}×${v.height} at ${Math.round(v.fps * 10) / 10} fps${v.fps ? ` · ${Math.round(1000 / v.fps)} ms a frame` : ""}`} />
          {minFps != null && <Row k="Recommended" v={<span className="flex flex-wrap items-center justify-end gap-2"><Badge tone={fpsTone}>{fpsTone === "green" ? "meets it" : fpsTone === "amber" ? "above the minimum" : fpsTone === "red" ? "below the minimum" : "n/a"}</Badge>{minFps}+ fps, ideally {recFps}</span>} />}
          {cfg.capture?.camera && <Row k="Camera setup" v={cfg.capture.camera} />}
        </Group>
      )}
      {mockNote && <p className="mt-2 text-xs text-muted">{mockNote}</p>}
    </div>
  );
}
