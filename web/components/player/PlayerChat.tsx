"use client";

// Conversational analyst for one player. Answers come from the player's analysed matches only (see api/services/player_chat.py).
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { Badge, Card } from "@/components/ui";

type Msg = { role: "user" | "assistant"; content: string; source?: string; match_ids?: string[] };

const SUGGESTED = ["Give me an overall summary", "Am I improving?", "What should I improve?", "What is my best strength?", "Where do I position myself on court?", "Which shots do I use most?"];

export default function PlayerChat({ playerId, name }: { playerId: string; name?: string }) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => { end.current?.scrollIntoView({ block: "nearest" }); }, [msgs, busy]);

  async function send(q: string) {
    const question = q.trim();
    if (!question || busy) return;
    const next: Msg[] = [...msgs, { role: "user", content: question }];
    setMsgs(next); setText(""); setBusy(true); setError(null);
    try {
      const r = await api.playerChat(playerId, next.map(({ role, content }) => ({ role, content })));
      setMsgs([...next, { role: "assistant", content: r.answer, source: r.source, match_ids: r.match_ids }]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The analyst could not answer.");
    } finally { setBusy(false); }
  }

  return (
    <Card title={`Ask the analyst${name ? ` about ${name}` : ""}`}>
      <p className="mb-3 text-xs text-muted">Answers use only this player&apos;s analysed matches: how they play, where they position, what is best, what to improve, and whether they are improving. With little data it says so instead of guessing.</p>
      <div className="max-h-96 min-h-24 space-y-3 overflow-y-auto rounded-lg border border-border p-3">
        {!msgs.length && <div className="text-sm text-muted">Pick a question below or type your own.</div>}
        {msgs.map((m, i) => (
          <div key={i} className={m.role === "user" ? "flex justify-end" : "flex justify-start"}>
            <div className={`max-w-[85%] rounded-xl px-3 py-2 text-sm ${m.role === "user" ? "bg-accent text-white" : "bg-fg/5"}`}>
              <div>{m.content}</div>
              {m.role === "assistant" && (
                <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-muted">
                  <Badge tone={m.source === "claude" ? "blue" : "neutral"}>{m.source === "claude" ? "AI, numbers checked" : "from your stats"}</Badge>
                  {(m.match_ids ?? []).slice(-4).map((id) => <Link key={id} href={`/matches/${id}`} className="underline">{id}</Link>)}
                </div>
              )}
            </div>
          </div>
        ))}
        {busy && <div className="text-sm text-muted">Thinking…</div>}
        <div ref={end} />
      </div>
      {error && <div className="mt-2 text-sm text-red-500">{error}</div>}
      <div className="mt-3 flex flex-wrap gap-2">
        {SUGGESTED.map((s) => <button key={s} className="btn-ghost py-1 text-xs" disabled={busy} onClick={() => send(s)}>{s}</button>)}
      </div>
      <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); send(text); }}>
        <input className="input flex-1" value={text} onChange={(e) => setText(e.target.value)} placeholder="Ask about games, positions, weaknesses, progress…" />
        <button className="btn-primary" disabled={busy || !text.trim()}>Send</button>
      </form>
    </Card>
  );
}
