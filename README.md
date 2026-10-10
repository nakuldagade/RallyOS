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
pip install -r requirements.txt          # GPU machine: pip install -r requirements-gpu.txt first
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

Pipeline (once implemented): `python -m rallyos.pipeline <clip.mp4> --device auto --out demo/out/<clip>/`.
Device is chosen by `rallyos.device.get_device()` (`RALLYOS_DEVICE=auto|cpu|cuda`), so the same code runs on CPU and CUDA.

Regenerate the mock tracks: `python data/mock/make_mock_tracks.py`.

The AI coach uses Claude only when `ANTHROPIC_API_KEY` is set; every number it writes is checked against the stats JSON. Without a key (or offline) it falls back to templated insights. `GET /v1/matches/{id}/report?source=claude|template` forces a source.
