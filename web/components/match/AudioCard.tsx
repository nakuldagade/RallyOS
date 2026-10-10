// Hits heard from the soundtrack (§4.4) and how they were combined with the shuttle path.
import type { AudioStats } from "@/lib/types";
import { Badge } from "@/components/ui";

export default function AudioCard({ audio }: { audio: AudioStats }) {
  if (audio.status !== "ok") {
    return (
      <p className="text-sm text-muted">
        Audio not used: <span className="font-medium text-fg">{audio.status}</span>. Hits come from the shuttle path only.
        {audio.status === "no audio track" && " Record with sound on next time: every hit makes a sharp click that confirms it to about 1 ms."}
      </p>
    );
  }
  return (
    <div className="space-y-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">Spectral-flux onsets</span>
        <Badge tone="green" title="Signal processing only; no trained model">no training</Badge>
      </div>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
        <dt className="text-muted">Onsets heard</dt><dd className="text-right tabular-nums">{audio.onsets}</dd>
        <dt className="text-muted">Confirmed (sound + shuttle)</dt><dd className="text-right tabular-nums">{audio.matched}</dd>
        <dt className="text-muted">Sound only (shuttle hidden)</dt><dd className="text-right tabular-nums">{audio.audio_only}</dd>
        <dt className="text-muted">Shuttle only (no click)</dt><dd className="text-right tabular-nums">{audio.vision_only}</dd>
        <dt className="text-muted">A/V sync offset</dt><dd className="text-right tabular-nums">{(audio.av_offset_s * 1000).toFixed(0)} ms</dd>
        <dt className="text-muted">Speed-of-sound fix</dt>
        <dd className="text-right tabular-nums">{audio.sound_delay_corrected ? (audio.mean_sound_delay_ms != null ? `≈ ${audio.mean_sound_delay_ms} ms` : "on") : "off (no calibration)"}</dd>
      </dl>
      <p className="text-[11px] text-muted">
        Sound-only hits get their hitter from turn order (flagged) and lower confidence. Shuttle-only hits with no click are discounted.
      </p>
    </div>
  );
}
