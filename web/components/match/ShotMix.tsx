"use client";

import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { MatchJSON } from "@/lib/types";

export default function ShotMix({ match }: { match: MatchJSON }) {
  const per = match.stats.per_player ?? {};
  const players = match.players.filter((p) => per[String(p.track_id)]?.shot_mix);
  if (!players.length) {
    const why = match.stats.shots?.why_unlabelled;
    return (
      <div className="text-sm text-muted">
        No shot could be labelled for this match{match.stats.shots ? `: ${match.stats.shots.unlabelled} hits had no matching rule or no measurable flight` : " (no court calibration, so zones and flight times are unknown)"}.
        {why && <ul className="mt-1 list-disc pl-5 text-xs">{Object.entries(why).map(([k, v]) => <li key={k}>{k} ({v as number})</li>)}</ul>}
      </div>
    );
  }
  const shots = Array.from(new Set(players.flatMap((p) => Object.keys(per[String(p.track_id)].shot_mix ?? {}))));
  const data = shots.map((shot) => ({
    shot,
    ...Object.fromEntries(players.map((p) => [p.name, per[String(p.track_id)].shot_mix?.[shot] ?? 0])),
  }));
  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ left: -16, right: 8, top: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--border))" />
          <XAxis dataKey="shot" tick={{ fill: "rgb(var(--muted))", fontSize: 12 }} />
          <YAxis tick={{ fill: "rgb(var(--muted))", fontSize: 12 }} allowDecimals={false} />
          <Tooltip contentStyle={{ background: "rgb(var(--card))", border: "1px solid rgb(var(--border))", borderRadius: 8 }} />
          <Legend />
          {players.map((p) => (
            <Bar key={p.track_id} dataKey={p.name} fill={p.color ?? "#22c55e"} radius={[4, 4, 0, 0]} />
          ))}
        </BarChart>
      </ResponsiveContainer>
      <p className="mt-1 text-xs text-muted">
        Shot types come from explainable rules in the sport&apos;s YAML (where it was hit from, where it landed, flight time, wrist height).
        {match.stats.shots ? ` ${match.stats.shots.labelled} of ${match.stats.shots.labelled + match.stats.shots.unlabelled} hits matched a rule; the rest are left unlabelled rather than guessed. Apex height is estimated from the flight time, not measured.` : ""}
      </p>
    </div>
  );
}
