# Local Development Runbook

> This file is kept current by Claude. Feature status is updated after every build task.

---

## Prerequisites (one-time)

- Python 3.10+
- Node.js 18+
- API keys (see Environment Setup below)

---

## 1. Environment Setup

**Backend — copy and fill in your `.env`:**
```bash
cp backend/.env.example backend/.env
# Fill in: DEEPGRAM_API_KEY, GROQ_API_KEY, ELEVENLABS_API_KEY, SIMLI_API_KEY
```

**Backend — create virtualenv and install deps:**
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Frontend — install Node deps:**
```bash
cd frontend
npm install
```

---

## 2. Starting the App

Two terminals required.

**Terminal 1 — Backend:**
```bash
cd backend
source venv/bin/activate
python run.py
# Starts at http://localhost:8000
# Verify: curl http://localhost:8000/health
# Logs: backend/logs/server.log (5 MB rotating, 1 backup)
```

**Terminal 2 — Frontend:**
```bash
cd frontend
npm run dev
# Opens at http://localhost:5173
# Logs: frontend/logs/dev.log (truncated at 5 MB on restart)
```

> **Mock mode:** `frontend/.env.development` has `VITE_MOCK=true` by default — the frontend
> runs with simulated data and no backend is needed. Set `VITE_MOCK=false` to use the real pipeline.

---

## 3. Running Tests

See **[TEST_GATES.md](TEST_GATES.md)** for the full gate taxonomy (unit → contract → browser-deterministic → live-canary) and command map.

### Backend
```bash
cd backend
source venv/bin/activate

# Unit + contract (default; no API keys needed)
pytest -m "not integration" -v

# Unit only (no WebSocket contract tests)
pytest -m "not integration and not contract" -v

# Contract only (WebSocket/HTTP protocol tests)
pytest -m contract -v

# All tests including live API calls (real keys required)
pytest -v

# Specific file
pytest tests/test_server.py -v

# Eval/benchmark artifact tests (no API keys)
pytest tests/test_eval_artifacts.py -v
```

### Evals and benchmarks (artifact generation)

From `backend/` with virtualenv activated and API keys in `.env`:

```bash
# Socratic quality eval (requires GROQ_API_KEY) — writes evals/results/socratic_validation.json + socratic_validation_summary.md
python -m evals.run_socratic_eval

# Quick smoke: 5 turns per topic
python -m evals.run_socratic_eval --turns 5

# Single topic
python -m evals.run_socratic_eval --topic photosynthesis

# Legacy: run validate_socratic_prompt directly (same artifacts + --turns N)
python -m evals.validate_socratic_prompt --turns 10

# Provider validation + pipeline latency benchmark — writes benchmarks/results/benchmark_report.json + benchmark_summary.md
python -m benchmarks.run_benchmarks

# Providers only (no pipeline benchmark)
python -m benchmarks.run_benchmarks --providers-only

# Pipeline latency only (e.g. 5 runs)
python -m benchmarks.run_benchmarks --pipeline-only --runs 5
```

Artifacts: `backend/evals/results/`, `backend/benchmarks/results/`. Exit code 1 on failure for CI.

| Test file | What it covers |
|---|---|
| [tests/test_slice1_integration.py](backend/tests/test_slice1_integration.py) | Full STT → LLM → TTS pipeline |
| [tests/test_server.py](backend/tests/test_server.py) | HTTP endpoints + WebSocket handshake (contract gate) |
| [tests/test_metrics.py](backend/tests/test_metrics.py) | Latency collection and timing |
| [tests/test_sentence_buffer.py](backend/tests/test_sentence_buffer.py) | Token-to-sentence splitting |
| [tests/test_session_manager.py](backend/tests/test_session_manager.py) | Session state management |
| [tests/test_vad_handler.py](backend/tests/test_vad_handler.py) | Voice activity detection |
| [tests/test_llm_engine.py](backend/tests/test_llm_engine.py) | Groq LLM streaming |
| [tests/test_stt_adapter.py](backend/tests/test_stt_adapter.py) | Deepgram STT |
| [tests/test_tts_adapter.py](backend/tests/test_tts_adapter.py) | TTS adapter (Deepgram / ElevenLabs) |
| [tests/test_eval_artifacts.py](backend/tests/test_eval_artifacts.py) | Eval/benchmark artifact schema, percentile, pass/fail logic |
| [tests/test_visuals.py](backend/tests/test_visuals.py) | Visual registry: step-tag parsing, step/recap lookup, clamping, message serialisation |

### Frontend
```bash
cd frontend

# Run all tests (no backend needed — mock mode)
npm test

# Watch mode
npm test -- --watch

# With coverage
npm test -- --coverage
```

---

## 4. Manual End-to-End Testing

With both servers running and `VITE_MOCK=false` in `frontend/.env.development`:

1. Open `http://localhost:5173` — you should see the **Topic Selection** screen with 6 cards
2. Click **Photosynthesis** (or Newton's Laws) — transitions to **Getting Ready** view
3. Watch the progress stepper: "Connecting to tutor…" ✓ → "Loading avatar…" ✓ → "Ready!"
4. Click **Start Lesson** (enabled once WS + avatar are connected) — transitions to **Lesson** view
5. Nova automatically greets the student (mic is disabled during greeting, hint says "Nova is introducing the topic…")
6. After greeting completes, mic enables — hold to speak, release to send
7. The AI tutor responds with text + synthesized audio via the 8-turn Socratic flow
8. Check latency breakdown at `http://localhost:8000/metrics`

**Mock mode** (`VITE_MOCK=true`): The full 3-view flow works without a backend — greeting is simulated.

---

## 5. WebSocket Protocol

**Endpoint:** `ws://localhost:8000/session?topic=photosynthesis`

Query params: `topic` — required, one of `photosynthesis`, `newtons_laws`

**Client → Server:**
- Binary: PCM Int16 @ 16 kHz audio frames
- JSON: `{ "type": "end_of_utterance" | "barge_in" | "start_lesson" | "simli_sdp_offer" }`

**Server → Client:**
- `{ "type": "session_start", "session_id": "uuid", "topic": "..." }` — handshake
- `{ "type": "student_partial", "text": "..." }` — live partial transcript (streaming STT)
- `{ "type": "student_transcript", "text": "..." }` — final STT result
- `{ "type": "tutor_text_chunk", "text": "...", "timing": {...}, "is_greeting": bool }` — response + latency metrics
- `{ "type": "audio_chunk", "data": "base64-pcm" }` — TTS audio (streamed)
- `{ "type": "greeting_complete" }` — greeting turn finished, mic can enable
- `{ "type": "barge_in_ack" }` — interrupt acknowledged
- `{ "type": "error", "code": "...", "message": "...", "timing": {...} }` — error with partial timing (stages that completed before the failure)

**REST endpoints:**
- `GET /topics` — returns available topic list
- `GET /health`, `GET /ready`, `GET /metrics` — health/readiness/metrics

---

## 6. Feature Status

> Updated by Claude after each build task.

| Feature | Status | Notes |
|---|---|---|
| STT → LLM → TTS pipeline | ✅ Done | Deepgram Nova-3 → Groq Llama 3.3 70B → Cartesia Sonic-3 — live e2e verified |
| WebSocket session management | ✅ Done | Max 5 concurrent sessions |
| Frontend UI components | ✅ Done | TopBar, AvatarFeed, ConversationHistory, TutorResponse, BottomBar |
| Mock mode (UI without backend) | ✅ Done | `VITE_MOCK=true` in `.env.development` |
| Backend latency metrics | ✅ Done | Per-stage nanosecond-precision timing; write-once TTFA; avatar stage; per-sentence TTS logging |
| Per-component latency display (UI) | ✅ Done | Shows STT/LLM/TTS/Total; updates on success AND on partial failure |
| Latency panel tooltips | ✅ Done | Hover tooltips explain stt_finish_ms, llm_ttf_ms, tts_ttf_ms, turn_duration_ms |
| Latency trend history (UI) | ✅ Done | Click latency panel to open trend chart |
| TTS: Cartesia Sonic-3 | ✅ Done | `CartesiaTTSAdapter` with `sonic-3`; select via `TTS_PROVIDER=cartesia` in `.env` |
| Simli avatar WebRTC signaling (C1) | ✅ Done | `connect()` does token→ICE→WS→SDP exchange; `simli_sdp_offer` handler wired; handles legacy "START" + new JSON protocol |
| Simli TTS audio forwarding (C2) | ✅ Done | `send_audio()` forwards each TTS chunk to Simli WS for lip-sync; keepalive prevents idle timeout |
| Simli keepalive (idle timeout fix) | ✅ Done | Background asyncio task sends 320-byte silent PCM every 3s between turns to prevent Simli closing the WS |
| Simli DataChannel keepalive (frontend) | ✅ Done | Frontend sends 320-byte silent PCM every 3s on the WebRTC DataChannel to prevent Simli closing it between turns |
| Frontend log timestamps | ✅ Done | `[HH:MM:SS.mmm]` prefix on all `[TutorSocket]` and `[SimliWebRTC]` console logs |
| Avatar connecting shimmer + slow fallback | ✅ Done | Shimmer on load → "almost ready" at 8s → error state on failure → retry button → auto-recovers on stream |
| Immediate audio playback | ✅ Done | Play each audio_chunk as it arrives (was: buffer all, play after response complete) |
| Frontend e2e latency metric | ✅ Done | Logs `frontend_e2e_ms` (mic release → first audio byte played in browser) |
| Streaming STT (Deepgram live) | ✅ Done | Live WebSocket streaming with partial transcripts; replaced batch/prerecorded API |
| SessionManager integration | ✅ Done | Turn counting, history compression, token economy — all driven by backend |
| 3-layer Socratic prompts | ✅ Done | `build_prompt(topic)` assembles identity + topic scaffold + adaptive rules |
| Backend-driven turn counting | ✅ Done | Frontend uses `timing.turn_number` from backend; no frontend self-increment |
| 15-turn session limit | ✅ Done | Configurable via `MAX_TURNS` env var (default 15); was hardcoded 8 |
| Latency budgets (spec-aligned) | ✅ Done | STT<300, LLM<200, TTS<150, Total<500 (was 5-10x too generous) |
| TTF metrics display | ✅ Done | Shows time-to-first (responsiveness) instead of total duration (throughput) |
| Avatar lifecycle fix | ✅ Done | `stop()` keeps WS open (SKIP only); `disconnect()` for cleanup; state validation |
| Silent failure logging | ✅ Done | All `except: pass` replaced with `logger.warning()` calls |
| Turn-aware LLM prompts | ✅ Done | `[Turn N of 15]` prefix + teach-back phase (turns 13-14) + final-turn summary |
| Session-keyed metrics | ✅ Done | `latest_metrics` keyed by session_id (was global single dict) |
| 3-view flow (topic-select → getting-ready → lesson) | ✅ Done | View state machine in useSessionStore; TopicSelectView + GettingReadyView + lesson layout |
| Topic selection (frontend) | ✅ Done | 6-card grid: Photosynthesis + Newton's Laws active; 4 "Coming Soon" stubs |
| Topic selection (backend) | ✅ Done | `GET /topics` endpoint; `?topic=` WS query param with validation |
| Auto-greeting (tutor-greeting mode) | ✅ Done | `start_lesson` → LLM greeting → TTS → `greeting_complete`; Turn 0 freebie; mic enables after |
| Getting Ready view + avatar fallback | ✅ Done | Progress stepper; Start/Continue entry for resumable lessons; immediate fallback on error, 10s timeout for connecting |
| Shared `_stream_llm_response()` helper | ✅ Done | DRY extraction from `_handle_turn`; reused by `_handle_greeting` |
| Orchestrator refactor | ✅ Done | main.py delegates to CustomOrchestrator; VAD wired; test_ws_end_of_utterance_pipeline skipped (TestClient hang) |
| Test gate taxonomy (unit/contract/browser-e2e/live-canary) | ✅ Done | See TEST_GATES.md; backend contract marker + RUNBOOK command map |
| Topic selection + greeting contract tests | ✅ Done | 5 new tests: /topics, topic param, invalid topic, start_lesson greeting, duplicate start_lesson guard |
| 3-view frontend architecture tests | ✅ Done | 57 frontend.test.tsx tests + 4 mic-pipeline E2E tests updated for topic-select -> getting-ready -> lesson flow |
| Avatar stream re-attach on view transition | ✅ Done | streamRef stores MediaStream; re-attached to new video element when view changes to lesson |
| Debug logging (frontend + backend) | ✅ Done | `console.debug` / `logger.debug` across App, WS, WebRTC, GettingReady, AvatarFeed, orchestrator, main |
| STT speech_final unblock | ✅ Done | `finish()` unblocked on `speech_final=True` (was: only on `UtteranceEnd`); safety timeout reduced to 1.0s |
| SentenceBuffer timeout flush | ✅ Done | 400ms flush when 15+ chars buffered without punctuation; prevents TTS starvation |
| LLM max_tokens + configurable model | ✅ Done | `max_tokens=150`, `temperature=0.7`; `llm_model`/`llm_max_tokens` in Settings |
| TTS timing instrumentation | ✅ Done | Cartesia `api_call_ms`, `ttfa_ms`, `total_ms`, chunk count per sentence |
| Turn counter guard | ✅ Done | `handle_turn()` rejects turns > max_turns with `session_complete` |
| README.md | ✅ Done | Architecture, latency analysis, cost analysis, tradeoff decisions, prompt system, tech stack |
| Celebration overlay (session complete) | ✅ Done | CSS-only confetti + stats + "Try another topic" CTA; renders on `sessionComplete`; 7 tests |
| Teacher Mode escalation | ✅ Done | After 3 wrong attempts, tutor explains directly then asks check-for-understanding question |
| Teach-Back phase | ✅ Done | Turns 13-14: student explains concept back; triggered by `[TEACH-BACK PHASE]` turn hint |
| Boredom detection / Cool Fact pivots | ✅ Done | "idk"/"boring"/short answers → Gross or Cool Fact from topic scaffold |
| Kid-culture analogies | ✅ Done | Minecraft, phone charging, smoothie analogies woven into prompts |
| Session persistence (reconnect) | ✅ Done | localStorage stores session/topic/avatar; only same-topic + same-avatar sessions can continue; restore sends welcome-back + repeated last prompt |
| Tutor identity: Socrates VI | ✅ Done | Tutor name updated across prompts, greeting copy, lesson UI, and conversation labels |
| Tutor speech pronunciation alias | ✅ Done | TTS-only normalization rewrites `Socrates VI` to `Socrates Six` before provider synthesis so spoken audio says "Six" while UI and transcripts stay unchanged |
| Scorer: Teacher Mode aware | ✅ Done | `score_no_direct_answer()` accepts `teacher_mode` flag; backward compatible |
| SessionManager serialization | ✅ Done | `to_dict()` / `from_dict()` for session persistence and crash recovery |
| TTS no-word text guard | ✅ Done | Cartesia rejects punctuation-only text with 400; replaced fragile regex with alphanumeric presence check |
| Simli reconnect cleanup | ✅ Done | `connect()` calls `disconnect()` before creating new session; fixes React StrictMode double-connect race |
| Avatar SSL transport detection | ✅ Done | `_is_ws_alive()` checks `transport.is_closing()` + pings enabled (20s interval, no pong timeout) |
| Greeting error handling fix | ✅ Done | `greeting_complete` no longer sent on GREETING_FAILED; frontend resets mode and shows error |
| VAD state reset on empty transcript | ✅ Done | `cancel_listening()` returns VAD to idle; prevents `listening → listening` transition errors |
| Avatar ready state accuracy | ✅ Done | Uses `requestVideoFrameCallback` + dimension check instead of WebRTC track receipt |
| Avatar connection stability (double-WS fix) | ✅ Done | `serverUrlRef` prevents `connect` identity change; `simliConnectingRef` guards against redundant Simli handshakes |
| Vite proxy IPv4 fix | ✅ Done | Proxy targets use `127.0.0.1` instead of `localhost` to avoid Docker IPv6 port conflict |
| Langfuse LLM observability | ✅ Done | Traces every Groq call (stream + quick_call) with input/output/usage/timing; graceful no-op when keys missing |
| Eval/benchmark artifact generation | ✅ Done | run_socratic_eval + run_benchmarks produce JSON + markdown; p50/p95 stats; CI exit codes; test_eval_artifacts.py |
| Fly.io deployment infra | ✅ Done | Multi-stage Dockerfile, fly.toml, .dockerignore, static file serving from FastAPI |
| Production deployment (Fly.io) | ✅ Done | Live at https://nerdy-tutor.fly.dev; auto-stop/start; health check at /health |
| CI/CD pipeline (GitHub Actions) | ✅ Done | Push to main → pytest + npm test → deploy to Fly.io; concurrency-controlled |
| Visual teaching: contracts (Phase 0) | ✅ Done | LLM step-tag prompt, WS message schema, frontend types, backend visual registry with emoji diagrams |
| Visual teaching: store + socket (Phase 1.1) | ✅ Done | Frontend store visual state + useTutorSocket parsing for lesson_visual_update |
| Visual teaching: orchestrator emit (Phase 1.2) | ✅ Done | Backend step-tag parsing + lesson_visual_update emission in handle_turn, handle_greeting, session_complete |
| Visual teaching: TeachingPanel UI (Phase 1.3) | ✅ Done | TeachingPanel + ConceptCanvas + StepProgress components with emoji diagrams |
| Visual teaching: App integration (Phase 1.4) | ✅ Done | TeachingPanel wired into right rail; mobile-responsive; backward compatible |
| Visual teaching: session_restore visual (Phase 1.5) | ✅ Done | Send lesson_visual_update after session_restore with clamped step approximation |
| Visual teaching: tests (Phase 1.6) | ✅ Done | 23 tests: store visual state (5), StepProgress (6), ConceptCanvas (5), TeachingPanel (7) + socket tests |
| Visual teaching: backend tests (Phase 1.7) | ✅ Done | 23 backend pytest tests: parse_step_tag (6), get_visual_for_step (8), get_recap_visual (3), get_total_steps (3), visual_to_message (3) |
| Browser E2E tests (Phase 5) | ✅ Done | 23 Playwright deterministic tests + live canary; covers topic select, greeting, student turn, visual panel, session complete, avatar fallback |
| SpatialReal avatar integration | ✅ Done | Feature flag `AVATAR_PROVIDER=spatialreal`; URL param `?avatar=spatialreal`; SDK Mode (frontend-driven); 10 backend tests |
| Wider concept map panel | ✅ Done | Right rail 340px (was 280px); larger emoji diagrams (28px); asymmetric grid layout |
