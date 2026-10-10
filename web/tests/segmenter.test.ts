// Run with: npm test   (node's built-in runner; no browser, the MediaRecorder and the clock are fakes)
import assert from "node:assert/strict";
import { test } from "node:test";
import { Segmenter } from "../lib/segmenter.ts";
import type { Chunk } from "../lib/segmenter.ts";
import { FakeClock, FakeRecorder, decodeFake } from "./fakes.ts";

function rig(opts: { jitterMs?: number } = {}) {
  const clock = new FakeClock();
  const recorders: FakeRecorder[] = [];
  const chunks: Chunk[] = [];
  const maxAlive = { n: 0 };
  const seg = new Segmenter({
    makeRecorder: () => new FakeRecorder(clock, recorders),
    mime: "video/webm", clock, onChunk: (c) => chunks.push(c),
  });
  return { clock, recorders, chunks, seg, maxAlive };
}

test("30 s of a fake stream gives 6 chunks, each a complete file", async () => {
  const { clock, chunks, seg } = rig();
  seg.start();
  await clock.advance(30_000);
  await seg.stop();
  assert.equal(chunks.length, 6);
  assert.deepEqual(chunks.map((c) => c.seq), [0, 1, 2, 3, 4, 5]);
  for (const c of chunks) {
    const f = await decodeFake(c.blob);                          // complete, parseable file
    assert.ok(Math.abs((f.to - f.from) - c.duration) < 1e-6, "metadata duration matches the file");
    assert.equal(c.ext, "webm");
  }
});

test("no gaps and an overlap of 0.5 s between neighbours", async () => {
  const { clock, chunks, seg } = rig();
  seg.start();
  await clock.advance(30_000);
  await seg.stop();
  for (let k = 0; k < chunks.length - 1; k++) {
    const end = chunks[k].t0 + chunks[k].duration;
    const overlap = end - chunks[k + 1].t0;
    assert.ok(overlap >= 0, `gap between chunk ${k} and ${k + 1}`);
    assert.ok(Math.abs(overlap - 0.5) < 0.05, `overlap ${overlap} s between chunk ${k} and ${k + 1}`);
  }
  assert.ok(Math.abs(chunks[1].t0 - 5) < 0.05, "chunk 1 starts at 5 s");
  assert.equal(chunks[5].duration, 5, "the last chunk is cut where Stop was pressed");
});

test("two recorders are alive around each boundary, never more", async () => {
  const { clock, seg } = rig();
  seg.start();
  let max = 0;
  for (let i = 0; i < 300; i++) {                                // 30 s in 100 ms steps
    await clock.advance(100);
    max = Math.max(max, seg.active.length);
  }
  await seg.stop();
  assert.equal(max, 2);
});

test("a late timer does not make later chunks drift", async () => {
  const { clock, chunks, seg } = rig();
  seg.start();
  await clock.advance(5_000);
  // the main thread was blocked for 300 ms around the second boundary
  clock.t += 300;
  await clock.advance(25_000);
  await seg.stop();
  for (const c of chunks.slice(2)) assert.ok(Math.abs(c.t0 - c.seq * 5) < 0.05, `chunk ${c.seq} t0 ${c.t0}`);
});

test("Stop right after a boundary drops a chunk that holds nothing new", async () => {
  const { clock, chunks, seg } = rig();
  seg.start();
  await clock.advance(10_200);                                   // chunk 2 has run for 0.2 s: only repeats chunk 1's tail
  const last = await seg.stop();
  assert.equal(last, 1);
  assert.deepEqual(chunks.map((c) => c.seq), [0, 1]);
});
