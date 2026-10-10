"use client";

// A player's profile and full analysis. A coach reaches it from the roster; a player sees their own on /me.
import Link from "next/link";
import { useParams } from "next/navigation";
import PlayerProfile from "@/components/player/PlayerProfile";

export default function PlayerPage() {
  const { id } = useParams<{ id: string }>();
  return <PlayerProfile id={id} actions={<Link href="/players" className="btn-ghost">All players</Link>} />;
}
