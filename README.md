# Cartesia Sonic TTS - Home Assistant Custom Integration

A Home Assistant custom integration that connects to the [Cartesia Sonic](https://cartesia.ai) text-to-speech API, giving HA access to Cartesia's library of 600+ voices across 42 languages with fine-grained control over speed, volume, and emotion.

> **Disclaimer:** This is an unofficial, community-developed integration. It is not affiliated with, endorsed by, or supported by Cartesia AI. For Cartesia API support, visit [cartesia.ai](https://cartesia.ai) or their [Discord](https://discord.gg/cartesia). For integration issues, please open a GitHub issue on this repository.

## Features

- Full `tts.speak` support in Home Assistant.
- Two Cartesia models: `sonic-3` (42 languages, 90ms latency) and `sonic-turbo` (15 languages, 40ms latency).
- 600+ voices filterable by language in the config UI.
- 59 emotion presets for expressive speech.
- Speed (0.6 to 1.5) and volume (0.5 to 2.0) controls.
- All generation parameters overridable per `tts.speak` call.
- SSML passthrough: embed Cartesia tags directly in message text.
- Lazy voice list loading: no API calls on HA restart.
- Config flow setup and reconfiguration entirely through the HA UI.

## Requirements

- Home Assistant 2025.x or later.
- A Cartesia API key. Sign up and create a free key at [play.cartesia.ai/keys](https://play.cartesia.ai/keys).

---

## Installation

> [!NOTE]
> Only one instance of the integration is supported. If you attempt to add it again, HA will show a message directing you to the Configure button on the existing entry.

### HACS (Recommended)

1. Open **HACS** in your Home Assistant sidebar.
2. Click the three-dot menu (top right) and choose **Custom repositories**.
3. Paste `https://github.com/sfox38/cartesia_tts` and select **Integration** as the category.
4. Click **Add**, then find **cartesia_tts** in the HACS Integration list and click **Download**
5. Restart Home Assistant.

### Manual Installation

1. Download the latest release zip from this repository and unpack it.
2. Copy the `cartesia_tts` folder into your `config/custom_components/` directory. The result should be `config/custom_components/cartesia_tts/`.
3. Restart Home Assistant.

---

## Setup Wizard

The initial setup wizard has four steps.

### Step 1: API Key

Enter your Cartesia API key. The integration validates it against the Cartesia API before continuing.

### Step 2: Model

Choose your default Cartesia model.

| Model | Latency | Languages | Emotion support |
|---|---|---|---|
| Sonic 3 (recommended) | 90ms | 42 | Full (59 emotions) |
| Sonic Turbo | 40ms | 15 | Full (59 emotions) |

### Step 3: Language and generation settings

Choose your default language, speed, volume, and emotion. The language list is filtered to only show languages supported by the model chosen in step 2.

Use the option at the bottom to go back to model selection if needed.

### Step 4: Voice

Choose your default voice. The dropdown shows only voices for the selected language. Voices are sorted alphabetically. Voice names include accent information where relevant (e.g. "Matilda - Australian Female").

Use the option at the bottom to go back to settings.

## Reconfiguring After Setup

Go to Settings -> Devices and Services -> Cartesia Sonic TTS -> Configure.

The Configure dialog follows the same three-step flow (model, settings, voice) with your current values pre-filled. The voice list is loaded from the in-memory cache. If the cache is empty (e.g. after a HA restart), it is fetched automatically when you reach the voice step - this may take several seconds.

---

## Using `tts.speak`

### Basic example

```yaml
service: tts.speak
target:
  entity_id: tts.cartesia_sonic_tts
data:
  media_player_entity_id: media_player.living_room
  message: "Hello from Cartesia."
```

### With per-call overrides

All generation parameters can be overridden for a single call via the `options` dict. Overrides take precedence over the defaults set in the Configure dialog.

```yaml
service: tts.speak
target:
  entity_id: tts.cartesia_sonic_tts
data:
  media_player_entity_id: media_player.living_room
  message: "This is urgent!"
  options:
    emotion: alarmed
    speed: 1.3
    volume: 1.5
```

### Override voice, language, or model for a single call

```yaml
service: tts.speak
target:
  entity_id: tts.cartesia_sonic_tts
data:
  media_player_entity_id: media_player.kitchen
  message: "Bonjour le monde."
  language: fr
  options:
    model: sonic-3
    voice_id: "ab636c8b-9960-4fb3-bb0c-b7b655fb9745"
```

### With SSML tags

Cartesia SSML tags can be embedded directly in the message text. They are passed to the API as-is and take precedence over any `options` values for the same parameter.

```yaml
message: "<emotion value='angry'/> How dare you speak to me like that!"
message: "<speed ratio='1.5'/> I like to talk fast."
message: "That is hilarious. [laughter] I cannot believe it."
message: "<volume ratio='1.5'/> This part is louder."
```

See the [Cartesia SSML documentation](https://docs.cartesia.ai/build-with-cartesia/sonic-3/ssml-tags) for the full tag reference.

---

## Options Reference

The following keys are accepted in the `options` dict of `tts.speak`:

| Key | Type | Description |
|---|---|---|
| `model` | string | `sonic-3` or `sonic-turbo` |
| `voice_id` | string | Cartesia voice UUID |
| `language` | string | ISO 639-1 language code (e.g. `en`, `fr`, `ja`) |
| `speed` | float | Speed multiplier. 0.6 slowest, 1.0 normal, 1.5 fastest |
| `volume` | float | Volume multiplier. 0.5 quietest, 1.0 normal, 2.0 loudest |
| `emotion` | string | Emotion name (see list below) |

---

## Supported Emotions

Emotions are guidance to the model, not strict transformations. Results vary by voice and transcript. For best results use one of Cartesia's recommended emotive voices (tagged "Emotive" in the [Cartesia voice library](https://play.cartesia.ai/voices)).

The primary emotions with the most training data are: `angry`, `content`, `excited`, `neutral`, `sad`, `scared`.

Full list (pass to the API or options dict):

affectionate, agitated, alarmed, amazed, angry, anticipation, anxious, apologetic, bored, calm, confident, confused, contemplative, contempt, content, curious, dejected, determined, disappointed, disgusted, distant, elated, enthusiastic, envious, euphoric, excited, flirtatious, frustrated, grateful, guilty, happy, hesitant, hurt, insecure, ironic, joking/comedic, mad, melancholic, mysterious, neutral, nostalgic, outraged, panicked, peaceful, proud, rejected, resigned, sad, sarcastic, scared, serene, skeptical, surprised, sympathetic, threatened, tired, triumphant, trust, wistful

---

## Supported Languages

### Sonic 3 (42 languages)

Arabic, Bengali, Bulgarian, Chinese, Croatian, Czech, Danish, Dutch, English, Finnish, French, Georgian, German, Greek, Gujarati, Hebrew, Hindi, Hungarian, Indonesian, Italian, Japanese, Kannada, Korean, Malay, Malayalam, Marathi, Norwegian, Polish, Portuguese, Punjabi, Romanian, Russian, Slovak, Spanish, Swedish, Tagalog, Tamil, Telugu, Thai, Turkish, Ukrainian, Vietnamese

### Sonic Turbo (15 languages)

Chinese, Dutch, English, French, German, Hindi, Italian, Japanese, Korean, Polish, Portuguese, Russian, Spanish, Swedish, Turkish

## Voice Dialects and Accents

The Cartesia API does not expose dialect codes (e.g. `en-AU`) in the synthesis request. Accent is a property of the voice itself. Many voices in the Cartesia library include accent information in their name (e.g. "Matilda - Australian Female"). Voice selection is effectively dialect selection.

---

## Troubleshooting

**"No voice_id configured"**: Open Configure and complete the voice selection step.

**Voice dropdown shows no voices**: Your API key may not have access to the Cartesia voice library. Check your account at [play.cartesia.ai](https://play.cartesia.ai).

**Emotion has no effect**: Not all voices respond well to emotion guidance. Try one of the recommended emotive voices from the Cartesia voice library (filter by "Emotive" tag).

**Wrong accent**: The language code alone does not control accent. Select a voice whose name or description matches your desired accent.

**SSML not working**: The message string must contain valid Cartesia SSML. Invalid or malformed tags are silently ignored by the Cartesia API.

**Voice Cache Behaviour**: The integration does not fetch the voice list on HA restart. The cache starts empty and is populated only when you open the Configure dialog and reach the voice selection step. This may take several seconds. Since the cache is only cleared on a HA restart, any voices Cartesia has added since your last session will appear automatically the next time you open Configure.

**No audio output or other unexpected behaviour**: Check Settings -> System -> Logs in the HA UI, or open /config/home-assistant.log. Error and warning messages from this integration are always logged at standard level with no configuration needed. If you need more detail (such as the exact request being sent to Cartesia), add the following to your configuration.yaml and restart HA:

```yaml
logger:
  logs:
    custom_components.cartesia_tts: debug
```
