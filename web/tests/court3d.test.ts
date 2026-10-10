// The 3D viewer's maths (no browser): finding the sample at a time, interpolating a player, and placing the shuttle on its flight.
import assert from "node:assert/strict";
import { test } from "node:test";
import { positionAt, sampleIndex, shuttleAt } from "../lib/court3d.ts";
import type { Flight3D } from "../lib/court3d.ts";

const flight = (t0: number, t1: number, kind: "physics" | "estimate" = "physics"): Flight3D => ({
  rally_idx: 0, track_id: 1, t0, t1, kind, from: [0, 0, 1], to: [4, 8, 0], peak_z: 3, shot: null, speed_kmh: null, speed_err_pct: null,
  samples: [[t0, 0, 0, 1], [(t0 + t1) / 2, 2, 4, 3], [t1, 4, 8, 0]],
});

test("sampleIndex is the last sample at or before the time, and -1 before the first", () => {
  const s = [[1.0], [2.0], [3.0]];
  assert.deepEqual([0.5, 1.0, 1.5, 2.0, 2.999, 3.0, 9.0].map((t) => sampleIndex(s, t)), [-1, 0, 0, 1, 1, 2, 2]);
  assert.equal(sampleIndex([], 1), -1);
});

test("a player is interpolated between samples and held before the first and after the last", () => {
  const pos: [number, number, number][] = [[1, 0, 0], [3, 4, 8]];
  assert.deepEqual(positionAt(pos, 2), [2, 4]);
  assert.deepEqual(positionAt(pos, 0), [0, 0]);
  assert.deepEqual(positionAt(pos, 9), [4, 8]);
  assert.equal(positionAt([], 1), null);
});

test("the shuttle exists only while a flight is in the air, and moves along its samples", () => {
  const flights = [flight(1, 2), flight(3, 4)];
  assert.equal(shuttleAt(flights, 0.5), null);
  assert.equal(shuttleAt(flights, 2.5), null);                          // between two flights: not drawn
  const mid = shuttleAt(flights, 1.5)!;
  assert.deepEqual(mid.at, [2, 4, 3]);                                  // the middle sample
  const q = shuttleAt(flights, 1.25)!;
  assert.deepEqual(q.at, [1, 2, 2]);                                    // halfway between the first and the middle one
  assert.equal(shuttleAt(flights, 4)!.flight.t0, 3);
});
