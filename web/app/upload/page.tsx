"use client";

// Upload a clip. The court is found automatically on a preview frame (drag a corner if it is off, or tap by
// hand); the real pipeline's progress streams back over SSE, one row per stage, on the same clock as the bar.
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { sportLabel } from "@/lib/sports";
import type { CourtDetection, Job, JobStage, SportConfig } from "@/lib/types";
import { Badge, Card, ConfidenceBar, PageHeader } from "@/components/ui";
import DetectedCourt from "@/components/court3d/DetectedCourt";
import CourtTapper from "@/components/upload/CourtTapper";

const STAGE_HINT: Record<string, string> = {
  calibrate: "Court lines + sport template, or your corners",
  players: "Pretrained YOLO11n-pose on the court area, plus shuttle candidates, in one pass over the video",
  audio: "Spectral-flux onsets from the soundtrack",
  ball: "Motion + physics-consistent linking, no trained ball detector",
  rallies: "Shuttle path + nearest wrist, fused with the sounds",
  outcome: "Landing, IN/OUT with uncertainty, suggested winner and score",
  analytics: "Distance, speed, coverage and zones per player",
  render: "match.json, tracks, review clips, SHA-256",
};

function StageRow({ st, index }: { st: JobStage; index: number }) {
  const done = st.state === "done";
  const active = st.state === "active";
  const skipped = st.state === "skipped";
  const failed = st.state === "failed";
  return (
    <li className="flex items-start gap-3 text-sm">
      <span className={`mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full text-xs transition-colors ${
        done ? "bg-accent text-accent-fg" : active ? "animate-pulse bg-amber-500 text-black" : failed ? "bg-rose-500 text-white"
          : "bg-fg/10 text-muted"}`}>
        {done ? "✓" : skipped ? "–" : failed ? "!" : index + 1}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className={done || active || failed ? "font-medium" : "text-muted"}>{st.label}</span>
          {skipped && <Badge title={st.note ?? undefined}>skipped</Badge>}
          {active && st.frac > 0 && <span className="text-xs tabular-nums text-muted">{Math.round(st.frac * 100)}%</span>}
          {(done || active) && st.seconds != null && <span className="ml-auto text-xs tabular-nums text-muted">{st.seconds.toFixed(1)} s</span>}
        </div>
        <div className="text-xs text-muted">
          {active || skipped || failed ? (st.note ?? STAGE_HINT[st.id]) : STAGE_HINT[st.id]}
        </div>
        {active && st.frac > 0 && (
          <div className="mt-1 h-1 w-full overflow-hidden rounded bg-fg/10">
            <div className="h-1 rounded bg-amber-500 transition-all" style={{ width: `${Math.round(st.frac * 100)}%` }} />
          </div>
        )}
      </div>
    </li>
  );
}

export default function UploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const [sport, setSport] = useState("auto");           // "auto" = the court template that fits best decides the sport
  const [sports, setSports] = useState<SportConfig[]>([]);
  const [taps, setTaps] = useState<[number, number][] | null>(null);
  const [detected, setDetected] = useState<CourtDetection | null>(null);
  const [finding, setFinding] = useState(false);       // the court preview is running: wait for it, or it competes with the analysis
  const [nearName, setNearName] = useState("");
  const [farName, setFarName] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(Date.now());
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    api.sports().then(setSports).catch(() => setSports([]));
    return () => esRef.current?.close();
  }, []);

  useEffect(() => {
    if (!busy) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [busy]);

  const effectiveSport = sport === "auto" ? (detected?.sport ?? "auto") : sport;

  const start = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    setJob(null);
    try {
      const { job_id } = await api.upload(file, effectiveSport, { taps, nearName, farName });
      esRef.current?.close();
      const es = new EventSource(api.jobStreamUrl(job_id));
      esRef.current = es;
      es.onmessage = (ev) => {
        const j = JSON.parse(ev.data) as Job;
        setJob(j);
        if (j.status === "done" || j.status === "failed") {
          es.close();
          setBusy(false);
        }
      };
      es.onerror = () => {
        es.close();
        setBusy(false);
      };
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  const elapsed = job?.started ? Math.max(0, Math.round(now / 1000 - job.started)) : 0;

  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader title="Analyse a match" subtitle="Upload a phone video. RallyOS finds the court and the sport itself, then processes the clip on this machine." />
      <Card>
        <div className="space-y-4">
          <label className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-border p-6 text-center hover:border-accent">
            <span className="text-3xl">🎥</span>
            <span className="text-sm font-medium">{file ? file.name : "Choose a video (MP4 / H.264 plays best in the browser)"}</span>
            <span className="text-xs text-muted">{file ? `${(file.size / 1e6).toFixed(1)} MB` : "Fixed camera behind the baseline, 2–3 m high, all 4 corners visible. Short clips (10–60 s) process fastest on CPU."}</span>
            <input type="file" accept="video/*" className="hidden"
              onChange={(e) => { setFile(e.target.files?.[0] ?? null); setJob(null); setTaps(null); setDetected(null); setFinding(!!e.target.files?.[0]); e.target.value = ""; }} />
          </label>

          {file && (
            <div>
              <div className="label mb-2">Court calibration</div>
              <CourtTapper file={file} sport={sport} onChange={setTaps} onDetected={setDetected} onBusy={setFinding} />
              <p className="mt-1 text-xs text-muted">
                Court positions (top-down view, distance, heatmap, line calls, score) need the court, and players are only looked for on and around it, so umpires and spectators are ignored.
                {" "}If no corners are set here, the court is searched for automatically while analysing.
              </p>
            </div>
          )}

          <div className="grid gap-3 sm:grid-cols-3">
            <div>
              <div className="label mb-1">Sport</div>
              <select className="input w-full" value={sport} onChange={(e) => setSport(e.target.value)}>
                <option value="auto">Auto-detect sport</option>
                {sports.map((s) => (
                  <option key={s.sport} value={s.sport}>{s.display_name ?? sportLabel(s.sport)}</option>
                ))}
              </select>
              {sport === "auto" && detected?.sport && <div className="mt-1 text-xs text-muted">Detected: {sportLabel(detected.sport)}</div>}
            </div>
            <div>
              <div className="label mb-1">Near player (closest to camera)</div>
              <input className="input w-full" placeholder="Near player" value={nearName} onChange={(e) => setNearName(e.target.value)} />
            </div>
            <div>
              <div className="label mb-1">Far player</div>
              <input className="input w-full" placeholder="Far player" value={farName} onChange={(e) => setFarName(e.target.value)} />
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <button className="btn-primary" disabled={!file || busy || finding} onClick={start}
              title={finding ? "Wait for the court to be found, so the analysis can use it" : undefined}>
              {busy ? "Processing…" : finding ? "Finding the court…" : "Upload & analyse"}
            </button>
            {file && taps && <span className="text-xs text-emerald-600 dark:text-emerald-400">✓ Using these 4 corners: players and shuttle are searched on the court only</span>}
            {file && !taps && <span className="text-xs text-amber-600 dark:text-amber-400">No corners set: the court will be searched for automatically (applied only if the fit is clearly good).</span>}
          </div>
          {error && <div className="text-sm text-rose-500">{error}</div>}
        </div>
      </Card>

      {job && (
        <Card className="mt-4" title={
          <span className="flex flex-wrap items-center gap-2">
            Job {job.job_id}
            {job.simulated && <Badge tone="amber">simulated pipeline</Badge>}
            {job.status === "running" && <span className="text-xs font-normal text-muted">{elapsed} s elapsed</span>}
            <span className="ml-auto text-sm font-normal tabular-nums">{Math.round(job.progress * 100)}%</span>
          </span>}>
          {job.note && <p className="mb-2 text-sm text-amber-600 dark:text-amber-400">Queued: {job.note}.</p>}
          <ConfidenceBar value={job.progress} tone={job.status === "failed" ? "red" : "accent"} />
          <ol className="mt-4 space-y-3">
            {(job.stages ?? []).map((st, i) => <StageRow key={st.id} st={st} index={i} />)}
          </ol>
          {job.detected && <div className="mt-4"><DetectedCourt summary={job.detected} /></div>}
          {job.status === "done" && job.match_id && (
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <Link href={`/matches/${job.match_id}`} className="btn-primary">Open your match →</Link>
              {job.simulated && <span className="text-xs text-muted">Simulated run: this opens the demo match.</span>}
            </div>
          )}
          {job.status === "failed" && <div className="mt-3 text-sm text-rose-500">Failed: {job.error}. Stage outputs written so far are kept on disk.</div>}
        </Card>
      )}
    </div>
  );
}
