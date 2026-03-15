# Nerdy — Multimodal Socratic Tutor

Nerdy is a real-time AI tutoring app for middle-school science. It combines a live avatar, voice conversation, and a deterministic visual teaching panel so students can hear and see concepts while they answer.

## What It Does

- Student selects a topic (`photosynthesis` or `newtons_laws`).
- Tutor `Socrates VI` starts with a greeting question, then runs a Socratic lesson.
- Student responds with mic audio; backend streams STT -> LLM -> TTS in real time.
- Right-rail teaching panel updates from backend-owned `lesson_visual_update` events.
- Session completes after the configured turn budget (`MAX_TURNS`, default `15`).

## Why It Is Different

- **Multimodal by default:** avatar + speech + visual concept progression.
- **Deterministic visual state:** visuals are driven by backend lesson state, not free-form model drawing output.
- **Submission-grade evidence path:** deterministic browser tests, live canary tests, benchmark artifacts, and eval artifacts.

## Architecture At A Glance

```
React (Vite/TS) <-> FastAPI WebSocket (PCM16 + JSON)
                     |- Deepgram STT (streaming)
                     |- Groq LLM (streaming)
                     |- Cartesia TTS (streaming PCM16)
                     |- Simli / SpatialReal avatar session setup
```

Core orchestration lives in `backend/pipeline/orchestrator_custom.py`.

## Quick Start

```bash
# 1) Backend env
cp backend/.env.example backend/.env
# Fill required keys from backend/.env.example

# 2) Backend
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python run.py

# 3) Frontend (new terminal)
cd frontend
npm install
npm run dev
```

- Frontend: `http://localhost:5173`
- Backend: `http://localhost:8000`
- Detailed ops: `RUNBOOK.md`

## Test Commands

```bash
# Backend full suite (required gate before task closeout)
cd backend
source venv/bin/activate
pytest

# Frontend full suite (required gate before task closeout)
cd frontend
npm test

# Deterministic browser E2E
cd frontend
npm run e2e

# Live canary browser E2E (real keys + running stack)
cd frontend
npm run e2e:live
```

## Evals And Benchmarks

From `backend/` with virtualenv active:

```bash
# Socratic eval artifacts
python -m evals.run_socratic_eval

# Optional quick smoke
python -m evals.run_socratic_eval --turns 5

# Benchmark/provider artifacts
python -m benchmarks.run_benchmarks
```

Expected artifact outputs:
- `backend/evals/results/socratic_validation.json`
- `backend/evals/results/socratic_validation_summary.md`
- `backend/benchmarks/results/benchmark_report.json`
- `backend/benchmarks/results/benchmark_summary.md`

If eval artifacts are missing, run the eval command locally before packaging submission evidence.

## Evidence Map

| Evidence Type | Location |
|---|---|
| Deterministic browser screenshots | `frontend/e2e/evidence/` |
| Playwright run outputs | `frontend/test-results/` |
| Benchmark report (JSON) | `backend/benchmarks/results/benchmark_report.json` |
| Benchmark summary (Markdown) | `backend/benchmarks/results/benchmark_summary.md` |
| Socratic eval report (JSON) | `backend/evals/results/socratic_validation.json` |
| Socratic eval summary (Markdown) | `backend/evals/results/socratic_validation_summary.md` |

## Current Limits

- English-only speech pipeline.
- Two active curriculum topics.
- External provider keys required for full live mode.
- No user auth or long-term student account persistence.

## License

Course project — not licensed for redistribution.
