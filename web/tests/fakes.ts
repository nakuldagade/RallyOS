// Test doubles: a virtual clock (timers fire in order as time is advanced) and a MediaRecorder that "records" the virtual
// time it ran for. Its output is a small self-describing blob, so a test can check that every chunk is a complete file.
import type { Clock, RecorderLike } from "../lib/segmenter.ts";

interface Timer { id: number; at: number; fn: () => void }

export class FakeClock implements Clock {
  t = 0;                       // virtual ms
  epoch = 1_700_000_000_000;
  private timers: Timer[] = [];
  private n = 0;

  now() { return this.t; }
  wall() { return this.epoch + this.t; }
  setTimeout(fn: () => void, ms: number) {
    const id = ++this.n;
    this.timers.push({ id, at: this.t + Math.max(0, ms), fn });
    return id;
  }
  clearTimeout(id: unknown) { this.timers = this.timers.filter((x) => x.id !== id); }
  sleep = (ms: number) => new Promise<void>((res) => { this.setTimeout(res, ms); });

  /** Move time forward, running every timer that falls due and letting promise callbacks settle in between. */
  async advance(ms: number) {
    const end = this.t + ms;
    for (;;) {
      await settle();
      const due = this.timers.filter((x) => x.at <= end).sort((a, b) => a.at - b.at || a.id - b.id)[0];
      if (!due) break;
      this.timers = this.timers.filter((x) => x !== due);
      this.t = Math.max(this.t, due.at);
      due.fn();
    }
    this.t = end;
    await settle();
  }
}

export async function settle(rounds = 12) {
  for (let i = 0; i < rounds; i++) await new Promise<void>((r) => setImmediate(r));
}

/** Records nothing real: on stop it emits a blob that says when it started and stopped (virtual seconds). */
export class FakeRecorder implements RecorderLike {
  ondataavailable: ((e: { data: Blob }) => void) | null = null;
  onstart: (() => void) | null = null;
  onstop: (() => void) | null = null;
  onerror: ((e: unknown) => void) | null = null;
  private startedAt = 0;
  private state: "inactive" | "recording" = "inactive";
  private clock: FakeClock;
  constructor(clock: FakeClock, registry: FakeRecorder[]) { this.clock = clock; registry.push(this); }
  start() { this.state = "recording"; this.startedAt = this.clock.now(); this.onstart?.(); }
  stop() {
    if (this.state !== "recording") throw new Error("InvalidStateError: recorder is not recording");
    this.state = "inactive";
    const header = JSON.stringify({ magic: "FAKEWEBM", from: this.startedAt / 1000, to: this.clock.now() / 1000 });
    this.ondataavailable?.({ data: new Blob([header]) });
    this.onstop?.();
  }
}

/** A chunk is "decodable" here when its blob parses as a complete fake file whose length matches the chunk's metadata. */
export async function decodeFake(blob: Blob): Promise<{ from: number; to: number }> {
  const j = JSON.parse(await blob.text());
  if (j.magic !== "FAKEWEBM") throw new Error("not a complete file");
  return { from: j.from, to: j.to };
}
