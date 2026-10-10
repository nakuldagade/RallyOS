"use client";

// Live dashboard driven by a mock stream: an already-processed match replayed chunk by chunk as if it were being played now.
// A test bed and a camera-free demo; the real capture page (/capture) feeds the same dashboard from the real pipeline.
import Link from "next/link";
import { useEffect, useState } from "react";
import { API, api } from "@/lib/api";
import { useLive } from "@/lib/live";
import { BADMINTON } from "@/lib/sports";
import type { MatchSummary, SportConfig } from "@/lib/types";
import { Card, PageHeader } from "@/components/ui";
import LiveDashboard from "@/components/live/LiveDashboard";

export default function LiveDemoPage() {
  const { state, connect } = useLive();
  const [matches, setMatches] = useState<MatchSummary[]>([]);
  const [matchId, setMatchId] = useState("");
  const [speed, setSpeed] = useState(1);
  const [sport, setSport] = useState<SportConfig>(BADMINTON);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.matches().then((r) => { setMatches(r); if (r[0]) setMatchId((m) => m || r[0].match_id); }).catch(() => setMatches([]));
  }, []);
  useEffect(() => {
    if (state.sport) api.sport(state.sport).then(setSport).catch(() => setSport(BADMINTON));
  }, [state.sport]);

  const start = async () => {
    setError(null);
    try {
      const res = await fetch(`${API}/v1/live/mock`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ match_id: matchId, speed, chunk_seconds: 5 }) });
      if (!res.ok) throw new Error((await res.json()).detail ?? res.statusText);
      connect((await res.json()).session_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader title="Live dashboard (replay)" subtitle="A processed match replayed as if it were live: the same events the camera path sends, released chunk by chunk." />
      <Card>
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-sm">
            <div className="label mb-1">Match to replay</div>
            <select className="input" value={matchId} onChange={(e) => setMatchId(e.target.value)}>
              {matches.map((m) => <option key={m.match_id} value={m.match_id}>{m.title ?? m.match_id} ({m.duration_s ?? "?"} s)</option>)}
            </select>
          </label>
          <label className="text-sm">
            <div className="label mb-1">Speed</div>
            <select className="input" value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
              {[1, 2, 5, 20].map((s) => <option key={s} value={s}>{s}× real time</option>)}
            </select>
          </label>
          <button className="btn-primary" disabled={!matchId || state.status === "live" || state.status === "connecting"} onClick={start}>
            {state.status === "idle" || state.status === "done" ? "Start replay" : "Replaying…"}
          </button>
          {state.matchId && state.status === "done" && <Link href={`/matches/${state.matchId}`} className="btn-ghost">Open the match →</Link>}
          <Link href="/capture" className="ml-auto text-sm text-accent">Use the camera instead →</Link>
        </div>
        {error && <div className="mt-2 text-sm text-rose-500">{error}</div>}
      </Card>
      <div className="mt-4"><LiveDashboard live={state} sport={sport} /></div>
    </div>
  );
}
