"""
Custom orchestrator implementation — coordinates STT → LLM → TTS → Avatar.

Implements the Orchestrator protocol so that main.py can delegate the full
pipeline to this class. Uses VADHandler for state machine and interrupt handling.
Pipeline stage: Orchestration (delegation from main.py)
"""

from __future__ import annotations

import base64
import logging
import time
from collections.abc import Awaitable, Callable
from typing import AsyncIterator

from adapters.avatar_adapter import SimliAvatarAdapter
from adapters.llm_engine import GroqLLMEngine
from adapters.stt_adapter import DeepgramSTTAdapter
from adapters.tts_adapter import CartesiaTTSAdapter, DeepgramTTSAdapter
from observability.langfuse_setup import trace_generation, trace_span
from pipeline.errors import TutorError
from pipeline.lesson_progress import LessonProgressState, evaluate_lesson_progress
from pipeline.metrics import MetricsCollector
from pipeline.orchestrator_protocol import Orchestrator
from pipeline.sentence_buffer import SentenceBuffer
from pipeline.session_manager import SessionManager
from pipeline.vad_handler import VADHandler
from prompts import build_greeting_prompt
from prompts.visuals import (
    get_recap_visual,
    get_total_steps,
    get_visual_for_step,
    parse_step_tag,
    visual_to_message,
)

logger = logging.getLogger("tutor")


def _default_max_turns() -> int:
    return 15


def _can_teach_back(progress: LessonProgressState, total_steps: int) -> bool:
    if total_steps <= 0:
        return False
    return progress.current_step_id >= total_steps - 1


def _build_turn_hint(
    turn_number: int,
    max_turns: int,
    progress: LessonProgressState,
    total_steps: int,
) -> str:
    """Build the runtime hint injected ahead of the student transcript."""
    turn_hint = f"[Turn {turn_number} of {max_turns}]"

    if turn_number == max_turns:
        return (
            f"{turn_hint} This is the FINAL turn. Summarize what the student learned. "
            "Celebrate their progress. End with encouragement, not a question."
        )

    if progress.current_scaffold_level == 1:
        turn_hint += (
            " [RUNTIME STATE: SAME CONCEPT, SCAFFOLD LEVEL 1, FAILED ATTEMPTS=1] "
            "The student is not there yet. Give one short conceptual clue, celebrate the effort, "
            "and ask one narrow follow-up question. Do not advance the concept map."
        )
    elif progress.current_scaffold_level == 2:
        turn_hint += (
            " [RUNTIME STATE: SAME CONCEPT, SCAFFOLD LEVEL 2, FAILED ATTEMPTS=2] "
            "The student is still stuck on this concept. Use one vivid real-world analogy from a kid's world, "
            "keep it short, and ask one narrow follow-up question. Do not advance the concept map."
        )
    elif progress.current_scaffold_level == 3:
        turn_hint += (
            " [RUNTIME STATE: SAME CONCEPT, SCAFFOLD LEVEL 3, FAILED ATTEMPTS=3] "
            "The student is stuck. Use a multiple-choice rescue with exactly three options labeled A, B, and C. "
            "Make one answer clearly correct and ask them to choose. Do not advance the concept map."
        )
    elif progress.current_scaffold_level >= 4:
        turn_hint += (
            f" [RUNTIME STATE: SAME CONCEPT, SCAFFOLD LEVEL 4, FAILED ATTEMPTS={progress.failed_attempts_on_current_step}] "
            "The student is deeply stuck on this same concept. Enter Teacher Mode: say "
            "\"Let's pause the guessing game and look at the map,\" explain the concept clearly in 2-3 vivid sentences, "
            "then ask a simple check-for-understanding question. Do not advance the concept map."
        )

    if _can_teach_back(progress, total_steps):
        if turn_number >= max_turns - 2:
            turn_hint += (
                " [TEACH-BACK PHASE] Time to check deep understanding. "
                "Ask the student to explain the concept in their own words. "
                "Use one of these: 'Explain this to a 2nd grader in 30 seconds' "
                "or 'Imagine you're a leaf — write your to-do list for the day.'"
            )
        elif turn_number >= max_turns - 4:
            turn_hint += " Approaching the end — start wrapping up the key concept."
    elif turn_number >= max_turns - 2:
        turn_hint += (
            " The student has not finished the concept map yet. Stay on the current concept, simplify, "
            "and do not force a recap or teach-back."
        )

    return turn_hint


class CustomOrchestrator:
    """Orchestrates STT → LLM → TTS → Avatar for a single session.

    Satisfies the Orchestrator protocol. Holds per-session adapters and
    delegates turn execution and interrupt handling. VADHandler drives
    state transitions and cancel callbacks on barge-in.
    """

    def __init__(
        self,
        settings,
        session_id: str,
        send_json: Callable[[dict], Awaitable[None]],
        max_turns: int | None = None,
        braintrust_logger=None,
        avatar_provider: str | None = None,
    ) -> None:
        self._settings = settings
        self._session_id = session_id
        self._send_json = send_json
        self._max_turns = max_turns if max_turns is not None else _default_max_turns()
        self._avatar_provider: str = avatar_provider or getattr(settings, "avatar_provider", "simli")
        self._stt = DeepgramSTTAdapter(settings)
        self._llm = GroqLLMEngine(settings)
        self._tts = (
            CartesiaTTSAdapter(settings)
            if settings.tts_provider == "cartesia"
            else DeepgramTTSAdapter(settings)
        )
        self._simli: SimliAvatarAdapter | None = None
        self._vad = VADHandler()
        self._last_metrics: dict = {}
        self._topic: str = ""
        self._lesson_progress: LessonProgressState | None = None

        # Register cancel callbacks for interrupt (barge-in)
        self._vad.register_cancel_callback("llm", self._llm.cancel)
        self._vad.register_cancel_callback("tts", self._tts.cancel)
        self._vad.register_cancel_callback(
            "simli",
            self._cancel_simli,
        )

    async def _cancel_simli(self) -> None:
        if self._simli is not None:
            await self._simli.stop()

    def set_simli(self, adapter: SimliAvatarAdapter) -> None:
        """Set the Simli avatar adapter (called after SDP handshake)."""
        self._simli = adapter

    async def handle_turn(
        self,
        audio_chunks: AsyncIterator[bytes],
        session: SessionManager,
    ) -> None:
        """Execute a full conversational turn: STT → LLM → TTS → Avatar."""
        if not self._topic and session.lesson_progress:
            self._topic = str(session.lesson_progress.get("topic", ""))
        turn_number = session.turn_count + 1
        logger.debug("handle_turn_start session_id=%s turn=%d simli=%s", self._session_id, turn_number, self._simli is not None)

        # Guard: reject turns beyond the session limit
        if turn_number > self._max_turns:
            logger.warning(
                "turn_rejected session_id=%s turn=%d max=%d",
                self._session_id, turn_number, self._max_turns,
            )
            await self._send_json({
                "type": "session_complete",
                "turn_number": session.turn_count,
                "total_turns": self._max_turns,
                "message": "Great job! You've completed all your questions for this session.",
            })
            return

        self._vad.start_listening()
        mc = MetricsCollector()
        try:
            await self._stt.start(
                mc,
                on_partial=lambda t: self._send_json({"type": "student_partial", "text": t}),
                on_final=lambda t: self._send_json({"type": "student_partial", "text": t}),
            )
        except Exception as exc:
            logger.error(
                "stt_start_failed session_id=%s error=%s",
                self._session_id,
                exc,
            )
            await self._send_json({"type": "error", "code": "STT_START_FAILED", "message": str(exc)})
            return

        # Stream audio through STT
        async for chunk in audio_chunks:
            await self._stt.send_audio(chunk)

        t0 = time.monotonic_ns()
        transcript = await self._stt.finish()
        stt_finish_ms = (time.monotonic_ns() - t0) / 1_000_000

        if not transcript.strip():
            self._vad.cancel_listening()
            mc.end_turn()
            self._last_metrics = mc.to_dict()
            return

        logger.info(
            "stt_result session_id=%s transcript=%s stt_finish_ms=%.1f",
            self._session_id,
            transcript[:80],
            stt_finish_ms,
        )
        await self._send_json({"type": "student_transcript", "text": transcript})

        mc.start_turn()
        turn_number = session.turn_count + 1
        self._vad.start_processing()

        # Langfuse: trace the LLM processing portion of the turn
        finish_trace = trace_span(
            f"turn-{turn_number}",
            metadata={
                "session_id": self._session_id,
                "turn_number": turn_number,
                "topic": self._topic,
                "transcript": transcript[:200],
            },
        )

        try:
            context = session.get_context()
            progress = self._ensure_lesson_progress(session)
            previous_visual_step = progress.visual_step_id
            total_steps = get_total_steps(self._topic)
            turn_hint = _build_turn_hint(turn_number, self._max_turns, progress, total_steps)

            full_text = await self._stream_llm_response(
                f"{turn_hint} {transcript}",
                context,
                mc,
                label=f"turn-{turn_number}",
            )

            # Parse step tag from LLM output and strip before sending to frontend
            step_id, clean_text = parse_step_tag(full_text) if full_text else (None, full_text)
            progress = evaluate_lesson_progress(
                self._topic,
                transcript,
                step_id,
                progress,
                total_steps,
            )
            self._lesson_progress = progress
            session.lesson_progress = progress.to_dict()
            logger.info(
                "lesson_progress_update session_id=%s topic=%s current_step=%d visual_step=%d hinted_step=%s advanced=%s",
                self._session_id,
                self._topic,
                progress.current_step_id,
                progress.visual_step_id,
                step_id,
                progress.visual_step_id > previous_visual_step,
            )

            if clean_text:
                session.append_turn(transcript, clean_text)
                await session.maybe_compress_history()

            self._vad.finish_speaking()
            mc.end_turn()
            timing = mc.to_dict()
            timing["stt_finish_ms"] = stt_finish_ms
            timing["turn_number"] = session.turn_count
            timing["total_turns"] = self._max_turns
            self._last_metrics = timing

            await self._send_json({"type": "tutor_text_chunk", "text": clean_text, "timing": timing})

            # The frontend map follows server-owned lesson progress, not raw LLM hints.
            visual = get_visual_for_step(self._topic, progress.visual_step_id)
            if visual:
                await self._send_json(
                    visual_to_message(
                        visual,
                        self._topic,
                        session.turn_count,
                        lesson_progress=progress.to_dict(),
                    ),
                )

            logger.info(
                "turn_complete session_id=%s turn=%d/%d step=%d text=%s timing=%s",
                self._session_id,
                session.turn_count,
                self._max_turns,
                progress.visual_step_id,
                (clean_text or "")[:80],
                timing,
            )

            if session.turn_count >= self._max_turns:
                await self._send_json({
                    "type": "session_complete",
                    "turn_number": session.turn_count,
                    "total_turns": self._max_turns,
                    "message": "Great job! You've completed all your questions for this session.",
                })
                # Send recap visual on session completion
                recap = get_recap_visual(self._topic)
                if recap:
                    await self._send_json(
                        visual_to_message(
                            recap,
                            self._topic,
                            session.turn_count,
                            is_recap=True,
                            lesson_progress=progress.to_dict(),
                        ),
                    )

        except TutorError as exc:
            mc.end_turn()
            timing = mc.to_dict()
            timing["stt_finish_ms"] = stt_finish_ms
            timing["turn_number"] = turn_number
            timing["total_turns"] = self._max_turns
            self._last_metrics = timing
            logger.error("turn_error session_id=%s error=%s timing=%s", self._session_id, exc, timing)
            await self._send_json({
                "type": "error",
                "code": "TURN_FAILED",
                "message": str(exc),
                "timing": timing,
            })
            if self._vad.state == "speaking":
                self._vad.finish_speaking()
        except Exception as exc:
            mc.end_turn()
            timing = mc.to_dict()
            timing["stt_finish_ms"] = stt_finish_ms
            timing["turn_number"] = turn_number
            timing["total_turns"] = self._max_turns
            self._last_metrics = timing
            logger.error("turn_error session_id=%s error=%s timing=%s", self._session_id, exc, timing)
            await self._send_json({
                "type": "error",
                "code": "TURN_FAILED",
                "message": str(exc),
                "timing": timing,
            })
            if self._vad.state == "speaking":
                self._vad.finish_speaking()
        finally:
            finish_trace()

    async def _stream_llm_response(
        self,
        user_input: str,
        context: list[dict],
        mc: MetricsCollector,
        label: str = "turn",
        use_vad: bool = True,
    ) -> str:
        """Stream LLM → SentenceBuffer → TTS, send audio_chunk messages. Returns full text.
        use_vad: if True, drive VAD state (speaking); set False for greeting (no listening phase).
        """
        logger.debug("_stream_llm_response session_id=%s label=%s input_len=%d context_len=%d", self._session_id, label, len(user_input), len(context))

        # Langfuse: trace the LLM generation (nests under parent turn span)
        messages = list(context) + [{"role": "user", "content": user_input}]
        finish_gen = trace_generation(
            f"llm_stream_{label}",
            model=self._llm._default_model,
            input=messages,
            model_parameters={
                "temperature": 0.7,
                "max_tokens": self._llm._max_tokens,
            },
        )

        token_stream = self._llm.stream(user_input, context, mc)
        sentence_buffer = SentenceBuffer()
        full_text = ""
        sentence_idx = 0

        async for sentence in sentence_buffer.process(token_stream):
            sentence_idx += 1
            full_text += sentence + " "
            if use_vad and sentence_idx == 1:
                self._vad.start_speaking()

            sent_tts_start = time.monotonic_ns()
            sent_first_byte_ns = None

            async for audio_chunk in self._tts.stream(sentence, mc):
                if sent_first_byte_ns is None:
                    sent_first_byte_ns = time.monotonic_ns()
                b64 = base64.b64encode(audio_chunk).decode("ascii")
                # The browser owns Simli lip-sync by forwarding these chunks over
                # the active WebRTC DataChannel. Keeping a single audio path avoids
                # backend/frontend drift when one transport dies mid-session.
                await self._send_json({"type": "audio_chunk", "data": b64})

            sent_tts_end = time.monotonic_ns()
            sent_ttfa = (
                (sent_first_byte_ns - sent_tts_start) / 1_000_000 if sent_first_byte_ns else None
            )
            sent_dur = (sent_tts_end - sent_tts_start) / 1_000_000
            logger.info(
                "tts_sentence session_id=%s %s idx=%d ttfa_ms=%.1f duration_ms=%.1f chars=%d text=%s",
                self._session_id,
                label,
                sentence_idx,
                sent_ttfa if sent_ttfa is not None else -1,
                sent_dur,
                len(sentence),
                sentence[:60],
            )

        result = full_text.strip()
        finish_gen(output=result)
        return result

    async def _stream_text_audio(
        self,
        text: str,
        mc: MetricsCollector,
        label: str,
    ) -> None:
        """Stream a prebuilt text response through TTS and avatar channels."""
        sent_tts_start = time.monotonic_ns()
        sent_first_byte_ns = None

        async for audio_chunk in self._tts.stream(text, mc):
            if sent_first_byte_ns is None:
                sent_first_byte_ns = time.monotonic_ns()
            b64 = base64.b64encode(audio_chunk).decode("ascii")
            # Welcome-back and other prebuilt tutor audio use the same frontend-
            # owned Simli path as normal turns.
            await self._send_json({"type": "audio_chunk", "data": b64})

        sent_tts_end = time.monotonic_ns()
        sent_ttfa = (
            (sent_first_byte_ns - sent_tts_start) / 1_000_000 if sent_first_byte_ns else None
        )
        sent_dur = (sent_tts_end - sent_tts_start) / 1_000_000
        logger.info(
            "tts_sentence session_id=%s %s idx=1 ttfa_ms=%.1f duration_ms=%.1f chars=%d text=%s",
            self._session_id,
            label,
            sent_ttfa if sent_ttfa is not None else -1,
            sent_dur,
            len(text),
            text[:60],
        )

    async def handle_interrupt(self, session: SessionManager) -> None:
        """Handle barge-in: cancel STT/LLM/TTS and stop avatar."""
        await self._stt.cancel()
        try:
            await self._vad.interrupt()
        except Exception:
            # Fallback: cancel adapters directly if VAD interrupt fails
            await self._llm.cancel()
            await self._tts.cancel()
            await self._cancel_simli()
        await self._send_json({"type": "barge_in_ack"})
        logger.info("barge_in session_id=%s", self._session_id)

    async def cancel_active_turn(self) -> None:
        """Best-effort cancellation used for disconnect cleanup paths."""
        try:
            await self._stt.cancel()
        except Exception as exc:
            logger.warning("stt_cancel_failed session_id=%s error=%s", self._session_id, exc)
        try:
            await self._llm.cancel()
        except Exception as exc:
            logger.warning("llm_cancel_failed session_id=%s error=%s", self._session_id, exc)
        try:
            await self._tts.cancel()
        except Exception as exc:
            logger.warning("tts_cancel_failed session_id=%s error=%s", self._session_id, exc)
        try:
            await self._cancel_simli()
        except Exception as exc:
            logger.warning("simli_cancel_failed session_id=%s error=%s", self._session_id, exc)

    async def get_metrics(self) -> dict:
        """Return the latest turn timing dict for this session."""
        return dict(self._last_metrics)

    async def handle_greeting(self, session: SessionManager, topic: str) -> None:
        """Generate and stream the tutor greeting (Turn 0). Does not count toward max_turns."""
        logger.debug("handle_greeting_start session_id=%s topic=%s simli=%s", self._session_id, topic, self._simli is not None)
        self._topic = topic
        self._lesson_progress = LessonProgressState(topic=topic, current_step_id=0, visual_step_id=0)
        session.lesson_progress = self._lesson_progress.to_dict()

        # Langfuse: trace the greeting as a top-level span
        finish_trace = trace_span(
            "greeting",
            metadata={
                "session_id": self._session_id,
                "topic": topic,
                "turn_number": 0,
            },
        )

        mc = MetricsCollector()
        mc.start_turn()
        try:
            greeting_prompt = build_greeting_prompt(topic)
            context = session.get_context()
            full_text = await self._stream_llm_response(
                greeting_prompt,
                context,
                mc,
                label="greeting",
                use_vad=False,
            )
            # Parse step tag from greeting (LLM might include [STEP:0])
            _, clean_text = parse_step_tag(full_text) if full_text else (None, full_text)

            if clean_text:
                session.history.append({"role": "assistant", "content": clean_text})

            mc.end_turn()
            timing = mc.to_dict()
            timing["turn_number"] = 0
            timing["total_turns"] = self._max_turns
            await self._send_json({
                "type": "tutor_text_chunk",
                "text": clean_text,
                "timing": timing,
                "is_greeting": True,
            })

            # Send visual for step 0 (hook) — hardcoded, don't rely on LLM tag
            visual = get_visual_for_step(topic, 0)
            if visual:
                await self._send_json(
                    visual_to_message(
                        visual,
                        topic,
                        0,
                        lesson_progress=session.lesson_progress,
                    ),
                )

            await self._send_json({"type": "greeting_complete"})
            logger.info(
                "greeting_complete session_id=%s text=%s timing=%s",
                self._session_id,
                (clean_text or "")[:80],
                timing,
            )
        except Exception as exc:
            mc.end_turn()
            logger.error("greeting_error session_id=%s error=%s", self._session_id, exc)
            await self._send_json({
                "type": "error",
                "code": "GREETING_FAILED",
                "message": str(exc),
            })
        finally:
            finish_trace()

    async def handle_welcome_back(self, session: SessionManager, topic: str) -> None:
        """Speak a short resume prompt after a restored session reconnects."""
        self._topic = topic
        self._ensure_lesson_progress(session)

        last_prompt = next(
            (
                msg["content"].replace(" [interrupted]", "").strip()
                for msg in reversed(session.history)
                if msg.get("role") == "assistant" and msg.get("content", "").strip()
            ),
            "",
        )
        if not last_prompt:
            return

        welcome_text = (
            f'Welcome back! Last time, I asked: "{last_prompt}" '
            "Let's pick up right there. What do you think?"
        )

        finish_trace = trace_span(
            "welcome_back",
            metadata={
                "session_id": self._session_id,
                "topic": topic,
                "turn_number": session.turn_count,
            },
        )

        mc = MetricsCollector()
        mc.start_turn()
        try:
            await self._stream_text_audio(welcome_text, mc, label="welcome-back")
            mc.end_turn()
            timing = mc.to_dict()
            timing["turn_number"] = session.turn_count
            timing["total_turns"] = self._max_turns
            self._last_metrics = timing
            await self._send_json({
                "type": "tutor_text_chunk",
                "text": welcome_text,
                "timing": timing,
                "is_greeting": True,
            })
            await self._send_json({"type": "greeting_complete"})
            logger.info(
                "welcome_back_complete session_id=%s turn=%d text=%s timing=%s",
                self._session_id,
                session.turn_count,
                welcome_text[:80],
                timing,
            )
        except Exception as exc:
            mc.end_turn()
            logger.error("welcome_back_error session_id=%s error=%s", self._session_id, exc)
            await self._send_json({
                "type": "error",
                "code": "GREETING_FAILED",
                "message": str(exc),
            })
        finally:
            finish_trace()

    def _ensure_lesson_progress(self, session: SessionManager) -> LessonProgressState:
        topic = self._topic
        if not topic:
            topic = session.lesson_progress.get("topic") if session.lesson_progress else ""
        if self._lesson_progress is not None and self._lesson_progress.topic == topic:
            return self._lesson_progress

        progress = LessonProgressState.from_dict(session.lesson_progress, topic)
        total_steps = get_total_steps(topic)
        if total_steps > 0:
            progress.current_step_id = min(progress.current_step_id, total_steps - 1)
            progress.visual_step_id = min(progress.visual_step_id, total_steps - 1)
        else:
            progress.current_step_id = 0
            progress.visual_step_id = 0
        self._lesson_progress = progress
        session.lesson_progress = progress.to_dict()
        return progress
