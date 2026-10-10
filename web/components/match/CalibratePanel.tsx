"use client";

// Calibrate an already-uploaded match: tap the 4 court corners on its video, then re-run the pipeline on it.
import { useEffect, useRef, useState } from "react";
import { api, mediaUrl } from "@/lib/api";
import type { MatchJSON } from "@/lib/types";
import { ConfidenceBar } from "@/components/ui";
import CourtTapper from "@/components/upload/CourtTapper";

interface Job { status: string; stage?: string | null; progress: number; error?: string | null }

export default function CalibratePanel({ match, onDone }: { match: MatchJSON; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [taps, setTaps] = useState<[number, number][] | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const es = useRef<EventSource | null>(null);
  useEffect(() => () => es.current?.close(), []);
  const recal = match.calibration.method !== "none";

  const run = async () => {
    if (!taps) return;
    setError(null);
    try {
      const { job_id } = await api.recalibrate(match.match_id, taps);
      setJob({ status: "queued", progress: 0 });
      es.current?.close();
      const s = new EventSource(api.jobStreamUrl(job_id));
      es.current = s;
      s.onmessage = (ev) => {
        const j = JSON.parse(ev.data) as Job;
        setJob(j);
        if (j.status === "done") { s.close(); setOpen(false); setJob(null); onDone(); }
        if (j.status === "failed") s.close();
      };
      s.onerror = () => s.close();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  if (!open) {
    return (
      <button className={recal ? "btn-ghost py-1 text-xs" : "btn-primary py-1.5 text-sm"} onClick={() => setOpen(true)}>
        {recal ? "Re-calibrate court" : "Calibrate court (4 taps)"}
      </button>
    );
  }
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted">
        The court is found automatically; drag any corner that is off (or click the 4 outer corners by hand). RallyOS then re-analyses this clip: players and the shuttle are
        only searched on and around the court, and court positions, heatmaps, line calls and the score become available.
      </p>
      <CourtTapper src={mediaUrl(match.video.src)} sport={match.sport} onChange={setTaps} />
      <div className="flex flex-wrap items-center gap-2">
        <button className="btn-primary py-1.5" disabled={!taps || (job !== null && job.status !== "failed")} onClick={run}>
          {job && job.status !== "failed" ? "Re-analysing…" : "Re-analyse with this calibration"}
        </button>
        <button className="btn-ghost py-1.5" onClick={() => { setOpen(false); setJob(null); }}>Cancel</button>
      </div>
      {job && job.status !== "failed" && (
        <div>
          <div className="mb-1 flex justify-between text-xs text-muted"><span>{job.stage ?? "queued"}</span><span>{Math.round(job.progress * 100)}%</span></div>
          <ConfidenceBar value={job.progress} />
          <p className="mt-1 text-xs text-muted">Runs on this laptop&apos;s CPU: roughly 1.5–2.5× the clip length.</p>
        </div>
      )}
      {(error || job?.error) && <div className="text-sm text-rose-500">{error ?? job?.error}</div>}
    </div>
  );
}
