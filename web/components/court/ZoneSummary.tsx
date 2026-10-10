// Where each player spends most time: share per zone of their own half, live up to the current moment
// or for the whole clip. Zones are front/mid/rear x left/centre/right from the player's point of view.
import { pct } from "@/lib/format";
import type { ZoneShare } from "@/lib/sports";
import type { PlayerRef } from "@/lib/types";

export interface PlayerZones { player: PlayerRef; live: ZoneShare[]; whole: ZoneShare[] }

const nice = (z: string) => z.replace("-", " · ");

export default function ZoneSummary({ rows, timeLabel }: { rows: PlayerZones[]; timeLabel: string }) {
  if (!rows.some((r) => r.whole.length)) return null;
  return (
    <div className="mt-3 space-y-3">
      <div className="label">Where each player spends most time</div>
      {rows.map(({ player, live, whole }) => (
        <div key={player.track_id} className="text-sm">
          <div className="flex items-center gap-2">
            <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: player.color ?? "#94a3b8" }} />
            <span className="font-medium">{player.name}</span>
            {whole[0] && <span className="ml-auto text-xs text-muted">whole clip: <b className="text-fg">{nice(whole[0].zone)}</b> {pct(whole[0].pct)}</span>}
          </div>
          <div className="mt-1 space-y-0.5">
            {live.slice(0, 3).map((z) => (
              <div key={z.zone} className="flex items-center gap-2 text-xs">
                <span className="w-28 text-muted">{nice(z.zone)}</span>
                <div className="h-1.5 flex-1 rounded bg-fg/10">
                  <div className="h-1.5 rounded" style={{ width: `${Math.round(z.pct * 100)}%`, background: player.color ?? "#94a3b8" }} />
                </div>
                <span className="w-10 text-right tabular-nums">{pct(z.pct)}</span>
              </div>
            ))}
            {!live.length && <div className="text-xs text-muted">Not tracked on court yet.</div>}
          </div>
        </div>
      ))}
      <p className="text-[11px] text-muted">Bars: share of tracked time {timeLabel}. Left/right as the player sees it, facing the net. Dashed boxes on the court mark each player&apos;s top zone so far.</p>
    </div>
  );
}
