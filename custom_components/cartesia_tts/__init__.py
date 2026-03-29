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

Voice list: fetched lazily when the user opens the Configure dialog, not on
startup. Any voices added by Cartesia appear automatically on the next
Configure session after an HA restart.

Schema versioning:
  VERSION 1 / MINOR_VERSION 1 - initial release
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CartesiaClient, CartesiaApiError, CartesiaAuthError
from .const import (
    DOMAIN,
    CONF_API_KEY,
    CONF_MODEL,
    CONF_LANGUAGE,
    CONF_VOICE_ID,
    CONF_VOICE_NAME,
    CONF_SPEED,
    CONF_VOLUME,
    CONF_EMOTION,
    DEFAULT_MODEL,
    DEFAULT_LANGUAGE,
    DEFAULT_SPEED,
    DEFAULT_VOLUME,
    DEFAULT_EMOTION,
)
from .voice_cache import VoiceCache

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["tts"]


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate config entry options to the current schema version.

    Called by HA when the stored VERSION or MINOR_VERSION is lower than the
    current values defined in CartesiaTTSConfigFlow.

    Migration strategy: always fill in any missing options keys with their
    defaults so old entries work with new code that expects new keys.
    Any future breaking changes should increment VERSION; non-breaking
    additions (new optional keys) should increment MINOR_VERSION only.

    Returns True on success, False if migration cannot be completed (which
    will disable the entry and prompt the user to reconfigure).
    """
    _LOGGER.debug(
        "Migrating Cartesia TTS config entry from version %s.%s",
        entry.version,
        entry.minor_version,
    )

    new_options = dict(entry.options)

    if entry.version == 1:
        # Fill in any options keys added after initial release.
        # As new keys are added in future versions, add them here with defaults.
        new_options.setdefault(CONF_MODEL, DEFAULT_MODEL)
        new_options.setdefault(CONF_LANGUAGE, DEFAULT_LANGUAGE)
        new_options.setdefault(CONF_VOICE_ID, "")
        new_options.setdefault(CONF_VOICE_NAME, "")
        new_options.setdefault(CONF_SPEED, DEFAULT_SPEED)
        new_options.setdefault(CONF_VOLUME, DEFAULT_VOLUME)
        new_options.setdefault(CONF_EMOTION, DEFAULT_EMOTION)

        hass.config_entries.async_update_entry(
            entry,
            options=new_options,
            minor_version=1,
        )

    _LOGGER.debug("Migration to version 1.1 complete")
    return True


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