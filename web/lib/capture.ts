// Glue for the capture page: create a live session, cut the camera stream into chunks (segmenter), keep them safe and send
// them in order (outbox), and on Stop wait until everything has been delivered before telling the server the match is over.
// No DOM here either: the recorder factory and the HTTP layer are injected so the tests can run it with fakes.
import { PermanentUploadError, Uploader } from "./outbox.ts";
import type { ChunkPhase, OutboxStore, StoredChunk, UploaderStatus } from "./outbox.ts";
import { Segmenter, realClock } from "./segmenter.ts";
import type { Chunk, Clock, RecorderLike } from "./segmenter.ts";

export interface SessionInfo {
  session_id: string;
  chunk_seconds: number;
  storage: string;
}

export interface CaptureHttp {
  createSession(body: { sport: string; corners: number[][] | null; chunk_seconds: number }): Promise<SessionInfo>;
  sendChunk(sessionId: string, c: StoredChunk, uploadS: number): Promise<void>;   // throws PermanentUploadError when retrying is pointless
  stop(sessionId: string, lastSeq: number): Promise<void>;
  setCorners(sessionId: string, taps: number[][]): Promise<void>;
}

export interface CaptureOptions {
  http: CaptureHttp;
  store: OutboxStore;
  makeRecorder: () => RecorderLike;
  mime: string;
  clock?: Clock;
  sleep?: (ms: number) => Promise<void>;
  chunkSeconds?: number;
  overlapSeconds?: number;
  onPhase?: (seq: number, phase: ChunkPhase, info: { tries: number; uploadS?: number }, chunk?: Chunk) => void;
  onStatus?: (s: UploaderStatus) => void;
  onError?: (err: unknown) => void;
}

export class Capture {
  private o: CaptureOptions;
  private seg: Segmenter | null = null;
  private up: Uploader;
  private sessionId = "";
  private lastUploadS = 0;
  private enqueued: Promise<void>[] = [];
  private chunks = new Map<number, Chunk>();

  constructor(o: CaptureOptions) {
    this.o = o;
    this.up = new Uploader({
      store: o.store,
      sleep: o.sleep,
      now: () => (o.clock ?? realClock).now(),
      send: (c) => o.http.sendChunk(c.sessionId, c, this.lastUploadS),
      onPhase: (seq, phase, info) => {
        if (phase === "uploaded" && info.uploadS !== undefined) this.lastUploadS = info.uploadS;
        o.onPhase?.(seq, phase, info, this.chunks.get(seq));
      },
      onStatus: o.onStatus,
    });
  }

  get id(): string {
    return this.sessionId;
  }

  get uploader(): Uploader {
    return this.up;
  }

  get segmenter(): Segmenter | null {
    return this.seg;
  }

  /** Create the session and begin recording. Resolves with the session once the first recorder is running. */
  async start(sport: string, corners: number[][] | null): Promise<SessionInfo> {
    const info = await this.o.http.createSession({ sport, corners, chunk_seconds: this.o.chunkSeconds ?? 5 });
    if (info.storage !== "local") {
      throw new Error(`The server uses "${info.storage}" storage; direct upload to it is phase E. Set RALLYOS_STORAGE=local.`);
    }
    this.sessionId = info.session_id;
    this.seg = new Segmenter({
      makeRecorder: this.o.makeRecorder, mime: this.o.mime, clock: this.o.clock,
      chunkSeconds: info.chunk_seconds, overlapSeconds: this.o.overlapSeconds,
      onChunk: (c) => {
        this.chunks.set(c.seq, c);
        this.enqueued.push(this.up.enqueue(this.sessionId, c));
      },
      onError: (err) => this.o.onError?.(err),
    });
    this.seg.start();
    return info;
  }

  /** Stop the recording, deliver everything still buffered, then end the match on the server. Resolves with the last seq. */
  async stop(): Promise<number> {
    const last = this.seg ? await this.seg.stop() : -1;
    await Promise.all(this.enqueued);
    await this.up.drained();
    if (last >= 0) await this.o.http.stop(this.sessionId, last);
    return last;
  }

  setCorners(taps: number[][]): Promise<void> {
    return this.o.http.setCorners(this.sessionId, taps);
  }
}

/** The real HTTP layer: local storage, chunks posted straight to the API. */
export function browserHttp(api: string): CaptureHttp {
  const json = async (path: string, body: unknown) => {
    const res = await fetch(api + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!res.ok) throw new Error(((await res.json().catch(() => ({}))) as { detail?: string }).detail ?? res.statusText);
    return res.json();
  };
  return {
    createSession: (b) => json("/v1/live/sessions", b),
    async sendChunk(sessionId, c, uploadS) {
      const form = new FormData();
      form.append("chunk", c.blob, `chunk_${String(c.seq).padStart(4, "0")}.${c.ext}`);
      form.append("seq", String(c.seq));
      form.append("t0", String(c.t0));
      form.append("duration", String(c.duration));
      form.append("upload_s", String(uploadS));
      const res = await fetch(`${api}/v1/live/sessions/${encodeURIComponent(sessionId)}/chunks`, { method: "POST", body: form });
      if (res.ok) return;
      // 4xx other than "slow down" means the server looked at this chunk and refused it: retrying cannot help.
      if (res.status >= 400 && res.status < 500 && res.status !== 408 && res.status !== 429) {
        throw new PermanentUploadError(`${res.status} ${await res.text().catch(() => "")}`);
      }
      throw new Error(`upload failed (${res.status})`);
    },
    async stop(sessionId, lastSeq) {
      await json(`/v1/live/sessions/${encodeURIComponent(sessionId)}/stop`, { last_seq: lastSeq });
    },
    async setCorners(sessionId, taps) {
      await json(`/v1/live/sessions/${encodeURIComponent(sessionId)}/corners`, { taps });
    },
  };
}

/** A MediaRecorder on the camera stream, at a bitrate high enough not to smear a small, fast shuttle. */
export function mediaRecorderFactory(stream: MediaStream, mime: string, bitsPerSecond = 8_000_000): () => RecorderLike {
  return () => new MediaRecorder(stream, { ...(mime ? { mimeType: mime } : {}), videoBitsPerSecond: bitsPerSecond }) as unknown as RecorderLike;
}
