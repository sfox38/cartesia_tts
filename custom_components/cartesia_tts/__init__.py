"""Cartesia Sonic TTS - Home Assistant custom integration.

Provides a TTS (text-to-speech) platform backed by the Cartesia Sonic API.
Supports sonic-3 (90ms latency, 42 languages) and sonic-turbo (40ms latency,
15 languages), with per-call overrides for speed, volume, emotion, voice,
language, and model via the tts.speak service options dict.

SSML tags embedded in the message text are passed through to Cartesia as-is,
enabling inline control of emotion, speed, volume, and non-verbal sounds
such as [laughter].

Storage layout:
  entry.data    - {"api_key": "..."}  (never changes after setup)
  entry.options - model, language, voice_id, voice_name, speed, volume, emotion

hass.data layout:
  hass.data[DOMAIN][entry_id] = {
      "client":      CartesiaClient,
      "voice_cache": VoiceCache,
  }

Reload behaviour: options are read live from entry.options on every tts.speak
call, so no reload is triggered when the user changes settings. A full HA
restart is only needed after changing entry.data (i.e. the API key).
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CartesiaClient, CartesiaApiError
from .const import DOMAIN, CONF_API_KEY
from .voice_cache import VoiceCache

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["tts"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Cartesia TTS config entry.

    Called by HA when the integration is first added or after a restart.
    Creates the API client, validates the key, and registers the TTS platform
    entity. The voice cache is intentionally left empty at this point and
    populated lazily on first use (either via tts.speak or the Configure
    dialog) to avoid an unnecessary API call on every HA restart.

    Returns False (and logs an error) if the API key is rejected.
    """
    api_key = entry.data[CONF_API_KEY]
    session = async_get_clientsession(hass)
    client = CartesiaClient(api_key, session)

    try:
        await client.validate_api_key()
    except CartesiaApiError as err:
        _LOGGER.error("Cartesia TTS setup failed: %s", err)
        return False

    # Voice list is loaded lazily: on the first tts.speak call (via
    # async_get_voices) or when the user opens the Configure dialog.
    # This avoids an unnecessary API call on every HA restart.
    voice_cache = VoiceCache(hass, client)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "voice_cache": voice_cache,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Cartesia TTS config entry.

    Unregisters the TTS platform and removes the entry's data from hass.data.
    Called by HA when the integration is removed or HA is shutting down.
    """
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded