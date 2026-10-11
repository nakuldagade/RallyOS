"use client";

// A written summary of this analysed match, built from its own stats (api/services/match_summary.py), with a free voice read-out
// from the browser's own speech engine (no key, works offline once the system voices are installed).
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { Badge, Card } from "@/components/ui";

function pickVoice(): SpeechSynthesisVoice | undefined {
  const voices = window.speechSynthesis.getVoices().filter((v) => /^en/i.test(v.lang));
  const rank = (v: SpeechSynthesisVoice) => (/natural|neural|online/i.test(v.name) ? 3 : 0) + (/google|microsoft/i.test(v.name) ? 1 : 0) + (/en-(IN|GB|US)/i.test(v.lang) ? 1 : 0);
  return [...voices].sort((a, b) => rank(b) - rank(a))[0];
}

export default function MatchSummaryBot({ matchId }: { matchId: string }) {
  const [res, setRes] = useState<{ summary: string; source: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [speaking, setSpeaking] = useState(false);
  const [canSpeak, setCanSpeak] = useState(false);
  const live = useRef(true);

  useEffect(() => {
    live.current = true;
    setCanSpeak(typeof window !== "undefined" && "speechSynthesis" in window);
    return () => { live.current = false; try { window.speechSynthesis?.cancel(); } catch { /* no speech engine */ } };
  }, []);

  useEffect(() => {
    setRes(null); setError(null);
    try { window.speechSynthesis?.cancel(); } catch { /* no speech engine */ }
    setSpeaking(false);
    api.matchSummary(matchId).then(setRes).catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [matchId]);

  function toggle() {
    const synth = window.speechSynthesis;
    if (speaking) { synth.cancel(); setSpeaking(false); return; }
    if (!res) return;
    const u = new SpeechSynthesisUtterance(res.summary);
    const v = pickVoice();
    if (v) { u.voice = v; u.lang = v.lang; } else u.lang = "en-IN";
    u.rate = 1.0;
    u.onend = u.onerror = () => live.current && setSpeaking(false);
    synth.cancel();
    synth.speak(u);
    setSpeaking(true);
  }

  return (
    <Card title="Analyst summary of this match" actions={
      <div className="flex items-center gap-2">
        {res && <Badge tone={res.source === "claude" ? "blue" : "neutral"}>{res.source === "claude" ? "AI, numbers checked" : "from the match stats"}</Badge>}
        {res && canSpeak && (
          <button className="btn-ghost py-1 text-xs" onClick={toggle} aria-pressed={speaking} title="Read the summary aloud with your browser's voice">
            {speaking ? "■ Stop" : "▶ Listen"}
          </button>
        )}
      </div>}>
      {error ? <p className="text-sm text-red-500">{error}</p> : !res ? <p className="text-sm text-muted">Writing the summary…</p> : <p className="text-sm leading-relaxed">{res.summary}</p>}
    </Card>
  );
}
