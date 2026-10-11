"use client";

// The player's own dashboard: their rating, history and full analysis. Coaches are sent to their own dashboard.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { homeFor, useAuth } from "@/lib/auth";
import { Card, Loading } from "@/components/ui";
import PlayerProfile from "@/components/player/PlayerProfile";
import LogoutButton from "@/components/LogoutButton";

export default function MyDashboard() {
  const { user, ready } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (ready && !user) router.replace("/login");
    else if (ready && user && user.role !== "player") router.replace(homeFor(user));
  }, [ready, user, router]);

  if (!ready || !user || user.role !== "player") return <Loading />;
  if (!user.player_id) return <Card title="My dashboard"><p className="text-sm">This account has no player profile yet.</p></Card>;
  return (
    <PlayerProfile id={user.player_id} title={`Welcome, ${user.name}`}
      actions={<><Link href="/upload" className="btn-ghost">Analyse a match</Link><Link href="/capture" className="btn-ghost">Record live</Link><LogoutButton /></>} />
  );
}
