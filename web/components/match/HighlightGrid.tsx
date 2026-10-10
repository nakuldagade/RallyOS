"use client";

// Highlight clips of the analysed matches, newest first: used on the home page (a few) and on /highlights (all).
import Link from "next/link";
import { api, mediaUrl } from "@/lib/api";
import { fmtTime } from "@/lib/format";
import { sportLabel } from "@/lib/sports";
import { useApi } from "@/lib/useApi";
import { Badge, ErrorBox, Loading } from "@/components/ui";
import { OUTCOME_LABEL } from "@/components/match/HighlightCard";

export default function HighlightGrid({ limit }: { limit?: number }) {
  const res = useApi(() => api.highlights(), []);
  if (res.loading) return <Loading />;
  if (res.error || !res.data) return <ErrorBox message={res.error ?? "No highlights"} onRetry={res.reload} />;
  const items = limit ? res.data.highlights.slice(0, limit) : res.data.highlights;
  if (items.length === 0) {
    return <p className="text-sm text-muted">No highlight yet. Every new analysis (an uploaded video or a live recording) cuts one automatically, once a shot could be rated.</p>;
  }
  return (
    <div className="space-y-2">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {items.map((it) => {
          const h = it.highlight;
          return (
            <div key={it.match_id} className="card overflow-hidden">
              <video src={mediaUrl(h.clip_url) ?? undefined} controls loop muted playsInline preload="metadata" className="aspect-video w-full bg-black" />
              <div className="space-y-1.5 p-3 text-sm">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium capitalize">{it.best_player ?? "Player"}: {h.shot ?? "shot"}</span>
                  <span className="tabular-nums text-muted">{h.score}/100</span>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  <Badge tone={h.outcome === "winner" || h.outcome === "forced_error" ? "green" : h.outcome === "error" ? "red" : "neutral"}>{OUTCOME_LABEL[h.outcome] ?? h.outcome}</Badge>
                  {it.sport && <Badge>{sportLabel(it.sport)}</Badge>}
                </div>
                <div className="text-xs text-muted">{it.players.filter(Boolean).join(" vs ")} · at {fmtTime(h.t)} in the match</div>
                <Link href={`/matches/${it.match_id}?t=${h.t}`} className="text-xs text-accent">Open the match →</Link>
              </div>
            </div>
          );
        })}
      </div>
      {res.data.matches_without > 0 && !limit && (
        <p className="text-xs text-muted">{res.data.matches_without} analysed match{res.data.matches_without === 1 ? " has" : "es have"} no highlight: no shot could be rated (court not calibrated, no hits found) or the source video is gone.</p>
      )}
    </div>
  );
}
