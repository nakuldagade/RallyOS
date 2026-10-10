"use client";

// Tournaments: register players, make a seeded draw.
import { useState } from "react";
import { api } from "@/lib/api";
import type { DrawMatch, Player, Tournament } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { Badge, Card, ErrorBox, Loading, PageHeader } from "@/components/ui";

function TournamentCard({ t, players }: { t: Tournament; players: Player[] }) {
  const [player, setPlayer] = useState(players[0]?.id ?? "");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [draw, setDraw] = useState<DrawMatch[] | null>(null);
  const name = (id?: string | null) => (id ? players.find((p) => p.id === id)?.name ?? id : "BYE");

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setMsg(null);
    try {
      await fn();
      setMsg({ ok: true, text: ok });
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) });
    }
  };

  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2">
        <div className="min-w-0 flex-1">
          <div className="font-medium">{t.name}</div>
          <div className="text-xs text-muted">{t.sport} · starts {t.start_date ?? "TBA"}</div>
        </div>
        <Badge tone="green">{t.status}</Badge>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <select className="input py-1.5" value={player} onChange={(e) => setPlayer(e.target.value)} aria-label="Player">
          {players.map((p) => <option key={p.id} value={p.id}>{p.name} ({Math.round(p.rating)})</option>)}
        </select>
        <button className="btn-ghost py-1.5" onClick={() => run(() => api.register(t.id, player), `${name(player)} registered`)}>Register</button>
        <button className="btn-primary py-1.5" onClick={() => run(async () => setDraw(await api.draw(t.id)), "Draw made (seeded by verified rating)")}>Make draw</button>
      </div>
      {msg && <div className={`mt-2 text-xs ${msg.ok ? "text-emerald-500" : "text-rose-500"}`}>{msg.text}</div>}
      {draw && (
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {draw.map((d) => (
            <div key={d.id} className="rounded-lg border border-border p-2 text-sm">
              <div className="label mb-1">Round {d.round} · Match {d.slot + 1}</div>
              <div>{name(d.p1)}</div>
              <div className="text-xs text-muted">vs</div>
              <div>{name(d.p2)}</div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

export default function TournamentsPage() {
  const tournaments = useApi(() => api.tournaments(), []);
  const players = useApi(() => api.players(), []);
  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader title="Tournaments" subtitle="Digital draws seeded by verified ratings; results feed the ranking." />
      {tournaments.loading || players.loading ? <Loading /> : tournaments.error ? <ErrorBox message={tournaments.error} onRetry={tournaments.reload} /> : (
        <div className="space-y-3">
          {tournaments.data?.map((t) => <TournamentCard key={t.id} t={t} players={players.data ?? []} />)}
        </div>
      )}
    </div>
  );
}
