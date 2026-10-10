"use client";

// "Who played?": the analysis only knows a near player and a far player. Saying who they are puts the match into those
// players' history and analysis. Shown to logged-in users only.
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { PlayerRef } from "@/lib/types";
import { useApi } from "@/lib/useApi";

export default function AssignPlayers({ matchId, players, onSaved }: { matchId: string; players: PlayerRef[]; onSaved: () => void }) {
  const { user } = useAuth();
  const all = useApi(() => api.players(), []);
  const current = (tid: number) => players.find((p) => p.track_id === tid)?.player_id ?? "";
  const [s1, setS1] = useState(current(1));
  const [s2, setS2] = useState(current(2));
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setS1(current(1)); setS2(current(2)); }, [players]);  // eslint-disable-line react-hooks/exhaustive-deps

  if (!user) return null;
  const save = async () => {
    setBusy(true);
    setMsg(null);
    try {
      await api.assignPlayers(matchId, s1 || null, s2 || null);
      setMsg("Saved: this match is now part of their history.");
      onSaved();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  const options = (all.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>);
  return (
    <details className="card p-3 text-sm" open={!current(1) && !current(2) ? undefined : undefined}>
      <summary className="cursor-pointer font-medium">Who played? <span className="font-normal text-muted">Put this match in a player&apos;s history</span></summary>
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <label><div className="label mb-1">Near side (player 1)</div>
          <select className="input" value={s1} onChange={(e) => setS1(e.target.value)}><option value="">not set</option>{options}</select></label>
        <label><div className="label mb-1">Far side (player 2)</div>
          <select className="input" value={s2} onChange={(e) => setS2(e.target.value)}><option value="">not set</option>{options}</select></label>
        <button className="btn-primary" onClick={save} disabled={busy}>{busy ? "Saving…" : "Save"}</button>
        {s1 && <Link href={`/players/${s1}`} className="text-xs text-accent">Open {all.data?.find((p) => p.id === s1)?.name}&apos;s analysis →</Link>}
      </div>
      {msg && <p className="mt-2 text-xs text-muted">{msg}</p>}
    </details>
  );
}
