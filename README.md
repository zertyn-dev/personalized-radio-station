# VibeFM

A tiny backend-first experiment for generating a VibeFM briefing.

Current flow:

```text
Google News + RSS/Atom feeds + Open-Meteo weather
        ↓
LiteLLM script generation
        ↓
LiteLLM TTS rendering
        ↓
episode.json + script.md + episode.mp3
```

The important part is that the AI layer is isolated in
`backend/src/personalized_radio_station/ai.py`, so the project can switch between
OpenRouter, OpenAI, Anthropic, Ollama, or anything else LiteLLM supports. TTS is
isolated separately in `backend/src/personalized_radio_station/tts.py`.

## Project Layout

```text
backend/   Python package, tests, config templates, lockfile, generated episodes
frontend/  Console-7 static prototype, styles, scripts, and fonts
```

## Setup

```bash
cd backend
uv sync
cp .env.example .env
# Optional, only if you want to edit backend provider/fallback settings:
cp config.example.yaml config.yaml
```

Radio stations are created in the UI and stored as vibes in SQLite. A vibe owns
the station name, RSS sources, host tone, host format, and episode length.
`config.yaml` is backend runtime config: AI/TTS provider settings plus fallback
locale/weather values used when the UI does not send them.

By default, `config.example.yaml` uses OpenRouter's Nitro route for
`openai/gpt-oss-20b` through LiteLLM:

```yaml
ai:
  model: "openrouter/openai/gpt-oss-20b:nitro"
  api_key_env: "OPENROUTER_API_KEY"
  max_tokens: 4000
  reasoning:
    effort: "low"
    exclude: true
```

Add the default LLM and TTS keys to `.env`:

```bash
OPENROUTER_API_KEY=...
ELEVENLABS_API_KEY=...
```

OpenRouter's model ID is `openai/gpt-oss-20b:nitro`; the config includes the
leading `openrouter/` so LiteLLM routes it through OpenRouter. The low reasoning
setting keeps enough output budget available for the final JSON script.

You can switch to a specific OpenRouter model by changing the model:

```yaml
ai:
  model: "openrouter/meta-llama/llama-3.3-70b-instruct"
  api_key_env: "OPENROUTER_API_KEY"
```

Or switch providers entirely while keeping the same application code:

```yaml
ai:
  model: "openai/gpt-4.1-mini"
  api_key_env: "OPENAI_API_KEY"
```

```yaml
ai:
  model: "anthropic/claude-3-5-haiku-latest"
  api_key_env: "ANTHROPIC_API_KEY"
```

```yaml
ai:
  model: "ollama/llama3.1"
  api_base: "http://localhost:11434"
```

Provider API keys are read from environment variables such as
`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, and
`ELEVENLABS_API_KEY`.

## Local API + Frontend

Run the API server:

```bash
cd backend
uv run python -m personalized_radio_station.web_server
```

In a second terminal, run the frontend:

```bash
pnpm install
pnpm dev:frontend
```

Then open the Console-7 frontend:

```text
http://127.0.0.1:5173
```

The frontend is static HTML/CSS/JS served by Vite. Tailwind runs through the
official Vite plugin, so the HTML links `frontend/src/tailwind.css` instead of
loading Tailwind from a browser CDN. Vite proxies `/api` to
`http://127.0.0.1:8765`, keeping the API and frontend dev servers separate.

The frontend can create saved vibes through `POST /api/vibes`, start real
playback through `POST /api/episodes`, listen to `GET /api/episodes/{id}/events`
with Server-Sent Events, and play generated audio segments through Web Audio as
soon as each segment is ready. Episodes write normal artifacts under
`backend/episodes/{episode_id}/`.

The opening is intentionally written as if the station was already on air and
you just tuned in. It should not start with a formal welcome.

Outputs are saved under `backend/episodes/`:

```text
backend/episodes/
  ep_20260509145245_6dfcbe44/
    sources.json
    episode.json
    script.md
    episode.wav or episode.mp3
    audio/
```

The file page can also save reusable vibes, which are radio stations stored in
SQLite. A vibe includes a name, default source presets, optional custom RSS
feeds, and host metadata for tone, voice gender, and solo/duo format. Default
source presets currently include Google News, Hacker News, TechCrunch, and
Product Hunt. When an episode is started from a vibe, that vibe's sources are
the station sources; backend config is not used as a hidden station playlist.
The backend exposes:

```text
GET  /api/vibes
POST /api/vibes
GET  /api/vibes/{id}
```

Create an episode from a saved vibe by passing its id:

```json
{
  "mode": "real",
  "vibe_id": "builder-radio-a1b2c3",
  "duration_minutes": 2
}
```

The web server stores vibes in `backend/vibefm.sqlite3` by default when run from
`backend/`. Override that path
by passing `db_path` to `personalized_radio_station.web_server.create_server()`
when embedding the API in tests or another local runner.

The file page also shows a debug timing log from the event stream. Each status,
script-ready, segment-ready, completion, or failure event includes
`elapsed_seconds`, which helps identify whether startup time is source fetching,
script generation, TTS, or audio playback scheduling.

Real mode uses the selected UI vibe for station settings, plus `config.yaml` and
`.env` from the current working directory for provider settings and secrets.

The frontend sends `"mode": "real"`. The server validates runtime requirements,
fetches the vibe's RSS/Atom feeds and Open-Meteo weather, generates the script
with the configured LiteLLM model, renders TTS with the configured provider,
emits `segment_ready` events as each TTS segment is written, and serves the
final stitched episode audio when complete.

## TTS

TTS is part of the real-mode API flow. A real episode request fetches sources,
creates a script, and renders speech.

```yaml
tts:
  enabled: true
  provider: "elevenlabs"
  model: "elevenlabs/eleven_turbo_v2_5"
  response_format: "mp3"
  api_key_env: "ELEVENLABS_API_KEY"
  single_voice: true
  primary_voice: "host"
  words_per_minute: 155
```

Add `ELEVENLABS_API_KEY` to `.env`. This goes through LiteLLM's `speech()` API.
By default every segment MP3 uses the same `primary_voice`, so stitched audio
sounds like one person speaking continuously. Voice values can be common mapped
names like `alloy`, or raw ElevenLabs voice IDs:

```yaml
tts:
  enabled: true
  provider: "elevenlabs"
  single_voice: true
  primary_voice: "host"
  voices:
    host:
      voice: "alloy"
      words_per_minute: 155
```

Duration targeting uses `words_per_minute` to estimate how many words the script
should contain. After TTS, `episode.json` stores the actual audio duration and
measured words per minute, which you can use to tune this value for your chosen
voice.

To avoid wasting tokens, the app only makes one length-correction LLM call, and
only when the first script is outside the target word range. Unlimited episodes
skip this correction.

The TTS interface is still provider-swappable. For OpenAI/Azure-style speech,
use the same LiteLLM speech path:

```yaml
tts:
  enabled: true
  provider: "litellm"
  model: "openai/gpt-4o-mini-tts"
  response_format: "wav"
  api_key_env: "OPENAI_API_KEY"
  voices:
    host:
      voice: "alloy"
      instructions: "Warm, conversational, casual morning radio host."
    anchor:
      voice: "onyx"
      instructions: "Clear, steady, professional news reader."
```

Piper is also wired as a local TTS provider:

```yaml
tts:
  enabled: true
  provider: "piper"
  piper_path: "piper"
  piper_model_path: "/path/to/voice.onnx"
```

## Cost Estimates

These are rough API-cost estimates for one 5 minute episode, last checked on
2026-05-09. Provider pricing changes, so treat this as a planning guide.

Assumptions:

- around 3,000 input tokens and 1,200 output tokens for the script
- around 750 spoken words, or 4,500-5,000 TTS characters
- no free tiers, credits, caching, Batch API discounts, taxes, or OpenRouter
  credit-purchase fees included

Simple 5 minute cost guide:

OpenAI TTS means `openai/gpt-4o-mini-tts` in the list below.

- `openai/gpt-4o-mini` + OpenAI TTS = ~$0.08 / 5 minutes. Cheap and good.
- `openai/gpt-4.1-mini` + OpenAI TTS = ~$0.08 / 5 minutes. Better script.
- `anthropic/claude-haiku-4.5` + OpenAI TTS = ~$0.08-$0.09 / 5 minutes. Better writing than most budget models.
- `anthropic/claude-sonnet-4.6` + OpenAI TTS = ~$0.10 / 5 minutes. Strong script quality.
- `openai/gpt-5.5` + OpenAI TTS = ~$0.13 / 5 minutes. Premium script, budget voice.
- `openai/gpt-4.1-mini` + ElevenLabs Flash/Turbo = ~$0.25-$0.30 / 5 minutes. Good script, better voice.
- `anthropic/claude-haiku-4.5` + ElevenLabs Flash/Turbo = ~$0.26-$0.31 / 5 minutes. Better writing, good voice.
- `anthropic/claude-sonnet-4.6` + ElevenLabs Flash/Turbo = ~$0.28-$0.33 / 5 minutes. Strong writing, good voice.
- `openai/gpt-5.5` + ElevenLabs Flash/Turbo = ~$0.30-$0.35 / 5 minutes. Premium script, good voice.
- `openai/gpt-4.1-mini` + ElevenLabs Multilingual v2/v3 = ~$0.45-$0.60 / 5 minutes. Budget script, premium voice.
- `anthropic/claude-haiku-4.5` + ElevenLabs Multilingual v2/v3 = ~$0.46-$0.61 / 5 minutes. Good balance.
- `anthropic/claude-sonnet-4.6` + ElevenLabs Multilingual v2/v3 = ~$0.48-$0.63 / 5 minutes. Premium-feeling brief.
- `openai/gpt-5.5` + ElevenLabs Multilingual v2/v3 = ~$0.50-$0.65 / 5 minutes. High-end cloud option.
- `openrouter/openrouter/auto` + ElevenLabs Multilingual v2/v3 = variable, often ~$0.46-$0.65 / 5 minutes. Check OpenRouter Activity.
- `ollama/...` + Piper = $0 API cost / 5 minutes. Local/offline; quality depends on your models.

Anthropic currently covers the script-generation side here, not TTS, so Claude
models need to be paired with OpenAI, ElevenLabs, Piper, or another speech
provider. Sources: [OpenAI pricing](https://openai.com/api/pricing/),
[OpenAI TTS model pricing](https://developers.openai.com/api/docs/models/gpt-4o-mini-tts),
[Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing),
[ElevenLabs API pricing](https://elevenlabs.io/pricing/api/),
[Google Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing), and
[OpenRouter Auto Router](https://openrouter.ai/docs/features/model-routing).

## Tests

```bash
cd backend
uv run python -m unittest discover -s tests
```

Tests use internal mock LLM/TTS providers for deterministic runs. Normal
programmatic generation rejects those mock providers unless the caller
explicitly opts in, so real usage goes through LiteLLM-backed providers such as
OpenRouter, OpenAI, Anthropic, or Ollama.

## What Is Intentionally Missing

- no user accounts
- no production auth
- no durable job queue

The current app is a local API and file-based test frontend. It is not hardened
as an internet-facing service.
# Handoff: Console-7 Personal AI Radio

## Overview

Console-7 is a tabletop radio for personal AI broadcast streams. The user "tunes" between **Vibes** (saved AI-generated stations) by turning a frequency knob; each Vibe is configured from RSS feeds, hosts/voices, and a casual↔professional tone. A timer knob sets a sleep duration, the POWER button starts the broadcast, and a recessed SETTINGS panel hinges open from above the grille for full station management.

The aesthetic is deliberately tactile — cream chassis, brass knobs, perforated grille, amber CRT-style display, subtle film-grain noise — meant to evoke a 70s-era home stereo component repurposed as an AI surface.

---

## About the design files

The files in this bundle are **design references created in HTML/CSS/React (via in-browser Babel)** — a working interactive prototype demonstrating the intended look and behavior. They are **not** production code to copy directly.

Your task is to **recreate this design in your target codebase's existing environment** (React + a real bundler, Vue, SwiftUI, native, etc.) using its established patterns, component library, and state management. If the project doesn't have an environment yet, choose what fits best (React + Vite + Tailwind/CSS Modules is a reasonable default for this kind of UI).

Treat the HTML as the **source of truth for visuals and interactions** — extract the design tokens, the layout math, the animation timings — but rebuild the components in idiomatic code for your stack.

## Fidelity

**High-fidelity.** Pixel-perfect mockup with final colors, typography, spacing, knob physics, animations, and state transitions. Recreate exactly — match the hex values, the radii, the easing curves, the drag-to-rotate behaviors. Every value here is intentional.

---

## Files in this bundle

```
frontend/
├── Console-7 Radio.html            ← static HTML entry
├── src/tailwind.css                ← Tailwind v4 CSS entry
├── vite.config.js                  ← frontend dev server + /api proxy
├── radio.jsx                       ← legacy React prototype, no longer loaded
├── styles.css                      ← legacy prototype styles
├── colors_and_type.css             ← shared font-face + token definitions
└── fonts/
    ├── geist-sans/                 ← Geist Sans (SIL OFL)
    └── plex-mono/                  ← IBM Plex Mono (SIL OFL)
```

To preview locally, run the Python API on `127.0.0.1:8765`, then run
`pnpm dev:frontend` and open `http://127.0.0.1:5173`.

---

## Layout — the device

The radio is a **fixed-width chassis (920 px)** centered on a near-black background (`#0e1015`). It scales down responsively via a CSS custom property (`--device-scale`) — 0.78 below 1000 px viewport, 0.6 below 760 px. The chassis has soft drop shadow and rounded corners; an antenna SVG protrudes from the top-right.

```
┌────────────────────────────────────────────────────────────┐
│              [SETTINGS push-button] (centered top)         │
│   ┌──────────────────────────────────────────────────┐     │
│   │  ⊙       ┌──────────────────────────────┐    ⊙   │     │  ← deck (top section)
│   │ TIMER    │  display + tuner strip       │   TUNE │     │
│   │ 10:50    └──────────────────────────────┘  96.0  │     │
│   └──────────────────────────────────────────────────┘     │
│   ┌──────────────────────────────────────────────────┐     │
│   │                                                  │     │
│   │           perforated grille (~440px tall)        │     │  ← grille (bottom section)
│   │           [POWER button centered]                │     │
│   │                                                  │     │
│   └──────────────────────────────────────────────────┘     │
│   VIBEFM       ●  BROADCASTING / STANDBY        SN-7042    │  ← footer
│                                                            │
│            [foot]                          [foot]          │  ← chassis feet
└────────────────────────────────────────────────────────────┘
```

### Top section ("deck")
- Cream chassis: `#e8d8b6` → `#d8c79a` linear gradient with inner shadow.
- Three columns: `130px | 1fr | 130px`, gap `22px`, padding `24px`.
- Left & right columns hold knobs (TIMER, TUNE) with mono labels below + readout.
- Center column is the **display** — dark amber CRT panel.

### Display
- Background: `#1a0e05` with inner radial vignette.
- Height ~104px, padding `12px 16px`, border-radius `6px`.
- Amber text colors: `--amber-hi: #ffd58a`, `--amber: #ffb347`, `--amber-deep: #c5803a`.
- Three rows:
  1. Eyebrow (`▸ ON AIR` / `STANDBY`) + power LED dot
  2. Station name or `XX.X FM` + timer readout (`10:50` or `— : —`)
  3. Tuner strip (frequency scale 88–108 with station markers)
- Behind everything: low-opacity (0.22) animated **frequency analyzer** (28 columns × 9 rows of amber cells).
- Overlay: scanline pattern (`repeating-linear-gradient`, 2px transparent / 1px black at 28% opacity, `mix-blend-mode: multiply`).
- Fonts: IBM Plex Mono throughout, with text-shadow for amber glow.

### Grille
- Background: dark warm brown `#3a2a1a` with bevel inset.
- **Perforated dot pattern**: CSS `radial-gradient` repeated as background, ~6px grid of small amber dots at low opacity.
- Holds the centered **POWER button** (large pushable circle).
- When SETTINGS is pressed, the grille panel hinges open along its top edge revealing the settings UI behind it (transform: rotateX with perspective).

### Footer strip
- Mono caption row inside the chassis: `VIBEFM` (left) · `● BROADCASTING / STANDBY` LED (center) · `SN-7042` (right).
- Bottom of chassis has two short cylindrical feet.

---

## Components

### `Knob`
Tactile rotary control. Drag vertically (or scroll) to rotate. Renders an SVG with:
- Brass bezel ring (`<radialGradient>` from `#f3e1b8` → `#a07a3a`)
- Inner cap (darker brass)
- 24 minute tick marks around the cap
- Indicator line from center to bezel edge, colored per knob
- Rotation range: **−135° to +135°** (270° sweep)

**Props:** `value`, `max`, `onChange(v)`, `color`, `size` (default 110), `label`.

**Drag behavior:** mousedown captures `clientY`, then on mousemove maps `dy * sensitivity` to `dvalue`. `sensitivity = max / 200` (200px drag = full sweep). Releases on mouseup. Wheel events also adjust value with smaller step.

**Below the knob:** mono label + numeric/text readout (`10:50`, `OFF`, `96.0`).

### `Analyzer`
Frequency bars visualizer. Grid of `columns × rows` cells (default 32×7).
- `useEffect` runs a `setInterval` at ~80ms cadence; updates a `levels` array with a perlin-ish bell curve weighted toward the center, scaled by `playing ? 1 : 0.15`.
- Each column lights `Math.round(level * rows)` cells from the bottom up.
- Top-most lit cell uses `.an-cell.hi` (brighter amber, glow); cells below use `.an-cell.lit` (standard amber). Unlit cells are dim brown.
- Cells have inner shadow + box-shadow glow when lit.

Used both as the standalone visualizer (not rendered in the final design) and as the **display backdrop** at 0.22 opacity behind the amber readout.

### `TunerStrip`
Horizontal frequency scale inside the display. Three stacked rows:
1. **Numbers row:** `90 95 100 105` evenly spaced, mono 8px, amber-deep.
2. **Tick rule:** thin top border with major ticks at every 5 MHz (taller, brighter) and minor ticks every 1 MHz. A **pointer** (small triangle on a 18px rod) sits at the current frequency, draggable along the rule to seek.
3. **Stations row:** each station shows as `● NAME` (3.5px dot + 7.5px mono label). Dot brightens to amber-hi when the strip is actively tuned to that station. Click any station to seek directly.

Pointer drag: pointerdown → captures rect → pointermove maps `clientX` to a frequency between `FREQ_MIN` (88.0) and `FREQ_MAX` (108.0).

### `Segmented`
Pill-shaped toggle group used throughout the settings UI.
- Container: `display: inline-flex`, gap `2px`, padding `2px`, background `rgba(0,0,0,0.06)`, border-radius `999px`.
- Buttons: 4px 10px padding, mono 9px, transparent until selected.
- Selected button: white background, drop shadow, dark text.

**Props:** `value`, `options: Array<[value, label]>`, `onChange(v)`.

### `RssChips`
Multi-RSS-feed input. Single text field + `+` button; pressing Enter or clicking the + commits the URL as a removable chip.
- Each chip: rounded pill (`border-radius: 999px`) with:
  - 5px amber dot indicator
  - domain extracted from URL (`new URL(u).hostname.replace(/^www\./, '')`) — falls back to raw input if not a valid URL
  - 18px circular `×` button (hovers to rust-orange fill)
- Duplicate URLs are silently rejected.
- Chip max-width 200px with text-overflow ellipsis; full URL shown via `title` attribute.

**Props:** `value: string[]`, `onChange(string[])`, `placeholder?`.

### `SettingsPanel`
Tabbed modal that appears when SETTINGS is pressed. Six tabs:
1. **VIBES** — list + edit existing stations
2. **+ NEW** — create a new vibe form
3. **API** — BYO API keys
4. **VOICES** — 6 factory voices with previews
5. **AUDIO** — 5-band EQ + processing toggles
6. **ABOUT** — device info

Tab bar: horizontal mono uppercase row across the top of the panel, active tab gets rust-orange underline.

### `StationsTab` (VIBES)
- **Top:** horizontal chip rail of all stations. Each chip: number + station name + `1H` (host count). Active chip inverts to dark.
- A dashed `+ NEW` chip at the end opens the Create Vibe tab.
- **Below:** 4-column form grid editing the selected station:
  - **NAME** (text)
  - **HOSTS** (Solo / Duo segmented)
  - **TONE** (Casual / Professional segmented)
  - **VOICES** (compact A: M/F + B: M/F; B greys when Solo)
  - **RSS · N** (RssChips, full width)
- Bottom-right: red **DELETE** button.

### `CreateVibeTab` (+ NEW)
Same form layout as the editor but for a new station. CREATE VIBE button at bottom; disabled until name + at least one RSS URL.

### Other settings tabs
- **API** — labeled key inputs (Anthropic, ElevenLabs, etc.) with show/hide.
- **VOICES** — grid of 6 voice cards (avatar circle, name, gender/style tags, ▸ preview button).
- **AUDIO** — 5 vertical EQ sliders (60Hz, 250Hz, 1kHz, 4kHz, 12kHz) + toggle rows (Normalize, Compressor, Spatial).
- **ABOUT** — device serial, firmware version, storage stats, factory reset link.

---

## Interactions & behavior

### Power
- Press POWER button → toggles `playing` boolean.
- ON: analyzer animates, display shows `▸ ON AIR` + station name + active timer countdown, footer LED lights.
- OFF: analyzer dims to ~15% activity, display shows `STANDBY`, timer reads `— : —`.

### Tuning
- **TUNE knob** sets `freqMHz` in 0.1 MHz steps from 88.0 to 108.0.
- **Tuner-strip pointer drag** does the same.
- **Click a station label** in the tuner strip → snaps to that station's `mhz`.
- "Tuned" detection: within 0.4 MHz of any station's `mhz` → display shows the station name; otherwise shows `XX.X FM`.

### Timer
- **TIMER knob** sets `timerSec` from 0 to 3600 (1 hour).
- Knob readout shows `MM:SS` or `OFF` when 0.
- When `playing && timerSec > 0`, a `setInterval` decrements every second; reaching 0 turns POWER off.

### Settings panel
- SETTINGS button is a pill-shaped push-button on the chassis, just above the grille. Click animates it pressing in (`transform: translateY(2px)` + shadow change), then triggers the grille hinge animation.
- **Grille hinge**: the perforated panel rotates open along its top edge (`transform-origin: top`, `transform: rotateX(-90deg)`, perspective `1200px`, easing `cubic-bezier(0.4, 0, 0.2, 1)`, 600ms).
- Behind the grille: the settings panel slides into place.
- A close button or pressing SETTINGS again reverses the animation.

### Chip rail (Vibes tab)
- Click any chip → selects that station for editing.
- Click `+ NEW` → switches to the Create Vibe tab.

### RSS chip input
- Type URL → press Enter or click `+`.
- Each chip × button removes that feed.

---

## State

Top-level state in the main `Radio` component:

```js
const [playing, setPlaying]     = useState(false);
const [freqMHz, setFreqMHz]     = useState(88.3);
const [timerSec, setTimerSec]   = useState(0);
const [stations, setStations]   = useState([]);
const [editingId, setEditingId] = useState("");
const [isOpen, setIsOpen]       = useState(false);  // settings panel
const [settingsTab, setSettingsTab] = useState("vibes");
```

### Station shape

```ts
type Station = {
  id: number;
  name: string;          // uppercase
  tag: string;           // optional tagline
  mhz: number;           // 88.0–108.0, unique per station
  hosts: 1 | 2;          // solo or duo
  voiceA: "M" | "F" | "N";
  voiceB: "M" | "F" | "N";
  tone: number;          // 0 = fully casual, 100 = fully professional (UI uses 25/75 binary)
  urls: string[];        // RSS feed URLs
  freq: "hourly" | "daily" | "continuous";
};
```

`length` (broadcast duration) was intentionally removed — vibes are always-on, no per-vibe timing.

### Derived
- `station = stations.find(s => Math.abs(s.mhz - freqMHz) < 0.4)` — currently tuned station, or null.
- `tuned = !!station` — whether display shows station name vs. raw frequency.

---

## Design tokens

### Colors

| Token | Hex | Usage |
|---|---|---|
| `--bg` | `#0e1015` | Page background |
| `--cream` | `#e8d8b6` | Chassis primary |
| `--cream-2` | `#d8c79a` | Chassis gradient end |
| `--cream-shadow` | `#b39b6a` | Chassis inner shadow |
| `--brass` | `#c5a572` | Knob bezel mid |
| `--brass-hi` | `#f3e1b8` | Knob bezel highlight |
| `--brass-lo` | `#a07a3a` | Knob bezel shadow |
| `--rust` | `#c5481e` | Settings underline, RSS dot, delete, accent |
| `--rust-deep` | `#9a3416` | Rust hover/pressed |
| `--ink` | `#1f160c` | Dark text on cream |
| `--ink-mid` | `#5a4630` | Mid text on cream |
| `--rule` | `#bda580` | Hairline rules on cream |
| `--rule-strong` | `#9a8158` | Stronger rules / borders |
| `--paper` | `#f5e7c6` | Light paper-cream for inputs |
| `--display-bg` | `#1a0e05` | CRT panel background |
| `--amber-hi` | `#ffd58a` | Brightest CRT text |
| `--amber` | `#ffb347` | Standard CRT text |
| `--amber-deep` | `#c5803a` | Dim CRT text / tuner numbers |
| `--grille` | `#3a2a1a` | Grille background |
| `--grille-hole` | `#c5a572` | Perforation dot color |

### Radii

`4px` (small chips, buttons), `6px` (display, panels), `10px` (chassis sections), `14px` (chassis outer), `999px` (pills, segmented).

### Shadows

```css
/* chassis outer */
0 30px 60px rgba(0,0,0,0.55), 0 8px 24px rgba(0,0,0,0.35)
/* sections */
inset 0 1px 0 rgba(255,255,255,0.4), inset 0 -1px 0 rgba(0,0,0,0.15)
/* display vignette */
inset 0 0 40px rgba(0,0,0,0.6)
/* knob raised */
0 2px 4px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.15)
/* amber glow */
0 0 6px rgba(255,179,71,0.55)
```

### Typography

- **Display/CRT readouts:** IBM Plex Mono, 18–22px, 600 weight, with text-shadow `0 0 6px rgba(255,179,71,0.7), 0 0 14px rgba(255,140,40,0.4)`.
- **Eyebrows / labels:** IBM Plex Mono, 9–10px, 600–700, uppercase, letter-spacing `0.3em`.
- **Settings body:** IBM Plex Mono throughout, 9.5–11px depending on context.
- **Tickers / numbers:** Plex Mono, 7.5–8px, slightly dimmer color.

Geist Sans is loaded but unused in the radio itself — kept available because the matching landing page uses it.

### Spacing

Internal grid follows 4px unit. Common values: `4 6 8 10 12 16 22 24` px.

---

## Animations & transitions

| Element | Property | Duration | Easing |
|---|---|---|---|
| POWER button press | `transform`, `box-shadow` | 80ms | `ease-out` |
| Settings push-button | `transform`, `box-shadow` | 100ms | `ease-out` |
| Grille hinge open/close | `transform: rotateX()` | 600ms | `cubic-bezier(0.4, 0, 0.2, 1)` |
| Power LED on/off | `background`, `box-shadow` | 200ms | linear |
| Analyzer cell update | `background`, `box-shadow` | 70ms | linear |
| Knob rotation | `transform: rotate()` | none (instant on drag) | — |
| Chip hover | `background`, `border-color` | 120ms | ease |
| Tuner pointer | follows pointer instantly | — | — |
| Settings tab change | content fades 150ms | 150ms | ease |

Analyzer interval: 80ms. Each tick generates a new bell-curve-weighted random level per column, capped at `1.0`.

---

## Assets

- **Fonts:** Geist Sans + IBM Plex Mono, self-hosted in `fonts/`. Both are SIL OFL — free to redistribute.
- **Antenna:** inline SVG (single white-cream line + small ball at base), positioned absolutely above the chassis top-right.
- **Noise overlay:** inline `<feTurbulence>` SVG as a base64 data URL, applied as a `background-image` at 10% opacity over the whole viewport. Adds subtle film grain.
- **Grille perforations:** pure CSS — `radial-gradient` repeated as background, no image asset.
- **Knob graphics:** pure SVG with radial gradients — no image asset.

---

## Implementation notes for porting

1. **Knob component:** the trickiest piece. Test drag, scroll, and keyboard (arrow keys) interactions; consider extracting into a reusable `<RotaryKnob>`. Use `Pointer Events`, not separate mouse/touch.
2. **Analyzer:** the current analyzer loop is inline in `Console-7 Radio.html`; keep the bell-curve weighting toward center columns or it looks uniformly noisy. Animation should use `requestAnimationFrame`.
3. **Grille hinge:** requires `perspective` on a parent and `transform-origin: top` on the grille. The settings panel must already be rendered behind the grille, not appear after — otherwise the reveal doesn't work.
4. **Display analyzer:** sits at `z-index: 0` inside `.display`; readout rows are `z-index: 2`; scanline overlay (`::before`) is `z-index: 3`. Keep this stack.
5. **Responsive scaling:** the chassis is fixed at 920px. The `--device-scale` variable on `:root` is a CSS-only zoom; consider real responsive layout for production (collapse to a single-column at small viewports).
6. **State persistence:** saved vibes come from the backend. Persist last-tuned `freqMHz` locally if desired.
7. **API integration:** RSS feeds, voice generation (TTS), and audio playback are wired through the local backend.
8. **Accessibility:** add ARIA labels to knobs (`role="slider"`, `aria-valuenow`, `aria-valuemin`, `aria-valuemax`), keyboard support (arrow keys = step, home/end = min/max), and a screen-reader-only text alternative for the analyzer.

---

## Default sources

New vibes start with source presets supplied by the backend: Google News,
Hacker News, TechCrunch, and Product Hunt. Custom RSS feeds can be added per
vibe in the UI.

---

## Questions?

The original conversation that produced this design is available in your project history. The HTML files in this bundle are runnable references — open them in a browser to see and interact with the design alongside your implementation.
