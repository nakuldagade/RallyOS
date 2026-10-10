"use client";

// "Court detected": the moment calibration and detection are done, the detected sport's 3D court and its specifications, before the
// rest of the analysis has run. Used on the upload page (job.detected) and the live capture page (the first chunk's calibration).
import { useRef } from "react";
import { api } from "@/lib/api";
import { emptyScene } from "@/lib/court3d";
import { sportLabel } from "@/lib/sports";
import type { CourtSummary, SportConfig } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { Badge, Card, ErrorBox, Loading } from "@/components/ui";
import dynamic from "next/dynamic";
import type { CameraPreset, ViewerHandle } from "@/components/court3d/CourtViewer";
import CourtSpecs from "@/components/court3d/CourtSpecs";

const CourtViewer = dynamic(() => import("@/components/court3d/CourtViewer"), { ssr: false, loading: () => <Loading label="Loading the 3D court…" /> });
const PRESETS: { id: CameraPreset; label: string }[] = [{ id: "behind", label: "Behind baseline" }, { id: "broadcast", label: "Broadcast" }, { id: "side", label: "Side" }, { id: "top", label: "Top-down" }];

export default function DetectedCourt({ summary }: { summary: Partial<CourtSummary> & { sport: string } }) {
  const cfg = useApi(() => api.sport(summary.sport), [summary.sport]);
  const viewer = useRef<ViewerHandle>(null);
  if (cfg.loading) return <Loading label="Loading the detected court…" />;
  if (cfg.error || !cfg.data) return <ErrorBox message={cfg.error ?? "No court"} onRetry={cfg.reload} />;
  const c = cfg.data as SportConfig;
  const scene = emptyScene(c);
  return (
    <Card title={`Court detected: ${sportLabel(summary.sport)}${summary.sport_confidence != null ? ` · ${Math.round(summary.sport_confidence * 100)}% fit` : ""}`}
      actions={<Badge tone={summary.calibrated ? "green" : "amber"}>{summary.calibrated ? "camera calibrated" : "court not calibrated yet"}</Badge>}>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <div className="relative overflow-hidden rounded-xl border border-border bg-[#0b1220]">
          <CourtViewer handle={viewer} className="h-[340px] w-full" sport={c.sport} court={scene.court} objectSize={scene.object_size_m} layers={[]} duration={1}
            playing={false} speed={1} loop={false} showPaths />
          <div className="absolute left-3 top-3 flex flex-wrap gap-1.5">
            {PRESETS.map((p) => <button key={p.id} onClick={() => viewer.current?.setPreset(p.id)} className="rounded-md bg-black/50 px-2 py-1 text-xs text-white hover:bg-black/70">{p.label}</button>)}
          </div>
        </div>
        <CourtSpecs cfg={c} summary={summary} />
      </div>
      <p className="mt-2 text-xs text-muted">Shown as soon as the court was found, while the players, the shuttle and the rest are still being analysed. The shots and players are added to this court on the match page when the analysis is done.</p>
    </Card>
  );
}
