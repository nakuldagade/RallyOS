"use client";

import Link from "next/link";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { Card, ErrorBox, Loading, PageHeader } from "@/components/ui";

export default function PlayersPage() {
  const players = useApi(() => api.players(), []);
  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader title="Players" subtitle="Glicko-2 ratings. Video-verified matches move a rating the most." />
      <Card>
        {players.loading ? <Loading /> : players.error ? <ErrorBox message={players.error} onRetry={players.reload} /> : (
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted">
              <tr><th className="py-2">#</th><th>Player</th><th>Sport</th><th className="text-right">Rating</th><th className="text-right">RD</th></tr>
            </thead>
            <tbody>
              {players.data?.map((p, i) => (
                <tr key={p.id} className="border-t border-border">
                  <td className="py-2.5 text-muted">{i + 1}</td>
                  <td><Link href={`/players/${p.id}`} className="font-medium hover:text-accent">{p.name}</Link></td>
                  <td className="text-muted">{p.sport}</td>
                  <td className="text-right font-semibold tabular-nums">{Math.round(p.rating)}</td>
                  <td className="text-right tabular-nums text-muted">±{Math.round(p.rd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
