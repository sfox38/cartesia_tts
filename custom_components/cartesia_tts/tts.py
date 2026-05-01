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

Option validation
-----------------
All options passed via tts.speak are validated before the API call.
Invalid values produce a WARNING log showing the received value, the
valid options, and the fallback being used. Synthesis still proceeds
using the configured default rather than failing the call entirely.
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
    SONIC3_LANGUAGES,
    SONIC3_EMOTIONS,
    MODELS,
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
from .api import CartesiaClient, CartesiaApiError, CartesiaQuotaError, CartesiaConcurrencyError, CartesiaPlanError

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


def _validate_options(
    opts: dict[str, Any],
    config_opts: dict[str, Any],
) -> dict[str, Any]:
    """Validate tts.speak options and return sanitised values.

    For each parameter, resolution order is:
      1. Value in opts (per-call override) - validated here
      2. Value in config_opts (user default from Configure dialog)
      3. Hard-coded DEFAULT_* constant

    Invalid overrides produce a WARNING and fall back to the configured
    default. Speed and volume are additionally clamped to the API bounds
    even when valid, since the config flow slider enforces this already
    but direct service calls bypass it.

    Returns a dict with keys: model, voice_id, language, speed, volume, emotion.
    All values are guaranteed to be safe to send to the API.
    """
    result: dict[str, Any] = {}

    # model
    if ATTR_MODEL in opts:
        val = opts[ATTR_MODEL]
        if val not in MODELS:
            fallback = config_opts.get(CONF_MODEL, DEFAULT_MODEL)
            _LOGGER.warning(
                "Cartesia TTS: invalid model %r. Valid options: %s. Using configured default %r.",
                val, list(MODELS.keys()), fallback,
            )
            result["model"] = fallback
        else:
            result["model"] = val
    else:
        result["model"] = config_opts.get(CONF_MODEL, DEFAULT_MODEL)

    # voice_id - check ATTR_VOICE_ID first, then ATTR_VOICE (HA voice picker)
    voice_raw = opts.get(ATTR_VOICE_ID) or opts.get(ATTR_VOICE)
    if voice_raw is not None:
        if not isinstance(voice_raw, str) or not voice_raw.strip():
            fallback = config_opts.get(CONF_VOICE_ID, "")
            _LOGGER.warning(
                "Cartesia TTS: invalid voice_id %r (must be a non-empty string). Using configured default.",
                voice_raw,
            )
            result["voice_id"] = fallback
        else:
            result["voice_id"] = voice_raw.strip()
    else:
        result["voice_id"] = config_opts.get(CONF_VOICE_ID, "")

    # language
    if ATTR_LANGUAGE in opts:
        val = opts[ATTR_LANGUAGE]
        if val not in SONIC3_LANGUAGES:
            fallback = config_opts.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)
            _LOGGER.warning(
                "Cartesia TTS: invalid language %r. Valid options: %s. Using configured default %r.",
                val, list(SONIC3_LANGUAGES.keys()), fallback,
            )
            result["language"] = fallback
        else:
            result["language"] = val
    else:
        result["language"] = config_opts.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)

    # speed - must be numeric, will be clamped to [SPEED_MIN, SPEED_MAX]
    if ATTR_SPEED in opts:
        try:
            val = float(opts[ATTR_SPEED])
            if val < SPEED_MIN or val > SPEED_MAX:
                clamped = max(SPEED_MIN, min(SPEED_MAX, val))
                _LOGGER.warning(
                    "Cartesia TTS: speed %s is outside the valid range [%s, %s]. Clamping to %s.",
                    val, SPEED_MIN, SPEED_MAX, clamped,
                )
                result["speed"] = clamped
            else:
                result["speed"] = val
        except (TypeError, ValueError):
            fallback = float(config_opts.get(CONF_SPEED, DEFAULT_SPEED))
            _LOGGER.warning(
                "Cartesia TTS: speed %r is not a valid number. Using configured default %s.",
                opts[ATTR_SPEED], fallback,
            )
            result["speed"] = fallback
    else:
        result["speed"] = float(config_opts.get(CONF_SPEED, DEFAULT_SPEED))

    # volume - must be numeric, will be clamped to [VOLUME_MIN, VOLUME_MAX]
    if ATTR_VOLUME in opts:
        try:
            val = float(opts[ATTR_VOLUME])
            if val < VOLUME_MIN or val > VOLUME_MAX:
                clamped = max(VOLUME_MIN, min(VOLUME_MAX, val))
                _LOGGER.warning(
                    "Cartesia TTS: volume %s is outside the valid range [%s, %s]. Clamping to %s.",
                    val, VOLUME_MIN, VOLUME_MAX, clamped,
                )
                result["volume"] = clamped
            else:
                result["volume"] = val
        except (TypeError, ValueError):
            fallback = float(config_opts.get(CONF_VOLUME, DEFAULT_VOLUME))
            _LOGGER.warning(
                "Cartesia TTS: volume %r is not a valid number. Using configured default %s.",
                opts[ATTR_VOLUME], fallback,
            )
            result["volume"] = fallback
    else:
        result["volume"] = float(config_opts.get(CONF_VOLUME, DEFAULT_VOLUME))

    # emotion
    if ATTR_EMOTION in opts:
        val = opts[ATTR_EMOTION]
        if val not in SONIC3_EMOTIONS:
            fallback = config_opts.get(CONF_EMOTION, DEFAULT_EMOTION)
            _LOGGER.warning(
                "Cartesia TTS: invalid emotion %r. Valid options: %s. Using configured default %r.",
                val, SONIC3_EMOTIONS, fallback,
            )
            result["emotion"] = fallback
        else:
            result["emotion"] = val
    else:
        result["emotion"] = config_opts.get(CONF_EMOTION, DEFAULT_EMOTION)

    return result


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
        """Initialise the TTS entity with the config entry, API client, and voice cache.

        The unique_id ties this entity to the config entry so HA can track it
        across restarts and renames.
        """
        self._config_entry = config_entry
        self._client = client
        self._voice_cache = voice_cache
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
            ATTR_VOICE,
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

        All options are validated before the API call. Invalid values produce
        a WARNING log and fall back to the configured default. Synthesis
        always proceeds unless voice_id is missing entirely.

        Returns (None, None) on error so HA can handle the failure gracefully.
        """
        opts = options or {}

        # If language comes from HA (not from options dict), inject it so
        # _validate_options can treat it as a per-call override.
        if ATTR_LANGUAGE not in opts and language:
            opts = {**opts, ATTR_LANGUAGE: language}

        validated = _validate_options(opts, self._config_entry.options)

        if not validated["voice_id"]:
            _LOGGER.error("Cartesia TTS: no voice_id configured, cannot synthesize")
            return None, None

        _LOGGER.debug(
            "Cartesia TTS synthesize: model=%s voice=%s lang=%s speed=%s volume=%s emotion=%s",
            validated["model"], validated["voice_id"], validated["language"],
            validated["speed"], validated["volume"], validated["emotion"],
        )

        try:
            audio_bytes = await self._client.synthesize(
                transcript=message,
                model=validated["model"],
                voice_id=validated["voice_id"],
                language=validated["language"],
                speed=validated["speed"],
                volume=validated["volume"],
                emotion=validated["emotion"],
            )
            return "mp3", audio_bytes
        except CartesiaQuotaError as err:
            _LOGGER.error(
                "Cartesia TTS: credit quota exhausted. Visit play.cartesia.ai to check your plan. (%s)",
                err,
            )
            return None, None
        except CartesiaConcurrencyError as err:
            _LOGGER.warning(
                "Cartesia TTS: concurrency limit reached, request dropped. (%s)", err
            )
            return None, None
        except CartesiaPlanError as err:
            _LOGGER.error(
                "Cartesia TTS: feature not available on current plan. (%s)", err
            )
            return None, None
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