"""
Unit tests for the SpatialReal avatar adapter.

Tests cover:
  - Successful session token generation
  - Missing API key / App ID validation
  - HTTP error handling (non-2xx responses)
  - Timeout handling
  - Malformed response handling
  - No-op behaviour of stream_audio() and stop()
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch, MagicMock

import pytest
import httpx

from adapters.spatialreal_adapter import SpatialRealAdapter
from pipeline.errors import AdapterError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeSettings:
    """Minimal settings-like object for SpatialReal adapter tests."""

    def __init__(
        self,
        api_key: str = "test-sr-key",
        app_id: str = "test-app-id",
        avatar_id: str = "test-avatar-id",
        region: str = "us-west",
    ) -> None:
        self.spatialreal_api_key = api_key
        self.spatialreal_app_id = app_id
        self.spatialreal_avatar_id = avatar_id
        self.spatialreal_region = region


def _mock_response(status_code: int = 200, json_data: dict | None = None, text: str = ""):
    """Create a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"HTTP {status_code}",
            request=MagicMock(),
            response=resp,
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


# ---------------------------------------------------------------------------
# Tests: generate_session_token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_session_token_success():
    """Token generation returns expected dict on success."""
    adapter = SpatialRealAdapter(_FakeSettings())

    mock_resp = _mock_response(200, {"sessionToken": "tok_abc123xyz"})
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("adapters.spatialreal_adapter.httpx.AsyncClient", return_value=mock_client):
        result = await adapter.generate_session_token()

    assert result["session_token"] == "tok_abc123xyz"
    assert result["app_id"] == "test-app-id"
    assert result["avatar_id"] == "test-avatar-id"

    # Verify the correct endpoint and headers were used
    call_kwargs = mock_client.post.call_args
    assert "session-tokens" in call_kwargs.args[0]
    assert "us-west" in call_kwargs.args[0]  # region-specific host
    assert call_kwargs.kwargs["headers"]["X-Api-Key"] == "test-sr-key"
    assert "expireAt" in call_kwargs.kwargs["json"]


@pytest.mark.asyncio
async def test_generate_session_token_snake_case_key():
    """Token generation handles snake_case 'session_token' response key."""
    adapter = SpatialRealAdapter(_FakeSettings())

    mock_resp = _mock_response(200, {"session_token": "tok_snake"})
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("adapters.spatialreal_adapter.httpx.AsyncClient", return_value=mock_client):
        result = await adapter.generate_session_token()

    assert result["session_token"] == "tok_snake"


@pytest.mark.asyncio
async def test_generate_session_token_missing_api_key():
    """Token generation raises AdapterError when API key is empty."""
    adapter = SpatialRealAdapter(_FakeSettings(api_key=""))

    with pytest.raises(AdapterError) as exc_info:
        await adapter.generate_session_token()

    assert exc_info.value.provider == "spatialreal"
    assert "SPATIALREAL_API_KEY" in str(exc_info.value.cause)


@pytest.mark.asyncio
async def test_generate_session_token_missing_app_id():
    """Token generation raises AdapterError when App ID is empty."""
    adapter = SpatialRealAdapter(_FakeSettings(app_id=""))

    with pytest.raises(AdapterError) as exc_info:
        await adapter.generate_session_token()

    assert exc_info.value.provider == "spatialreal"
    assert "SPATIALREAL_APP_ID" in str(exc_info.value.cause)


@pytest.mark.asyncio
async def test_generate_session_token_http_error():
    """Token generation raises AdapterError on non-2xx HTTP response."""
    adapter = SpatialRealAdapter(_FakeSettings())

    mock_resp = _mock_response(403, text="Forbidden")
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("adapters.spatialreal_adapter.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(AdapterError) as exc_info:
            await adapter.generate_session_token()

    assert exc_info.value.provider == "spatialreal"
    assert exc_info.value.stage == "avatar"


@pytest.mark.asyncio
async def test_generate_session_token_malformed_response():
    """Token generation raises AdapterError when response lacks sessionToken."""
    adapter = SpatialRealAdapter(_FakeSettings())

    mock_resp = _mock_response(200, {"other_field": "value"})
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("adapters.spatialreal_adapter.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(AdapterError) as exc_info:
            await adapter.generate_session_token()

    assert "missing 'sessionToken'" in str(exc_info.value.cause)


@pytest.mark.asyncio
async def test_generate_session_token_timeout():
    """Token generation raises AdapterError on request timeout."""
    adapter = SpatialRealAdapter(_FakeSettings())

    mock_client = AsyncMock()
    mock_client.post.side_effect = httpx.ReadTimeout("Connection timed out")
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("adapters.spatialreal_adapter.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(AdapterError) as exc_info:
            await adapter.generate_session_token()

    assert exc_info.value.provider == "spatialreal"
    assert isinstance(exc_info.value.cause, httpx.TimeoutException)


@pytest.mark.asyncio
async def test_generate_session_token_request_payload():
    """Verify the correct JSON payload is sent to the SpatialReal API."""
    adapter = SpatialRealAdapter(_FakeSettings(app_id="my-app", region="ap-northeast"))

    mock_resp = _mock_response(200, {"sessionToken": "tok_test"})
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("adapters.spatialreal_adapter.httpx.AsyncClient", return_value=mock_client):
        await adapter.generate_session_token()

    call_kwargs = mock_client.post.call_args
    assert "ap-northeast" in call_kwargs.args[0]  # region in URL host
    assert "expireAt" in call_kwargs.kwargs["json"]


# ---------------------------------------------------------------------------
# Tests: No-op methods
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_audio_noop():
    """stream_audio drains the iterator without error."""
    adapter = SpatialRealAdapter(_FakeSettings())
    chunks_consumed = 0

    async def _chunks():
        nonlocal chunks_consumed
        for _ in range(3):
            chunks_consumed += 1
            yield b"\x00" * 320

    # Should not raise; metrics param is unused so None is fine
    await adapter.stream_audio(_chunks(), None)  # type: ignore[arg-type]
    assert chunks_consumed == 3


@pytest.mark.asyncio
async def test_stop_noop():
    """stop() returns without error."""
    adapter = SpatialRealAdapter(_FakeSettings())
    await adapter.stop()
