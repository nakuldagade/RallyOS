"use client";

// Matchmaking: suggested opponents + explainable win prediction.
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { Badge, Card, ErrorBox, Loading, PageHeader } from "@/components/ui";
import PredictionBar from "@/components/network/PredictionBar";

function Play() {
  const params = useSearchParams();
  const router = useRouter();
  const players = useApi(() => api.players(), []);
  const a = params.get("a") ?? players.data?.[0]?.id ?? "";
  const b = params.get("b") ?? "";
  const suggestions = useApi(() => (a ? api.matchmaking(a) : Promise.resolve([])), [a]);
  const prediction = useApi(() => (a && b ? api.predict(a, b) : Promise.resolve(null)), [a, b]);
  const name = (pid: string) => players.data?.find((p) => p.id === pid)?.name ?? pid;
  const go = (na: string, nb: string) => router.replace(`/play?a=${na}${nb ? `&b=${nb}` : ""}`);

  if (players.loading) return <Loading />;
  if (players.error) return <ErrorBox message={players.error} onRetry={players.reload} />;

  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader title="Find a match" subtitle="Opponents with a similar verified rating, nearby, ranked by how well your styles test each other." />
      <Card className="mb-4">
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <div className="label mb-1">You are</div>
            <select className="input" value={a} onChange={(e) => go(e.target.value, "")}>
              {players.data?.map((p) => <option key={p.id} value={p.id}>{p.name} ({Math.round(p.rating)})</option>)}
            </select>
          </div>
          <div>
            <div className="label mb-1">Compare with</div>
            <select className="input" value={b} onChange={(e) => go(a, e.target.value)}>
              <option value="">—</option>
              {players.data?.filter((p) => p.id !== a).map((p) => <option key={p.id} value={p.id}>{p.name} ({Math.round(p.rating)})</option>)}
            </select>
          </div>
        </div>
      </Card>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Suggested opponents">
          {suggestions.loading ? <Loading /> : suggestions.error ? <ErrorBox message={suggestions.error} /> : (
            <div className="space-y-2">
              {suggestions.data?.map((s) => (
                <button key={s.player_id} onClick={() => go(a, s.player_id)}
                  className={`w-full rounded-lg border p-3 text-left transition hover:bg-fg/5 ${b === s.player_id ? "border-accent" : "border-border"}`}>
                  <div className="flex items-center justify-between">
                    <span className="font-medium">{s.name}</span>
                    <span className="text-sm tabular-nums">{Math.round(s.rating)}</span>
                  </div>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    <Badge>{s.distance_km} km away</Badge>
                    <Badge tone="blue">style gap {Math.round(s.style_complement * 100)}%</Badge>
                    <Badge tone="green">fit {Math.round(s.score * 100)}</Badge>
                  </div>
                </button>
              ))}
              {suggestions.data?.length === 0 && <div className="text-sm text-muted">No one within 25 km and ±250 rating.</div>}
            </div>
          )}
        </Card>
        <Card title="Win prediction">
          {!b ? <div className="text-sm text-muted">Pick an opponent to see the explained prediction.</div> :
            prediction.loading ? <Loading /> : prediction.error ? <ErrorBox message={prediction.error} /> : prediction.data && (
              <>
                <PredictionBar prediction={prediction.data} nameA={name(a)} nameB={name(b)} />
                <div className="mt-5 flex flex-wrap gap-2">
                  <Link href={`/players/${b}`} className="btn-primary">View {name(b)}</Link>
                </div>
              </>
            )}
        </Card>
      </div>
    </div>
  );
}

export default function PlayPage() {
  return (
    <Suspense fallback={<Loading />}>
      <Play />
    </Suspense>
  );
}
