# ELEV02

## RallyOS — racket-sports intelligence from one camera

*One phone. Any court. Every rally counted.*

RallyOS turns an ordinary phone video of a racket-sports match into a structured, verifiable match record: court and sport detection, camera self-calibration, player and shuttle/ball tracking, audio hit detection, scoring, analytics with confidence values, dispute replays and an evidence-linked AI coach. It works across six sports (badminton, tennis, table tennis, pickleball, padel, squash) with **no training**: only pretrained general models (YOLO person/pose), geometry, physics and signal processing. Each sport is one YAML file in [core/rallyos/sports/](core/rallyos/sports/).

Built for Elevate 1.0, Problem Statement 02. The full product and build plan is in [AGENTS.md](AGENTS.md).

### Layout

| Folder | What |
|---|---|
| `core/` | `rallyos` Python package (all computer vision, scoring rules, analytics). `pip install -e core/` |
| `api/` | FastAPI backend, a thin wrapper around `rallyos` |
| `web/` | Next.js frontend |
| `data/mock/` | Mock `match.json` + `tracks.json` (the data contract, AGENTS.md §11.3) |
| `data/seed/` | Sample players, venues, tournaments |
| `demo/` | Demo clips and precomputed outputs (videos are not committed) |

### Run

Requires Python 3.11 and Node 18+ (Windows paths shown).

```powershell
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt          # CPU build of torch; everything runs locally
copy .env.example .env

# Tests: scoring rules for all 6 sports, sport configs, device, Glicko-2, coach grounding, API routers
python -m pytest -q

# Backend: http://localhost:8000/docs  (quick check: /v1/matches/m_001)
python -m api.seed                        # DB tables, sample players/venues/tournaments, imports the mock match
uvicorn api.main:app --reload --port 8000
python -m api.import_match demo/out/<clip>/   # import a finished pipeline output folder

# Frontend: http://localhost:3000
cd web; npm install; npm run dev
```

Analyse your own video: open http://localhost:3000/upload, pick a clip, tap the 4 court corners, upload.
Or from the command line (taps = near-left, near-right, far-right, far-left in video pixels):
`python -m rallyos.pipeline clip.mp4 --sport badminton --taps "[[330,948],[1583,948],[1253,333],[638,333]]" --out demo/out/clip/`
This version tracks players + pose (pretrained YOLO11n-pose), the shuttle (geometric, no trained detector), hits and rallies.
Not built yet: audio onsets, shot types, speeds, line calls, automatic score (the score is confirmed by a person).
Device is chosen by `rallyos.device.get_device()` (`RALLYOS_DEVICE=auto|cpu|cuda`), so the same code runs on CPU (default) or CUDA if a GPU is ever available.

Regenerate the mock tracks: `python data/mock/make_mock_tracks.py`.

The AI coach uses Claude only when `ANTHROPIC_API_KEY` is set; every number it writes is checked against the stats JSON. Without a key (or offline) it falls back to templated insights. `GET /v1/matches/{id}/report?source=claude|template` forces a source.

### Optional ball tracker: RacketVision (inference only)

The pretrained RacketVision TrackNetV3 checkpoint is used as released (inference only); nothing is trained.
Its CSV output plugs into the same `match.json` / `tracks.json` contract (badminton, table tennis, tennis):

```powershell
# precomputed predictions for the 46 test clips, unzipped into demo/racketvision/extracted/ (git-ignored)
python -m rallyos.track.plugins.racketvision list  demo/racketvision/extracted/balltrack_badminton_test_predictions.csv
python -m rallyos.track.plugins.racketvision build demo/racketvision/extracted/balltrack_badminton_test_predictions.csv --clip match117_000 --video demo/racketvision/videos/match117_000.mp4
python -m api.import_match demo/out/rv_match117_000/
# optional, new video (needs its own venv, slow on CPU):  python -m rallyos.track.plugins.racketvision run clip.mp4 --out demo/out/rv_clip/
```

Reference accuracy (RacketVision badminton test set, 46 broadcast clips, measured with their test script): precision 0.91, recall 0.87, F1 0.89.
Not yet measured on our own phone footage.
