# Nerdy — Live AI Video Tutor

A real-time AI tutoring system that teaches 6th-graders science concepts through Socratic questioning, with a lip-syncing avatar, streaming audio, and sub-second latency.

## What It Does

A student picks a topic (Photosynthesis or Newton's Laws), and an AI tutor named **Nova** guides them through an 8-turn Socratic conversation. Nova never gives answers directly — instead, she asks guiding questions, redirects wrong answers, and celebrates correct ones. The avatar speaks with lip-sync, and the student responds with their microphone.

## Architecture

```
┌─────────────┐     WebSocket (PCM16 + JSON)     ┌──────────────────┐
│  React UI   │ ◄──────────────────────────────► │  FastAPI Backend │
│  (Vite/TS)  │                                   │  (Python 3.12)   │
└──────┬──────┘                                   └───────┬──────────┘
       │                                                  │
       │  WebRTC (SDP via WS)                             ├─► Deepgram Nova-3 (STT)
       │                                                  │     Live WebSocket streaming
       ▼                                                  │
┌──────────────┐                                          ├─► Groq Llama 3.3 70B (LLM)
│ Simli Avatar │                                          │     Streaming token generation
│  (WebRTC)    │                                          │
└──────────────┘                                          ├─► Cartesia Sonic-3 (TTS)
                                                          │     SSE streaming audio
                                                          │
                                                          └─► Simli (Avatar)
                                                                WebRTC audio forwarding
```

**Pipeline per turn:**

```
Student speaks → VAD detects end → STT (Deepgram) → LLM (Groq) → SentenceBuffer
                                                                       │
                                            ┌──────────────────────────┘
                                            ▼
                                    TTS (Cartesia) → Audio to browser
                                            │           + Avatar lip-sync
                                            ▼
                                    Student hears response
```

### Key Components

| Component | File | Role |
|-----------|------|------|
| **Orchestrator** | `backend/pipeline/orchestrator_custom.py` | Coordinates STT → LLM → TTS → Avatar per turn |
| **STT Adapter** | `backend/adapters/stt_adapter.py` | Deepgram Nova-3 live WebSocket streaming |
| **LLM Engine** | `backend/adapters/llm_engine.py` | Groq Llama 3.3 70B with streaming tokens |
| **TTS Adapter** | `backend/adapters/tts_adapter.py` | Cartesia Sonic-3 SSE streaming (PCM16) |
| **Avatar Adapter** | `backend/adapters/avatar_adapter.py` | Simli WebRTC audio forwarding |
| **SentenceBuffer** | `backend/pipeline/sentence_buffer.py` | Splits LLM token stream into sentences for TTS |
| **VAD Handler** | `backend/pipeline/vad_handler.py` | Voice Activity Detection state machine |
| **Session Manager** | `backend/pipeline/session_manager.py` | Turn counting, history, token economy |
| **Metrics** | `backend/pipeline/metrics.py` | Nanosecond-precision per-stage latency tracking |
| **Prompts** | `backend/prompts/` | 3-layer Socratic prompt system |
| **Frontend App** | `frontend/src/App.tsx` | 3-view flow: topic select → getting ready → lesson |
| **WebSocket Hook** | `frontend/src/useTutorSocket.ts` | Audio streaming, message handling, metrics display |
| **Audio Capture** | `frontend/src/useAudioCapture.ts` | Mic → PCM Int16 via AudioWorklet |
| **Simli WebRTC** | `frontend/src/useSimliWebRTC.ts` | Avatar WebRTC connection management |

## Quick Start

```bash
# 1. Clone and set up environment
cp backend/.env.example backend/.env
# Fill in API keys: DEEPGRAM_API_KEY, GROQ_API_KEY, CARTESIA_API_KEY,
#                   CARTESIA_VOICE_ID, SIMLI_API_KEY, SIMLI_FACE_ID

# 2. Backend
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python run.py          # http://localhost:8000

# 3. Frontend (new terminal)
cd frontend
npm install
npm run dev            # http://localhost:5173
```

See [RUNBOOK.md](RUNBOOK.md) for detailed development instructions.

## Latency Analysis

### Per-Stage Budget

| Stage | Target | Max | Measurement |
|-------|--------|-----|-------------|
| STT (Deepgram Nova-3) | 150ms | 300ms | `stt_ttf_ms` — time from first audio to first transcript |
| LLM (Groq Llama 3.3) | 200ms | 400ms | `llm_ttf_ms` — time-to-first-token |
| TTS (Cartesia Sonic-3) | 150ms | 300ms | `tts_ttf_ms` — time-to-first-audio-byte |
| Avatar (Simli) | 100ms | 200ms | `avatar_ttf_ms` — WebRTC audio forward |
| **End-to-End** | **500ms** | **1000ms** | `turn_duration_ms` — full turn |

### Measurement Methodology

All timing uses `time.monotonic_ns()` — monotonic, high-resolution, unaffected by wall-clock drift. The `MetricsCollector` (`backend/pipeline/metrics.py`) tracks:

- **`start(stage)`** — records when a stage begins (first call preserved as `first_start_ns`)
- **`mark_first(stage)`** — write-once timestamp for the first output byte/token
- **`end(stage)`** — records stage completion
- **`time_to_first_ms`** — `first_start_ns` → `first_token_ns` (what the user perceives)
- **`duration_ms`** — `first_start_ns` → `end_ns` (total processing time)

Metrics are sent to the frontend in `tutor_text_chunk` messages and displayed in the latency panel.

### Optimization Strategies

1. **STT: `speech_final` unblocks `finish()` immediately** — Deepgram's `UtteranceEnd` event is unreliable after `send_finalize()`. We set `_transcript_done` on `speech_final=True`, avoiding a 1-3s timeout on every turn.

2. **SentenceBuffer timeout flush** — If 400ms pass with 15+ chars buffered and no `.?!`, flush to TTS. Prevents starvation when the LLM generates fragments without terminal punctuation.

3. **LLM `max_tokens=150`** — Socratic responses are 30-50 words. Capping tokens lets Groq allocate compute efficiently, reducing TTFT.

4. **Streaming at every stage** — STT streams partials, LLM streams tokens, TTS streams audio chunks. No stage waits for the previous to fully complete.

5. **Sentence-level TTS pipelining** — As soon as the SentenceBuffer yields a sentence, TTS starts generating audio. The user hears the first sentence while later sentences are still being generated.

## Educational Design

### 3-Layer Prompt System

The system prompt is assembled from three layers (`backend/prompts/`):

1. **Layer 1 — Identity & Rules** (`socratic_system.py`): Nova's persona, absolute rules (never give direct answers, always ask guiding questions, keep responses under 2 sentences + 1 question)

2. **Layer 2 — Topic Scaffold** (`photosynthesis.py`, `newtons_laws.py`): Topic-specific concept maps, prerequisite chains, common misconceptions, and question progressions

3. **Layer 3 — Adaptive Behavior** (`adaptive_rules.py`): Rules for handling wrong answers (redirect, don't correct), celebrating correct answers, managing frustration, and wrapping up sessions

### Socratic Flow

- **Turn 0**: Nova greets the student with a hook and first guiding question
- **Turns 1-7**: Progressive questioning following the concept map
- **Wrong answers**: Nova redirects with hints ("What if we think about it this way?") — never says "wrong"
- **Turn 8**: Summary of what was learned, celebration, encouragement

### Token Economy

The `SessionManager` maintains a rolling conversation history. When token count exceeds a threshold, older turns are compressed via a fast LLM call (Llama 3.1 8B Instant) into a summary, preserving context while staying within limits.

## Cost Analysis

| Provider | Model | Pricing | Per-Turn Est. |
|----------|-------|---------|---------------|
| Deepgram | Nova-3 STT | $0.0043/min | ~$0.0005 |
| Groq | Llama 3.3 70B | $0.59/$0.79 per 1M tokens | ~$0.0003 |
| Cartesia | Sonic-3 TTS | $0.06/1K chars | ~$0.005 |
| Simli | Avatar | Usage-based | ~$0.01 |

**Estimated cost per 8-turn session: ~$0.05-0.15**

## Tradeoff Decisions

### Cartesia over Deepgram for TTS
Cartesia Sonic-3 targets ~40ms TTFA vs Deepgram Aura-2's ~150-200ms. For a real-time tutoring experience where the student is waiting, every 100ms matters. Cartesia's SSE streaming also provides finer-grained audio chunks.

### Groq over OpenAI/Anthropic for LLM
Groq's inference speed (100-300ms TTFT on Llama 3.3 70B) is 3-5x faster than OpenAI GPT-4o or Anthropic Claude for similar quality. For Socratic tutoring, response quality is sufficient and latency is critical.

### Custom Orchestrator over LiveKit
LiveKit Agents would simplify WebRTC handling but adds a dependency and reduces control over the pipeline. A custom orchestrator gives us fine-grained metrics, sentence-level TTS pipelining, and direct control over interrupt handling.

### SentenceBuffer vs Word-Level TTS
Sending individual words to TTS would minimize latency but degrades audio quality (prosody, intonation). Sentence-level synthesis produces natural-sounding speech while the 400ms timeout flush prevents long stalls.

### WebSocket + Separate Simli WebRTC
Audio is streamed over WebSocket (reliable, ordered) while the avatar uses WebRTC (low-latency, unreliable). This separation means audio works even when the avatar fails — the student always hears Nova.

## Limitations

- **Single language**: English only (Deepgram `language="en"`)
- **Two topics**: Photosynthesis and Newton's Laws (extensible via prompt scaffolds)
- **API dependency**: Requires active internet and valid API keys for all providers
- **Avatar reliability**: Simli WebRTC connection can be flaky; fallback to voice-only is available
- **No persistence**: Session history is in-memory; refreshing the page starts a new session
- **No authentication**: No user accounts or progress tracking
- **Browser requirement**: Requires a modern browser with WebRTC and AudioWorklet support

## Tech Stack

- **Backend**: Python 3.12, FastAPI, WebSockets, Pydantic Settings
- **Frontend**: React 18, TypeScript, Vite, Zustand (state management)
- **STT**: Deepgram Nova-3 (live WebSocket streaming)
- **LLM**: Groq Llama 3.3 70B Versatile (streaming)
- **TTS**: Cartesia Sonic-3 (SSE streaming, PCM16)
- **Avatar**: Simli (WebRTC, lip-sync)
- **Testing**: pytest (backend, 257 tests), Vitest (frontend, 113 tests)

## Testing

```bash
# Backend (257 tests)
cd backend && source venv/bin/activate && pytest -v

# Frontend (113 tests)
cd frontend && npm test
```

## License

Course project — not licensed for redistribution.
