"use client";

// The frame around every page. Logged out, only the login page exists (full screen, no menu); logged in, the menu with every
// feature appears and each role starts on its own dashboard.
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import type { ReactNode } from "react";
import { useAuth } from "@/lib/auth";
import Nav from "@/components/Nav";
import { Loading } from "@/components/ui";

export default function AppShell({ children }: { children: ReactNode }) {
  const { user, ready } = useAuth();
  const path = usePathname();
  const router = useRouter();
  const onLogin = path === "/login";

  useEffect(() => {
    if (ready && !user && !onLogin) router.replace("/login");
  }, [ready, user, onLogin, router]);

  if (onLogin) return <>{children}</>;
  if (!ready || !user) return <div className="grid min-h-screen place-items-center"><Loading label="Checking your login…" /></div>;
  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <Nav />
      <main className="min-w-0 flex-1 px-4 py-6 md:px-8">{children}</main>
    </div>
  );
}
