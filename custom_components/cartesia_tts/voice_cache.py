"""In-memory cache for the Cartesia voice list.

The full voice library (~600-700 entries) is fetched on demand and held
in memory for the lifetime of the HA session. The cache starts empty and
is populated on first use: either when the user opens the Configure
dialog, or when HA calls async_get_voices to list available voices in
the UI.

Voices are NOT fetched on HA startup. This avoids a gratuitous API call
on every restart. Since the cache is cleared on every HA restart, any
voices added by Cartesia will appear automatically the next time the user
opens Configure, with no explicit reload action needed.

The cache is intentionally simple: no TTL, no disk persistence.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .api import CartesiaClient

_LOGGER = logging.getLogger(__name__)


class VoiceCache:
    """Holds the Cartesia voice list and provides filtered views of it.

    One instance is created per config entry and stored in
    hass.data[DOMAIN][entry_id]["voice_cache"].
    """

    def __init__(self, hass: HomeAssistant, client: CartesiaClient) -> None:
        self._hass = hass
        self._client = client
        self._voices: list[dict[str, Any]] = []
        self._load_lock = asyncio.Lock()

    @property
    def voices(self) -> list[dict[str, Any]]:
        """The full raw voice list as returned by the API."""
        return self._voices

    async def async_refresh(self) -> None:
        """Fetch the complete voice list from Cartesia and replace the cache."""
        _LOGGER.debug("Refreshing Cartesia voice list from API")
        self._voices = await self._client.get_voices()
        _LOGGER.debug("Loaded %d voices from Cartesia", len(self._voices))

    async def async_ensure_loaded(self) -> None:
        """Fetch voices if the cache is empty. No-op if already populated."""
        if self._voices:
            return
        async with self._load_lock:
            if not self._voices:
                await self.async_refresh()

    def get_voices_for_language(self, language: str) -> list[dict[str, Any]]:
        """Return voices whose language field starts with the given ISO code."""
        return [
            v for v in self._voices
            if self._voice_supports_language(v, language)
        ]

    def get_all_voices(self) -> list[dict[str, Any]]:
        """Return a shallow copy of the full voice list."""
        return list(self._voices)

    def _voice_supports_language(self, voice: dict[str, Any], language: str) -> bool:
        """Return True if this voice supports the given ISO 639-1 language code.

        Matches exact codes ("en") and dialect variants ("en-US", "en-GB") but
        not unrelated codes that happen to share a prefix ("eng").
        """
        def _matches(voice_lang: str) -> bool:
            return voice_lang == language or voice_lang.startswith(language + "-")

        voice_lang = voice.get("language", "")
        if isinstance(voice_lang, str):
            return _matches(voice_lang)
        if isinstance(voice_lang, list):
            return any(_matches(lang) for lang in voice_lang)
        return False