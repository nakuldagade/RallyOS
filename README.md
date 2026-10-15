# RallyOS — Racket-Sports Intelligence from One Camera

> **One phone. Any court. Every rally counted.**

RallyOS turns consumer smartphone video of a racket-sports match into a structured, verifiable match record: automatic court fingerprinting, camera self-calibration, player pose estimation, shuttle/ball tracking, audio-visual hit detection, scoring, movement analytics with confidence bounds, dispute replays, and an evidence-grounded AI coach.

Built across six racket sports (**badminton, tennis, table tennis, pickleball, padel, squash**) with **zero training or fine-tuning**: powered entirely by pretrained general vision models (YOLO11 pose), projective geometry, projectile physics, and audio signal processing. Every sport rule, court geometry, projectile parameter, and scoring mechanism lives declaratively in YAML config files.

Developed for **Elevate 1.0 (Problem Statement 02)**.

---

## 📸 Screenshots

<img width="1470" height="860" alt="Screenshot 2026-10-15 at 6 55 28 PM" src="https://github.com/user-attachments/assets/edda18b3-b860-4f6d-8314-7c17b9ac2c88" />
<img width="1470" height="843" alt="Screenshot 2026-10-15 at 6 56 46 PM" src="https://github.com/user-attachments/assets/50b836dd-1e80-4586-be24-84da8fd0b49d" />
<img width="1470" height="857" alt="Screenshot 2026-10-15 at 6 57 28 PM" src="https://github.com/user-attachments/assets/3467e8d6-c082-428e-9e3b-f76a8b6c8ae4" />
<img width="1470" height="855" alt="Screenshot 2026-10-15 at 6 58 44 PM" src="https://github.com/user-attachments/assets/d47197c7-eeab-4d44-9b2e-916ee654d577" />
<img width="1470" height="851" alt="Screenshot 2026-10-15 at 6 59 24 PM" src="https://github.com/user-attachments/assets/cbc9af6f-a3ed-4a8d-adac-8445a754a7f7" />
<img width="1470" height="849" alt="Screenshot 2026-10-15 at 6 59 43 PM" src="https://github.com/user-attachments/assets/8620284c-6118-417d-85b7-b220924b3cef" />



> *Tip: Drop your UI screenshots into [`docs/screenshots/`](docs/screenshots/) with the filenames above to preview them directly in this README.*

---

## 🌟 Key Features & Innovations

RallyOS replaces multi-camera commercial hardware (like Hawk-Eye or PlaySight) with a single consumer smartphone using **10 training-free techniques**:

### 1. Court Fingerprinting & Automatic Sport Detection
- **Line & Corner Extraction:** Top-hat morphology filters and OpenCV Line Segment Detection (LSD) identify court lines and candidate intersections.
- **Multi-Sport Template Matching:** RANSAC-fits court line templates across sports to determine the sport automatically with confidence scores (e.g., *"Badminton detected, 96% fit"*).
- **Distinguishing Similar Outlines:** Differentiates courts with nearly identical perimeters (such as badminton $13.40 \times 6.10\text{ m}$ vs. pickleball $13.41 \times 6.10\text{ m}$) by matching interior service lines and kitchen boundaries.
- **Interactive Manual Fallback:** 4-tap corner calibration tool available directly in the web UI for extreme camera angles or obscured lines.

### 2. Camera Self-Calibration
- **Zhang's Single-Plane Method:** Recovers camera intrinsics ($f$) and extrinsic pose ($R, t$) directly from the planar court homography ($H$) assuming square pixels and centered principal point.
- **Net-Height Sanity Checks:** Verifies the camera model against known physical net heights from the sport YAML configs.
- **Camera Jitter Compensation:** ORB feature tracking preserves calibration stability against hand-held camera movements and wobbly tripods.

### 3. Physics-Guided Shuttle & Ball Tracking
- **Blob Detection & Player Masking:** Three-frame temporal differencing and MOG2 background subtraction, masked by dilated YOLO player bounding boxes to eliminate racket/limb false positives.
- **Viterbi Candidate Selection:** Dynamic programming identifies the path of maximum likelihood matching the sport's aerodynamic drag model.
- **Quadratic Air Drag Model:** Accurately models steep deceleration and vertical drop characteristics of badminton shuttles (terminal velocity $\approx 6.7\text{ m/s}$) vs. elastic bounces of tennis and pickleball balls.
- **Kalman Filtering:** Smooths trajectories and flags occluded frames with lower confidence scores.
- **Optional RacketVision TrackNetV3 Plugin:** Clean adapter for integrating pretrained TrackNetV3 inference for broadcast-style footage without retraining.

### 4. "Hear the Rally" Audio-Visual Fusion
- **Acoustic Hit Detection:** Analyzes raw audio via spectral flux onset detection (NumPy only, no heavy dependencies) at $44,100\text{ Hz}$ for sub-frame timing precision ($\sim 1\text{ ms}$ vs. $16\text{--}33\text{ ms}$ video frames).
- **Speed-of-Sound Correction:** Adjusts sound arrival latency ($d / 343\text{ m/s}$) using the hitter's 3D court position relative to the phone's microphone.
- **Hitter Attribution:** Assigns hits to the player whose wrist keypoint is closest in space-time to the trajectory inflection.

### 5. Interactive 3D Smart Court
- **Three.js Scene Engine:** Renders the detected sport's 3D court specifications (court lines, net, wall heights, and colors directly from YAML).
- **Reconstructed Flight Paths:** Generates 3D trajectory arcs between consecutive hits. Full physics drag paths are rendered solid; interpolated flights are rendered dashed with confidence flags.
- **Animated Procedural Figures:** Color-coded 3D player models follow measured foot tracking with dynamic walk cycles and swing animations timed to hit events.
- **Interactive Controls:** Orbit, pan, zoom, camera presets, play/pause, scrub, and slow-motion replays ($1\times, 0.5\times, 0.25\times, 0.1\times$).
- **Heatmap Overlays:** 3D floor heatmaps indicating player court coverage and positioning.

### 6. Live Mode Stream Analyzer
- **Real-Time Chunk Processing:** Ingests continuous camera footage in 5-second overlapping chunks via HTTP/SSE.
- **Low Latency Performance:** Measured 3.3–4.5s processing latency with a real-time factor (RTF) of 0.6–0.73 on standard laptop CPU.
- **Progressive Live Smart Court:** Builds and streams live 3D match state, shot paths, and heatmaps progressively to the `/capture` browser interface.
- **Storage Abstraction:** Supports local offline chunk storage or signed uploads to Cloudinary CDN.

### 7. Movement Intelligence & Biomechanics
- **Return to Base:** Tracks post-hit recovery time and percentage of returns within $1.2\text{ m}$ of the optimal base position.
- **Split-Step Detection:** High-speed pose evaluation analyzing pre-opponent contact ankle vertical lift.
- **Fatigue Degradation Curves:** Compares player movement speed and recovery rates across match thirds.
- **Zone Distribution:** Breakdown of time spent across front, mid, and rear court zones.

### 8. Fair-Play Dispute Desk & Highlight Generation
- **Line Calling with Uncertainty Ellipses:** Height-corrected court landing projection evaluating $\text{IN} / \text{OUT} / \text{TOO CLOSE}$ probabilities.
- **Automated Dispute Replay:** Instant video clips generated for close calls (<90% confidence).
- **Best Shot Highlights:** Automatic 8-second H.264 video clipping of the match's highest-rated shot with score badges and shuttle trail overlays.

### 9. Grounded AI Coach & Summary
- **Zero Hallucination Validation:** AI summaries and coaching insights cite strictly verified numbers from the match stats JSON (`stat_ids` and timestamps). Any ungrounded claims trigger automatic fallback to template rules.
- **Elevate Gateway & Model Support:** Powered by Elevate AI Gateway (OpenAI Chat Completions format with `gpt-5.6-luna`, `deepseek-v4-pro`, or `gpt-5-mini`) or Anthropic Claude API.
- **Browser Text-to-Speech:** Zero-cost, local voice narration of match summaries via the Web Speech API.

### 10. Platform & Network Features
- **Glicko-2 Ratings Engine:** Dynamic skill ratings calculated with evidence confidence weights.
- **Predictive Matchmaking:** Explainable head-to-head win probability predictions based on player movement metrics and shot profiles.
- **Tournaments & Rosters:** Multi-stage tournament management and coach roster dashboards.

---

## 🏸 Supported Sports (YAML-Driven)

RallyOS requires **no code changes** to support new sports. All court specifications, net heights, bounce properties, physics models, scoring engines, and visual themes live in `core/rallyos/sports/*.yaml`:

| Sport | Config File | Dimensions | Net Height | Physics Model | Scoring Engine |
|---|---|---|---|---|---|
| **Badminton** | [`badminton.yaml`](core/rallyos/sports/badminton.yaml) | $13.40 \times 6.10\text{ m}$ | $1.524\text{ m}$ | Quadratic air drag, no bounce | BWF rally point to 21 |
| **Tennis** | [`tennis.yaml`](core/rallyos/sports/tennis.yaml) | $23.77 \times 10.97\text{ m}$ | $0.914\text{ m}$ | Gravity + drag, surface bounce | Traditional (15, 30, 40, game) |
| **Table Tennis**| [`table_tennis.yaml`](core/rallyos/sports/table_tennis.yaml) | $2.74 \times 1.525\text{ m}$ | $0.1525\text{ m}$ | Table-plane contact, drag, bounce | ITTF 11-point games, alternate serve |
| **Pickleball** | [`pickleball.yaml`](core/rallyos/sports/pickleball.yaml) | $13.41 \times 6.10\text{ m}$ | $0.86\text{ m}$ | Low bounce, kitchen non-volley zone | Side-out scoring to 11 |
| **Padel** | [`padel.yaml`](core/rallyos/sports/padel.yaml) | $20.00 \times 10.00\text{ m}$ | $0.88\text{ m}$ | Wall rebounds, surface bounce | Traditional tennis sets |
| **Squash** | [`squash.yaml`](core/rallyos/sports/squash.yaml) | $9.75 \times 6.40\text{ m}$ | Tin $0.48\text{ m}$ | 4-wall rebound physics, floor bounce | PAR-11 rally scoring |

---

## 🏛 System Architecture & Repository Layout

RallyOS is structured as a modular monorepo:

```
ELEV02/
├── core/                       # rallyos CV, physics, calibration & analytics library
│   └── rallyos/
│       ├── calibration/        # Court line detection, RANSAC homography, camera model
│       ├── track/              # YOLO pose, geometric shuttle tracker, RacketVision plugin
│       ├── audio/              # Spectral flux hit onset detector & audio fusion
│       ├── physics/            # Aerodynamic quadratic drag models & trajectory solvers
│       ├── analytics/          # Movement, shot classification, best shot, split-step, flights
│       ├── scoring/            # Rules engines for badminton, tennis, table tennis, etc.
│       └── sports/             # Declarative YAML definitions for all 6 sports
├── api/                        # FastAPI backend application
│   ├── main.py                 # Application startup, lifecycle, OpenVINO model warmup
│   ├── routers/                # REST endpoints: auth, matches, live, 3D scenes, coach, tournaments
│   ├── services/               # Live stream analyzer, AI gateway LLM service, audio processing
│   ├── db.py                   # SQLModel ORM (SQLite local / Supabase Postgres)
│   └── seed.py                 # Demo accounts and seed match data importer
├── web/                        # Next.js 14 frontend web application
│   ├── app/                    # App Router pages (/login, /me, /coach, /matches, /capture, etc.)
│   ├── components/             # UI widgets, 3D court viewer (Three.js), video replays, heatmaps
│   └── lib/                    # API client, types, auth tokens, speech synthesis
├── data/                       # Database files, seed records, mock matches
├── models/                     # YOLO11n pose weights (yolo11n-pose.pt / .onnx)
└── requirements.txt            # Python dependencies (CPU-optimized PyTorch)
```

---

## 🚀 Quickstart Guide

### 1. Prerequisites
- **Python**: 3.11 or 3.12 (standard CPU build)
- **Node.js**: v18+ (tested on v20+)
- **OS**: macOS, Linux, or Windows 11

### 2. Environment Setup
Clone the repository and set up environment files:
```bash
cp .env.example .env
cp web/.env.local.example web/.env.local
```

*(Optional)* Paste your team key into `AI_GATEWAY_KEY` in `.env` for AI coach and summaries. If omitted, RallyOS automatically falls back to deterministic template rules.

### 3. Backend Setup & Dependencies
Create a virtual environment and install dependencies:
```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate       # On Windows: .venv\Scripts\activate

# Install Python packages and editable core library
pip install -r requirements.txt
pip install -e core/

# Pre-download YOLO11 pose weights (if not already downloaded)
curl -L -o models/yolo11n-pose.pt https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo11n-pose.pt
```

### 4. Database Initialization & Seed Data
Initialize the database and populate demo players, coach, mock match, and table-tennis sample games:
```bash
python -m api.seed
python -m api.make_sample_tt
```

### 5. Frontend Setup
Install frontend dependencies:
```bash
cd web
npm install
cd ..
```

### 6. Run the Application
Start the backend API and frontend dev servers in separate terminals:

**Terminal 1 (Backend API):**
```bash
source .venv/bin/activate
uvicorn api.main:app --port 8000
```
- API Docs: [http://localhost:8000/docs](http://localhost:8000/docs)
- Health Check: [http://localhost:8000/health](http://localhost:8000/health)

**Terminal 2 (Frontend Dashboard):**
```bash
cd web
npm run dev
```
- Web Application: [http://localhost:3000](http://localhost:3000)

---

## 👥 Demo Accounts

The application features full-screen role-based authentication. Use password **`rallyos-demo`**:

| Account | Role | Features |
|---|---|---|
| `coach.vikram@rallyos.demo` | **Coach** | Accesses `/coach` roster, team trends, drill focus, and player analytics |
| `anika@rallyos.demo` | **Player** | Accesses `/me` dashboard, personal rating curve, multi-match heatmaps |
| `rohan@rallyos.demo` | **Player** | Analyzed badminton match history, movement stats, AI chat analyst |
| `meera@rallyos.demo` | **Player** | Match replays, 3D Smart Court breakdown, best shot highlights |
| `kabir@rallyos.demo` | **Player** | Singles ratings, fatigue curves, zone distributions |
| `isha@rallyos.demo` | **Player** | Dispute replays, fair-play reviews |
| `tara@rallyos.demo` | **Player** | Table tennis matches (synthetic sample games), return-to-base analysis |

---

## 💻 CLI & Pipeline Commands

### Run Offline Analysis on a Video File
```bash
# Analyze a clip with automatic court detection
python -m rallyos.pipeline demo/clip.mp4 --out demo/out/clip/

# Analyze with manual 4-corner pixel coordinates [near-left, near-right, far-right, far-left]
python -m rallyos.pipeline demo/clip.mp4 --sport badminton --taps "[[330,948],[1583,948],[1253,333],[638,333]]" --out demo/out/clip/

# Import the analyzed match output into the database
python -m api.import_match demo/out/clip/
```

### Simulate Real-Time Camera Stream
```bash
python -m api.live_client demo/clip.mp4 --realtime
```

### Run Tests
```bash
# Python backend & core vision tests (336 passing tests)
pytest

# Frontend TypeScript check & unit tests
cd web
npm run typecheck
npm test
```

---

## 📊 Measured Accuracy & Benchmarks

All metrics measured locally on laptop CPU:

| Metric | Measured Result | Benchmark Condition |
|---|---|---|
| **Court Calibration Error** | $< 0.6\text{ px}$ | Synthetic courts with known ground-truth homography $H$ |
| **Shuttle Tracking (F1 Score)** | **0.82** | Evaluated against RacketVision reference on broadcast clips |
| **Audio-Visual Hit Detection (F1 Score)** | **0.74** | Multimodal inflection + spectral flux alignment |
| **Live Chunk Latency** | **3.3 – 4.5 s** | 5-second video chunks on standard laptop CPU |
| **Real-Time Factor (RTF)** | **0.60 – 0.73** | Execution time / video duration ($< 1.0$ is faster than real time) |
| **Pose Inference Acceleration** | **$\sim 1.3\times$ speedup** | OpenVINO CPU runtime vs. baseline PyTorch |
| **Automated Test Coverage** | **336 unit tests** | Core geometry, physics models, scoring engines, API endpoints |

*Honesty disclosure:* The badminton and pickleball clips represent real phone and broadcast footage analyzed through the pipeline. Table tennis matches (Tara) and ratings are simulated benchmark matches processed with the real analytics algorithms to demonstrate multi-sport mechanics.

---

## 👤 Author & Contributor

- **Nakul Dagade** ([@nakuldagade](https://github.com/nakuldagade))

---

## 📄 License

Developed for Elevate 1.0 Hackathon. Licensed under the [MIT License](LICENSE).
