"use client";

import Link from "next/link";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { Card, ErrorBox, Loading } from "@/components/ui";
import MatchList from "@/components/match/MatchList";

const FEATURES = [
  { href: "/sports", title: "Court Fingerprint", text: "Detects the sport from the court lines and calibrates the camera. Six sports, one YAML each, no training." },
  { href: "/matches/m_001", title: "Match Vision", text: "Players, pose, shuttle trail, hits heard from audio, rallies and score, all from one phone." },
  { href: "/disputes/d_001", title: "Fair-Play Replay", text: "Close calls come with an uncertainty ellipse and a probability, never fake certainty." },
  { href: "/matches/m_001/report", title: "AI Coach", text: "Insights that cite the exact stat and jump to the moment in the video." },
  { href: "/play", title: "Verified network", text: "Glicko-2 ratings where video-verified matches count most, plus style-aware matchmaking." },
  { href: "/developers", title: "SDK + API", text: "pip-installable core, REST API and a sport config format for partners." },
];

export default function Home() {
  const matches = useApi(() => api.matches(), []);
  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <section className="card relative overflow-hidden p-6 md:p-8">
        <div className="absolute -right-16 -top-16 h-56 w-56 rounded-full bg-accent/20 blur-3xl" />
        <div className="relative max-w-2xl">
          <div className="label mb-2">RallyOS · racket-sports intelligence</div>
          <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">One phone. Any court. Every rally counted.</h1>
          <p className="mt-3 text-muted">
            Any smartphone becomes a match analyst that calibrates itself and needs no training, across badminton, tennis,
            table tennis, pickleball, padel and squash. Every match becomes a verified record.
          </p>
          <div className="mt-5 flex flex-wrap gap-2">
            <Link href="/upload" className="btn-primary">Analyse a match</Link>
            <Link href="/matches/m_001" className="btn-ghost">Open demo match</Link>
          </div>
        </div>
      </section>

      <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
        <Card title="Recent matches" actions={<Link href="/matches" className="text-xs text-accent">All matches →</Link>}>
          {matches.loading ? <Loading /> : matches.error ? <ErrorBox message={matches.error} onRetry={matches.reload} /> : <MatchList matches={matches.data ?? []} />}
        </Card>
        <Card title="What's real in this demo">
          <ul className="space-y-2 text-sm">
            <li><span className="text-emerald-500">●</span> Real logic: scoring rules (6 sports), Glicko-2, matchmaking, predictions, coach grounding, bookings, draws</li>
            <li><span className="text-amber-500">●</span> Approximate, shown with confidence: speeds (± band), line calls, shot types</li>
            <li><span className="text-sky-500">●</span> Sample data until the vision pipeline runs: the mock match and tracks</li>
          </ul>
        </Card>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {FEATURES.map((f) => (
          <Link key={f.title} href={f.href} className="card p-4 transition hover:border-accent">
            <div className="font-medium">{f.title}</div>
            <p className="mt-1 text-sm text-muted">{f.text}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}
