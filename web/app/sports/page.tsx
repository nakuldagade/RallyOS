"use client";

// Supported sports, each drawn from its YAML. Adding a sport = adding one file, zero training.
import { useState } from "react";
import { api } from "@/lib/api";
import { scoringSummary, sportLabel } from "@/lib/sports";
import { useApi } from "@/lib/useApi";
import { Badge, Card, ErrorBox, Loading, PageHeader } from "@/components/ui";
import MiniCourt from "@/components/court/MiniCourt";

export default function SportsPage() {
  const sports = useApi(() => api.sports(), []);
  const [open, setOpen] = useState<string | null>("badminton");
  const selected = sports.data?.find((s) => s.sport === open);

  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader title="Sports" subtitle="One shared vision core; every sport difference lives in a YAML file. Court Fingerprint tries every template below." />
      {sports.loading ? <Loading /> : sports.error ? <ErrorBox message={sports.error} onRetry={sports.reload} /> : (
        <div className="grid gap-4 xl:grid-cols-[1fr_460px]">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {sports.data?.map((s) => (
              <button key={s.sport} onClick={() => setOpen(s.sport)}
                className={`card p-3 text-left transition hover:border-accent ${open === s.sport ? "border-accent" : ""}`}>
                <MiniCourt sport={s} className="h-40 w-full" highlightLines={s.court.fingerprint_lines ?? []} />
                <div className="mt-2 flex items-center justify-between">
                  <span className="font-medium">{s.display_name ?? sportLabel(s.sport)}</span>
                  <span className="text-xs tabular-nums text-muted">{s.court.length} × {s.court.width} m</span>
                </div>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  <Badge>{s.projectile.kind} {Math.round(s.projectile.size_m * 1000) / 10} cm</Badge>
                  <Badge tone="blue">{s.projectile.bounces ? "bounces" : "no bounce"}{s.projectile.wall_rebounds ? " + walls" : ""}</Badge>
                </div>
                <div className="mt-1.5 text-xs text-muted">{scoringSummary(s)}</div>
              </button>
            ))}
          </div>
          {selected && (
            <Card title={`${selected.display_name ?? sportLabel(selected.sport)} · ${selected.sport}.yaml`}>
              <p className="mb-2 text-xs text-muted">Yellow lines are the fingerprint lines that tell look-alike courts apart (e.g. badminton vs pickleball).</p>
              <pre className="max-h-[70vh] overflow-auto rounded-lg bg-fg/5 p-3 text-[11px] leading-relaxed">{selected.yaml}</pre>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
