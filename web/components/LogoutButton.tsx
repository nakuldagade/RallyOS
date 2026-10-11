"use client";

import { useAuth } from "@/lib/auth";

/** Ends the session; the app shell then sends the visitor back to the login page. */
export default function LogoutButton({ className = "btn-ghost" }: { className?: string }) {
  const { signOut } = useAuth();
  return <button type="button" onClick={signOut} className={className}>Log out</button>;
}
