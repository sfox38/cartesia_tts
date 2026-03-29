"""Config flow and options flow for the Cartesia Sonic TTS integration.

Initial setup flow (CartesiaTTSConfigFlow)
------------------------------------------
Three steps, each rendered as a separate HA dialog page:

  Step 1 - user:     Enter API key. Validates against Cartesia and fetches
                     the full voice list before advancing.
  Step 2 - model:    Choose sonic-3 or sonic-turbo. The selected model
                     determines which languages are available in step 3.
  Step 3 - settings: Choose language, speed, volume, and emotion defaults.
                     A radio at the bottom lets the user go back to step 2.
  Step 4 - voice:    Choose a default voice filtered by the selected language.
                     A radio at the bottom offers: save, or go back to settings.

Reconfigure flow (CartesiaTTSOptionsFlow)
-----------------------------------------
Same three-step structure as the setup flow but using the existing config
entry's options as pre-filled defaults. The API key is never re-requested.

Navigation rationale
--------------------
HA's config flow frontend caches selector options within a step. Re-rendering
the same step_id with different options does not update the dropdown. To
ensure language and voice dropdowns always reflect the chosen model/language,
each selection advances to a new step_id so HA renders a completely fresh form.

Form field naming
-----------------
Form fields use distinct names from storage keys (e.g. "select_model" in
the form vs "model" stored in entry.options). This prevents any confusion
between the intermediate form state and what is persisted. The _extract_*
helpers perform the translation before calling async_create_entry.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    SelectOptionDict,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import CartesiaClient, CartesiaAuthError, CartesiaApiError
from .const import (
    DOMAIN,
    CONF_API_KEY,
    CONF_MODEL,
    CONF_VOICE_ID,
    CONF_VOICE_NAME,
    CONF_LANGUAGE,
    CONF_SPEED,
    CONF_VOLUME,
    CONF_EMOTION,
    MODELS,
    LANGUAGES,
    LANGUAGES_BY_MODEL,
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

_LOGGER = logging.getLogger(__name__)

# Form field keys. These are separate from CONF_* storage keys so that
# intermediate form state cannot accidentally be confused with persisted data.
CONF_SELECT_MODEL = "select_model"
CONF_DEFAULT_LANGUAGE = "default_language"
CONF_DEFAULT_VOICE = "default_voice"
CONF_DEFAULT_SPEED = "default_speed"
CONF_DEFAULT_VOLUME = "default_volume"
CONF_DEFAULT_EMOTION = "default_emotion"


def _languages_for_model(model: str) -> dict[str, str]:
    """Return the language dict for a model, falling back to the full list."""
    return LANGUAGES_BY_MODEL.get(model, LANGUAGES)


def _safe_language(language: str, model: str) -> str:
    """Return language if valid for model, otherwise English."""
    langs = _languages_for_model(model)
    return language if language in langs else DEFAULT_LANGUAGE


def _voice_selector(voices: dict[str, str]) -> SelectSelector:
    """Build a dropdown SelectSelector from a {voice_id: voice_name} dict.

    Voices are sorted alphabetically by name. A sentinel "none" option is
    prepended so the user can submit without choosing a voice (which is then
    caught as a validation error).
    """
    options = [SelectOptionDict(value="none", label="-- No default voice --")]
    for vid, vname in sorted(voices.items(), key=lambda x: x[1]):
        options.append(SelectOptionDict(value=vid, label=vname))
    return SelectSelector(
        SelectSelectorConfig(
            options=options,
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


def _speed_selector() -> NumberSelector:
    """Slider for speed in the range supported by Cartesia generation_config."""
    return NumberSelector(
        NumberSelectorConfig(
            min=SPEED_MIN,
            max=SPEED_MAX,
            step=0.05,
            mode=NumberSelectorMode.SLIDER,
        )
    )


def _volume_selector() -> NumberSelector:
    """Slider for volume in the range supported by Cartesia generation_config."""
    return NumberSelector(
        NumberSelectorConfig(
            min=VOLUME_MIN,
            max=VOLUME_MAX,
            step=0.05,
            mode=NumberSelectorMode.SLIDER,
        )
    )


def _model_schema(default_model: str = DEFAULT_MODEL) -> vol.Schema:
    """Schema for the model selection step."""
    return vol.Schema(
        {
            vol.Required(CONF_SELECT_MODEL, default=default_model): vol.In(MODELS),
        }
    )


def _settings_schema(model: str, defaults: dict | None = None) -> vol.Schema:
    """Schema for the language/speed/volume/emotion step.

    Language options are filtered to only those supported by the selected
    model. If the previously saved language is not valid for the new model,
    it falls back to English.

    The voice_action radio at the bottom drives navigation:
      "continue" -> advance to the voice step
      "go_back"  -> return to the model step
    """
    d = defaults or {}
    languages = _languages_for_model(model)
    lang_default = _safe_language(d.get(CONF_DEFAULT_LANGUAGE, DEFAULT_LANGUAGE), model)
    return vol.Schema(
        {
            vol.Required(CONF_DEFAULT_LANGUAGE, default=lang_default): vol.In(languages),
            vol.Optional(CONF_DEFAULT_SPEED, default=d.get(CONF_DEFAULT_SPEED, DEFAULT_SPEED)): _speed_selector(),
            vol.Optional(CONF_DEFAULT_VOLUME, default=d.get(CONF_DEFAULT_VOLUME, DEFAULT_VOLUME)): _volume_selector(),
            vol.Optional(CONF_DEFAULT_EMOTION, default=d.get(CONF_DEFAULT_EMOTION, DEFAULT_EMOTION)): vol.In({e: e.title() for e in SONIC3_EMOTIONS}),
            vol.Required("voice_action", default="continue"): vol.In({
                "continue": "Continue to voice selection",
                "go_back": "Go back to model selection",
            }),
        }
    )


def _voice_schema(voices: dict[str, str], current_voice: str = "none") -> vol.Schema:
    """Schema for the voice selection step.

    The voice_action radio drives navigation:
      "save"     -> validate and persist (error shown if voice is still "none")
      "go_back"  -> return to settings step with values preserved
    """
    return vol.Schema(
        {
            vol.Optional(CONF_DEFAULT_VOICE, default=current_voice): _voice_selector(voices),
            vol.Optional("voice_action", default="save"): vol.In({
                "save": "Save selected voice",
                "go_back": "Go back to settings",
            }),
        }
    )


def _filter_voices_by_language(voices_raw: list[dict], language: str) -> dict[str, str]:
    """Filter a raw voice list to those matching the given ISO 639-1 language code.

    Matches exact codes ("en") and dialect variants ("en-US", "en-GB") but not
    unrelated codes that share a prefix ("eng" does not match "en").
    Returns {voice_id: voice_name}.
    """
    def _matches(voice_lang: str) -> bool:
        return voice_lang == language or voice_lang.startswith(language + "-")

    return {
        v["id"]: v.get("name", v["id"])
        for v in voices_raw
        if "id" in v and _matches(str(v.get("language", "")))
    }


class CartesiaTTSConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Initial setup wizard shown when the user adds the integration.

    State carried across steps:
      _api_key        - validated key, stored in entry.data on completion
      _voices_raw     - full voice list fetched after key validation
      _pending_model  - model chosen in step 2, used to filter languages in step 3
      _pending_settings - form values from step 3, used to build entry.options

    VERSION is incremented for breaking schema changes (requires migration).
    MINOR_VERSION is incremented for backwards-compatible additions (new
    optional keys with defaults). async_migrate_entry in __init__.py handles
    all migrations.
    """

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        self._api_key: str = ""
        self._voices_raw: list[dict] = []
        self._pending_model: str = DEFAULT_MODEL
        self._pending_settings: dict = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Step 1: API key entry.

        Validates the key against Cartesia and pre-fetches the voice list
        before advancing. A failed key shows an inline error without
        leaving the step.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            # Prevent duplicate entries. Since there is only one TTS entity
            # per installation, we use the domain as the unique ID.
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()

            api_key = user_input[CONF_API_KEY].strip()
            session = async_get_clientsession(self.hass)
            client = CartesiaClient(api_key, session)
            try:
                await client.validate_api_key()
                self._api_key = api_key
                self._voices_raw = await client.get_voices()
                return await self.async_step_model()
            except CartesiaAuthError:
                errors[CONF_API_KEY] = "invalid_auth"
            except CartesiaApiError as err:
                _LOGGER.error("Cartesia API error during setup: %s", err)
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_API_KEY): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))}
            ),
            errors=errors,
        )

    async def async_step_model(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Step 2: Model selection.

        Stores the chosen model in _pending_model and advances. The model
        is stored separately so the language step can filter its list.
        """
        if user_input is not None:
            self._pending_model = user_input.get(CONF_SELECT_MODEL, DEFAULT_MODEL)
            return await self.async_step_settings()

        return self.async_show_form(
            step_id="model",
            data_schema=_model_schema(self._pending_model),
            errors={},
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Step 3: Language, speed, volume, and emotion defaults.

        voice_action == "go_back" returns to the model step.
        voice_action == "continue" stores the values in _pending_settings
        and advances to the voice step.
        """
        if user_input is not None:
            if user_input.get("voice_action") == "go_back":
                return self.async_show_form(
                    step_id="model",
                    data_schema=_model_schema(self._pending_model),
                    errors={},
                )
            # Strip the navigation key before storing form values.
            self._pending_settings = {k: v for k, v in user_input.items() if k != "voice_action"}
            return await self.async_step_voice()

        return self.async_show_form(
            step_id="settings",
            data_schema=_settings_schema(self._pending_model, self._pending_settings),
            errors={},
            description_placeholders={"model": MODELS.get(self._pending_model, self._pending_model)},
        )

    async def async_step_voice(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Step 4: Voice selection.

        The voice dropdown is pre-filtered to voices matching the language
        chosen in step 3.

        voice_action == "go_back" -> return to step 3 with values preserved
        voice_action == "save" (default) -> validate voice and create entry
        """
        lang = self._pending_settings.get(CONF_DEFAULT_LANGUAGE, DEFAULT_LANGUAGE)
        filtered = _filter_voices_by_language(self._voices_raw, lang)
        lang_label = _languages_for_model(self._pending_model).get(lang, lang)

        if user_input is not None:
            action = user_input.get("voice_action", "save")

            if action == "go_back":
                return self.async_show_form(
                    step_id="settings",
                    data_schema=_settings_schema(self._pending_model, self._pending_settings),
                    errors={},
                    description_placeholders={"model": MODELS.get(self._pending_model, self._pending_model)},
                )

            voice_id = user_input.get(CONF_DEFAULT_VOICE, "none")
            if voice_id == "none":
                # User submitted without selecting a voice - show error.
                return self.async_show_form(
                    step_id="voice",
                    data_schema=_voice_schema(filtered),
                    errors={CONF_DEFAULT_VOICE: "voice_required"},
                    description_placeholders={"voice_count": str(len(filtered)), "language": lang_label},
                )

            # filtered is already {id: name} for the current language; fall back
            # to a full scan of _voices_raw if the voice isn't in the filtered set
            # (e.g. user typed an override ID not in the current language).
            all_voices = {**{v["id"]: v.get("name", v["id"]) for v in self._voices_raw if "id" in v}, **filtered}
            return self.async_create_entry(
                title="Cartesia Sonic TTS",
                data={CONF_API_KEY: self._api_key},
                options={
                    CONF_MODEL: self._pending_model,
                    CONF_LANGUAGE: lang,
                    CONF_VOICE_ID: voice_id,
                    CONF_VOICE_NAME: all_voices.get(voice_id, voice_id),
                    CONF_SPEED: float(self._pending_settings.get(CONF_DEFAULT_SPEED, DEFAULT_SPEED)),
                    CONF_VOLUME: float(self._pending_settings.get(CONF_DEFAULT_VOLUME, DEFAULT_VOLUME)),
                    CONF_EMOTION: self._pending_settings.get(CONF_DEFAULT_EMOTION, DEFAULT_EMOTION),
                },
            )

        return self.async_show_form(
            step_id="voice",
            data_schema=_voice_schema(filtered),
            errors={},
            description_placeholders={"voice_count": str(len(filtered)), "language": lang_label},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> CartesiaTTSOptionsFlow:
        """Return the options flow handler for the gear icon in the UI."""
        return CartesiaTTSOptionsFlow()


class CartesiaTTSOptionsFlow(config_entries.OptionsFlow):
    """Reconfigure flow shown when the user clicks Configure on the integration.

    Mirrors the setup flow structure but pre-fills all fields from the
    current entry.options. The API key is never re-requested.

    Note: HA injects self.config_entry automatically. Do not define __init__
    with self.config_entry = ... as this causes a 500 error in modern HA.

    State carried across steps:
      _pending_model    - model chosen in init step
      _pending_settings - form values from the settings step
    """

    def __init__(self) -> None:
        self._pending_model: str = DEFAULT_MODEL
        self._pending_settings: dict = {}

    async def _async_voices_raw(self) -> list[dict]:
        """Return the voice cache contents, loading from the API if empty.

        The cache is empty after a HA restart (startup fetch was removed to
        avoid unnecessary API calls). async_ensure_loaded fetches once on
        first use and is a no-op on subsequent calls.
        """
        if DOMAIN in self.hass.data and self.config_entry.entry_id in self.hass.data[DOMAIN]:
            voice_cache = self.hass.data[DOMAIN][self.config_entry.entry_id].get("voice_cache")
            if voice_cache is not None:
                await voice_cache.async_ensure_loaded()
                return voice_cache.get_all_voices()
        return []

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Step 1 (options): Model selection, pre-filled from current options."""
        current = self.config_entry.options
        self._pending_model = current.get(CONF_MODEL, DEFAULT_MODEL)

        if user_input is not None:
            self._pending_model = user_input.get(CONF_SELECT_MODEL, self._pending_model)
            return await self.async_step_settings()

        return self.async_show_form(
            step_id="init",
            data_schema=_model_schema(self._pending_model),
            errors={},
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Step 2 (options): Language and generation defaults, pre-filled from current options."""
        current = self.config_entry.options

        if user_input is not None:
            if user_input.get("voice_action") == "go_back":
                return self.async_show_form(
                    step_id="init",
                    data_schema=_model_schema(self._pending_model),
                    errors={},
                )
            self._pending_settings = {k: v for k, v in user_input.items() if k != "voice_action"}
            return await self.async_step_voice()

        defaults = {
            CONF_DEFAULT_LANGUAGE: current.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
            CONF_DEFAULT_SPEED: current.get(CONF_SPEED, DEFAULT_SPEED),
            CONF_DEFAULT_VOLUME: current.get(CONF_VOLUME, DEFAULT_VOLUME),
            CONF_DEFAULT_EMOTION: current.get(CONF_EMOTION, DEFAULT_EMOTION),
        }
        return self.async_show_form(
            step_id="settings",
            data_schema=_settings_schema(self._pending_model, defaults),
            errors={},
            description_placeholders={"model": MODELS.get(self._pending_model, self._pending_model)},
        )

    async def async_step_voice(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Step 3 (options): Voice selection filtered by the chosen language.

        The previously saved voice is pre-selected if the language hasn't
        changed. If the language has changed, the dropdown defaults to
        "-- No default voice --" so the user must make a new selection.

        If the current voice is not in the filtered list (e.g. it was added
        from a different language previously), it is injected into the options
        so it remains selectable.
        """
        current = self.config_entry.options
        voices_raw = await self._async_voices_raw()
        lang = self._pending_settings.get(CONF_DEFAULT_LANGUAGE, current.get(CONF_LANGUAGE, DEFAULT_LANGUAGE))
        prev_lang = current.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)
        filtered = _filter_voices_by_language(voices_raw, lang)
        lang_label = _languages_for_model(self._pending_model).get(lang, lang)

        current_voice_id = current.get(CONF_VOICE_ID, "")
        # Keep the current voice in the list only if the language hasn't changed.
        if lang == prev_lang and current_voice_id and current_voice_id not in filtered:
            filtered[current_voice_id] = current.get(CONF_VOICE_NAME, current_voice_id)
        default_voice = current_voice_id if (lang == prev_lang and current_voice_id) else "none"

        if user_input is not None:
            action = user_input.get("voice_action", "save")

            if action == "go_back":
                return self.async_show_form(
                    step_id="settings",
                    data_schema=_settings_schema(self._pending_model, self._pending_settings),
                    errors={},
                    description_placeholders={"model": MODELS.get(self._pending_model, self._pending_model)},
                )

            voice_id = user_input.get(CONF_DEFAULT_VOICE, "none")
            if voice_id == "none":
                return self.async_show_form(
                    step_id="voice",
                    data_schema=_voice_schema(filtered, default_voice),
                    errors={CONF_DEFAULT_VOICE: "voice_required"},
                    description_placeholders={"voice_count": str(len(filtered)), "language": lang_label},
                )

            all_voices = {**{v["id"]: v.get("name", v["id"]) for v in voices_raw if "id" in v}, **filtered}
            return self.async_create_entry(title="", data={
                CONF_MODEL: self._pending_model,
                CONF_LANGUAGE: lang,
                CONF_VOICE_ID: voice_id,
                CONF_VOICE_NAME: all_voices.get(voice_id, current.get(CONF_VOICE_NAME, voice_id)),
                CONF_SPEED: float(self._pending_settings.get(CONF_DEFAULT_SPEED, current.get(CONF_SPEED, DEFAULT_SPEED))),
                CONF_VOLUME: float(self._pending_settings.get(CONF_DEFAULT_VOLUME, current.get(CONF_VOLUME, DEFAULT_VOLUME))),
                CONF_EMOTION: self._pending_settings.get(CONF_DEFAULT_EMOTION, current.get(CONF_EMOTION, DEFAULT_EMOTION)),
            })

        return self.async_show_form(
            step_id="voice",
            data_schema=_voice_schema(filtered, default_voice),
            errors={},
            description_placeholders={"voice_count": str(len(filtered)), "language": lang_label},
        )