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

/** The real HTTP layer. Local storage: chunks are posted to the API. Cloudinary: signed by the API, uploaded straight to Cloudinary, then registered. */
export function browserHttp(api: string): CaptureHttp {
  const storage = { mode: "local" as string };
  const json = async (path: string, body: unknown) => {
    const res = await fetch(api + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!res.ok) throw new Error(((await res.json().catch(() => ({}))) as { detail?: string }).detail ?? res.statusText);
    return res.json();
  };
  return {
    async createSession(b) {
      const info = (await json("/v1/live/sessions", b)) as SessionInfo;
      storage.mode = info.storage;
      return info;
    },
    async sendChunk(sessionId, c, uploadS) {
      const id = encodeURIComponent(sessionId);
      const name = `chunk_${String(c.seq).padStart(4, "0")}.${c.ext}`;
      const fail = async (res: Response, what: string) => {
        // 4xx other than "slow down" means the server looked at this chunk and refused it: retrying cannot help.
        if (res.status >= 400 && res.status < 500 && res.status !== 408 && res.status !== 429) {
          throw new PermanentUploadError(`${what}: ${res.status} ${await res.text().catch(() => "")}`);
        }
        throw new Error(`${what} failed (${res.status})`);
      };
      if (storage.mode === "cloudinary") {
        // The API signs, the chunk goes straight to Cloudinary, then the API is told where it is and fetches it to analyse it.
        const signRes = await fetch(`${api}/v1/live/sessions/${id}/sign?seq=${c.seq}`, { method: "POST" });
        if (!signRes.ok) return fail(signRes, "sign");
        const sign = (await signRes.json()) as { upload_url: string; fields: Record<string, string>; file_field: string };
        const cf = new FormData();
        for (const [k, v] of Object.entries(sign.fields)) cf.append(k, v);
        cf.append(sign.file_field, c.blob, name);
        const up = await fetch(sign.upload_url, { method: "POST", body: cf });
        if (!up.ok) {
          // an expired signature or a bad upload is retried with a fresh signature (a new attempt signs again)
          throw new Error(`Cloudinary upload failed (${up.status})`);
        }
        const url = ((await up.json()) as { secure_url: string }).secure_url;
        const reg = await fetch(`${api}/v1/live/sessions/${id}/chunks/register`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ seq: c.seq, url, t0: c.t0, duration: c.duration, upload_s: uploadS }),
        });
        if (!reg.ok) return fail(reg, "register");
        return;
      }
      const form = new FormData();
      form.append("chunk", c.blob, name);
      form.append("seq", String(c.seq));
      form.append("t0", String(c.t0));
      form.append("duration", String(c.duration));
      form.append("upload_s", String(uploadS));
      const res = await fetch(`${api}/v1/live/sessions/${id}/chunks`, { method: "POST", body: form });
      if (res.ok) return;
      return fail(res, "upload");
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
