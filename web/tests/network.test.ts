// Network-loss behaviour of the whole capture path (segmenter + outbox + ordered upload), with fakes for the camera,
// the clock and the server.
import assert from "node:assert/strict";
import { test } from "node:test";
import { Capture } from "../lib/capture.ts";
import type { CaptureHttp } from "../lib/capture.ts";
import { MemoryStore, PermanentUploadError } from "../lib/outbox.ts";
import type { ChunkPhase, StoredChunk } from "../lib/outbox.ts";
import { FakeClock, FakeRecorder, decodeFake } from "./fakes.ts";

function rig(blockedFromS: number, blockedToS: number) {
  const clock = new FakeClock();
  const recorders: FakeRecorder[] = [];
  const received: { seq: number; at: number; from: number; to: number }[] = [];
  const calls = { attempts: 0, stop: null as null | { at: number; last: number }, created: 0 };
  const phases: [number, ChunkPhase, number][] = [];
  let maxPending = 0;
  const http: CaptureHttp = {
    async createSession(body) { calls.created++; return { session_id: "s_test", chunk_seconds: body.chunk_seconds, storage: "local" }; },
    async sendChunk(_id, c: StoredChunk) {
      calls.attempts++;
      const s = clock.now() / 1000;
      if (s >= blockedFromS && s < blockedToS) throw new Error("network down");
      const f = await decodeFake(c.blob);
      received.push({ seq: c.seq, at: s, ...f });
    },
    async stop(_id, last) { calls.stop = { at: clock.now() / 1000, last }; },
    async setCorners() {},
  };
  const store = new MemoryStore();
  const cap = new Capture({
    http, store, clock, sleep: clock.sleep, mime: "video/webm",
    makeRecorder: () => new FakeRecorder(clock, recorders),
    onPhase: (seq, phase) => phases.push([seq, phase, clock.now() / 1000]),
    onStatus: (s) => { maxPending = Math.max(maxPending, s.pending); },
  });
  return { clock, cap, received, calls, phases, store, maxPending: () => maxPending };
}

test("uploads blocked for 20 s: buffered chunks arrive later, in order, and the match is complete", async () => {
  const r = rig(8, 28);                                          // network down from 8 s to 28 s
  await r.cap.start("badminton", null);
  await r.clock.advance(40_000);
  const stopping = r.cap.stop();
  await r.clock.advance(20_000);
  const last = await stopping;

  // 40 s of footage = 8 chunks, and all of them reached the server
  assert.equal(last, 7);
  assert.deepEqual(r.received.map((x) => x.seq), [0, 1, 2, 3, 4, 5, 6, 7], "every chunk arrived exactly once, in order");
  // chunks recorded during the outage were delivered after it
  const during = r.received.filter((x) => x.from >= 4 && x.to <= 28.6);
  assert.ok(during.length >= 3, "some chunks were recorded during the outage");
  for (const x of during) assert.ok(x.at >= 28, `chunk ${x.seq} sent at ${x.at} s, after the network came back`);
  // retries really happened, and the buffer filled up while offline
  assert.ok(r.calls.attempts > r.received.length, "failed attempts were retried");
  assert.ok(r.maxPending() >= 3, `buffer peaked at ${r.maxPending()} chunks`);
  // the file contents are intact and consecutive chunks still overlap by about 0.5 s
  for (let k = 0; k < r.received.length - 1; k++) {
    const overlap = r.received[k].to - r.received[k + 1].from;
    assert.ok(overlap > 0.4 && overlap < 0.6, `overlap ${overlap} between chunk ${k} and ${k + 1}`);
  }
  // the server is told to finish only after the last chunk was delivered, and which one was last
  assert.ok(r.calls.stop);
  assert.equal(r.calls.stop!.last, 7);
  assert.ok(r.calls.stop!.at >= r.received[r.received.length - 1].at);
  assert.equal((await r.store.list("s_test")).length, 0, "nothing is left in the outbox");
});

test("Stop while still offline waits for the network instead of dropping the buffered chunks", async () => {
  const r = rig(3, 40);
  await r.cap.start("badminton", null);
  await r.clock.advance(12_000);
  let finished = false;
  const stopping = r.cap.stop().then((n) => { finished = true; return n; });
  await r.clock.advance(20_000);
  assert.equal(finished, false, "stop must not complete while chunks are undelivered");
  assert.equal(r.calls.stop, null, "the server has not been told the match ended");
  await r.clock.advance(30_000);
  const last = await stopping;
  assert.equal(finished, true);
  assert.equal(r.received.length, last + 1);
});

test("a chunk the server refuses for good is dropped and the queue moves on", async () => {
  const clock = new FakeClock();
  const recorders: FakeRecorder[] = [];
  const got: number[] = [];
  const phases: [number, ChunkPhase][] = [];
  const cap = new Capture({
    http: {
      async createSession(b) { return { session_id: "s_x", chunk_seconds: b.chunk_seconds, storage: "local" }; },
      async sendChunk(_i, c) { if (c.seq === 1) throw new PermanentUploadError("409 conflict"); got.push(c.seq); },
      async stop() {}, async setCorners() {},
    },
    store: new MemoryStore(), clock, sleep: clock.sleep, mime: "video/webm",
    makeRecorder: () => new FakeRecorder(clock, recorders),
    onPhase: (seq, phase) => phases.push([seq, phase]),
  });
  await cap.start("auto", null);
  await clock.advance(15_000);
  const stopping = cap.stop();
  await clock.advance(5_000);
  await stopping;
  assert.deepEqual(got, [0, 2]);
  assert.ok(phases.some(([s, p]) => s === 1 && p === "failed"));
});

test("a server that does not use local storage is refused with a clear message", async () => {
  const clock = new FakeClock();
  const cap = new Capture({
    http: { async createSession(b) { return { session_id: "s", chunk_seconds: b.chunk_seconds, storage: "cloudinary" }; },
            async sendChunk() {}, async stop() {}, async setCorners() {} },
    store: new MemoryStore(), clock, mime: "video/webm", makeRecorder: () => new FakeRecorder(clock, []),
  });
  await assert.rejects(() => cap.start("auto", null), /phase E/);
});
