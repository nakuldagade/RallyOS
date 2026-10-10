"use client";

// Record live: press Start once, the phone keeps cutting 5-second chunks by itself and the dashboard fills while the match
// is played. One Stop button ends the match (not a chunk). Hands-off after Start: the screen is kept awake and every chunk is
// buffered on the device until the server has it, so a dropped network only delays the numbers.
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { API, api } from "@/lib/api";
import { Capture, browserHttp, mediaRecorderFactory } from "@/lib/capture";
import { useLive } from "@/lib/live";
import { IdbStore } from "@/lib/outbox";
import type { UploaderStatus } from "@/lib/outbox";
import { pickMime } from "@/lib/segmenter";
import { BADMINTON, sportLabel } from "@/lib/sports";
import type { CourtDetection, SportConfig } from "@/lib/types";
import { Badge, Card, ErrorBox, PageHeader } from "@/components/ui";
import LiveDashboard from "@/components/live/LiveDashboard";
import DetectedCourt from "@/components/court3d/DetectedCourt";

type Pt = [number, number];
const CORNER_NAMES = ["near-left", "near-right", "far-right", "far-left"];
const CORNER_COLORS = ["#22c55e", "#3b82f6", "#f59e0b", "#ef4444"];
const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

interface CameraInfo { w: number; h: number; fps: number | null }

export default function CapturePage() {
  const router = useRouter();
  const { state, dispatch, connect } = useLive();
  const stateRef = useRef(state);
  stateRef.current = state;

  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const capRef = useRef<Capture | null>(null);
  const wakeRef = useRef<{ release: () => Promise<void> } | null>(null);
  const storeRef = useRef<IdbStore | null>(null);

  const [sports, setSports] = useState<SportConfig[]>([]);
  const [sport, setSport] = useState("auto");
  const [sportCfg, setSportCfg] = useState<SportConfig>(BADMINTON);
  const [camera, setCamera] = useState<CameraInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [phase, setPhase] = useState<"setup" | "recording" | "finalising">("setup");
  const [elapsed, setElapsed] = useState(0);
  const [corners, setCorners] = useState<Pt[]>([]);
  const [marking, setMarking] = useState(false);
  const [drag, setDrag] = useState<number | null>(null);
  const [cornersSent, setCornersSent] = useState(false);
  const [net, setNet] = useState<UploaderStatus>({ pending: 0, online: true, sent: 0, failed: 0 });
  const [hidden, setHidden] = useState<{ since: number; total: number } | null>(null);
  const [wake, setWake] = useState<"off" | "on" | "unsupported">("off");
  const [persistent, setPersistent] = useState(true);
  const [storageMode, setStorageMode] = useState<string | null>(null);
  const [check, setCheck] = useState<{ busy: boolean; result?: CourtDetection; error?: string } | null>(null);
  const t0Ref = useRef(0);

  useEffect(() => { api.sports().then(setSports).catch(() => setSports([])); }, []);
  useEffect(() => {
    if (state.sport) api.sport(state.sport).then(setSportCfg).catch(() => setSportCfg(BADMINTON));
  }, [state.sport]);

  // --- camera -----------------------------------------------------------------------------------------------------
  const openCamera = async () => {
    setError(null);
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error("This browser cannot open the camera here. Camera access needs https or localhost.");
      if (typeof MediaRecorder === "undefined") throw new Error("This browser has no MediaRecorder, so it cannot record chunks.");
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1080 }, frameRate: { ideal: 60 } },
        audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },     // hits are short clicks: do not filter them out
      });
      streamRef.current = stream;
      const st = stream.getVideoTracks()[0].getSettings();
      setCamera({ w: st.width ?? 0, h: st.height ?? 0, fps: st.frameRate ? Math.round(st.frameRate) : null });
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => undefined);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  useEffect(() => () => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    void wakeRef.current?.release().catch(() => undefined);
  }, []);

  // --- keeping the screen on, noticing a hidden tab ---------------------------------------------------------------
  const requestWake = useCallback(async () => {
    const wl = (navigator as unknown as { wakeLock?: { request: (t: "screen") => Promise<{ release: () => Promise<void> }> } }).wakeLock;
    if (!wl) { setWake("unsupported"); return; }
    try { wakeRef.current = await wl.request("screen"); setWake("on"); } catch { setWake("off"); }
  }, []);

  useEffect(() => {
    if (phase !== "recording") return;
    let since = 0;
    let total = 0;
    const onVis = () => {
      if (document.hidden) { since = performance.now(); setHidden({ since, total }); }
      else {
        if (since) total += (performance.now() - since) / 1000;
        since = 0;
        setHidden(total > 0 ? { since: 0, total } : null);
        void requestWake();                                   // the lock is released whenever the tab is hidden
      }
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [phase, requestWake]);

  // --- timer and the "recording" chunk row ------------------------------------------------------------------------
  useEffect(() => {
    if (phase !== "recording") return;
    const id = setInterval(() => {
      setElapsed((performance.now() - t0Ref.current) / 1000);
      const cap = capRef.current;
      const L = stateRef.current.chunkSeconds;
      for (const seq of cap?.segmenter?.active ?? []) {
        if (!stateRef.current.chunks.some((c) => c.seq === seq)) {
          dispatch({ type: "local_chunk", chunk: { seq, t0: seq * L, t1: seq * L + L, state: "recording" } });
        }
      }
    }, 250);
    return () => clearInterval(id);
  }, [phase, dispatch]);

  // --- court check before recording: the same court detection as the upload page, on one frame of the camera -------------
  const checkCourt = async () => {
    const v = videoRef.current;
    if (!v || !camera || !v.videoWidth) return;
    setCheck({ busy: true });
    try {
      const c = document.createElement("canvas");
      c.width = v.videoWidth;
      c.height = v.videoHeight;
      c.getContext("2d")?.drawImage(v, 0, 0);
      const blob = await new Promise<Blob | null>((res) => c.toBlob(res, "image/jpeg", 0.9));
      if (!blob) throw new Error("could not grab a frame from the camera");
      const d = await api.detectCourt(blob, sport);
      setCheck({ busy: false, result: d });
      if (d.found && d.corners_px && d.width) {
        const k = camera.w / d.width;                           // the answer is in the pixels of the frame that was analysed
        setCorners(d.corners_px.map(([x, y]) => [Math.round(x * k), Math.round(y * k)] as Pt));
        setMarking(false);
      } else {
        setCorners([]);
      }
    } catch (e) {
      setCheck({ busy: false, error: e instanceof Error ? e.message : String(e) });
    }
  };

  // --- start / stop -----------------------------------------------------------------------------------------------
  const start = async () => {
    const stream = streamRef.current;
    if (!stream) return;
    setError(null);
    try {
      const mime = pickMime((m) => MediaRecorder.isTypeSupported(m));
      const store = storeRef.current ?? new IdbStore();
      storeRef.current = store;
      const cap = new Capture({
        http: browserHttp(API), store, mime, makeRecorder: mediaRecorderFactory(stream, mime),
        onPhase: (seq, ph, info, chunk) => {
          const cur = stateRef.current.chunks.find((c) => c.seq === seq);
          if (cur && (cur.state === "processed" || (ph === "uploaded" && cur.state === "received"))) return;   // never step back
          const L = stateRef.current.chunkSeconds;
          dispatch({ type: "local_chunk", chunk: {
            seq, t0: chunk?.t0 ?? seq * L, t1: chunk ? chunk.t0 + chunk.duration : (seq + 1) * L,
            state: ph === "uploaded" ? "received" : ph === "failed" ? "failed" : ph === "uploading" ? "uploading" : "buffered", tries: info.tries,
          } });
        },
        onStatus: (s) => { setNet(s); setPersistent(store.persistent); },
        onError: (err) => setError(`Recorder problem: ${err instanceof Error ? err.message : String(err)}`),
      });
      capRef.current = cap;
      const info = await cap.start(sport, corners.length === 4 ? corners : null);
      setCornersSent(corners.length === 4);                    // corners given at the start are already used by the analysis
      setStorageMode(info.storage);
      connect(info.session_id);
      t0Ref.current = performance.now();
      setElapsed(0);
      setPhase("recording");
      void requestWake();
    } catch (e) {
      capRef.current = null;
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const stop = async () => {
    const cap = capRef.current;
    if (!cap) return;
    setPhase("finalising");
    try {
      await cap.stop();                                       // waits for buffered chunks, then tells the server the match is over
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    void wakeRef.current?.release().catch(() => undefined);
    setWake("off");
  };

  useEffect(() => {
    if (state.status === "done" && state.matchId) {
      streamRef.current?.getTracks().forEach((t) => t.stop());
      router.push(`/matches/${state.matchId}`);
    }
  }, [state.status, state.matchId, router]);

  // --- court corners: tap four points on the preview, drag to adjust ---------------------------------------------
  const toVideo = (e: React.PointerEvent<SVGSVGElement>): Pt | null => {
    const r = e.currentTarget.getBoundingClientRect();
    if (!camera || !r.width) return null;
    return [Math.round(((e.clientX - r.left) / r.width) * camera.w), Math.round(((e.clientY - r.top) / r.height) * camera.h)];
  };
  const onDown = (e: React.PointerEvent<SVGSVGElement>) => {
    if (!marking && drag === null) return;
    const p = toVideo(e);
    if (!p) return;
    if (corners.length < 4 && marking) { setCorners([...corners, p]); if (corners.length === 3) setMarking(false); }
  };
  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    if (drag === null) return;
    const p = toVideo(e);
    if (p) setCorners(corners.map((c, i) => (i === drag ? p : c)));
  };
  const applyCorners = async () => {
    if (corners.length !== 4) return;
    try { await capRef.current?.setCorners(corners); setCornersSent(true); } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };

  const cal = state.calibration;
  const recording = phase === "recording";
  const lowFps = camera?.fps != null && camera.fps < 50;
  const needsCorners = recording && cal?.quality === "check";
  // the court the analysis found (from the first chunk), drawn on the camera picture unless the user marked their own corners
  const detectedCourt = recording && corners.length === 0 && cal?.corners_px && cal.corners_px.length === 4 ? (cal.corners_px as [number, number][]) : null;

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        title="Record live"
        subtitle="Press Start once. RallyOS cuts the camera into 5-second chunks by itself, analyses each as it arrives, and builds the match while it is played."
      />
      {error && <div className="mb-3"><ErrorBox message={error} /></div>}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <Card title="Camera">
          <div className="relative mx-auto w-full overflow-hidden rounded-lg bg-black" style={{ aspectRatio: camera && camera.h ? `${camera.w} / ${camera.h}` : "16 / 9", maxHeight: "62vh" }}>
            <video ref={videoRef} muted playsInline className="absolute inset-0 h-full w-full object-fill" />
            {!camera && <div className="absolute inset-0 flex items-center justify-center text-sm text-white/70">Camera is off</div>}
            {camera && (
              <svg className={`absolute inset-0 h-full w-full ${marking || drag !== null ? "cursor-crosshair" : ""}`} viewBox={`0 0 ${camera.w} ${camera.h}`} preserveAspectRatio="none"
                   onPointerDown={onDown} onPointerMove={onMove} onPointerUp={() => setDrag(null)} onPointerLeave={() => setDrag(null)} style={{ touchAction: "none" }}>
                {corners.length < 2 && !marking && (
                  <g stroke="rgba(255,255,255,0.7)" strokeWidth={camera.w / 400} strokeDasharray={`${camera.w / 60} ${camera.w / 90}`} fill="none">
                    <polygon points={`${camera.w * 0.12},${camera.h * 0.9} ${camera.w * 0.88},${camera.h * 0.9} ${camera.w * 0.7},${camera.h * 0.3} ${camera.w * 0.3},${camera.h * 0.3}`} />
                  </g>
                )}
                {detectedCourt && (
                  <g>
                    <polygon points={detectedCourt.map((c) => c.join(",")).join(" ")} fill="rgba(34,197,94,0.10)"
                             stroke={cal?.quality === "check" ? "#f59e0b" : "#22c55e"} strokeWidth={camera.w / 300} strokeDasharray={cal?.quality === "check" ? `${camera.w / 80} ${camera.w / 120}` : undefined} />
                    <text x={detectedCourt[3][0]} y={Math.max(camera.h / 30, detectedCourt[3][1] - camera.w / 90)} fontSize={camera.w / 50} fill="white" stroke="black" strokeWidth={camera.w / 1000}>
                      {cal?.sport ? sportLabel(cal.sport) : "court"}{cal?.precision != null ? ` · fit ${Math.round(cal.precision * 100)}%` : ""}{cal?.quality === "check" ? " · check the corners" : ""}
                    </text>
                  </g>
                )}
                {corners.length >= 2 && (
                  <polygon points={corners.map((c) => c.join(",")).join(" ")} fill="rgba(34,197,94,0.12)" stroke="#22c55e" strokeWidth={camera.w / 400} />
                )}
                {corners.map((c, i) => (
                  <g key={i} onPointerDown={(e) => { e.stopPropagation(); setDrag(i); }} style={{ cursor: "grab" }}>
                    <circle cx={c[0]} cy={c[1]} r={camera.w / 70} fill={CORNER_COLORS[i]} stroke="white" strokeWidth={camera.w / 500} />
                    <text x={c[0] + camera.w / 55} y={c[1] - camera.w / 80} fontSize={camera.w / 55} fill="white" stroke="black" strokeWidth={camera.w / 900}>{CORNER_NAMES[i]}</text>
                  </g>
                ))}
              </svg>
            )}
            {recording && (
              <div className="absolute left-2 top-2 flex items-center gap-2 rounded-full bg-black/60 px-3 py-1 text-sm text-white">
                <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-red-500" /> REC {mmss(elapsed)}
              </div>
            )}
          </div>

          {check && !check.busy && (
            <p className="mt-2 text-sm">
              {check.error ? <span className="text-red-500">Court check failed: {check.error}</span>
                : check.result?.found
                  ? <span>
                      <Badge tone={check.result.quality === "check" ? "amber" : "green"}>{check.result.sport ? sportLabel(check.result.sport) : "court"} found{check.result.precision != null ? ` · fit ${Math.round(check.result.precision * 100)}%` : ""}</Badge>
                      <span className="ml-2 text-muted">{check.result.quality === "check" ? "Part of the court may be hidden: drag the corners to fix them, then start." : "Corners are set. Drag any corner to adjust, or just start recording." + (sport === "auto" ? " The sport is a guess (badminton and pickleball courts look alike): pick it in the list if it is wrong." : "")}</span>
                    </span>
                  : <span className="text-amber-500">{check.result?.message ?? "No court found."} Move the camera so all four corners show, or use "Mark court corners".</span>}
            </p>
          )}
          <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
            {!camera && <button className="btn-primary" onClick={openCamera}>Open camera</button>}
            {camera && phase === "setup" && (
              <>
                <label className="flex items-center gap-2">
                  <span className="label">Sport</span>
                  <select className="input" value={sport} onChange={(e) => setSport(e.target.value)}>
                    <option value="auto">Auto-detect</option>
                    {sports.map((s) => <option key={s.sport} value={s.sport}>{sportLabel(s.sport)}</option>)}
                  </select>
                </label>
                <button className="btn-ghost" disabled={check?.busy} onClick={checkCourt}>{check?.busy ? "Checking the court…" : "Check court"}</button>
                <button className="btn-ghost" onClick={() => { setCorners([]); setMarking(true); setCheck(null); }}>{corners.length === 4 ? "Re-mark court corners" : "Mark court corners (optional)"}</button>
                {marking && <span className="text-muted">Tap {CORNER_NAMES[corners.length]} ({corners.length + 1}/4)</span>}
                <button className="btn-primary ml-auto" onClick={start}>Start recording</button>
              </>
            )}
            {recording && (
              <>
                {needsCorners && corners.length < 4 && <button className="btn-ghost" onClick={() => { setCorners([]); setMarking(true); setCornersSent(false); }}>Fix court corners</button>}
                {corners.length === 4 && recording && !cornersSent && <button className="btn-ghost" onClick={applyCorners}>Apply corners</button>}
                {cornersSent && <Badge tone="blue">corners sent: re-analysing the stored chunks</Badge>}
                <button className="btn-ghost ml-auto border-red-500 text-red-500 hover:bg-red-500/10" onClick={stop}>Stop match</button>
              </>
            )}
            {phase === "finalising" && <Badge tone="blue">finalising… delivering the last chunks and building the match</Badge>}
          </div>
        </Card>

        <div className="space-y-4">
          <Card title="Framing guide">
            <ul className="list-disc space-y-1.5 pl-5 text-sm text-muted">
              <li>All four court corners inside the frame.</li>
              <li>Behind the baseline, 2–3 m high, centred, phone fixed (a tripod or a clamp).</li>
              <li>Landscape. Lock exposure and focus if the phone lets you.</li>
              <li>60 fps or more helps with a fast shuttle.</li>
            </ul>
            {camera && (
              <p className="mt-3 text-sm">
                Camera: <span className="font-medium">{camera.w}×{camera.h}</span>{camera.fps ? ` at ${camera.fps} fps` : ""}
                {lowFps && <span className="ml-2"><Badge tone="amber" title="At 30 fps a smash moves several metres per frame">30 fps: fast shots may be missed</Badge></span>}
              </p>
            )}
          </Card>
          <Card title="Connection and device">
            <div className="space-y-1.5 text-sm">
              <div className="flex items-center justify-between"><span className="text-muted">Upload</span>
                {net.online ? <Badge tone="green">connected</Badge> : <Badge tone="red">offline: buffering</Badge>}</div>
              {storageMode && <div className="flex items-center justify-between"><span className="text-muted">Chunk storage</span>
                <Badge tone={storageMode === "local" ? "neutral" : "blue"} title={storageMode === "local" ? "Chunks go to the laptop running RallyOS" : "Chunks go straight to Cloudinary (signed by the API); the laptop fetches them to analyse"}>{storageMode}</Badge></div>}
              <div className="flex items-center justify-between"><span className="text-muted">Buffered on this device</span>
                <span className="tabular-nums font-medium">{net.pending} chunk{net.pending === 1 ? "" : "s"}</span></div>
              <div className="flex items-center justify-between"><span className="text-muted">Delivered</span><span className="tabular-nums">{net.sent}</span></div>
              {net.failed > 0 && <div className="flex items-center justify-between"><span className="text-muted">Refused by the server</span><span className="tabular-nums text-red-500">{net.failed}</span></div>}
              <div className="flex items-center justify-between"><span className="text-muted">Screen</span>
                {wake === "on" ? <Badge tone="green">kept awake</Badge> : wake === "unsupported" ? <Badge tone="amber" title="Keep the screen on by hand">cannot lock: keep it on</Badge> : <Badge>not locked</Badge>}</div>
              {!persistent && <p className="text-xs text-amber-500">Offline storage is unavailable in this browser mode: buffered chunks are lost if the page is closed.</p>}
            </div>
          </Card>
        </div>
      </div>

      {hidden && (
        <div className="mt-3 rounded-lg border border-amber-500/50 bg-amber-500/10 p-3 text-sm">
          {hidden.since ? "This tab is hidden: the browser may pause the camera and the recording. Bring it back to the front."
            : `The tab was hidden for about ${Math.round(hidden.total)} s while recording: footage from that time may have gaps.`}
        </div>
      )}
      {net.pending > 0 && !net.online && (
        <div className="mt-3 rounded-lg border border-amber-500/50 bg-amber-500/10 p-3 text-sm">
          Network is down. Buffered: {net.pending} chunk{net.pending === 1 ? "" : "s"}. Recording continues; the chunks are sent in order as soon as the connection is back, and the numbers catch up.
        </div>
      )}

      {state.calibration?.sport && (
        <div className="mt-4">
          <DetectedCourt summary={{ sport: state.calibration.sport, calibrated: state.calibration.quality !== "none", quality: state.calibration.quality, method: state.calibration.method ?? null,
            precision: state.calibration.precision ?? null, corners_px: (state.calibration.corners_px as [number, number][] | null | undefined) ?? null, note: state.calibration.note ?? null,
            sport_source: "auto-detected on the first chunk", video: camera ? { fps: camera.fps ?? 25, width: camera.w, height: camera.h } : undefined }} />
        </div>
      )}

      <div className="mt-4">
        {state.status === "idle" && phase === "setup"
          ? <Card><p className="text-sm text-muted">Open the camera, frame the court, press Start. Live results appear here as soon as the first chunk has been analysed.</p></Card>
          : <LiveDashboard live={state} sport={sportCfg} />}
      </div>
    </div>
  );
}
