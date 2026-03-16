"""
FastAPI app entry point for the Live AI Video Tutor.

Exposes HTTP health/metrics endpoints and a WebSocket /session endpoint
that drives the STT -> LLM -> SentenceBuffer -> TTS pipeline. The frontend
connects via WebSocket and exchanges binary PCM audio frames and JSON
control messages.

Audio frames are forwarded to Deepgram's live WebSocket as they arrive,
producing partial transcripts in real time. The LLM pipeline triggers
once the final transcript is available (on mic release / Deepgram flush).

Pipeline stage: Entry point — routes WebSocket connections to the pipeline.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone
from pythonjsonlogger.json import JsonFormatter

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from adapters.avatar_adapter import SimliAvatarAdapter
from adapters.spatialreal_adapter import SpatialRealAdapter
from adapters.llm_engine import GroqLLMEngine
from config import settings
from observability.langfuse_setup import init_langfuse, shutdown_langfuse
from pipeline.orchestrator_custom import CustomOrchestrator
from pipeline.session_manager import SessionManager
from pipeline.session_store import SessionStore
from prompts import build_prompt, AVAILABLE_TOPICS
from prompts.visuals import get_visual_for_step, get_total_steps, visual_to_message
from observability.braintrust_logger import BraintrustLogger

logger = logging.getLogger("tutor")

class _ISOJsonFormatter(JsonFormatter):
    """JSON formatter with proper ISO-8601 timestamps including milliseconds."""
    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        log_record["timestamp"] = (
            datetime.fromtimestamp(record.created, tz=timezone.utc)
            .isoformat(timespec="milliseconds")
        )

_LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)
_json_fmt = _ISOJsonFormatter(
    fmt="%(levelname)s %(name)s %(message)s",
    rename_fields={"levelname": "level", "name": "logger"},
)
_file_handler = RotatingFileHandler(
    os.path.join(_LOG_DIR, "server.log"), maxBytes=5 * 1024 * 1024, backupCount=1
)
_file_handler.setFormatter(_json_fmt)
_console_handler = logging.StreamHandler()
_console_handler.setFormatter(_json_fmt)
logging.basicConfig(level=logging.INFO, handlers=[_console_handler, _file_handler])

# ── FastAPI app ─────────────────────────────────────────────────────────────

_braintrust: BraintrustLogger | None = None

@asynccontextmanager
async def _lifespan(app: FastAPI):
    """FastAPI lifespan: initialize on startup, clean up on shutdown."""
    global _braintrust
    init_langfuse(settings)
    _braintrust = BraintrustLogger(api_key=settings.braintrust_api_key)
    yield
    shutdown_langfuse()

app = FastAPI(title="Live AI Video Tutor", version="0.1.0", lifespan=_lifespan)

# Track active sessions for the /ready endpoint and concurrency control
active_sessions: set[str] = set()
MAX_SESSIONS = 5
MAX_TURNS = settings.max_turns

# Store latest metrics for the /metrics endpoint (keyed by session_id)
latest_metrics: dict[str, dict] = {}

# Persistent session store for reconnection support
session_store = SessionStore()


def _resolve_avatar_provider(avatar_query: str, default_provider: str) -> str:
    avatar_param = (avatar_query or "").lower()
    if avatar_param in ("simli", "spatialreal"):
        return avatar_param
    return default_provider if default_provider in ("simli", "spatialreal") else "simli"


def _resolve_simli_mode(simli_mode_query: str, env_default: str, sdk_enabled: bool) -> tuple[str, str]:
    """Resolve Simli mode with URL override and env fallback.

    Returns:
        (mode, source) where source is one of url/env/default/forced.
    """
    requested = (simli_mode_query or "").lower()
    env_mode = (env_default or "").lower()

    if requested in ("custom", "sdk"):
        if requested == "sdk" and not sdk_enabled:
            return "custom", "forced"
        return requested, "url"

    if env_mode in ("custom", "sdk"):
        if env_mode == "sdk" and not sdk_enabled:
            return "custom", "forced"
        return env_mode, "env"

    return "custom", "default"


# ── HTTP endpoints ──────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Liveness probe."""
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    """Readiness probe with active session count."""
    return {"status": "ready", "active_sessions": len(active_sessions)}


@app.get("/metrics")
async def metrics():
    """Return the latest pipeline metrics from the most recent turn."""
    if not latest_metrics:
        return {}
    # Return the most recently updated session's metrics
    return next(reversed(latest_metrics.values()), {})


@app.get("/topics")
async def topics():
    """Return the list of available topic identifiers."""
    return {"topics": AVAILABLE_TOPICS}


# ── WebSocket: queue stream for orchestrator ───────────────────────────────

async def _stream_from_queue(q: asyncio.Queue) -> AsyncIterator[bytes]:
    """Yield bytes from queue until None sentinel (used by CustomOrchestrator.handle_turn)."""
    while True:
        chunk = await q.get()
        if chunk is None:
            break
        yield chunk


# ── WebSocket tutoring session ──────────────────────────────────────────────

@app.websocket("/session")
async def session_handler(ws: WebSocket):
    """Handle a single tutoring session; delegates pipeline to CustomOrchestrator.

    Supports session recovery: if the client provides a ``session_id`` query
    parameter that matches a persisted (non-expired) session, the server
    restores conversation history and sends a ``session_restore`` message
    instead of starting fresh.
    """
    await ws.accept()
    if len(active_sessions) >= MAX_SESSIONS:
        await _send_json(ws, {"type": "error", "code": "SESSION_LIMIT_EXCEEDED", "message": "Max concurrent sessions reached"})
        await ws.close(code=1008, reason="Session limit exceeded")
        return
    topic = ws.query_params.get("topic", "photosynthesis")
    if topic not in AVAILABLE_TOPICS:
        await _send_json(ws, {"type": "error", "code": "INVALID_TOPIC", "message": f"Unknown topic '{topic}'. Available: {', '.join(AVAILABLE_TOPICS)}"})
        await ws.close(code=1008, reason="Invalid topic")
        return

    # ── Session recovery or new session ─────────────────────────────────
    client_session_id = ws.query_params.get("session_id")
    restored = False
    session_id: str
    system_prompt = build_prompt(topic)
    llm_engine = GroqLLMEngine(settings)

    if client_session_id:
        saved = await session_store.load(client_session_id)
        if saved is not None and saved.get("topic") == topic:
            # Restore existing session
            session_id = client_session_id
            session_mgr = SessionManager.from_dict(saved, system_prompt, llm_engine)
            restored = True
            logger.info("Session restored", extra={"event": "session_restore", "session_id": session_id, "topic": topic, "turn_count": session_mgr.turn_count})
        else:
            # Expired or mismatched topic — start fresh with new ID
            session_id = str(uuid.uuid4())
            session_mgr = SessionManager(system_prompt, llm_engine)
    else:
        session_id = str(uuid.uuid4())
        session_mgr = SessionManager(system_prompt, llm_engine)


    active_sessions.add(session_id)
    logger.info("Session started", extra={"event": "session_start", "session_id": session_id, "topic": topic, "restored": restored})
    send = lambda data: _send_json(ws, data)
    # Allow URL param ?avatar=spatialreal to override the env default
    avatar_provider = _resolve_avatar_provider(ws.query_params.get("avatar", ""), settings.avatar_provider)
    simli_mode = "custom"
    simli_mode_source = "not_applicable"
    if avatar_provider == "simli":
        simli_mode, simli_mode_source = _resolve_simli_mode(
            ws.query_params.get("simli_mode", ""),
            settings.simli_mode,
            settings.simli_sdk_enabled,
        )
    logger.info(
        "avatar_mode_selected session_id=%s avatar_provider=%s simli_mode=%s source=%s",
        session_id,
        avatar_provider,
        simli_mode,
        simli_mode_source,
    )
    orchestrator = CustomOrchestrator(
        settings,
        session_id,
        send,
        max_turns=MAX_TURNS,
        braintrust_logger=_braintrust,
        avatar_provider=avatar_provider,
        simli_mode=simli_mode,
    )
    simli: SimliAvatarAdapter | None = None
    turn_queue: asyncio.Queue | None = None
    turn_task: asyncio.Task | None = None
    greeting_sent = False  # set True after start_lesson or continue_lesson

    try:
        async def _send_simli_sdk_init_if_needed() -> None:
            if avatar_provider != "simli" or simli_mode != "sdk":
                return
            if not settings.simli_api_key or not settings.simli_face_id:
                await _send_json(
                    ws,
                    {
                        "type": "error",
                        "code": "SIMLI_NOT_CONFIGURED",
                        "message": "SIMLI_API_KEY and SIMLI_FACE_ID must be set in .env",
                    },
                )
                return
            try:
                sdk_session_adapter = SimliAvatarAdapter(settings)
                sdk_session = await sdk_session_adapter.initialize_session()
                await _send_json(
                    ws,
                    {
                        "type": "simli_sdk_init",
                        "session_token": sdk_session["session_token"],
                        "ice_servers": sdk_session.get("ice_servers", []),
                    },
                )
                logger.info("simli_sdk_init_sent session_id=%s", session_id)
            except Exception as exc:
                logger.error("simli_sdk_init_failed session_id=%s error=%s", session_id, exc, exc_info=True)
                await _send_json(
                    ws,
                    {"type": "error", "code": "SIMLI_SDK_INIT_FAILED", "message": str(exc)},
                )

        if restored:
            # Send restore message with full history so frontend can rebuild UI
            await _send_json(ws, {
                "type": "session_restore",
                "session_id": session_id,
                "topic": topic,
                "total_turns": MAX_TURNS,
                "turn_count": session_mgr.turn_count,
                "avatar_provider": avatar_provider,
                "simli_mode": simli_mode,
                "simli_mode_source": simli_mode_source,
                "history": [
                    {"role": msg["role"], "content": msg["content"]}
                    for msg in session_mgr.history
                ],
            })
            # Restore the last server-owned concept-map step when available.
            saved_progress = session_mgr.lesson_progress if isinstance(session_mgr.lesson_progress, dict) else None
            restore_step = None
            if saved_progress and saved_progress.get("topic") == topic:
                restore_step = int(saved_progress.get("visual_step_id", 0))
            if restore_step is None:
                restore_step = min(session_mgr.turn_count, get_total_steps(topic) - 1)
            restore_step = max(0, restore_step)  # clamp to 0 if no steps
            restore_visual = get_visual_for_step(topic, restore_step)
            if restore_visual:
                await _send_json(
                    ws,
                    visual_to_message(
                        restore_visual,
                        topic,
                        session_mgr.turn_count,
                        lesson_progress=session_mgr.lesson_progress,
                    ),
                )
            # SpatialReal needs a fresh token on restore too
            if avatar_provider == "spatialreal":
                try:
                    sr_adapter = SpatialRealAdapter(settings)
                    sr_init = await sr_adapter.generate_session_token()
                    await _send_json(ws, {
                        "type": "spatialreal_session_init",
                        "session_token": sr_init["session_token"],
                        "app_id": sr_init["app_id"],
                        "avatar_id": sr_init["avatar_id"],
                    })
                except Exception as exc:
                    logger.error("spatialreal_init_failed session_id=%s error=%s", session_id, exc, exc_info=True)
                    await _send_json(ws, {"type": "error", "code": "SPATIALREAL_INIT_FAILED", "message": str(exc)})
            else:
                await _send_simli_sdk_init_if_needed()
            # Welcome-back is deferred until the frontend explicitly chooses
            # Continue. If the user picks Start Lesson instead, we now restart
            # the lesson in place on this same websocket/avatar connection.
        else:
            await _send_json(
                ws,
                {
                    "type": "session_start",
                    "session_id": session_id,
                    "topic": topic,
                    "total_turns": MAX_TURNS,
                    "avatar_provider": avatar_provider,
                    "simli_mode": simli_mode,
                    "simli_mode_source": simli_mode_source,
                },
            )

            # SpatialReal: generate session token and send init message
            if avatar_provider == "spatialreal":
                try:
                    sr_adapter = SpatialRealAdapter(settings)
                    sr_init = await sr_adapter.generate_session_token()
                    await _send_json(ws, {
                        "type": "spatialreal_session_init",
                        "session_token": sr_init["session_token"],
                        "app_id": sr_init["app_id"],
                        "avatar_id": sr_init["avatar_id"],
                    })
                    logger.info("spatialreal_session_init sent session_id=%s", session_id)
                except Exception as exc:
                    logger.error("spatialreal_init_failed session_id=%s error=%s", session_id, exc, exc_info=True)
                    await _send_json(ws, {"type": "error", "code": "SPATIALREAL_INIT_FAILED", "message": str(exc)})
            else:
                await _send_simli_sdk_init_if_needed()

        logger.debug("Session start sent", extra={"event": "session_start_sent", "session_id": session_id})
        while True:
            raw = await ws.receive()
            if "bytes" in raw and raw["bytes"] is not None:
                if turn_task is not None:
                    turn_queue.put_nowait(raw["bytes"])
                else:
                    if session_mgr.turn_count >= MAX_TURNS:
                        logger.debug("Turn limit reached", extra={"event": "turn_limit_reached", "session_id": session_id, "turn_count": session_mgr.turn_count})
                        await _send_json(ws, {"type": "session_complete", "turn_number": session_mgr.turn_count, "total_turns": MAX_TURNS, "message": "Great job! You've completed all your questions for this session."})
                        continue
                    logger.info("Audio first chunk received", extra={"event": "audio_first_chunk", "session_id": session_id, "turn": session_mgr.turn_count + 1, "chunk_bytes": len(raw["bytes"])})
                    turn_queue = asyncio.Queue()
                    turn_task = asyncio.create_task(orchestrator.handle_turn(_stream_from_queue(turn_queue), session_mgr))
                    turn_queue.put_nowait(raw["bytes"])
                continue
            if "text" in raw and raw["text"] is not None:
                try:
                    msg = json.loads(raw["text"])
                except json.JSONDecodeError:
                    await _send_json(ws, {"type": "error", "code": "INVALID_JSON"})
                    continue
                msg_type = msg.get("type", "")
                logger.info("ws_msg session_id=%s type=%s", session_id, msg_type)
                if msg_type == "start_lesson":
                    if greeting_sent:
                        logger.debug("duplicate_start_lesson session_id=%s — ignored", session_id)
                        continue
                    greeting_sent = True
                    if restored:
                        logger.info("start_lesson_reset_restored_session session_id=%s topic=%s", session_id, topic)
                        session_mgr = SessionManager(system_prompt, llm_engine)
                        restored = False
                    logger.info("start_lesson session_id=%s topic=%s", session_id, topic)
                    await orchestrator.handle_greeting(session_mgr, topic)
                    # Persist after greeting so restore can skip it
                    await session_store.save(session_id, session_mgr.to_dict(), topic)
                elif msg_type == "continue_lesson":
                    if greeting_sent:
                        logger.debug("duplicate_continue_lesson session_id=%s — ignored", session_id)
                        continue
                    greeting_sent = True
                    logger.info("continue_lesson session_id=%s topic=%s", session_id, topic)
                    if any(m.get("role") == "assistant" and m.get("content", "").strip() for m in session_mgr.history):
                        await orchestrator.handle_welcome_back(session_mgr, topic)
                    await session_store.save(session_id, session_mgr.to_dict(), topic)
                elif msg_type == "end_of_utterance":
                    logger.info("end_of_utterance session_id=%s turn_task_active=%s", session_id, turn_task is not None)
                    if turn_task is not None:
                        turn_queue.put_nowait(None)
                        try:
                            await turn_task
                        except asyncio.CancelledError:
                            pass
                        except Exception as exc:
                            logger.warning("turn_task_failed session_id=%s error=%s", session_id, exc)
                        latest_metrics[session_id] = await orchestrator.get_metrics()
                        logger.info("turn_complete_metrics session_id=%s metrics=%s", session_id, latest_metrics[session_id])
                        turn_task = None
                        turn_queue = None
                        # Persist session after each completed turn
                        await session_store.save(session_id, session_mgr.to_dict(), topic)
                elif msg_type == "barge_in":
                    logger.info("barge_in_received session_id=%s", session_id)
                    await orchestrator.handle_interrupt(session_mgr)
                    if turn_task is not None:
                        turn_task.cancel()
                        try:
                            await turn_task
                        except asyncio.CancelledError:
                            pass
                        except Exception as exc:
                            logger.warning("turn_task_cancel_failed session_id=%s error=%s", session_id, exc)
                        await orchestrator.cancel_active_turn()
                        turn_task = None
                        turn_queue = None
                elif msg_type == "simli_sdp_offer":
                    if simli_mode != "custom":
                        await _send_json(
                            ws,
                            {
                                "type": "error",
                                "code": "SIMLI_MODE_UNSUPPORTED",
                                "message": "simli_sdp_offer is only supported in custom mode.",
                            },
                        )
                        continue
                    logger.debug("simli_sdp_offer session_id=%s sdp_len=%d", session_id, len(msg.get("sdp", "")))
                    sdp_offer = msg.get("sdp", "")
                    if not sdp_offer:
                        await _send_json(ws, {"type": "error", "code": "MISSING_SDP", "message": "simli_sdp_offer requires 'sdp' field"})
                        continue
                    if not settings.simli_api_key or not settings.simli_face_id:
                        logger.debug("simli_not_configured session_id=%s", session_id)
                        await _send_json(ws, {"type": "error", "code": "SIMLI_NOT_CONFIGURED", "message": "SIMLI_API_KEY and SIMLI_FACE_ID must be set in .env"})
                        continue
                    if simli is None:
                        simli = SimliAvatarAdapter(settings)
                    try:
                        logger.debug("simli_connect_start session_id=%s", session_id)
                        result = await simli.connect(sdp_offer)
                        orchestrator.set_simli(simli)
                        logger.debug("simli_sdp_answer_sending session_id=%s answer_sdp_len=%d ice_servers=%d", session_id, len(result["sdp"]), len(result.get("ice_servers", [])))
                        await _send_json(ws, {"type": "simli_sdp_answer", "sdp": result["sdp"], "iceServers": result["ice_servers"]})
                        logger.info("simli_connected session_id=%s", session_id)
                    except Exception as exc:
                        logger.error("simli_connect_failed session_id=%s error=%s", session_id, exc, exc_info=True)
                        simli = None
                        await _send_json(ws, {"type": "error", "code": "SIMLI_CONNECT_FAILED", "message": str(exc)})
    except WebSocketDisconnect:
        logger.info("session_end session_id=%s reason=disconnect", session_id)
    except Exception as exc:
        logger.error("session_error session_id=%s error=%s", session_id, exc)
    finally:
        if turn_task is not None:
            turn_task.cancel()
            try:
                await turn_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("turn_task_cleanup_failed session_id=%s error=%s", session_id, exc)
            await orchestrator.cancel_active_turn()
        if simli is not None:
            try:
                await simli.disconnect()
            except Exception as exc:
                logger.warning("simli_disconnect_failed session_id=%s error=%s", session_id, exc)
        # Clean up session on completion; keep in store for reconnection
        if session_mgr.turn_count >= MAX_TURNS:
            await session_store.delete(session_id)
        active_sessions.discard(session_id)
        latest_metrics.pop(session_id, None)
        logger.info("session_cleanup session_id=%s", session_id)


# ── Helpers ─────────────────────────────────────────────────────────────────

async def _send_json(ws: WebSocket, data: dict) -> None:
    """Send a JSON message over the WebSocket, logging any failures."""
    try:
        await ws.send_text(json.dumps(data))
    except Exception as exc:
        logger.warning("ws_send_failed type=%s error=%s", data.get("type", "?"), exc)


# ── Static file serving (production) ───────────────────────────────────────
# In production the frontend Vite build is copied into ./static/ by the
# Dockerfile. StaticFiles(html=True) serves index.html for directory
# requests (SPA root). Mounted AFTER all routes so API endpoints take
# priority (Starlette checks @app routes before mounts).

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_STATIC_DIR):
    from starlette.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="spa")
