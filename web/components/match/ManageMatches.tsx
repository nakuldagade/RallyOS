"use client";

// The match list with a "Remove videos" mode: tick the analysed matches to remove, confirm, done. The demo match is locked.
import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import type { MatchSummary } from "@/lib/types";
import MatchList from "@/components/match/MatchList";

const PROTECTED = new Set(["m_001"]);

export default function ManageMatches({ matches, onChanged }: { matches: MatchSummary[]; onChanged: () => void }) {
  const [managing, setManaging] = useState(false);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const removable = matches.filter((m) => !PROTECTED.has(m.match_id));

  const toggle = (id: string) => setPicked((p) => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const stop = () => { setManaging(false); setPicked(new Set()); };

  const remove = async () => {
    const ids = [...picked];
    if (!ids.length) return;
    const ok = window.confirm(
      `Remove ${ids.length} analysed video${ids.length === 1 ? "" : "s"}?\n\n` +
      "This deletes the match record, its stats and tracks, and the stored copy of the video.\n" +
      "The original upload file and player ratings are kept. This cannot be undone.");
    if (!ok) return;
    setBusy(true);
    setMessage(null);
    try {
      const r = await api.deleteMatches(ids);
      setMessage(`Removed ${r.deleted.length} match${r.deleted.length === 1 ? "" : "es"}${r.skipped.length ? `; skipped ${r.skipped.length} (${r.skipped.map((s) => s.reason).join(", ")})` : ""}.`);
      stop();
      onChanged();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        {!managing ? (
          <button className="btn-ghost py-1 text-xs" disabled={!removable.length} onClick={() => setManaging(true)}
            title={removable.length ? "Choose analysed videos to remove" : "Nothing to remove"}>Remove videos…</button>
        ) : (
          <>
            <button className="btn-ghost py-1 text-xs" onClick={() => setPicked(picked.size === removable.length ? new Set() : new Set(removable.map((m) => m.match_id)))}>
              {picked.size === removable.length ? "Select none" : "Select all"}
            </button>
            <button className="btn-primary bg-rose-600 py-1 text-xs hover:bg-rose-700" disabled={!picked.size || busy} onClick={remove}>
              {busy ? "Removing…" : `Delete selected (${picked.size})`}
            </button>
            <button className="btn-ghost py-1 text-xs" onClick={stop} disabled={busy}>Cancel</button>
            <span className="text-xs text-muted">The demo match is locked.</span>
          </>
        )}
        {message && <span className="text-xs text-muted">{message}</span>}
      </div>
      {managing ? (
        <div className="divide-y divide-border">
          {matches.map((m) => {
            const locked = PROTECTED.has(m.match_id);
            return (
              <label key={m.match_id} className={`flex cursor-pointer items-center gap-3 py-3 ${locked ? "opacity-50" : "hover:bg-fg/5"}`}>
                <input type="checkbox" disabled={locked} checked={picked.has(m.match_id)} onChange={() => toggle(m.match_id)} className="h-4 w-4 accent-rose-600" />
                <div className="min-w-0 flex-1">
                  <div className="font-medium">{m.title || m.players.join(" vs ") || m.match_id}</div>
                  <div className="text-xs text-muted">{m.match_id}{m.duration_s ? ` · ${Math.round(m.duration_s)} s` : ""}{locked ? " · demo match" : ""}</div>
                </div>
                {!locked && <Link href={`/matches/${m.match_id}`} className="text-xs text-accent" onClick={(e) => e.stopPropagation()}>open</Link>}
              </label>
            );
          })}
        </div>
      ) : <MatchList matches={matches} />}
    </div>
  );
}
