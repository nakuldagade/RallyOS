"use client";

// Two doors, one form: a player logs in to their own dashboard, a coach to the academy dashboard.
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { homeFor, useAuth } from "@/lib/auth";
import { Card, ErrorBox, PageHeader } from "@/components/ui";

type Role = "player" | "coach";
const COPY: Record<Role, { title: string; text: string; email: string }> = {
  player: { title: "Player", text: "Your own history, your heatmap over every analysed match, and how you are changing.", email: "anika@rallyos.demo" },
  coach: { title: "Coach", text: "Every player on your roster in one place: who is improving, who needs attention.", email: "coach.vikram@rallyos.demo" },
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
    <div className="mx-auto max-w-3xl">
      <PageHeader title="Log in to RallyOS" subtitle="Players and coaches have separate logins and separate dashboards." />
      <div className="mb-4 grid grid-cols-2 gap-3">
        {(["player", "coach"] as Role[]).map((r) => (
          <button key={r} onClick={() => { setRole(r); setError(null); }} type="button"
            className={`card p-4 text-left transition ${role === r ? "border-accent ring-1 ring-accent" : "hover:border-accent/60"}`}>
            <div className="font-medium">{COPY[r].title} login</div>
            <p className="mt-1 text-sm text-muted">{COPY[r].text}</p>
          </button>
        ))}
      </div>
      <Card title={`${mode === "login" ? "Log in" : "Create an account"} as a ${role}`}>
        <form onSubmit={submit} className="space-y-3">
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
          <div className="flex flex-wrap items-center gap-3">
            <button className="btn-primary" disabled={busy}>{busy ? "Please wait…" : mode === "login" ? "Log in" : "Create account"}</button>
            <button type="button" className="text-sm text-accent" onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(null); }}>
              {mode === "login" ? "New here? Create an account" : "Have an account? Log in"}
            </button>
          </div>
        </form>
        <div className="mt-4 rounded-lg bg-fg/5 p-3 text-xs text-muted">
          Demo accounts (password <code>rallyos-demo</code>): <button type="button" className="text-accent" onClick={() => { setMode("login"); setEmail(COPY[role].email); setPassword("rallyos-demo"); }}>
            fill in {COPY[role].email}</button>. Players: anika, rohan, meera, kabir, isha @rallyos.demo. Coach: coach.vikram@rallyos.demo (has all five players on the roster).
        </div>
      </Card>
    </div>
  );
}
