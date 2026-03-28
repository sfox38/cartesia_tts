"""In-memory cache for the Cartesia voice list.

The full voice library (~600-700 entries) is fetched on demand and held
in memory for the lifetime of the HA session. The cache starts empty and
is populated in one situation only: when the user opens the Configure
dialog (async_ensure_loaded is called by the options flow before rendering
the voice dropdown).

Voices are NOT fetched on HA startup. This avoids a gratuitous API call
on every restart. Since the cache is cleared on every HA restart, any
voices added by Cartesia will appear automatically the next time the user
opens Configure, with no explicit reload action needed.

The cache is intentionally simple: no TTL, no disk persistence.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .const import DOMAIN, VOICE_CACHE_KEY
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
        if not self._voices:
            await self.async_refresh()

    def get_voices_for_language(self, language: str) -> list[dict[str, Any]]:
        """Return voices whose language field starts with the given ISO code.

        Uses prefix matching so "en" matches both "en" and "en-US" if Cartesia
        ever adds dialect codes to voice objects.
        """
        return [
            v for v in self._voices
            if self._voice_supports_language(v, language)
        ]

    def get_all_voices(self) -> list[dict[str, Any]]:
        """Return a shallow copy of the full voice list."""
        return list(self._voices)

    def find_voice_by_id(self, voice_id: str) -> dict[str, Any] | None:
        """Return the voice dict for a given ID, or None if not found."""
        for v in self._voices:
            if v.get("id") == voice_id:
                return v
        return None

    def find_voice_by_name(self, name: str) -> dict[str, Any] | None:
        """Return the first voice whose name matches case-insensitively."""
        name_lower = name.lower()
        for v in self._voices:
            if v.get("name", "").lower() == name_lower:
                return v
        return None

    def search_voices(self, query: str, language: str | None = None) -> list[dict[str, Any]]:
        """Return voices whose name or description contains the query string.

        Optionally pre-filters by language before applying the text search.
        """
        query_lower = query.lower()
        results = []
        for v in self._voices:
            if language and not self._voice_supports_language(v, language):
                continue
            name = v.get("name", "").lower()
            description = v.get("description", "").lower()
            if query_lower in name or query_lower in description:
                results.append(v)
        return results

    def build_voice_options(
        self,
        language: str | None = None,
        search: str | None = None,
    ) -> dict[str, str]:
        """Return a {voice_id: voice_name} dict suitable for a UI selector.

        Applies optional language and text-search filters.
        """
        voices = self._voices

        if language:
            voices = [v for v in voices if self._voice_supports_language(v, language)]

        if search:
            search_lower = search.lower()
            voices = [
                v for v in voices
                if search_lower in v.get("name", "").lower()
                or search_lower in v.get("description", "").lower()
            ]

        return {v["id"]: v.get("name", v["id"]) for v in voices if "id" in v}

    def _voice_supports_language(self, voice: dict[str, Any], language: str) -> bool:
        """Return True if this voice's language field starts with the given code."""
        voice_lang = voice.get("language", "")
        if isinstance(voice_lang, str):
            return voice_lang.startswith(language)
        if isinstance(voice_lang, list):
            return any(lang.startswith(language) for lang in voice_lang)
        return False