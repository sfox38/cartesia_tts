"""Cartesia Sonic TTS entity for Home Assistant.

Implements the TextToSpeechEntity interface so HA can call tts.speak
against Cartesia Sonic. Audio is always returned as MP3 at 44100 Hz.

Per-call overrides
------------------
All generation parameters can be overridden on a per-call basis by passing
an options dict to tts.speak:

    service: tts.speak
    target:
      entity_id: tts.cartesia_sonic_tts
    data:
      media_player_entity_id: media_player.living_room
      message: "Hello!"
      options:
        model: sonic-turbo
        voice_id: <uuid>
        language: fr
        speed: 1.2
        volume: 1.5
        emotion: excited

SSML passthrough
----------------
The message string is sent to Cartesia verbatim. Cartesia SSML tags
embedded in the text are honoured by the API, for example:
  <emotion value="angry"/> How dare you!
  <speed ratio="1.5"/> I speak quickly.
  [laughter] That is hilarious.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.tts import (
    ATTR_VOICE,
    TextToSpeechEntity,
    TtsAudioType,
    Voice,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    CONF_MODEL,
    CONF_VOICE_ID,
    CONF_LANGUAGE,
    CONF_SPEED,
    CONF_VOLUME,
    CONF_EMOTION,
    ATTR_SPEED,
    ATTR_VOLUME,
    ATTR_EMOTION,
    ATTR_VOICE_ID,
    ATTR_LANGUAGE,
    ATTR_MODEL,
    LANGUAGES,
    SONIC3_LANGUAGES,
    SONIC3_EMOTIONS,
    DEFAULT_MODEL,
    DEFAULT_LANGUAGE,
    DEFAULT_SPEED,
    DEFAULT_VOLUME,
    DEFAULT_EMOTION,
    SPEED_MIN,
    SPEED_MAX,
    VOLUME_MIN,
    VOLUME_MAX,
)
from .api import CartesiaClient, CartesiaApiError

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create and register the CartesiaTTSEntity for this config entry."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    client: CartesiaClient = data["client"]
    voice_cache = data["voice_cache"]

    async_add_entities([CartesiaTTSEntity(config_entry, client, voice_cache)])


class CartesiaTTSEntity(TextToSpeechEntity):
    """HA TTS entity backed by the Cartesia Sonic API.

    Generation parameters (model, voice, language, speed, volume, emotion)
    are read from config entry options on every call. No reload is needed
    when the user changes settings in the Configure dialog.

    The entity exposes all SONIC3_LANGUAGES as supported_languages so HA
    knows which language codes are valid when tts.speak is called with a
    language override.
    """

    _attr_has_entity_name = True
    _attr_name = "Cartesia Sonic TTS"

    def __init__(self, config_entry: ConfigEntry, client: CartesiaClient, voice_cache) -> None:
        self._config_entry = config_entry
        self._client = client
        self._voice_cache = voice_cache
        # Unique ID ties the entity to the config entry so HA can track it
        # across restarts and renames.
        self._attr_unique_id = f"{config_entry.entry_id}_tts"

    @property
    def default_language(self) -> str:
        """The language code configured as default in the options flow."""
        return self._config_entry.options.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)

    @property
    def supported_languages(self) -> list[str]:
        """All language codes supported by sonic-3 (the broadest model)."""
        return list(SONIC3_LANGUAGES.keys())

    @property
    def supported_options(self) -> list[str]:
        """Option keys accepted in the tts.speak options dict."""
        return [
            ATTR_VOICE_ID,
            ATTR_LANGUAGE,
            ATTR_MODEL,
            ATTR_SPEED,
            ATTR_VOLUME,
            ATTR_EMOTION,
        ]

    @property
    def default_options(self) -> dict[str, Any]:
        """Current config entry values exposed as default tts.speak options."""
        opts = self._config_entry.options
        return {
            ATTR_MODEL: opts.get(CONF_MODEL, DEFAULT_MODEL),
            ATTR_VOICE_ID: opts.get(CONF_VOICE_ID, ""),
            ATTR_LANGUAGE: opts.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
            ATTR_SPEED: opts.get(CONF_SPEED, DEFAULT_SPEED),
            ATTR_VOLUME: opts.get(CONF_VOLUME, DEFAULT_VOLUME),
            ATTR_EMOTION: opts.get(CONF_EMOTION, DEFAULT_EMOTION),
        }

    async def async_get_tts_audio(
        self,
        message: str,
        language: str,
        options: dict[str, Any] | None = None,
    ) -> TtsAudioType:
        """Synthesize speech and return (format, audio_bytes).

        Resolution order for each parameter:
          1. Value in options dict (per-call override)
          2. Value in config entry options (user default)
          3. Hard-coded default from const.py

        Speed and volume are clamped to Cartesia's accepted range to prevent
        API errors when values are passed outside bounds.

        Returns (None, None) on error so HA can handle the failure gracefully.
        """
        opts = options or {}
        config_opts = self._config_entry.options

        model = opts.get(ATTR_MODEL, config_opts.get(CONF_MODEL, DEFAULT_MODEL))
        voice_id = opts.get(ATTR_VOICE_ID, config_opts.get(CONF_VOICE_ID, ""))
        lang = opts.get(ATTR_LANGUAGE, language or config_opts.get(CONF_LANGUAGE, DEFAULT_LANGUAGE))
        speed = self._clamp(
            float(opts.get(ATTR_SPEED, config_opts.get(CONF_SPEED, DEFAULT_SPEED))),
            SPEED_MIN,
            SPEED_MAX,
        )
        volume = self._clamp(
            float(opts.get(ATTR_VOLUME, config_opts.get(CONF_VOLUME, DEFAULT_VOLUME))),
            VOLUME_MIN,
            VOLUME_MAX,
        )
        emotion = opts.get(ATTR_EMOTION, config_opts.get(CONF_EMOTION, DEFAULT_EMOTION))

        if not voice_id:
            _LOGGER.error("Cartesia TTS: no voice_id configured, cannot synthesize")
            return None, None

        _LOGGER.debug(
            "Cartesia TTS synthesize: model=%s voice=%s lang=%s speed=%s volume=%s emotion=%s",
            model, voice_id, lang, speed, volume, emotion,
        )

        try:
            audio_bytes = await self._client.synthesize(
                transcript=message,
                model=model,
                voice_id=voice_id,
                language=lang,
                speed=speed,
                volume=volume,
                emotion=emotion,
            )
            return "mp3", audio_bytes
        except CartesiaApiError as err:
            _LOGGER.error("Cartesia TTS synthesis failed: %s", err)
            return None, None

    async def async_get_voices(self, language: str) -> list[Voice] | None:
        """Return available voices for the given language code.

        Called by HA when the user browses voices in the UI. Falls back to
        all voices if none match the requested language (e.g. for languages
        not yet represented in the Cartesia library).
        """
        await self._voice_cache.async_ensure_loaded()
        voices = self._voice_cache.get_voices_for_language(language)
        if not voices:
            voices = self._voice_cache.get_all_voices()
        return [
            Voice(voice_id=v["id"], name=v.get("name", v["id"]))
            for v in voices
            if "id" in v
        ]

    def _clamp(self, value: float, min_val: float, max_val: float) -> float:
        """Clamp value to [min_val, max_val]."""
        return max(min_val, min(max_val, value))