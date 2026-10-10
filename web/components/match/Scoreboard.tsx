"use client";

// Score per game + human-in-the-loop confirmation (POST /score/confirm -> video_verified + rating update).
import { useState } from "react";
import { api } from "@/lib/api";
import type { PlayerRef, RatingChange, Score } from "@/lib/types";
import { Badge } from "@/components/ui";

interface Props {
  matchId: string;
  score: Score;
  players: PlayerRef[];
  canConfirm: boolean;
  onConfirmed: (s: Score) => void;
}

export default function Scoreboard({ matchId, score, players, canConfirm, onConfirmed }: Props) {
  const [editing, setEditing] = useState(false);
  const [games, setGames] = useState<number[][]>(score.games.map((g) => [...g]));
  const [winner, setWinner] = useState<number | null>(score.winner_track_id ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [changes, setChanges] = useState<RatingChange[] | null>(null);
  const two = players.slice(0, 2);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const played = games.filter((g) => g[0] + g[1] > 0); // ignore empty 0-0 rows
      const res = await api.confirmScore(matchId, { games: played, winner_track_id: winner });
      setGames(played);
      setChanges(res.rating_update ?? []);
      setEditing(false);
      onConfirmed(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const setCell = (gi: number, pi: number, v: string) =>
    setGames((gs) => gs.map((g, i) => (i === gi ? g.map((x, j) => (j === pi ? Math.max(0, parseInt(v) || 0) : x)) : g)));

  return (
    <div>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-muted">
            <th className="py-1 text-left font-normal">Player</th>
            {(editing ? games : score.games).map((_, i) => (
              <th key={i} className="w-12 py-1 text-center font-normal">G{i + 1}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {two.map((p, pi) => (
            <tr key={p.track_id} className="border-t border-border">
              <td className="py-2">
                <span className="mr-2 inline-block h-2.5 w-2.5 rounded-full" style={{ background: p.color ?? "#94a3b8" }} />
                <span className="font-medium">{p.name}</span>
                {(editing ? winner : score.winner_track_id) === p.track_id && <span className="ml-2 text-amber-500" title="Winner">★</span>}
              </td>
              {(editing ? games : score.games).map((g, gi) => (
                <td key={gi} className="py-2 text-center tabular-nums">
                  {editing ? (
                    <input className="input w-12 px-1 py-1 text-center" value={g[pi]} inputMode="numeric"
                      onChange={(e) => setCell(gi, pi, e.target.value)} aria-label={`${p.name} game ${gi + 1}`} />
                  ) : (
                    <span className={g[pi] > g[1 - pi] ? "font-semibold" : "text-muted"}>{g[pi]}</span>
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>

      {!score.confirmed_by_human && score.source && (
        <p className="mt-2 text-xs text-muted">
          Suggested from line calls{score.from_clip_start ? ", counted from 0-0 at the start of this clip" : ""}.
          {score.unresolved_rallies ? ` ${score.unresolved_rallies} rall${score.unresolved_rallies === 1 ? "y has" : "ies have"} no suggested winner and ${score.unresolved_rallies === 1 ? "is" : "are"} not counted.` : ""}
        </p>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {score.confirmed_by_human ? (
          <Badge tone="green">✓ Confirmed by a human · video verified</Badge>
        ) : (
          <Badge tone="amber" title="The pipeline suggests the score; a person confirms it">Auto score · needs confirmation</Badge>
        )}
        {canConfirm && !editing && (
          <button className="btn-ghost ml-auto py-1 text-xs" onClick={() => setEditing(true)}>
            {score.confirmed_by_human ? "Correct score" : "Review & confirm"}
          </button>
        )}
      </div>

      {editing && (
        <div className="mt-3 space-y-2 rounded-lg border border-border p-3">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-muted">Winner</span>
            <select className="input py-1" value={winner ?? ""} onChange={(e) => setWinner(e.target.value ? parseInt(e.target.value) : null)}>
              <option value="">—</option>
              {two.map((p) => <option key={p.track_id} value={p.track_id}>{p.name}</option>)}
            </select>
            <button className="btn-ghost py-1 text-xs" onClick={() => setGames((g) => [...g, [0, 0]])}>+ game</button>
            {games.length > 1 && <button className="btn-ghost py-1 text-xs" onClick={() => setGames((g) => g.slice(0, -1))}>− game</button>}
          </div>
          <div className="flex gap-2">
            <button className="btn-primary py-1.5" disabled={busy} onClick={submit}>{busy ? "Saving…" : "Confirm score"}</button>
            <button className="btn-ghost py-1.5" onClick={() => setEditing(false)}>Cancel</button>
          </div>
          {error && <div className="text-xs text-rose-500">{error}</div>}
        </div>
      )}

      {changes && (
        <div className="mt-3 rounded-lg bg-accent/10 p-3 text-xs">
          {changes.length ? (
            <>
              <div className="mb-1 font-medium">Verified rating update (Glicko-2, full evidence weight)</div>
              {changes.map((c) => (
                <div key={c.player_id} className="tabular-nums">
                  {players.find((p) => p.player_id === c.player_id)?.name ?? c.player_id}: {c.before} → <b>{c.after}</b>
                  <span className="text-muted"> ({c.after >= c.before ? "+" : ""}{(c.after - c.before).toFixed(1)}, RD {c.rd})</span>
                </div>
              ))}
            </>
          ) : (
            <span className="text-muted">Score saved. Ratings were already updated for this match, so they are not counted twice.</span>
          )}
        </div>
      )}
    </div>
  );
}
