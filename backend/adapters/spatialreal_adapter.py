"""
SpatialReal avatar adapter for on-device WebGL/WebGPU avatar rendering.

In SDK Mode the backend only generates a session token via REST. The
frontend initialises the AvatarKit Web SDK, receives TTS audio chunks
over the existing WebSocket, and forwards them to SpatialReal directly.
There is no backend-side audio proxy — the adapter is intentionally thin.

Pipeline stage: Avatar (Stage 4 — token generation only)

Exports:
    SpatialRealAdapter -- Session-token generator for SpatialReal SDK Mode
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

import httpx

from adapters.base import BaseAvatarAdapter
from pipeline.errors import AdapterError
from pipeline.metrics import MetricsCollector

logger = logging.getLogger(__name__)

# SpatialReal Console API (session token generation)
# Base URL is region-specific: console.{region}.spatialwalk.cloud
_REGION_HOSTS = {
    "us-west": "console.us-west.spatialwalk.cloud",
    "ap-northeast": "console.ap-northeast.spatialwalk.cloud",
}
_TOKEN_PATH = "/v1/console/session-tokens"
_TOKEN_REQUEST_TIMEOUT_S = 10.0


class SpatialRealAdapter(BaseAvatarAdapter):
    """SpatialReal avatar adapter — generates session tokens for SDK Mode.

    In SDK Mode the frontend owns the avatar connection. The backend's
    sole responsibility is to mint a session token via the SpatialReal
    Console REST API and hand it (along with app_id and avatar_id) to
    the frontend.  Audio streaming, rendering, and interruption are all
    handled client-side by the AvatarKit Web SDK.

    Args:
        settings: Application settings with ``spatialreal_api_key``,
                  ``spatialreal_app_id``, ``spatialreal_avatar_id``,
                  and ``spatialreal_region``.
    """

    def __init__(self, settings) -> None:
        self._api_key: str = settings.spatialreal_api_key
        self._app_id: str = settings.spatialreal_app_id
        self._avatar_id: str = settings.spatialreal_avatar_id
        self._region: str = settings.spatialreal_region

    async def generate_session_token(self) -> dict:
        """Generate a SpatialReal session token via the Console API.

        Returns:
            Dict with ``session_token``, ``app_id``, and ``avatar_id``.

        Raises:
            AdapterError: If the API call fails, returns a non-2xx status,
                          or the response is missing the expected token.
        """
        if not self._api_key:
            raise AdapterError(
                stage="avatar",
                provider="spatialreal",
                cause=ValueError("SPATIALREAL_API_KEY is not configured"),
                context={"app_id": self._app_id},
            )
        if not self._app_id:
            raise AdapterError(
                stage="avatar",
                provider="spatialreal",
                cause=ValueError("SPATIALREAL_APP_ID is not configured"),
                context={},
            )

        try:
            # Build region-specific endpoint URL
            host = _REGION_HOSTS.get(self._region)
            if not host:
                raise ValueError(
                    f"Unknown SpatialReal region '{self._region}'. "
                    f"Supported: {', '.join(_REGION_HOSTS)}"
                )
            token_url = f"https://{host}{_TOKEN_PATH}"

            # Token expires in 1 hour (max allowed: 24h)
            import time
            expire_at = int(time.time()) + 3600

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    token_url,
                    json={
                        "expireAt": expire_at,
                    },
                    headers={
                        "Content-Type": "application/json",
                        "X-Api-Key": self._api_key,
                    },
                    timeout=_TOKEN_REQUEST_TIMEOUT_S,
                )
                resp.raise_for_status()
                data = resp.json()

            session_token = data.get("sessionToken") or data.get("session_token")
            if not session_token:
                raise RuntimeError(
                    f"SpatialReal token response missing 'sessionToken': {data!r}"
                )

            logger.info(
                "SpatialReal session token generated: token=%s..., app_id=%s, avatar_id=%s",
                session_token[:8],
                self._app_id,
                self._avatar_id,
            )

            return {
                "session_token": session_token,
                "app_id": self._app_id,
                "avatar_id": self._avatar_id,
            }

        except AdapterError:
            raise
        except httpx.TimeoutException as exc:
            raise AdapterError(
                stage="avatar",
                provider="spatialreal",
                cause=exc,
                context={"app_id": self._app_id, "region": self._region},
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise AdapterError(
                stage="avatar",
                provider="spatialreal",
                cause=exc,
                context={
                    "app_id": self._app_id,
                    "status_code": exc.response.status_code,
                    "body": exc.response.text[:200],
                },
            ) from exc
        except Exception as exc:
            raise AdapterError(
                stage="avatar",
                provider="spatialreal",
                cause=exc,
                context={"app_id": self._app_id},
            ) from exc

    # ── BaseAvatarAdapter interface (no-ops in SDK Mode) ─────────────────

    async def stream_audio(
        self,
        audio_chunks: AsyncIterator[bytes],
        metrics: MetricsCollector,
    ) -> None:
        """No-op: in SDK Mode the frontend forwards audio to SpatialReal directly."""
        # Drain the iterator to prevent upstream stalls, but don't send anywhere.
        async for _ in audio_chunks:
            pass

    async def stop(self) -> None:
        """No-op: in SDK Mode the frontend handles interrupt via controller.interrupt()."""
        pass
