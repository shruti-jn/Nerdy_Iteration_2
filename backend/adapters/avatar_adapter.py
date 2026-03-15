"""
Simli avatar adapter for real-time lip-synced video rendering.

Server-side signaling proxy that:
  1. Creates a Simli session (session token + ICE servers)
  2. Streams TTS audio chunks to Simli via WebSocket
  3. Returns WebRTC connection details for the frontend to render

The frontend establishes a WebRTC peer connection directly with Simli
servers using the session token and ICE servers provided by this adapter.
Audio is forwarded from the backend TTS pipeline to Simli, which drives
the lip-synced avatar video stream sent to the frontend.

Pipeline stage: Avatar (Stage 4 of STT -> LLM -> TTS -> Avatar)

Exports:
    SimliAvatarAdapter -- Concrete avatar adapter backed by Simli
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import AsyncIterator, Optional

import httpx
import websockets

from adapters.base import BaseAvatarAdapter
from pipeline.errors import AdapterError
from pipeline.metrics import MetricsCollector

logger = logging.getLogger(__name__)

# Simli API endpoints
_SIMLI_BASE_URL = "https://api.simli.ai"
_TOKEN_ENDPOINT = f"{_SIMLI_BASE_URL}/compose/token"
_ICE_ENDPOINT = f"{_SIMLI_BASE_URL}/compose/ice"
_WS_BASE_URL = "wss://api.simli.ai/compose/webrtc/p2p"

_HANDSHAKE_TIMEOUT_S = 10.0  # Max wait per step during WebRTC handshake
_KEEPALIVE_INTERVAL_S = 3.0  # Send silent audio to prevent Simli idle timeout
# 10 ms of silence at 16 kHz mono PCM16 = 320 bytes (160 samples × 2 bytes)
_SILENT_FRAME = b"\x00" * 320


class SimliAvatarAdapter(BaseAvatarAdapter):
    """Simli-backed avatar adapter for real-time lip-synced rendering.

    Manages the lifecycle of a Simli session: creation, audio streaming,
    and cleanup. Audio chunks from the TTS stage are forwarded to Simli
    via WebSocket, and the resulting video stream is delivered to the
    frontend via WebRTC.

    The adapter supports multi-turn sessions: after connect(), the
    WebSocket remains open across turns. send_audio() can be called
    on each turn. Only stop() or disconnect() closes the connection.

    A background keepalive task sends silent audio frames every 3 seconds
    to prevent Simli's server from closing the WebSocket due to inactivity
    between conversational turns.

    Args:
        settings: Application settings with ``simli_api_key``,
                  ``simli_face_id``, and ``avatar_max_ms``.
    """

    def __init__(self, settings) -> None:
        self._api_key: str = settings.simli_api_key
        self._face_id: str = settings.simli_face_id
        self._avatar_max_ms: int = settings.avatar_max_ms
        self._session_token: Optional[str] = None
        self._ice_servers: list[dict] = []
        self._ws = None
        self._ready: bool = False
        self._keepalive_task: Optional[asyncio.Task] = None
        self._drop_logged: bool = False  # Log first audio drop per not-ready period

    @property
    def is_ready(self) -> bool:
        """Whether the adapter is connected and ready to receive audio."""
        return self._ready and self._ws is not None

    async def initialize_session(self) -> dict:
        """Create a Simli session and retrieve WebRTC connection details.

        Calls the Simli REST API to get a session token and ICE servers.
        The returned dict can be forwarded to the frontend to establish
        a WebRTC peer connection.

        Returns:
            Dict with 'session_token' and 'ice_servers' keys.

        Raises:
            AdapterError: If the Simli API returns an error or the
                          connection fails.
        """
        try:
            async with httpx.AsyncClient() as client:
                # Step 1: Get session token
                token_resp = await client.post(
                    _TOKEN_ENDPOINT,
                    json={
                        "faceId": self._face_id,
                        "handleSilence": True,
                        "maxSessionLength": 3600,
                        "maxIdleTime": 300,
                    },
                    headers={
                        "Content-Type": "application/json",
                        "x-simli-api-key": self._api_key,
                    },
                    timeout=10.0,
                )
                token_resp.raise_for_status()
                token_data = token_resp.json()
                self._session_token = token_data["session_token"]

                # Step 2: Get ICE servers
                ice_resp = await client.get(
                    _ICE_ENDPOINT,
                    headers={"x-simli-api-key": self._api_key},
                    timeout=10.0,
                )
                ice_resp.raise_for_status()
                self._ice_servers = ice_resp.json()

            logger.info(
                "Simli session created: token=%s..., ice_servers=%d",
                self._session_token[:8] if self._session_token else "none",
                len(self._ice_servers),
            )

            return {
                "session_token": self._session_token,
                "ice_servers": self._ice_servers,
            }

        except Exception as exc:
            raise AdapterError(
                stage="avatar",
                provider="simli",
                cause=exc,
                context={"face_id": self._face_id},
            ) from exc

    async def connect(self, sdp_offer: str) -> dict:
        """Full WebRTC handshake: init session, open WebSocket, exchange SDP.

        Steps:
            1. POST /compose/token -> session_token
            2. GET /compose/ice -> ice_servers
            3. Connect WebSocket to /compose/webrtc/p2p?session_token=...
            4. Wait for ready signal: legacy API sends "START"; new API sends
               JSON {"destination": "<b64>", "session_id": "..."}
            5. Send SDP offer as JSON {"type": "offer", "sdp": "..."}
            6. Receive SDP answer as JSON {"type": "answer", "sdp": "..."}

        Args:
            sdp_offer: SDP offer string from the frontend RTCPeerConnection.

        Returns:
            Dict with "sdp" (Simli's answer SDP) and "ice_servers" list.

        Raises:
            AdapterError: On timeout, connection failure, or protocol error.
        """
        try:
            # Clean up any previous connection before creating a new one.
            # This handles React StrictMode double-invokes where connect()
            # is called twice in quick succession — without cleanup, the
            # first Simli session stays alive and may cause Simli to reject
            # the second session for the same face_id.
            if self._ws is not None or self._ready:
                logger.info("Simli connect: closing previous connection before reconnect")
                await self.disconnect()

            # Steps 1-2: REST session init (token + ICE servers)
            session = await self.initialize_session()
            ice_servers = session["ice_servers"]

            # Step 3: Open WebSocket to Simli signaling endpoint.
            # Enable pings (20s interval) to keep the connection alive, but
            # disable the pong timeout (ping_timeout=None) so the library
            # won't kill the connection if Simli doesn't respond to pings.
            # Previous approach (ping_interval=None) caused the connection
            # to die silently at ~40s — either from Simli's server-side
            # ping timeout or a network intermediary (CDN/ALB) idle timeout.
            # With pings enabled but no timeout, the pings themselves act as
            # traffic that prevents intermediary timeouts, and our
            # _is_ws_alive() transport check catches true dead connections.
            url = f"{_WS_BASE_URL}?session_token={self._session_token}"
            self._ws = await asyncio.wait_for(
                websockets.connect(url, ping_interval=20, ping_timeout=None),
                timeout=_HANDSHAKE_TIMEOUT_S,
            )

            # Step 4: Wait for ready signal from Simli.
            # Older Simli API sends the literal string "START".
            # Newer API sends JSON: {"destination": "<b64-addr>", "session_id": "..."}
            start_msg = await asyncio.wait_for(
                self._ws.recv(), timeout=_HANDSHAKE_TIMEOUT_S
            )
            if start_msg == "START":
                logger.info("Simli ready (legacy protocol): START received")
            else:
                try:
                    conn_info = json.loads(start_msg)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(
                        f"Expected 'START' or JSON connection info from Simli, "
                        f"got: {start_msg!r}"
                    ) from exc
                if "destination" not in conn_info:
                    raise RuntimeError(
                        f"Simli JSON missing 'destination' field: {conn_info!r}"
                    )
                dest_decoded = base64.b64decode(conn_info["destination"]).decode()
                logger.info(
                    "Simli ready (new protocol): session_id=%s destination=%s",
                    conn_info.get("session_id", "?"),
                    dest_decoded,
                )

            # Step 5: Send SDP offer
            logger.info(
                "Simli sending SDP offer (ws_state=%s)",
                getattr(self._ws, "state", "unknown"),
            )
            await self._ws.send(json.dumps({"type": "offer", "sdp": sdp_offer}))
            logger.info("Simli SDP offer sent; awaiting answer...")

            # Step 6: Receive SDP answer
            raw_answer = await asyncio.wait_for(
                self._ws.recv(), timeout=_HANDSHAKE_TIMEOUT_S
            )
            logger.info("Simli SDP answer received (len=%d)", len(raw_answer))
            answer_data = json.loads(raw_answer)
            answer_sdp = answer_data.get("sdp") or answer_data.get("answer")
            if not answer_sdp:
                raise RuntimeError(
                    f"Simli SDP answer missing 'sdp'/'answer' field: {answer_data!r}"
                )

            self._ready = True
            self._drop_logged = False
            self._start_keepalive()
            logger.info(
                "Simli WebRTC handshake complete: token=%s...",
                self._session_token[:8] if self._session_token else "none",
            )
            return {"sdp": answer_sdp, "ice_servers": ice_servers}

        except AdapterError:
            raise
        except asyncio.TimeoutError as exc:
            raise AdapterError(
                stage="avatar",
                provider="simli",
                cause=exc,
                context={"face_id": self._face_id},
            ) from exc
        except Exception as exc:
            raise AdapterError(
                stage="avatar",
                provider="simli",
                cause=exc,
                context={"face_id": self._face_id},
            ) from exc

    # ── Transport health ─────────────────────────────────────────────────────

    def _is_ws_alive(self) -> bool:
        """Check if the WebSocket connection is truly alive.

        Checks both the WebSocket protocol state AND the underlying asyncio
        transport.  The websockets library may report state=OPEN even after
        the SSL/TCP transport has been closed by the remote end (especially
        when ping_interval is None), so we must also inspect the transport.
        """
        if self._ws is None:
            return False
        # Protocol-level check (OPEN = 1)
        ws_state = getattr(self._ws, "state", None)
        if ws_state is not None and ws_state != 1:
            return False
        # Transport-level check — catches SSL connection deaths that the
        # websockets protocol layer hasn't noticed yet.
        transport = getattr(self._ws, "transport", None)
        if transport is not None and transport.is_closing():
            return False
        return True

    # ── Keepalive ──────────────────────────────────────────────────────────────

    def _start_keepalive(self) -> None:
        """Start the background keepalive task (idempotent)."""
        self._stop_keepalive()
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())
        logger.debug("Simli keepalive started")

    def _stop_keepalive(self) -> None:
        """Cancel the background keepalive task if running."""
        if self._keepalive_task is not None:
            self._keepalive_task.cancel()
            self._keepalive_task = None

    async def _keepalive_loop(self) -> None:
        """Send silent PCM frames every few seconds to prevent Simli idle timeout."""
        try:
            while True:
                await asyncio.sleep(_KEEPALIVE_INTERVAL_S)
                if not self._ready or self._ws is None:
                    break
                if not self._is_ws_alive():
                    logger.warning(
                        "Simli keepalive: connection dead (state=%s, transport_closing=%s), stopping",
                        getattr(self._ws, "state", "?"),
                        getattr(getattr(self._ws, "transport", None), "is_closing", lambda: "?")(),
                    )
                    self._ready = False
                    break
                try:
                    await self._ws.send(_SILENT_FRAME)
                except Exception as exc:
                    logger.warning("Simli keepalive send failed: %s", exc)
                    self._ready = False
                    break
        except asyncio.CancelledError:
            pass  # Normal shutdown

    # ── Audio streaming ──────────────────────────────────────────────────────

    async def send_audio(self, chunk: bytes) -> None:
        """Forward a single PCM audio chunk to Simli for lip-sync rendering.

        Logs a warning on the first drop per not-ready period (avoids log spam).
        Called per TTS audio chunk in _handle_turn so the avatar lip-syncs
        in real time.

        Args:
            chunk: Raw PCM Int16 16 kHz mono audio bytes.
        """
        if not self._ready or self._ws is None:
            if not self._drop_logged:
                logger.warning(
                    "Simli send_audio: not ready (ws=%s, ready=%s) — audio will be dropped until reconnect",
                    self._ws is not None,
                    self._ready,
                )
                self._drop_logged = True
            return

        # Check both WebSocket protocol state AND transport health.
        if not self._is_ws_alive():
            logger.warning(
                "Simli send_audio: connection dead (state=%s, transport_closing=%s) — marking not ready",
                getattr(self._ws, "state", "?"),
                getattr(getattr(self._ws, "transport", None), "is_closing", lambda: "?")(),
            )
            self._ready = False
            self._drop_logged = False
            self._stop_keepalive()
            return

        try:
            await self._ws.send(chunk)
        except Exception as exc:
            logger.warning("Simli send_audio failed: %s — marking not ready", exc)
            self._ready = False
            self._drop_logged = False
            self._stop_keepalive()

    async def stream_audio(
        self,
        audio_chunks: AsyncIterator[bytes],
        metrics: MetricsCollector,
    ) -> None:
        """Feed TTS audio chunks to Simli for lip-synced rendering.

        Forwards each audio chunk as a binary WebSocket message to the
        active Simli session. Records rendering latency via the metrics
        collector.

        Args:
            audio_chunks: Async iterator yielding PCM16 16kHz mono audio.
            metrics:      MetricsCollector for avatar stage timing.

        Raises:
            AdapterError: If the session is not initialized or streaming
                          fails.
        """
        if not self._ready or self._ws is None:
            raise AdapterError(
                stage="avatar",
                provider="simli",
                cause=RuntimeError("Session not initialized. Call initialize_session() first."),
            )

        metrics.start("avatar")
        first_chunk = True

        try:
            async for chunk in audio_chunks:
                await self._ws.send(chunk)
                if first_chunk:
                    metrics.mark_first("avatar")
                    first_chunk = False

            metrics.end("avatar")

        except Exception as exc:
            metrics.end("avatar")
            raise AdapterError(
                stage="avatar",
                provider="simli",
                cause=exc,
            ) from exc

    async def stop(self) -> None:
        """Stop speaking and clear any buffered audio in the Simli session.

        Sends a SKIP command to flush Simli's audio buffer (so the avatar
        stops lip-syncing the old audio). Does NOT close the WebSocket
        — the connection stays alive for the next turn. The keepalive
        task continues running to prevent idle timeout.

        To fully close the connection, use disconnect().
        """
        if self._ws is not None and self._ready:
            try:
                await self._ws.send("SKIP")
                logger.info("Simli SKIP sent (clearing audio buffer)")
            except Exception as exc:
                logger.warning("Simli SKIP failed: %s — connection may be stale", exc)
                self._ready = False
                self._stop_keepalive()

    async def disconnect(self) -> None:
        """Fully close the Simli WebSocket connection.

        Call this on session cleanup. After disconnect(), a new connect()
        call is needed to resume streaming.
        """
        self._stop_keepalive()
        if self._ws is not None:
            try:
                await self._ws.send("SKIP")
            except Exception:
                pass  # Best-effort
            try:
                await self._ws.close()
            except Exception:
                pass  # Best-effort

        self._ws = None
        self._ready = False
        self._session_token = None
        self._drop_logged = False
        logger.info("Simli disconnected")
