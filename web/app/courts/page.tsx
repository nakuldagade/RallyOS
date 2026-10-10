"use client";

// Smart Courts list + mock booking (payment mocked).
import { useState } from "react";
import { api } from "@/lib/api";
import type { Booking, CourtRow, Player } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { Badge, Card, ErrorBox, Loading, PageHeader } from "@/components/ui";

const NEAR = [
  { label: "Near Thane", value: "19.19,72.97" },
  { label: "Near Dadar", value: "19.02,72.84" },
];

function tomorrow(): string {
  const d = new Date(Date.now() + 86400000);
  return d.toISOString().slice(0, 10);
}

function BookForm({ row, players }: { row: CourtRow; players: Player[] }) {
  const [date, setDate] = useState(tomorrow());
  const [hour, setHour] = useState(18);
  const [player, setPlayer] = useState(players[0]?.id ?? "");
  const [result, setResult] = useState<Booking | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const book = async () => {
    setBusy(true);
    setError(null);
    setResult(null);
    const pad = (n: number) => String(n).padStart(2, "0");
    try {
      setResult(await api.book({ court_id: row.court.id, player_id: player, slot_start: `${date}T${pad(hour)}:00:00`, slot_end: `${date}T${pad(hour + 1)}:00:00` }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-3 space-y-2">
      <div className="flex flex-wrap gap-2">
        <input type="date" className="input py-1.5" value={date} onChange={(e) => setDate(e.target.value)} aria-label="Date" />
        <select className="input py-1.5" value={hour} onChange={(e) => setHour(parseInt(e.target.value))} aria-label="Start time">
          {Array.from({ length: 16 }, (_, i) => i + 6).map((h) => <option key={h} value={h}>{h}:00–{h + 1}:00</option>)}
        </select>
        <select className="input py-1.5" value={player} onChange={(e) => setPlayer(e.target.value)} aria-label="Player">
          {players.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <button className="btn-primary py-1.5" disabled={busy || !player} onClick={book}>{busy ? "Booking…" : "Book (₹0 demo)"}</button>
      </div>
      {result && <div className="text-xs text-emerald-500">Booked #{result.id}: {result.slot_start.replace("T", " ")} – {result.slot_end.slice(11, 16)}</div>}
      {error && <div className="text-xs text-rose-500">{error}</div>}
    </div>
  );
}

export default function CourtsPage() {
  const [near, setNear] = useState(NEAR[0].value);
  const courts = useApi(() => api.courts(near), [near]);
  const players = useApi(() => api.players(), []);
  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader title="Smart Courts" subtitle="Calibrated once, ready instantly. Matches played here can count toward verified rankings."
        actions={<select className="input" value={near} onChange={(e) => setNear(e.target.value)}>{NEAR.map((n) => <option key={n.value} value={n.value}>{n.label}</option>)}</select>} />
      {courts.loading ? <Loading /> : courts.error ? <ErrorBox message={courts.error} onRetry={courts.reload} /> : (
        <div className="space-y-3">
          {courts.data?.map((r) => (
            <Card key={r.court.id}>
              <div className="flex flex-wrap items-center gap-2">
                <div className="min-w-0 flex-1">
                  <div className="font-medium">{r.venue.name} · Court {r.court.id}</div>
                  <div className="text-xs text-muted">{r.venue.city} · {r.court.sport}{r.distance_km !== undefined ? ` · ${r.distance_km} km` : ""}</div>
                </div>
                {r.court.smart_court ? <Badge tone="green" title="Saved calibration: analysis is ready instantly">Smart Court</Badge> : <Badge>Standard</Badge>}
              </div>
              {players.data && <BookForm row={r} players={players.data} />}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
