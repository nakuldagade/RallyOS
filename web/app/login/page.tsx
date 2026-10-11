"use client";

// The front door: a full-screen login (no menu). A player goes on to their own dashboard, a coach to the academy dashboard.
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { homeFor, useAuth } from "@/lib/auth";
import { ErrorBox } from "@/components/ui";

type Role = "player" | "coach";
const COPY: Record<Role, { title: string; text: string; email: string }> = {
  player: { title: "Player", text: "Your history, heatmap and progress over every analysed match.", email: "anika@rallyos.demo" },
  coach: { title: "Coach", text: "Your whole roster: who is improving, who needs attention.", email: "coach.vikram@rallyos.demo" },
};

export default function LoginPage() {
  const router = useRouter();
  const { user, ready, signIn } = useAuth();
  const [role, setRole] = useState<Role>("player");
  const [mode, setMode] = useState<"login" | "register">("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (ready && user) router.replace(homeFor(user));
  }, [ready, user, router]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = mode === "login" ? await api.login(email, password, role) : await api.registerAccount({ name, email, password, role });
      signIn(res.token, res.user);
      router.replace(homeFor(res.user));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      <aside className="relative hidden flex-col justify-between overflow-hidden bg-card p-12 lg:flex">
        <div className="absolute -left-24 -top-24 h-96 w-96 rounded-full bg-accent/15 blur-3xl" />
        <div className="relative flex items-center gap-3">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/logo.png" alt="RallyOS" className="h-12 w-12 object-contain dark:invert" />
          <span className="text-2xl font-semibold tracking-tight">RallyOS</span>
        </div>
        <div className="relative max-w-md">
          <h1 className="text-4xl font-semibold leading-tight tracking-tight">One phone. Any court. Every rally counted.</h1>
          <p className="mt-4 text-muted">A match analyst for six racket sports that calibrates itself and needs no training. Every match becomes a verified record: stats, heatmaps, shot paths in 3D, and a coach that cites its evidence.</p>
          <ul className="mt-6 space-y-2 text-sm text-fg/80">
            <li>● Court and sport detected automatically</li>
            <li>● Players, rallies, shots and movement from one camera</li>
            <li>● Progress over time, for players and coaches</li>
          </ul>
        </div>
        <div className="relative text-xs text-muted">Elevate 1.0 · Problem Statement 02</div>
      </aside>

      <main className="flex items-center justify-center px-6 py-10">
        <div className="w-full max-w-md">
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/logo.png" alt="RallyOS" className="h-10 w-10 object-contain dark:invert" />
            <span className="text-xl font-semibold">RallyOS</span>
          </div>
          <h2 className="text-2xl font-semibold tracking-tight">{mode === "login" ? "Welcome back" : "Create your account"}</h2>
          <p className="mt-1 text-sm text-muted">Log in to open your own dashboard.</p>

          <div className="mt-6 grid grid-cols-2 gap-1 rounded-xl bg-fg/5 p-1" role="tablist" aria-label="Account type">
            {(["player", "coach"] as Role[]).map((r) => (
              <button key={r} type="button" role="tab" aria-selected={role === r} onClick={() => { setRole(r); setError(null); }}
                className={`rounded-lg px-3 py-2 text-sm font-medium transition ${role === r ? "bg-card shadow-sm" : "text-muted hover:text-fg"}`}>
                {COPY[r].title}
              </button>
            ))}
          </div>
          <p className="mt-2 text-xs text-muted">{COPY[role].text}</p>

          <form onSubmit={submit} className="mt-6 space-y-4">
            {mode === "register" && (
              <label className="block text-sm"><div className="label mb-1">Name</div>
                <input className="input w-full" value={name} onChange={(e) => setName(e.target.value)} required autoComplete="name" /></label>
            )}
            <label className="block text-sm"><div className="label mb-1">Email</div>
              <input className="input w-full" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" /></label>
            <label className="block text-sm"><div className="label mb-1">Password</div>
              <input className="input w-full" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={mode === "register" ? 8 : 1}
                autoComplete={mode === "login" ? "current-password" : "new-password"} /></label>
            {error && <ErrorBox message={error} />}
            <button className="btn-primary w-full py-2.5" disabled={busy}>{busy ? "Please wait…" : mode === "login" ? `Log in as ${COPY[role].title.toLowerCase()}` : "Create account"}</button>
            <button type="button" className="w-full text-center text-sm text-accent" onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(null); }}>
              {mode === "login" ? "New here? Create an account" : "Have an account? Log in"}
            </button>
          </form>

          <div className="mt-8 rounded-xl border border-border p-3 text-xs text-muted">
            <div className="mb-1 font-medium text-fg/80">Demo accounts</div>
            Password <code>rallyos-demo</code>.{" "}
            <button type="button" className="text-accent" onClick={() => { setMode("login"); setEmail(COPY[role].email); setPassword("rallyos-demo"); }}>
              Fill in {COPY[role].email}
            </button>
            <div className="mt-1">Players: anika, rohan, meera, kabir, isha, tara @rallyos.demo. Coach: coach.vikram@rallyos.demo.</div>
          </div>
        </div>
      </main>
    </div>
  );
}
