"use client";

// The 3D Smart Court of a live session: the detected court with the players, the reconstructed shot paths and the heatmaps of
// everything analysed so far. It refreshes whenever another chunk has been analysed, and once more when the match is finalised.
// Before any chunk has been analysed it shows the detected court and its specifications (DetectedCourt).
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { LiveState } from "@/lib/live";
import type { Scene3DData } from "@/lib/court3d";
import type { CourtSummary } from "@/lib/types";
import { Badge, Card } from "@/components/ui";
import DetectedCourt from "@/components/court3d/DetectedCourt";
import Scene3DPanel from "@/components/court3d/Scene3DPanel";

export default function LiveSmartCourt({ live, summary }: { live: LiveState; summary: Partial<CourtSummary> & { sport: string } }) {
  const [scene, setScene] = useState<Scene3DData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const processed = live.chunks.filter((c) => c.state === "processed").length;
  const finalised = live.status === "done" || live.status === "finalising";
  const id = live.sessionId;

  useEffect(() => {
    if (!id || !processed) return;
    let alive = true;
    api.liveScene3d(id).then((s) => { if (alive) { setScene(s); setError(null); } })
      .catch((e) => { if (alive) setError(e instanceof Error ? e.message : String(e)); });
    return () => { alive = false; };
  }, [id, processed, finalised, live.events.length]);

  const shots = scene?.flights.length ?? 0;
  const nobody = useMemo(() => !scene || scene.players.length === 0, [scene]);
  if (!scene) return <DetectedCourt summary={summary} />;
  return (
    <Card title="Live Smart Court (3D)" actions={
      <div className="flex items-center gap-2">
        {live.status !== "done" && <Badge tone="amber" title="Computed while the match is being played; recomputed over the whole match when it ends">provisional</Badge>}
        <Badge>{shots} shot path{shots === 1 ? "" : "s"} · {processed} chunk{processed === 1 ? "" : "s"} analysed</Badge>
      </div>}>
      <Scene3DPanel role="viewer" now={scene} height="h-[min(52vh,480px)] min-h-[320px]" />
      {nobody && <p className="mt-2 text-xs text-muted">No player has been tracked on the court yet.</p>}
      {error && <p className="mt-2 text-xs text-amber-600">The 3D view could not be refreshed: {error}</p>}
    </Card>
  );
}
