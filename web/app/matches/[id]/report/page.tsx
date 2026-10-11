"use client";

// AI coach report: each insight cites stat ids and links to the clip time.
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { Badge, Card, ErrorBox, Loading, PageHeader } from "@/components/ui";
import InsightCard from "@/components/coach/InsightCard";

const SOURCES = [
  { id: "auto", label: "Auto" },
  { id: "claude", label: "AI model" },
  { id: "template", label: "Offline templates" },
] as const;

const SOURCE_TEXT: Record<string, string> = {
  pipeline: "Insights produced by the analysis pipeline.",
  claude: "Written by the AI model from the stats JSON only; every number was checked against it.",
  template: "Rule-based templates (works offline, no API key needed).",
};

export default function ReportPage() {
  const { id } = useParams<{ id: string }>();
  const [source, setSource] = useState<string>("auto");
  const match = useApi(() => api.match(id), [id]);
  const report = useApi(() => api.report(id, source), [id, source]);
  const [speaking, setSpeaking] = useState(false);

  const speak = () => {
    if (typeof window === "undefined" || !("speechSynthesis" in window) || !report.data) return;
    window.speechSynthesis.cancel();
    if (speaking) return setSpeaking(false);
    const u = new SpeechSynthesisUtterance(report.data.insights.map((i) => i.text).join(" "));
    u.onend = () => setSpeaking(false);
    setSpeaking(true);
    window.speechSynthesis.speak(u);
  };

  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader
        title="AI coach report"
        subtitle={<>Grounded insights for <Link className="text-accent" href={`/matches/${id}`}>{id}</Link>. Click a clip to watch the evidence.</>}
        actions={<button className="btn-ghost" onClick={speak} disabled={!report.data}>{speaking ? "■ Stop" : "🔊 Read aloud"}</button>}
      />
      <Card className="mb-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="label mr-1">Source</span>
          {SOURCES.map((s) => (
            <button key={s.id} onClick={() => setSource(s.id)} className={source === s.id ? "btn-primary py-1 text-xs" : "btn-ghost py-1 text-xs"}>
              {s.label}
            </button>
          ))}
          {report.data && <Badge tone={report.data.source === "claude" ? "blue" : report.data.source === "template" ? "amber" : "green"}>using: {report.data.source}</Badge>}
        </div>
        {report.data && <p className="mt-2 text-xs text-muted">{SOURCE_TEXT[report.data.source]}{source === "claude" && report.data.source !== "claude" ? " the AI model is not available (no AI_GATEWAY_KEY on the backend, or offline), so the report fell back." : ""}</p>}
      </Card>
      {report.loading ? <Loading label="Building report…" /> : report.error ? <ErrorBox message={report.error} onRetry={report.reload} /> : (
        <div className="space-y-3">
          {report.data?.insights.map((i, k) => <InsightCard key={k} insight={i} match={match.data?.data} />)}
          {report.data?.insights.length === 0 && <div className="card p-4 text-sm text-muted">{report.data.note ?? "No insights could be grounded in this match's stats."}</div>}
        </div>
      )}
    </div>
  );
}
