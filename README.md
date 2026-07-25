# SwingJourney

A golf swing analysis app: upload a face-on swing video, get pose-estimation
metrics, annotated key frames, and AI coaching notes. Tracks improvement
across sessions.

## Stack

- Python 3.12, Flask, SQLite (via Flask-SQLALchemy)
- MediaPipe Pose + OpenCV + ffmpeg for the analysis pipeline
- Claude API for coaching narratives (metrics in, never raw video)
- Jinja templates + vanilla JS, deployed on Railway

## Run locally

```bash
python3.12 -m venv venv
./venv/bin/pip install -r requirements.txt
cp .env.example .env   # then fill in SECRET_KEY and ANTHROPIC_API_KEY
./venv/bin/python run.py
```

Open http://localhost:5001 — or http://<your-mac-ip>:5001 from your phone on
the same wifi.

## Pose model

MediaPipe's new Tasks API needs a model file. The app auto-downloads
`pose_landmarker_full.task` (~9 MB, from Google's official model server)
into `instance/models/` on first run if it's missing.

## Layout

- `app/__init__.py` — app factory; registers blueprints, creates tables
- `app/models.py` — Users → Sessions → Swings → Analyses
- `app/auth/`, `app/swings/` — route blueprints
- `app/analysis/` — the pipeline (pure Python, no Flask): frames → pose →
  positions → metrics → annotate → coach
- `instance/` — gitignored; sqlite db + uploaded videos live here

## How a swing gets analyzed

Upload → background worker extracts frames (720p, up to 60fps) → MediaPipe
pose per frame → auto-detection guesses P1/P4/P7/P10 from the wrist
trajectory (confidence-gated; manual tagging always available and always
wins) → metrics computed from landmarks → annotated key-frame images →
Claude writes coaching notes from the numbers (never the video). Every
report shows a tracking-quality indicator, and low-confidence metrics say
so instead of printing garbage.

## Data model in one breath

A **User** has practice **Sessions** (date, club, swing type). Each session
holds **Swings** (one video each, `status`: queued → processing → ready).
Each swing gets one or more **Analyses** (key positions P1/P4/P7/P10,
metrics JSON, quality/confidence JSON, AI coaching JSON) — separate table so
old videos can be re-analyzed when the pipeline improves.
