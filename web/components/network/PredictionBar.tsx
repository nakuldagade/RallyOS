import type { Prediction } from "@/lib/types";

const LABELS: Record<string, string> = { rating_gap: "Rating gap", style_matchup: "Style matchup", head_to_head: "Head-to-head" };

export default function PredictionBar({ prediction, nameA, nameB }: { prediction: Prediction; nameA: string; nameB: string }) {
  const pa = Math.round(prediction.p_a_wins * 100);
  const maxC = Math.max(0.01, ...prediction.factors.map((f) => Math.abs(f.contribution)));
  return (
    <div>
      <div className="mb-1 flex justify-between text-sm font-medium">
        <span className="text-sky-500">{nameA} {pa}%</span>
        <span className="text-rose-500">{100 - pa}% {nameB}</span>
      </div>
      <div className="flex h-3 overflow-hidden rounded-full">
        <div className="bg-sky-500" style={{ width: `${pa}%` }} />
        <div className="flex-1 bg-rose-500" />
      </div>
      <div className="mt-4 space-y-2">
        <div className="label">Top factors (log-odds contribution)</div>
        {prediction.factors.map((f) => (
          <div key={f.factor} className="grid grid-cols-[110px_1fr] items-center gap-3 text-sm">
            <span className="text-muted">{LABELS[f.factor] ?? f.factor}</span>
            <div>
              <div className="relative h-2 rounded-full bg-fg/10">
                <div className={`absolute top-0 h-2 rounded-full ${f.contribution >= 0 ? "left-1/2 bg-sky-500" : "right-1/2 bg-rose-500"}`}
                  style={{ width: `${(Math.abs(f.contribution) / maxC) * 50}%` }} />
              </div>
              <div className="mt-1 text-xs text-muted">{f.explanation}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
