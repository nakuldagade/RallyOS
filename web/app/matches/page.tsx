"use client";

import Link from "next/link";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { Card, ErrorBox, Loading, PageHeader } from "@/components/ui";
import MatchList from "@/components/match/MatchList";

export default function MatchesPage() {
  const matches = useApi(() => api.matches(), []);
  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader title="Matches" subtitle="Every processed match is a structured record with a SHA-256 fingerprint."
        actions={<Link href="/upload" className="btn-primary">Analyse a match</Link>} />
      <Card>
        {matches.loading ? <Loading /> : matches.error ? <ErrorBox message={matches.error} onRetry={matches.reload} /> : <MatchList matches={matches.data ?? []} />}
      </Card>
    </div>
  );
}
