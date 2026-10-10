"use client";

// The 3D view on a match's own page: the same Smart Court as the Smart Courts page, for this match, right after the analysis.
// It is open for a match nobody was assigned to; once players are assigned, only they and their coaches can open it.
import Link from "next/link";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/useApi";
import { Card, Loading } from "@/components/ui";
import Scene3DPanel from "@/components/court3d/Scene3DPanel";

export default function MatchSmartCourt({ matchId, time, mock }: { matchId: string; time: number; mock?: boolean }) {
  const { user } = useAuth();
  const scene = useApi(() => (mock ? Promise.reject(new Error("the sample match has no stored tracking")) : api.matchScene3d(matchId)), [matchId, user?.id]);
  if (scene.loading) return <Loading label="Building the 3D court from this match…" />;
  if (scene.error || !scene.data) {
    const needLogin = /log in|belongs/i.test(scene.error ?? "");
    return (
      <div className="rounded-lg border border-border p-4 text-sm">
        <p>{needLogin ? "The 3D court of this match is for its players and their coaches." : `The 3D court is not available: ${scene.error}`}</p>
        {needLogin && !user && <Link href="/login" className="btn-primary mt-3 inline-block">Log in</Link>}
        <p className="mt-2 text-xs text-muted">Matches nobody was assigned to are open to everyone; once players are assigned, only they and their coaches see it.</p>
      </div>
    );
  }
  return <Scene3DPanel role={user?.role ?? "viewer"} now={scene.data} follow={{ time }} height="h-[min(58vh,560px)] min-h-[340px]" />;
}

export function SmartCourtLink() {
  return <Link href="/courts" className="text-xs text-accent">Open in Smart Courts →</Link>;
}
