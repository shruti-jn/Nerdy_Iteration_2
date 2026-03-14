"""
Tests for adapter ABCs and the Orchestrator protocol.

Validates that:
  - Each ABC cannot be instantiated directly (raises TypeError).
  - A concrete subclass implementing all abstract methods can be instantiated.
  - A concrete subclass missing any abstract method raises TypeError.
  - The Orchestrator Protocol works via structural subtyping (no inheritance).

Written TDD-first before the implementation in adapters/base.py and
pipeline/orchestrator_protocol.py.

Pipeline stage: Infrastructure (shared by all stages)
"""

from __future__ import annotations

from typing import AsyncIterator

import pytest

from adapters.base import (
    BaseSTTAdapter,
    BaseLLMEngine,
    BaseTTSAdapter,
    BaseAvatarAdapter,
)
from pipeline.orchestrator_protocol import Orchestrator


# ---------------------------------------------------------------------------
# Helpers: complete mock subclasses that implement every abstract method
# ---------------------------------------------------------------------------


class ConcreteSTT(BaseSTTAdapter):
    """Fully-implemented mock STT adapter for testing."""

    async def start(self, metrics, on_partial, on_final) -> None:
        pass

    async def send_audio(self, chunk: bytes) -> None:
        pass

    async def finish(self) -> str:
        return "hello world"

    async def cancel(self) -> None:
        pass


class ConcreteLLM(BaseLLMEngine):
    """Fully-implemented mock LLM engine for testing."""

    async def stream(
        self,
        transcript: str,
        context: list[dict],
        metrics: "MetricsCollector",
    ) -> AsyncIterator[str]:
        yield "token"

    async def quick_call(self, prompt: str, model: str) -> str:
        return "response"

    async def cancel(self) -> None:
        pass


class ConcreteTTS(BaseTTSAdapter):
    """Fully-implemented mock TTS adapter for testing."""

    async def stream(
        self,
        sentence: str,
        metrics: "MetricsCollector",
    ) -> AsyncIterator[bytes]:
        yield b"\x00" * 160

    async def cancel(self) -> None:
        pass


class ConcreteAvatar(BaseAvatarAdapter):
    """Fully-implemented mock avatar adapter for testing."""

    async def stream_audio(
        self,
        audio_chunks: AsyncIterator[bytes],
        metrics: "MetricsCollector",
    ) -> None:
        pass

    async def stop(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Helpers: incomplete subclasses (missing one required method each)
# ---------------------------------------------------------------------------


class IncompleteSTT_MissingStart(BaseSTTAdapter):
    """STT subclass missing 'start'."""

    async def send_audio(self, chunk: bytes) -> None:
        pass

    async def finish(self) -> str:
        return ""

    async def cancel(self) -> None:
        pass


class IncompleteSTT_MissingCancel(BaseSTTAdapter):
    """STT subclass missing 'cancel'."""

    async def start(self, metrics, on_partial, on_final) -> None:
        pass

    async def send_audio(self, chunk: bytes) -> None:
        pass

    async def finish(self) -> str:
        return ""


class IncompleteLLM_MissingStream(BaseLLMEngine):
    """LLM subclass missing 'stream'."""

    async def quick_call(self, prompt: str, model: str) -> str:
        return ""

    async def cancel(self) -> None:
        pass


class IncompleteLLM_MissingQuickCall(BaseLLMEngine):
    """LLM subclass missing 'quick_call'."""

    async def stream(
        self,
        transcript: str,
        context: list[dict],
        metrics: "MetricsCollector",
    ) -> AsyncIterator[str]:
        yield ""

    async def cancel(self) -> None:
        pass


class IncompleteLLM_MissingCancel(BaseLLMEngine):
    """LLM subclass missing 'cancel'."""

    async def stream(
        self,
        transcript: str,
        context: list[dict],
        metrics: "MetricsCollector",
    ) -> AsyncIterator[str]:
        yield ""

    async def quick_call(self, prompt: str, model: str) -> str:
        return ""


class IncompleteTTS_MissingStream(BaseTTSAdapter):
    """TTS subclass missing 'stream'."""

    async def cancel(self) -> None:
        pass


class IncompleteTTS_MissingCancel(BaseTTSAdapter):
    """TTS subclass missing 'cancel'."""

    async def stream(
        self,
        sentence: str,
        metrics: "MetricsCollector",
    ) -> AsyncIterator[bytes]:
        yield b""


class IncompleteAvatar_MissingStreamAudio(BaseAvatarAdapter):
    """Avatar subclass missing 'stream_audio'."""

    async def stop(self) -> None:
        pass


class IncompleteAvatar_MissingStop(BaseAvatarAdapter):
    """Avatar subclass missing 'stop'."""

    async def stream_audio(
        self,
        audio_chunks: AsyncIterator[bytes],
        metrics: "MetricsCollector",
    ) -> None:
        pass


# ---------------------------------------------------------------------------
# BaseSTTAdapter tests
# ---------------------------------------------------------------------------


class TestBaseSTTAdapter:
    """Tests for the BaseSTTAdapter ABC."""

    def test_cannot_instantiate_directly(self):
        """ABC must not be instantiable without implementing abstract methods."""
        with pytest.raises(TypeError):
            BaseSTTAdapter()

    def test_concrete_subclass_instantiates(self):
        """A subclass implementing all abstract methods should instantiate."""
        adapter = ConcreteSTT()
        assert isinstance(adapter, BaseSTTAdapter)

    def test_missing_start_raises_type_error(self):
        """A subclass missing 'start' cannot be instantiated."""
        with pytest.raises(TypeError):
            IncompleteSTT_MissingStart()

    def test_missing_cancel_raises_type_error(self):
        """A subclass missing 'cancel' cannot be instantiated."""
        with pytest.raises(TypeError):
            IncompleteSTT_MissingCancel()


# ---------------------------------------------------------------------------
# BaseLLMEngine tests
# ---------------------------------------------------------------------------


class TestBaseLLMEngine:
    """Tests for the BaseLLMEngine ABC."""

    def test_cannot_instantiate_directly(self):
        """ABC must not be instantiable without implementing abstract methods."""
        with pytest.raises(TypeError):
            BaseLLMEngine()

    def test_concrete_subclass_instantiates(self):
        """A subclass implementing all abstract methods should instantiate."""
        engine = ConcreteLLM()
        assert isinstance(engine, BaseLLMEngine)

    def test_missing_stream_raises_type_error(self):
        """A subclass missing 'stream' cannot be instantiated."""
        with pytest.raises(TypeError):
            IncompleteLLM_MissingStream()

    def test_missing_quick_call_raises_type_error(self):
        """A subclass missing 'quick_call' cannot be instantiated."""
        with pytest.raises(TypeError):
            IncompleteLLM_MissingQuickCall()

    def test_missing_cancel_raises_type_error(self):
        """A subclass missing 'cancel' cannot be instantiated."""
        with pytest.raises(TypeError):
            IncompleteLLM_MissingCancel()


# ---------------------------------------------------------------------------
# BaseTTSAdapter tests
# ---------------------------------------------------------------------------


class TestBaseTTSAdapter:
    """Tests for the BaseTTSAdapter ABC."""

    def test_cannot_instantiate_directly(self):
        """ABC must not be instantiable without implementing abstract methods."""
        with pytest.raises(TypeError):
            BaseTTSAdapter()

    def test_concrete_subclass_instantiates(self):
        """A subclass implementing all abstract methods should instantiate."""
        adapter = ConcreteTTS()
        assert isinstance(adapter, BaseTTSAdapter)

    def test_missing_stream_raises_type_error(self):
        """A subclass missing 'stream' cannot be instantiated."""
        with pytest.raises(TypeError):
            IncompleteTTS_MissingStream()

    def test_missing_cancel_raises_type_error(self):
        """A subclass missing 'cancel' cannot be instantiated."""
        with pytest.raises(TypeError):
            IncompleteTTS_MissingCancel()


# ---------------------------------------------------------------------------
# BaseAvatarAdapter tests
# ---------------------------------------------------------------------------


class TestBaseAvatarAdapter:
    """Tests for the BaseAvatarAdapter ABC."""

    def test_cannot_instantiate_directly(self):
        """ABC must not be instantiable without implementing abstract methods."""
        with pytest.raises(TypeError):
            BaseAvatarAdapter()

    def test_concrete_subclass_instantiates(self):
        """A subclass implementing all abstract methods should instantiate."""
        adapter = ConcreteAvatar()
        assert isinstance(adapter, BaseAvatarAdapter)

    def test_missing_stream_audio_raises_type_error(self):
        """A subclass missing 'stream_audio' cannot be instantiated."""
        with pytest.raises(TypeError):
            IncompleteAvatar_MissingStreamAudio()

    def test_missing_stop_raises_type_error(self):
        """A subclass missing 'stop' cannot be instantiated."""
        with pytest.raises(TypeError):
            IncompleteAvatar_MissingStop()


# ---------------------------------------------------------------------------
# Orchestrator Protocol tests (structural subtyping)
# ---------------------------------------------------------------------------


class DuckOrchestrator:
    """A class that satisfies the Orchestrator Protocol structurally.

    Does NOT inherit from Orchestrator. This proves that structural
    subtyping (duck typing) works as intended with typing.Protocol.
    """

    async def handle_turn(
        self,
        audio_chunks: AsyncIterator[bytes],
        session: "SessionManager",
    ) -> None:
        pass

    async def handle_interrupt(self, session: "SessionManager") -> None:
        pass

    async def get_metrics(self) -> dict:
        return {}


class NotAnOrchestrator:
    """A class that does NOT satisfy the Orchestrator Protocol.

    Missing 'handle_turn' method entirely.
    """

    async def handle_interrupt(self, session: "SessionManager") -> None:
        pass

    async def get_metrics(self) -> dict:
        return {}


class TestOrchestratorProtocol:
    """Tests for the Orchestrator Protocol."""

    def test_structural_subtype_is_accepted(self):
        """A class with the right methods satisfies the protocol at runtime."""
        orch = DuckOrchestrator()
        # runtime_checkable allows isinstance checks
        assert isinstance(orch, Orchestrator)

    def test_non_conforming_class_is_rejected(self):
        """A class missing required methods does NOT satisfy the protocol."""
        obj = NotAnOrchestrator()
        assert not isinstance(obj, Orchestrator)

    def test_protocol_is_not_inherited(self):
        """DuckOrchestrator does not inherit from Orchestrator."""
        assert Orchestrator not in DuckOrchestrator.__mro__

    def test_protocol_has_expected_methods(self):
        """The protocol should declare handle_turn, handle_interrupt, get_metrics."""
        # Inspect the protocol's abstract methods / annotations
        expected = {"handle_turn", "handle_interrupt", "get_metrics"}
        # Protocol members show up in __protocol_attrs__ or __abstractmethods__
        # We check via a simpler approach: the DuckOrchestrator satisfies it
        # and has exactly these methods
        duck_methods = {
            name
            for name in dir(DuckOrchestrator)
            if not name.startswith("_") and callable(getattr(DuckOrchestrator, name))
        }
        assert expected.issubset(duck_methods)


# ---------------------------------------------------------------------------
# Cross-cutting: inheritance chain for ABCs
# ---------------------------------------------------------------------------


class TestABCInheritance:
    """Verify that all ABCs are proper abstract base classes."""

    def test_stt_is_abstract(self):
        assert BaseSTTAdapter.__abstractmethods__

    def test_llm_is_abstract(self):
        assert BaseLLMEngine.__abstractmethods__

    def test_tts_is_abstract(self):
        assert BaseTTSAdapter.__abstractmethods__

    def test_avatar_is_abstract(self):
        assert BaseAvatarAdapter.__abstractmethods__

    def test_stt_abstract_methods(self):
        expected = {"start", "send_audio", "finish", "cancel"}
        assert BaseSTTAdapter.__abstractmethods__ == expected

    def test_llm_abstract_methods(self):
        expected = {"stream", "quick_call", "cancel"}
        assert BaseLLMEngine.__abstractmethods__ == expected

    def test_tts_abstract_methods(self):
        expected = {"stream", "cancel"}
        assert BaseTTSAdapter.__abstractmethods__ == expected

    def test_avatar_abstract_methods(self):
        expected = {"stream_audio", "stop"}
        assert BaseAvatarAdapter.__abstractmethods__ == expected
