// Chunks wait here until the server has them. They are written to IndexedDB first (a dropped network, a reloaded page or a
// crashed tab does not lose footage), then sent strictly in order, one at a time, retrying the oldest one with exponential
// backoff. Strict order keeps the server's per-session worker simple, and a gap on the server is then a real loss, not a race.
import type { Chunk } from "./segmenter.ts";

export interface StoredChunk {
  key: string;                       // `${sessionId}:${seq}`
  sessionId: string;
  seq: number;
  blob: Blob;
  ext: string;
  t0: number;
  duration: number;
  wallStartMs: number;
  readyAtMs: number;
}

export interface OutboxStore {
  put(c: StoredChunk): Promise<void>;
  remove(key: string): Promise<void>;
  list(sessionId: string): Promise<StoredChunk[]>;
}

export class MemoryStore implements OutboxStore {
  private m = new Map<string, StoredChunk>();
  async put(c: StoredChunk) { this.m.set(c.key, c); }
  async remove(key: string) { this.m.delete(key); }
  async list(sessionId: string) { return [...this.m.values()].filter((c) => c.sessionId === sessionId).sort((a, b) => a.seq - b.seq); }
}

/** IndexedDB-backed store. If IndexedDB is unavailable (private mode), chunks stay in memory and `persistent` turns false. */
export class IdbStore implements OutboxStore {
  persistent = true;
  private db: Promise<IDBDatabase | null>;
  private fallback = new MemoryStore();

  constructor(name = "rallyos-outbox") {
    this.db = new Promise((resolve) => {
      try {
        const req = indexedDB.open(name, 1);
        req.onupgradeneeded = () => req.result.createObjectStore("chunks", { keyPath: "key" });
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => { this.persistent = false; resolve(null); };
      } catch {
        this.persistent = false;
        resolve(null);
      }
    });
  }

  private async tx<T>(mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>): Promise<T | undefined> {
    const db = await this.db;
    if (!db) return undefined;
    return new Promise<T>((resolve, reject) => {
      const r = fn(db.transaction("chunks", mode).objectStore("chunks"));
      r.onsuccess = () => resolve(r.result);
      r.onerror = () => reject(r.error);
    });
  }

  async put(c: StoredChunk) {
    if (!(await this.db)) return this.fallback.put(c);
    try { await this.tx("readwrite", (s) => s.put(c)); } catch { this.persistent = false; await this.fallback.put(c); }
  }
  async remove(key: string) {
    await this.fallback.remove(key);
    if (await this.db) { try { await this.tx("readwrite", (s) => s.delete(key)); } catch { /* already gone */ } }
  }
  async list(sessionId: string) {
    const out = new Map<string, StoredChunk>();
    for (const c of await this.fallback.list(sessionId)) out.set(c.key, c);
    if (await this.db) {
      const all = ((await this.tx("readonly", (s) => s.getAll())) ?? []) as StoredChunk[];
      for (const c of all) if (c.sessionId === sessionId) out.set(c.key, c);
    }
    return [...out.values()].sort((a, b) => a.seq - b.seq);
  }
}

/** Thrown by `send` when retrying cannot help (the server refused the chunk itself): the chunk is dropped, the queue moves on. */
export class PermanentUploadError extends Error {}

export type ChunkPhase = "buffered" | "uploading" | "uploaded" | "failed";

export interface UploaderStatus {
  pending: number;        // chunks not yet on the server (including the one being sent)
  online: boolean;        // false after a failed attempt, true again after a success
  sent: number;
  failed: number;
}

export interface UploaderOptions {
  store: OutboxStore;
  send: (c: StoredChunk, attempt: number) => Promise<void>;
  sleep?: (ms: number) => Promise<void>;
  onPhase?: (seq: number, phase: ChunkPhase, info: { tries: number; uploadS?: number }) => void;
  onStatus?: (s: UploaderStatus) => void;
  now?: () => number;
  baseMs?: number;
  capMs?: number;
}

export class Uploader {
  private o: UploaderOptions;
  private queue: StoredChunk[] = [];
  private running = false;
  private idle: (() => void)[] = [];
  private status: UploaderStatus = { pending: 0, online: true, sent: 0, failed: 0 };
  private tries = new Map<number, number>();
  private sleep: (ms: number) => Promise<void>;
  private now: () => number;
  private base: number;
  private cap: number;

  constructor(o: UploaderOptions) {
    this.o = o;
    this.sleep = o.sleep ?? ((ms) => new Promise((r) => setTimeout(r, ms)));
    this.now = o.now ?? (() => performance.now());
    this.base = o.baseMs ?? 1000;
    this.cap = o.capMs ?? 8000;
  }

  get state(): UploaderStatus {
    return this.status;
  }

  async enqueue(sessionId: string, c: Chunk): Promise<void> {
    const stored: StoredChunk = { key: `${sessionId}:${c.seq}`, sessionId, seq: c.seq, blob: c.blob, ext: c.ext, t0: c.t0,
                                  duration: c.duration, wallStartMs: c.wallStartMs, readyAtMs: c.readyAtMs };
    await this.o.store.put(stored);               // on disk first: from here on a dead network cannot lose it
    this.add(stored);
  }

  /** Chunks left in the store by an earlier page load of the same session. */
  async recover(sessionId: string): Promise<number> {
    const left = await this.o.store.list(sessionId);
    for (const c of left) this.add(c);
    return left.length;
  }

  private add(c: StoredChunk) {
    if (this.queue.some((q) => q.key === c.key)) return;
    this.queue.push(c);
    this.queue.sort((a, b) => a.seq - b.seq);
    this.o.onPhase?.(c.seq, "buffered", { tries: 0 });
    this.publish();
    void this.run();
  }

  private publish() {
    this.status = { ...this.status, pending: this.queue.length };
    this.o.onStatus?.(this.status);
  }

  private async run() {
    if (this.running) return;
    this.running = true;
    while (this.queue.length) {
      const head = this.queue[0];
      const attempt = (this.tries.get(head.seq) ?? 0) + 1;
      this.tries.set(head.seq, attempt);
      this.o.onPhase?.(head.seq, "uploading", { tries: attempt });
      const t = this.now();
      try {
        await this.o.send(head, attempt);
        this.queue.shift();
        await this.o.store.remove(head.key);
        this.status = { ...this.status, online: true, sent: this.status.sent + 1 };
        this.o.onPhase?.(head.seq, "uploaded", { tries: attempt, uploadS: (this.now() - t) / 1000 });
        this.publish();
      } catch (err) {
        if (err instanceof PermanentUploadError) {
          this.queue.shift();
          await this.o.store.remove(head.key);
          this.status = { ...this.status, failed: this.status.failed + 1 };
          this.o.onPhase?.(head.seq, "failed", { tries: attempt });
          this.publish();
          continue;
        }
        this.status = { ...this.status, online: false };
        this.o.onPhase?.(head.seq, "buffered", { tries: attempt });
        this.publish();
        const wait = Math.min(this.cap, this.base * 2 ** (attempt - 1));
        await this.sleep(wait * (0.85 + 0.3 * Math.random()));
      }
    }
    this.running = false;
    const waiting = this.idle.splice(0);
    waiting.forEach((r) => r());
  }

  /** Resolves when every enqueued chunk has been delivered (or permanently refused). */
  drained(): Promise<void> {
    if (!this.running && this.queue.length === 0) return Promise.resolve();
    return new Promise((r) => this.idle.push(r));
  }
}
