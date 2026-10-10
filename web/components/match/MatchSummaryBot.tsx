"use client";

// A written summary of this analysed match, built from its own stats (api/services/match_summary.py).
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Badge, Card } from "@/components/ui";

export default function MatchSummaryBot({ matchId }: { matchId: string }) {
  const [res, setRes] = useState<{ summary: string; source: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setRes(null); setError(null);
    api.matchSummary(matchId).then(setRes).catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [matchId]);
  return (
    <Card title="Analyst summary of this match" actions={res && <Badge tone={res.source === "claude" ? "blue" : "neutral"}>{res.source === "claude" ? "AI, numbers checked" : "from the match stats"}</Badge>}>
      {error ? <p className="text-sm text-red-500">{error}</p> : !res ? <p className="text-sm text-muted">Writing the summary…</p> : <p className="text-sm leading-relaxed">{res.summary}</p>}
    </Card>
  );
}
