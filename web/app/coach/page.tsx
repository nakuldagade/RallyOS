"use client";

// Coach / academy dashboard: roster with rating trends and a parent progress card.
import Link from "next/link";
import { useEffect, useState } from "react";
import { Line, LineChart, ResponsiveContainer } from "recharts";
import { api } from "@/lib/api";
import type { Player, RatingPoint } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { Badge, Card, ErrorBox, Loading, PageHeader } from "@/components/ui";

function ProgressCard({ player, history }: { player: Player; history: RatingPoint[] }) {
  const first = history[0]?.rating ?? player.rating;
  const delta = player.rating - first;
  return (
    <Card title={`Progress card · ${player.name}`} actions={<button className="btn-ghost py-1 text-xs" onClick={() => window.print()}>Print</button>}>
      <p className="text-sm">
        {player.name}&apos;s verified rating is <b>{Math.round(player.rating)}</b> ({delta >= 0 ? "up" : "down"} {Math.abs(Math.round(delta))} points
        over {history.length} rated periods). The rating is only moved by recorded matches, and video-verified matches count the most.
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        <Badge tone={delta >= 0 ? "green" : "red"}>{delta >= 0 ? "Improving" : "Dipping"}</Badge>
        <Badge>±{Math.round(player.rd * 2)} uncertainty</Badge>
      </div>
      <div className="mt-3 flex gap-2">
        <Link href={`/players/${player.id}`} className="btn-ghost py-1 text-xs">Full profile</Link>
        <Link href="/matches/m_001/report" className="btn-ghost py-1 text-xs">Latest coach report</Link>
      </div>
    </Card>
  );
}

export default function CoachPage() {
  const players = useApi(() => api.players(), []);
  const [histories, setHistories] = useState<Record<string, RatingPoint[]>>({});
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    if (!players.data) return;
    players.data.forEach((p) =>
      api.trends(p.id).then((t) => setHistories((h) => ({ ...h, [p.id]: t.rating_history }))).catch(() => undefined),
    );
  }, [players.data]);

  if (players.loading) return <Loading />;
  if (players.error) return <ErrorBox message={players.error} onRetry={players.reload} />;
  const sel = players.data?.find((p) => p.id === selected) ?? players.data?.[0];

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader title="Coach dashboard" subtitle="Every academy player's trend in one place, plus progress cards parents can read." />
      <div className="grid gap-4 lg:grid-cols-[1fr_380px]">
        <Card title="Roster">
          <div className="divide-y divide-border">
            {players.data?.map((p) => {
              const h = histories[p.id] ?? [];
              const delta = h.length ? p.rating - h[0].rating : 0;
              return (
                <button key={p.id} onClick={() => setSelected(p.id)} className={`flex w-full items-center gap-3 py-2.5 text-left hover:bg-fg/5 ${sel?.id === p.id ? "bg-accent/5" : ""}`}>
                  <span className="w-28 truncate font-medium">{p.name}</span>
                  <span className="w-14 text-right tabular-nums">{Math.round(p.rating)}</span>
                  <span className={`w-14 text-right text-xs tabular-nums ${delta >= 0 ? "text-emerald-500" : "text-rose-500"}`}>{delta >= 0 ? "+" : ""}{Math.round(delta)}</span>
                  <div className="h-8 flex-1">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={h.map((x) => ({ r: x.rating }))}>
                        <Line type="monotone" dataKey="r" stroke={delta >= 0 ? "#22c55e" : "#f43f5e"} strokeWidth={2} dot={false} isAnimationActive={false} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </button>
              );
            })}
          </div>
        </Card>
        {sel && <ProgressCard player={sel} history={histories[sel.id] ?? []} />}
      </div>
    </div>
  );
}
