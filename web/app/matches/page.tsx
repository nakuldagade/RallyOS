"use client";

import Link from "next/link";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { ErrorBox, Loading, PageHeader } from "@/components/ui";
import ManageMatches from "@/components/match/ManageMatches";

export default function MatchesPage() {
  const matches = useApi(() => api.matches(), []);
  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader title="Matches" subtitle="Every analysed match is a structured, tamper-evident record: score, rallies, shots, movement and a SHA-256 fingerprint of the video."
        actions={<>
          <Link href="/capture" className="btn-ghost">Record live</Link>
          <Link href="/upload" className="btn-primary">Analyse a match</Link>
        </>} />
      {matches.loading ? <Loading /> : matches.error ? <ErrorBox message={matches.error} onRetry={matches.reload} /> : <ManageMatches matches={matches.data ?? []} onChanged={matches.reload} />}
    </div>
  );
}
