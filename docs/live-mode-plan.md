# Live mode plan: continuous footage, processed in 5-second chunks

Source of truth is AGENTS.md; this page only says how live mode fits into it. Baseline measured on this laptop before
any live work: **30.2 s to analyse a 9.96 s clip (real-time factor 3.03)**: 20.2 s players + shuttle pass, 2.2 s audio,
4.3 s split-step analytics. Live needs a factor under 0.6 per chunk, so speed work (phase F) is part of the design.

## Module layout

```
core/rallyos/
  stages.py            NEW  the stages of Analyzer.run, moved out as functions both analyzers call (no copies):
                            build_scene (calibration once) · FrameScanner (pose + shuttle candidates per frame) ·
                            select_players · track_ball · detect_events · resolve_outcome · movement_analytics
  pipeline.py          Analyzer.run now composes stages.py (output must stay identical: checked on a real clip)
  live/
    stream.py          StreamAnalyzer: start / feed_chunk / snapshot / set_corners / finalize
    segments.py        chunk bookkeeping: ordering, overlap trimming, event de-duplication by time
    governor.py        lag-driven degradation (stride, input width, reduced-quality flag), measured per chunk
    replay.py          python -m rallyos.live.replay <clip> --chunk-seconds 5 --realtime
api/
  routers/live.py      sessions, sign, chunks, stop, SSE stream (thin)
  services/live.py     per-session ordered worker queue, SSE hub, finalise + import
  services/storage.py  local | cloudinary (signed uploads; Cloudinary only stores and serves media)
web/
  app/capture/page.tsx          Start once; preview + framing guide; chunk strip; live dashboard; one Stop button
  lib/segmenter.ts              two staggered MediaRecorders, gapless; IndexedDB outbox with retry/backoff
  components/live/*             live court, score, lag + calibration badges (provisional values marked)
```

## Where state lives

* **Browser:** chunk blobs not yet acknowledged (IndexedDB outbox); recorder timing. Nothing else.
* **StreamAnalyzer (one per session, in the API process):** the calibrated `Scene` (homography, camera, regions), the
  `FrameScanner` (detector, 3-frame window, last pose boxes), and per-frame raw detections (pose samples, shuttle
  candidates) for the whole session. Everything downstream is recomputed from them only over a **tail window**.
* **Disk:** `demo/out/live/<session_id>/chunk_<seq>/` (chunk file, audio onsets, per-chunk summary) + `session.json`.
  A crash keeps all of it; a session can be resumed or re-finalised from these files.

## Chunk-boundary strategy

* Chunk k covers `[5k, 5k + 5.5)`: the last 0.5 s overlaps the next chunk. Frames older than `processed_until` are
  decoded only to prime the 3-frame difference window and are never scanned twice. Times are session-relative seconds
  computed from the chunk's wall-clock start, not from frame counters, so a dropped frame cannot shift later hits.
* Shuttle linking, hits, audio fusion, rallies, landings and speeds are re-run over a tail window that always contains
  the open rally (frozen boundary = min(now - 6 s, first hit of the open rally - 2 s)). Earlier events are frozen.
  Events are matched by time (±0.12 s, same type and player) so a re-computed hit is the same event, not a new one.
* A rally is closed when no hit has happened for the sport's pause (4 s). Landing, line call, winner and score are only
  produced for closed rallies, so a call is never issued before the footage that shows the landing has been processed.
* Audio is extracted per chunk with ffmpeg; onsets are detected on the chunk including its overlap and de-duplicated
  against the previous chunk's by `min_gap_s`.
* Court calibration happens once, from the first ~30 frames (or the corners from the capture page). Quality "check"
  is shown in the UI; `set_corners` re-feeds the stored chunks from disk without ending the session.

## Honesty

Every live number is `provisional: true` until `finalize()` recomputes it over the whole match (including the split-step
pass, dispute clips and the full-video checks). The status section of AGENTS.md says what was proven on a real camera
(only phase G can) and what was only replayed or generated.

## Findings so far (updated per phase)

* **Phase B:** chunks are decoded by OpenCV correctly whether MP4 or WebM (frame count and 25 fps exact). Re-encoding a clip
  (chunks are separate recordings) removes the weakest hits and lowers shuttle detection by 4-5 points, so the capture page
  must request a high recording bitrate. Analysing a chunk takes 1.4-1.9x its length with pose at 1280 px: phase F is
  needed before this keeps up with real time. The first chunk also pays for loading the pose model.
