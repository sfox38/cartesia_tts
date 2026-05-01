"""Async HTTP client for the Cartesia TTS REST API.

Encapsulates all network I/O. The rest of the integration never imports
aiohttp directly; it calls methods on CartesiaClient instead.

API reference: https://docs.cartesia.ai/api-reference/tts/bytes

Error handling
--------------
The Cartesia API returns structured JSON errors:
  {
    "error_code": "quota_exceeded",
    "title": "Quota exceeded",
    "message": "You have exceeded your plan's credit quota.",
    "request_id": "..."
  }

Actionable error codes are mapped to specific exception subclasses so callers
can handle them distinctly. All others fall through to CartesiaApiError.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp

from .const import (
    CARTESIA_API_BASE,
    CARTESIA_API_VERSION,
    CARTESIA_TTS_ENDPOINT,
    CARTESIA_VOICES_ENDPOINT,
)

_LOGGER = logging.getLogger(__name__)

_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)
_MAX_VOICE_PAGES = 50


class CartesiaApiError(Exception):
    """Raised when the Cartesia API returns an unexpected response."""


class CartesiaAuthError(CartesiaApiError):
    """Raised on HTTP 401 - invalid or expired API key."""


class CartesiaQuotaError(CartesiaApiError):
    """Raised when the account has exhausted its credit quota (error_code: quota_exceeded)."""


class CartesiaConcurrencyError(CartesiaApiError):
    """Raised when the plan's concurrent request limit is exceeded (error_code: concurrency_limited)."""


class CartesiaPlanError(CartesiaApiError):
    """Raised when the requested feature requires a plan upgrade (error_code: plan_upgrade_required)."""


def _parse_error(status: int, body: str) -> CartesiaApiError:
    """Parse a Cartesia error response body and return the appropriate exception.

    Attempts to parse the body as JSON and extract the error_code field.
    Falls back to a generic CartesiaApiError if the body is not valid JSON
    or does not contain a known error_code.
    """
    try:
        data = json.loads(body)
        error_code = data.get("error_code", "")
        message = data.get("message") or data.get("title") or body
    except (json.JSONDecodeError, AttributeError):
        error_code = ""
        message = body

    full_message = f"HTTP {status}: {message}"

    if error_code == "quota_exceeded":
        return CartesiaQuotaError(
            f"{full_message} - Your Cartesia credit quota is exhausted. "
            "Visit play.cartesia.ai to check your plan."
        )
    if error_code == "concurrency_limited":
        return CartesiaConcurrencyError(
            f"{full_message} - Too many concurrent requests for your plan."
        )
    if error_code == "plan_upgrade_required":
        return CartesiaPlanError(
            f"{full_message} - This feature requires a higher Cartesia plan."
        )

    return CartesiaApiError(full_message)


class CartesiaClient:
    """Thin async wrapper around the Cartesia REST API.

    A single instance is created per config entry in async_setup_entry and
    stored in hass.data[DOMAIN][entry_id]["client"]. It is shared by the
    TTS entity and the VoiceCache.
    """

    def __init__(self, api_key: str, session: aiohttp.ClientSession) -> None:
        """Initialise the client with an API key and a shared aiohttp session."""
        self._api_key = api_key
        self._session = session
        # Headers sent on every request.
        self._base_headers = {
            "Authorization": f"Bearer {api_key}",
            "Cartesia-Version": CARTESIA_API_VERSION,
            "Content-Type": "application/json",
        }

    async def validate_api_key(self) -> bool:
        """Check that the API key is accepted by Cartesia.

        Makes a lightweight GET /voices request. Raises CartesiaAuthError on
        HTTP 401, CartesiaApiError on any other failure.
        """
        url = f"{CARTESIA_API_BASE}{CARTESIA_VOICES_ENDPOINT}"
        try:
            async with self._session.get(url, headers=self._base_headers, timeout=_REQUEST_TIMEOUT) as resp:
                if resp.status == 401:
                    raise CartesiaAuthError("Invalid API key")
                if resp.status != 200:
                    body = await resp.text()
                    raise _parse_error(resp.status, body)
                return True
        except aiohttp.ClientError as err:
            raise CartesiaApiError(f"Connection error: {err}") from err

    async def get_voices(self) -> list[dict[str, Any]]:
        """Fetch the complete list of voices available to this API key.

        The Cartesia /voices endpoint is paginated (up to 100 per page).
        This method follows the pagination cursor until all pages are
        consumed, returning every voice as a flat list.

        Each voice dict includes at minimum: id, name, language, description.
        Accent information is embedded in the voice name/description rather
        than as a structured field.

        Raises CartesiaAuthError or CartesiaApiError on failure.
        """
        url = f"{CARTESIA_API_BASE}{CARTESIA_VOICES_ENDPOINT}"
        all_voices: list[dict[str, Any]] = []
        starting_after: str | None = None

        try:
            pages_fetched = 0
            while True:
                pages_fetched += 1
                if pages_fetched > _MAX_VOICE_PAGES:
                    _LOGGER.warning(
                        "Cartesia /voices pagination exceeded %d pages, stopping",
                        _MAX_VOICE_PAGES,
                    )
                    break

                params: dict[str, Any] = {"limit": 100}
                if starting_after:
                    params["starting_after"] = starting_after

                async with self._session.get(
                    url, headers=self._base_headers, params=params, timeout=_REQUEST_TIMEOUT,
                ) as resp:
                    if resp.status == 401:
                        raise CartesiaAuthError("Invalid API key")
                    if resp.status != 200:
                        body = await resp.text()
                        raise _parse_error(resp.status, body)
                    raw_text = await resp.text()
                    data = json.loads(raw_text)

                if isinstance(data, list):
                    # Older API versions returned a plain list.
                    all_voices.extend(data)
                    break
                elif isinstance(data, dict):
                    # Current API returns {"data": [...], "has_more": bool}.
                    # Fall back to "voices" and "items" for forward compatibility.
                    page_voices = data.get("voices", data.get("data", data.get("items", [])))
                    if not isinstance(page_voices, list):
                        _LOGGER.warning(
                            "Cartesia /voices unexpected dict structure, keys: %s",
                            list(data.keys()),
                        )
                        break
                    all_voices.extend(page_voices)
                    has_more = data.get("has_more", False)
                    if not has_more or not page_voices:
                        break
                    # Cursor for next page is the id of the last voice on this page.
                    starting_after = page_voices[-1].get("id")
                    if not starting_after:
                        break
                else:
                    _LOGGER.warning(
                        "Cartesia /voices unexpected response type: %s", type(data)
                    )
                    break

        except aiohttp.ClientError as err:
            raise CartesiaApiError(f"Connection error fetching voices: {err}") from err

        _LOGGER.debug("Cartesia get_voices: total voices fetched = %d", len(all_voices))
        return all_voices

    async def synthesize(
        self,
        transcript: str,
        model: str,
        voice_id: str,
        language: str,
        speed: float,
        volume: float,
        emotion: str | None,
    ) -> bytes:
        """Generate speech and return the raw MP3 bytes.

        Calls POST /tts/bytes with the given parameters. The transcript is
        passed as-is, so Cartesia SSML tags embedded in the text (e.g.
        <emotion value="angry"/>, <speed ratio="1.5"/>, [laughter]) are
        honoured by the API.

        generation_config is sent for all supported models (sonic-3,
        sonic-turbo). "neutral" emotion is not sent to avoid overriding
        the model's natural emotional interpretation.

        Returns raw MP3 audio bytes on success.
        Raises a CartesiaApiError subclass on failure (see module docstring
        for the full error class hierarchy).
        """
        url = f"{CARTESIA_API_BASE}{CARTESIA_TTS_ENDPOINT}"

        output_format = {
            "container": "mp3",
            "encoding": "mp3",
            "sample_rate": 44100,
        }

        generation_config: dict[str, Any] = {
            "speed": speed,
            "volume": volume,
        }
        # Omit emotion entirely when neutral so the model uses its default
        # emotional interpretation rather than an explicit neutral override.
        if emotion and emotion != "neutral":
            generation_config["emotion"] = emotion

        payload: dict[str, Any] = {
            "model_id": model,
            "transcript": transcript,
            "voice": {
                "mode": "id",
                "id": voice_id,
            },
            "output_format": output_format,
            "language": language,
            "generation_config": generation_config,
        }

        transcript_preview = transcript[:50] + "..." if len(transcript) > 50 else transcript
        _LOGGER.debug(
            "Cartesia TTS request: model=%s voice=%s lang=%s transcript=%r",
            model, voice_id, language, transcript_preview,
        )

        try:
            async with self._session.post(
                url, headers=self._base_headers, json=payload, timeout=_REQUEST_TIMEOUT,
            ) as resp:
                if resp.status == 401:
                    raise CartesiaAuthError("Invalid API key")
                if resp.status != 200:
                    body = await resp.text()
                    raise _parse_error(resp.status, body)
                return await resp.read()
        except aiohttp.ClientError as err:
            raise CartesiaApiError(f"Connection error during synthesis: {err}") from err