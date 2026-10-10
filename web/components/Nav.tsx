"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

const SECTIONS: { title: string; links: { href: string; label: string }[] }[] = [
  { title: "Analyse", links: [
    { href: "/", label: "Home" },
    { href: "/upload", label: "Analyse a match" },
    { href: "/capture", label: "Record live" },
    { href: "/live/demo", label: "Live replay demo" },
    { href: "/matches", label: "Matches" },
  ] },
  { title: "Improve", links: [
    { href: "/players", label: "Players" },
    { href: "/coach", label: "Coach dashboard" },
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

export default function Nav() {
  const path = usePathname();
  const active = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
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
        <nav className="flex gap-1 overflow-x-auto md:flex-1 md:flex-col md:gap-4 md:overflow-visible">
          {SECTIONS.map((s) => (
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
