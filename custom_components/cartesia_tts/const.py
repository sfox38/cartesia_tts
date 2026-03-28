"""Constants for the Cartesia Sonic TTS integration.

All string literals used as config entry keys, attribute names, and API
parameters are defined here so they can be imported consistently across
the integration without risk of typos.
"""

# Integration domain. Must match the directory name under custom_components.
DOMAIN = "cartesia_tts"

# Cartesia REST API coordinates.
CARTESIA_API_BASE = "https://api.cartesia.ai"
CARTESIA_TTS_ENDPOINT = "/tts/bytes"
CARTESIA_VOICES_ENDPOINT = "/voices"
# Version header required on every Cartesia API request.
CARTESIA_API_VERSION = "2025-04-16"

# Keys used in config entry data (persistent, never shown to user after setup).
CONF_API_KEY = "api_key"

# Keys used in config entry options (user-editable via the Configure dialog).
CONF_MODEL = "model"
CONF_VOICE_ID = "voice_id"
CONF_VOICE_NAME = "voice_name"  # Human-readable name cached alongside voice_id.
CONF_LANGUAGE = "language"
CONF_SPEED = "speed"
CONF_VOLUME = "volume"
CONF_EMOTION = "emotion"

# Keys used in tts.speak service call options dict.
# These match CONF_* names intentionally so the same string works in both places.
ATTR_SPEED = "speed"
ATTR_VOLUME = "volume"
ATTR_EMOTION = "emotion"
ATTR_VOICE_ID = "voice_id"
ATTR_LANGUAGE = "language"
ATTR_MODEL = "model"

# Available Cartesia TTS models. Keys are API model_id values; values are
# human-readable labels shown in the config flow.
# sonic-2 was removed: its generation_config support was dropped after
# sonic-2-2025-03-07 and it offers no advantage over sonic-turbo.
MODELS = {
    "sonic-3": "Sonic 3 (recommended, 90ms latency, 42 languages)",
    "sonic-turbo": "Sonic Turbo (40ms latency, 15 languages, less emotive)",
}

# All 42 languages supported by sonic-3. English is listed first; the rest
# are sorted alphabetically by display name.
SONIC3_LANGUAGES = {
    "en": "English",
    "ar": "Arabic",
    "bn": "Bengali",
    "bg": "Bulgarian",
    "zh": "Chinese",
    "hr": "Croatian",
    "cs": "Czech",
    "da": "Danish",
    "nl": "Dutch",
    "fi": "Finnish",
    "fr": "French",
    "de": "German",
    "el": "Greek",
    "gu": "Gujarati",
    "he": "Hebrew",
    "hi": "Hindi",
    "hu": "Hungarian",
    "id": "Indonesian",
    "it": "Italian",
    "ja": "Japanese",
    "ka": "Georgian",
    "kn": "Kannada",
    "ko": "Korean",
    "ml": "Malayalam",
    "mr": "Marathi",
    "ms": "Malay",
    "no": "Norwegian",
    "pa": "Punjabi",
    "pl": "Polish",
    "pt": "Portuguese",
    "ro": "Romanian",
    "ru": "Russian",
    "sk": "Slovak",
    "es": "Spanish",
    "sv": "Swedish",
    "tl": "Tagalog",
    "ta": "Tamil",
    "te": "Telugu",
    "th": "Thai",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "vi": "Vietnamese",
}

# The 15 languages supported by sonic-turbo (subset of SONIC3_LANGUAGES).
TURBO_LANGUAGES = {
    "en": "English",
    "zh": "Chinese",
    "nl": "Dutch",
    "fr": "French",
    "de": "German",
    "hi": "Hindi",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "pl": "Polish",
    "pt": "Portuguese",
    "ru": "Russian",
    "es": "Spanish",
    "sv": "Swedish",
    "tr": "Turkish",
}

# Maps each model ID to its supported language dict. Used by the config flow
# to show only languages valid for the selected model.
LANGUAGES_BY_MODEL = {
    "sonic-3": SONIC3_LANGUAGES,
    "sonic-turbo": TURBO_LANGUAGES,
}

# Convenience alias used by tts.py for the full supported_languages list.
LANGUAGES = SONIC3_LANGUAGES

# All emotion values accepted by the Cartesia generation_config.emotion field
# for sonic-3 and sonic-turbo. Sorted alphabetically. The "neutral" value is
# included but omitted from the API payload (neutral = no emotion guidance).
SONIC3_EMOTIONS = [
    "affectionate",
    "agitated",
    "alarmed",
    "amazed",
    "angry",
    "anticipation",
    "anxious",
    "apologetic",
    "bored",
    "calm",
    "confident",
    "confused",
    "contemplative",
    "contempt",
    "content",
    "curious",
    "dejected",
    "determined",
    "disappointed",
    "disgusted",
    "distant",
    "elated",
    "enthusiastic",
    "envious",
    "euphoric",
    "excited",
    "flirtatious",
    "frustrated",
    "grateful",
    "guilty",
    "happy",
    "hesitant",
    "hurt",
    "insecure",
    "ironic",
    "joking/comedic",
    "mad",
    "melancholic",
    "mysterious",
    "neutral",
    "nostalgic",
    "outraged",
    "panicked",
    "peaceful",
    "proud",
    "rejected",
    "resigned",
    "sad",
    "sarcastic",
    "scared",
    "serene",
    "skeptical",
    "surprised",
    "sympathetic",
    "threatened",
    "tired",
    "triumphant",
    "trust",
    "wistful",
]

# Display labels for SONIC3_EMOTIONS, used in vol.In() so the config flow
# dropdown shows title-cased names while the stored/API value stays lowercase.
SONIC3_EMOTIONS_DISPLAY = {
    "affectionate": "Affectionate",
    "agitated": "Agitated",
    "alarmed": "Alarmed",
    "amazed": "Amazed",
    "angry": "Angry",
    "anticipation": "Anticipation",
    "anxious": "Anxious",
    "apologetic": "Apologetic",
    "bored": "Bored",
    "calm": "Calm",
    "confident": "Confident",
    "confused": "Confused",
    "contemplative": "Contemplative",
    "contempt": "Contempt",
    "content": "Content",
    "curious": "Curious",
    "dejected": "Dejected",
    "determined": "Determined",
    "disappointed": "Disappointed",
    "disgusted": "Disgusted",
    "distant": "Distant",
    "elated": "Elated",
    "enthusiastic": "Enthusiastic",
    "envious": "Envious",
    "euphoric": "Euphoric",
    "excited": "Excited",
    "flirtatious": "Flirtatious",
    "frustrated": "Frustrated",
    "grateful": "Grateful",
    "guilty": "Guilty",
    "happy": "Happy",
    "hesitant": "Hesitant",
    "hurt": "Hurt",
    "insecure": "Insecure",
    "ironic": "Ironic",
    "joking/comedic": "Joking/Comedic",
    "mad": "Mad",
    "melancholic": "Melancholic",
    "mysterious": "Mysterious",
    "neutral": "Neutral",
    "nostalgic": "Nostalgic",
    "outraged": "Outraged",
    "panicked": "Panicked",
    "peaceful": "Peaceful",
    "proud": "Proud",
    "rejected": "Rejected",
    "resigned": "Resigned",
    "sad": "Sad",
    "sarcastic": "Sarcastic",
    "scared": "Scared",
    "serene": "Serene",
    "skeptical": "Skeptical",
    "surprised": "Surprised",
    "sympathetic": "Sympathetic",
    "threatened": "Threatened",
    "tired": "Tired",
    "triumphant": "Triumphant",
    "trust": "Trust",
    "wistful": "Wistful",
}

# Default values used when no user preference has been set.
DEFAULT_MODEL = "sonic-3"
DEFAULT_LANGUAGE = "en"
DEFAULT_SPEED = 1.0
DEFAULT_VOLUME = 1.0
DEFAULT_EMOTION = "neutral"

# Cartesia API-enforced bounds for generation_config parameters.
SPEED_MIN = 0.6
SPEED_MAX = 1.5
VOLUME_MIN = 0.5
VOLUME_MAX = 2.0

# Key used to store the VoiceCache instance in hass.data.
VOICE_CACHE_KEY = "cartesia_voice_cache"