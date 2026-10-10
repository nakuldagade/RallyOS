// Cuts one continuous camera stream into independently decodable chunks: a new recorder starts every `chunkSeconds` and
// runs for `chunkSeconds + overlapSeconds`, so around a boundary two recorders are alive (the "staggered pair") and
// neither loses a frame: chunk k covers [k*L, (k+1)*L + O) and its last O seconds are the first O seconds of chunk k+1.
// The server skips the repeated frames by time. Every recorder starts and stops separately, so each file has its own
// header and can be decoded on its own (a MediaRecorder timeslice would give fragments that cannot).
//
// Timing uses a monotonic clock (performance.now) and absolute schedule times, so a late timer never accumulates drift.
// Nothing here touches the DOM: the recorder factory and the clock are injected, which is how the tests drive it.

export interface RecorderLike {
  start(): void;
  stop(): void;
  ondataavailable: ((e: { data: Blob }) => void) | null;
  onstart: (() => void) | null;
  onstop: (() => void) | null;
  onerror: ((e: unknown) => void) | null;
}

export interface Chunk {
  seq: number;
  blob: Blob;
  mime: string;
  ext: string;
  t0: number;            // seconds from the moment Start was pressed, measured when the recorder really started
  duration: number;      // seconds actually recorded (L + O, or less for the last chunk)
  wallStartMs: number;   // wall-clock (epoch ms) of t0, so chunks can be placed in real time
  readyAtMs: number;     // monotonic clock when the file was complete (latency is measured from here)
}

export interface Clock {
  now(): number;                                          // monotonic ms (performance.now)
  wall(): number;                                         // epoch ms (Date.now)
  setTimeout(fn: () => void, ms: number): unknown;
  clearTimeout(id: unknown): void;
}

export interface SegmenterOptions {
  makeRecorder: () => RecorderLike;
  mime: string;
  chunkSeconds?: number;
  overlapSeconds?: number;
  clock?: Clock;
  onChunk: (c: Chunk) => void;
  onError?: (err: unknown, seq: number) => void;
}

export const realClock: Clock = {
  now: () => performance.now(),
  wall: () => Date.now(),
  setTimeout: (fn, ms) => setTimeout(fn, ms),
  clearTimeout: (id) => clearTimeout(id as ReturnType<typeof setTimeout>),
};

/** File extension for a recorder mime type. */
export function extFor(mime: string): string {
  return /mp4/i.test(mime) ? "mp4" : "webm";
}

/** Best container the browser can record, preferring one with an audio track (hits are heard, too). */
export function pickMime(isSupported: (m: string) => boolean): string {
  const candidates = [
    "video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/mp4;codecs=avc1.42E01E,mp4a.40.2", "video/mp4", "video/webm",
  ];
  return candidates.find(isSupported) ?? "";
}

interface Live {
  seq: number;
  rec: RecorderLike;
  parts: Blob[];
  startedAt: number;
  startedWall: number;
  stopTimer: unknown;
  stopping: boolean;
  done: Promise<void>;
  finish: () => void;
}

export class Segmenter {
  private L: number;
  private O: number;
  private clock: Clock;
  private opts: SegmenterOptions;
  private origin = 0;
  private nextSeq = 0;
  private startTimer: unknown = null;
  private live = new Map<number, Live>();
  private running = false;
  private lastEmitted = -1;

  constructor(opts: SegmenterOptions) {
    this.opts = opts;
    this.L = opts.chunkSeconds ?? 5;
    this.O = opts.overlapSeconds ?? 0.5;
    this.clock = opts.clock ?? realClock;
  }

  get lastSeq(): number {
    return this.lastEmitted;
  }

  /** Sequence numbers of the recorders running right now (two around a boundary). */
  get active(): number[] {
    return [...this.live.keys()].sort((a, b) => a - b);
  }

  start(): void {
    if (this.running) return;
    this.running = true;
    this.origin = this.clock.now();
    this.beginChunk(0);
  }

  /** Stop: every chunk being recorded is closed now (the last one is shorter); resolves with the last seq handed out. */
  async stop(): Promise<number> {
    this.running = false;
    if (this.startTimer !== null) this.clock.clearTimeout(this.startTimer);
    this.startTimer = null;
    const pending = [...this.live.values()];
    for (const l of pending) this.endChunk(l);
    await Promise.all(pending.map((l) => l.done));
    return this.lastEmitted;
  }

  private beginChunk(seq: number): void {
    if (!this.running) return;
    this.nextSeq = seq + 1;
    // The next chunk starts L after this one's nominal start, measured from the origin (no accumulated drift).
    const nextAt = this.origin + this.nextSeq * this.L * 1000;
    this.startTimer = this.clock.setTimeout(() => this.beginChunk(this.nextSeq), Math.max(0, nextAt - this.clock.now()));

    let finish: () => void = () => {};
    const done = new Promise<void>((res) => { finish = res; });
    let rec: RecorderLike;
    try {
      rec = this.opts.makeRecorder();
    } catch (err) {
      this.opts.onError?.(err, seq);
      return;
    }
    const l: Live = { seq, rec, parts: [], startedAt: this.clock.now(), startedWall: this.clock.wall(), stopTimer: null, stopping: false, done, finish };
    this.live.set(seq, l);
    rec.ondataavailable = (e) => { if (e.data && e.data.size > 0) l.parts.push(e.data); };
    rec.onstart = () => { l.startedAt = this.clock.now(); l.startedWall = this.clock.wall(); };
    rec.onerror = (err) => this.opts.onError?.(err, seq);
    rec.onstop = () => this.emit(l);
    try {
      rec.start();
    } catch (err) {
      this.live.delete(seq);
      this.opts.onError?.(err, seq);
      finish();
      return;
    }
    const stopAt = this.origin + (seq * this.L + this.L + this.O) * 1000;
    l.stopTimer = this.clock.setTimeout(() => this.endChunk(l), Math.max(0, stopAt - this.clock.now()));
  }

  private endChunk(l: Live): void {
    if (l.stopping) return;
    l.stopping = true;
    this.clock.clearTimeout(l.stopTimer);
    try {
      l.rec.stop();
    } catch (err) {
      this.opts.onError?.(err, l.seq);
      this.live.delete(l.seq);
      l.finish();
    }
  }

  private emit(l: Live): void {
    const end = this.clock.now();
    this.live.delete(l.seq);
    const duration = (end - l.startedAt) / 1000;
    // A chunk that only ever saw the overlap of the previous one (Stop pressed right after a boundary) has nothing new.
    const nothingNew = l.seq > 0 && duration <= this.O + 0.1;
    if (!nothingNew && l.parts.length > 0) {
      const mime = this.opts.mime || (l.parts[0].type ?? "video/webm");
      this.lastEmitted = Math.max(this.lastEmitted, l.seq);
      this.opts.onChunk({
        seq: l.seq, blob: new Blob(l.parts, { type: mime }), mime, ext: extFor(mime),
        t0: (l.startedAt - this.origin) / 1000, duration, wallStartMs: l.startedWall, readyAtMs: end,
      });
    }
    l.finish();
  }
}
