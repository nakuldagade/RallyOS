"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { homeFor, useAuth } from "@/lib/auth";

const SECTIONS: { title: string; links: { href: string; label: string }[] }[] = [
  { title: "Analyse", links: [
    { href: "/", label: "Home" },
    { href: "/upload", label: "Analyse a match" },
    { href: "/capture", label: "Record live" },
    { href: "/live/demo", label: "Live replay demo" },
    { href: "/matches", label: "Matches" },
    { href: "/highlights", label: "Highlights" },
  ] },
  { title: "Improve", links: [
    { href: "/players", label: "Players" },
  ] },
  { title: "Play", links: [
    { href: "/play", label: "Find a match" },
    { href: "/courts", label: "Smart Courts" },
    { href: "/tournaments", label: "Tournaments" },
  ] },
  { title: "Platform", links: [
    { href: "/sports", label: "Sports (YAML)" },
    { href: "/developers", label: "Developers" },
  ] },
];

function ThemeToggle() {
  const [dark, setDark] = useState(true);
  useEffect(() => setDark(document.documentElement.classList.contains("dark")), []);
  const toggle = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    try {
      localStorage.setItem("rallyos-theme", next ? "dark" : "light");
    } catch {
      /* storage blocked */
    }
  };
  return (
    <button onClick={toggle} className="btn-ghost w-full text-xs" aria-label="Toggle theme">
      {dark ? "☀ Light mode" : "☾ Dark mode"}
    </button>
  );
}

function BackendStatus() {
  const [state, setState] = useState<"checking" | "up" | "down">("checking");
  const [coach, setCoach] = useState("");
  useEffect(() => {
    let live = true;
    const check = () =>
      api.health()
        .then((h) => live && (setState("up"), setCoach(h.coach)))
        .catch(() => live && setState("down"));
    check();
    const id = setInterval(check, 15000);
    return () => {
      live = false;
      clearInterval(id);
    };
  }, []);
  const dot = state === "up" ? "bg-emerald-500" : state === "down" ? "bg-rose-500" : "bg-amber-500";
  return (
    <div className="flex items-center gap-2 text-xs text-muted" title={coach ? `AI coach: ${coach}` : undefined}>
      <span className={`h-2 w-2 rounded-full ${dot}`} />
      API {state === "up" ? "online" : state === "down" ? "offline" : "…"}
      {state === "up" && coach && <span className="ml-auto">coach: {coach}</span>}
    </div>
  );
}

function Account() {
  const { user, ready, signOut } = useAuth();
  if (!ready) return <div className="h-14 rounded-lg bg-fg/5" />;
  if (!user) {
    return (
      <div className="rounded-lg border border-border p-3 text-sm">
        <div className="mb-2 text-xs text-muted">Players and coaches each get their own dashboard.</div>
        <Link href="/login" className="btn-primary w-full text-center">Log in</Link>
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-border p-3 text-sm">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate font-medium">{user.name}</span>
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${user.role === "coach" ? "bg-sky-500/15 text-sky-500" : "bg-emerald-500/15 text-emerald-500"}`}>{user.role}</span>
      </div>
      <div className="mt-2 flex gap-2">
        <Link href={homeFor(user)} className="btn-ghost flex-1 py-1 text-center text-xs">{user.role === "coach" ? "Coach dashboard" : "My dashboard"}</Link>
        <button onClick={signOut} className="btn-ghost py-1 text-xs">Log out</button>
      </div>
    </div>
  );
}

export default function Nav() {
  const path = usePathname();
  const { user } = useAuth();
  const active = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
  const sections = SECTIONS.map((s) => s.title !== "Improve" ? s : {
    ...s, links: [...(user ? [{ href: homeFor(user), label: user.role === "coach" ? "Coach dashboard" : "My dashboard" }] : []), ...s.links],
  });
  return (
    <aside className="border-b border-border bg-card md:sticky md:top-0 md:h-screen md:w-60 md:shrink-0 md:border-b-0 md:border-r">
      <div className="flex h-full flex-col gap-4 p-4">
        <Link href="/" className="flex items-center gap-2">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-accent font-black text-accent-fg">R</span>
          <span>
            <span className="block font-semibold leading-tight">RallyOS</span>
            <span className="block text-[11px] leading-tight text-muted">Every rally counted</span>
          </span>
        </Link>
        <Account />
        <nav className="flex gap-1 overflow-x-auto md:flex-1 md:flex-col md:gap-4 md:overflow-visible">
          {sections.map((s) => (
            <div key={s.title} className="flex gap-1 md:flex-col">
              <div className="label hidden px-2 md:block">{s.title}</div>
              {s.links.map((l) => (
                <Link
                  key={l.href}
                  href={l.href}
                  className={`whitespace-nowrap rounded-lg px-2 py-1.5 text-sm transition ${
                    active(l.href) ? "bg-accent/15 font-medium text-accent" : "text-fg/80 hover:bg-fg/5"
                  }`}
                >
                  {l.label}
                </Link>
              ))}
            </div>
          ))}
        </nav>
        <div className="hidden space-y-3 md:block">
          <BackendStatus />
          <ThemeToggle />
        </div>
      </div>
    </aside>
  );
}
