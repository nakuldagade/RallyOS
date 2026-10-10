"use client";

// Upload a clip, calibrate with 4 taps, watch the real pipeline's progress over SSE.
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { sportLabel } from "@/lib/sports";
import type { Job, SportConfig } from "@/lib/types";
import { Badge, Card, ConfidenceBar, PageHeader } from "@/components/ui";
import CourtTapper from "@/components/upload/CourtTapper";

const STAGES = ["calibrate", "players", "ball", "audio", "rallies", "analytics", "render"];
const STAGE_TEXT: Record<string, string> = {
  calibrate: "Court calibration (4 taps)",
  players: "Players + pose (pretrained YOLO11n-pose) and shuttle candidates",
  ball: "Shuttle trajectory (motion + linking)",
  audio: "Hit onsets from audio",
  rallies: "Hits (shuttle path + nearest wrist) and rallies",
  analytics: "Distance, speed and coverage per player",
  render: "Match record + tracks for the replay",
};

export default function UploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const [sport, setSport] = useState("badminton");
  const [sports, setSports] = useState<SportConfig[]>([]);
  const [taps, setTaps] = useState<[number, number][] | null>(null);
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

  const start = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    setJob(null);
    try {
      const { job_id } = await api.upload(file, sport, { taps, nearName, farName });
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

  const stageIdx = job?.stage ? STAGES.indexOf(job.stage) : -1;
  const elapsed = job?.started ? Math.max(0, Math.round(now / 1000 - job.started)) : 0;

  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader title="Analyse a match" subtitle="Upload a phone video, tap the 4 court corners, and RallyOS processes it on this machine." />
      <Card>
        <div className="space-y-4">
          <label className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-border p-6 text-center hover:border-accent">
            <span className="text-3xl">🎥</span>
            <span className="text-sm font-medium">{file ? file.name : "Choose a video (MP4 / H.264 plays best in the browser)"}</span>
            <span className="text-xs text-muted">{file ? `${(file.size / 1e6).toFixed(1)} MB` : "Fixed camera behind the baseline, 2–3 m high, all 4 corners visible. Short clips (10–60 s) process fastest on CPU."}</span>
            <input type="file" accept="video/*" className="hidden" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setJob(null); }} />
          </label>

          {file && (
            <div>
              <div className="label mb-2">Court calibration</div>
              <CourtTapper file={file} onChange={setTaps} />
              <p className="mt-1 text-xs text-muted">Optional but recommended: it gives court positions (top-down view, distance, heatmap) and filters out umpires and spectators. Automatic court detection isn&apos;t built yet.</p>
            </div>
          )}

          <div className="grid gap-3 sm:grid-cols-3">
            <div>
              <div className="label mb-1">Sport</div>
              <select className="input w-full" value={sport} onChange={(e) => setSport(e.target.value)}>
                {(sports.length ? sports : [{ sport: "badminton" } as SportConfig]).map((s) => (
                  <option key={s.sport} value={s.sport}>{s.display_name ?? sportLabel(s.sport)}</option>
                ))}
              </select>
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
            <button className="btn-primary" disabled={!file || busy} onClick={start}>{busy ? "Processing…" : "Upload & analyse"}</button>
            {file && !taps && <span className="text-xs text-amber-600 dark:text-amber-400">No calibration: players and shuttle are still tracked, but in video pixels only.</span>}
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
          </span>}>
          <ConfidenceBar value={job.progress} tone={job.status === "failed" ? "red" : "accent"} />
          <ol className="mt-4 space-y-2">
            {STAGES.map((s, i) => {
              const skipped = job.skipped?.includes(s) || (s === "calibrate" && job.calibrated === false);
              const done = !skipped && (job.status === "done" || i < stageIdx);
              const active = !skipped && i === stageIdx && job.status === "running";
              return (
                <li key={s} className="flex items-center gap-3 text-sm">
                  <span className={`grid h-6 w-6 place-items-center rounded-full text-xs ${done ? "bg-accent text-accent-fg" : active ? "animate-pulse bg-amber-500 text-black" : "bg-fg/10 text-muted"}`}>
                    {done ? "✓" : skipped ? "–" : i + 1}
                  </span>
                  <span className={done || active ? "" : "text-muted"}>{STAGE_TEXT[s]}</span>
                  {skipped && <Badge>{s === "calibrate" ? "no taps" : "not built yet"}</Badge>}
                  {active && s === "players" && <span className="text-xs text-muted">{Math.round(((job.progress - 0.05) / 0.8) * 100)}%</span>}
                </li>
              );
            })}
          </ol>
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
