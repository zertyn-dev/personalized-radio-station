# CONSOLE-7 MVP — Design Spec

**Date:** 2026-05-09
**File under design:** `index.html`
**Scope:** Frontend UI only. No backend, no real RSS fetch, no TTS.

## Vision

A live radio station for ritual news consumption. The visitor lands on
`index.html` and is immediately tuned in. There is no play, skip, or pause.
The only interaction is *tuning* between six topic stations. The intent is to
minimize information overload — calm, steady, glanceable.

## Product surface

- **Audio mode:** Ambient hum loop only. No spoken voice.
- **Stations:** Six topic stations on a band from 88 to 108.
  - 88.0  TOP
  - 92.0  WORLD
  - 96.0  TECH
  - 100.0 BUSINESS
  - 104.0 SPORTS
  - 108.0 SCIENCE
- **Liveness:** A real ticking clock (UTC). Headlines are hardcoded mock data
  shaped like Google News RSS output (title, source, age) so swapping in a
  real fetch later is a one-line change.
- **Layout:** Wide broadcast console (Approach A from brainstorming).

## Architecture

A single self-contained `index.html`. Inline `<style>` and `<script>`,
matching the existing `radio.html` pattern. No build step, no dependencies
beyond the Google Fonts link already used in the project. The current
`radio.html` is preserved untouched as a reference.

```
index.html
  ├─ <style>          warm-metal palette, amber CRT, IBM Plex Mono
  ├─ <body>
  │    ├─ #tune-in    full-bleed splash (one-tap to start)
  │    ├─ .status     ON AIR · station+freq · UTC clock
  │    ├─ .ticker     amber CRT panel, slow horizontal scroll
  │    ├─ .band       6 frequency markers + sliding indicator
  │    └─ .meta       UNIT id · STATUS · ambient toggle
  └─ <script>         data, ticker engine, tuning, ambient
```

## Components

### Tune-in splash (`#tune-in`)
- Full-bleed overlay shown on every page load (no persistence — each
  visit asks the user to tune in fresh, which fits the ritual framing).
- Single tap target with the label `TUNE IN`.
- Required because browsers block audio autoplay without a user gesture.
- On tap: starts ambient audio, dismisses with a short CRT warm-up sweep
  (~400ms), reveals the console underneath.

### Status bar (`.status`)
- Top edge of the console.
- Contents: pulsing amber dot · `ON AIR` · current station name and
  frequency (e.g. `96.0 TECH`) · UTC clock formatted `HH:MM UTC`.
- Clock ticks every second using `Date.now()`.

### Ticker (`.ticker`)
- The centerpiece. A long amber-phosphor CRT panel.
- Renders the current station's headlines as one continuous string separated
  by ` · `, scrolling right-to-left at a slow constant speed (~30 seconds
  for a single headline to cross the visible area).
- Visual treatment: scan lines, slight glow, faint flicker — reuses tokens
  from `radio.html`.
- Respects `prefers-reduced-motion`: when set, the ticker advances by
  swapping headlines every ~10s instead of scrolling continuously.

### Tuning band (`.band`)
- Below the ticker.
- Six frequency tick marks at 88 / 92 / 96 / 100 / 104 / 108 with their
  topic labels (`TOP / WORLD / TECH / BIZ / SPORT / SCI`) below each.
- A glowing `◉` indicator slides between positions when the user tunes.
- Three input methods:
  - Click a frequency → tune to it.
  - Drag the indicator → tune to the nearest frequency on release.
  - Keyboard `←` / `→` → step to previous/next station.
- Tuning never wraps around: at 108 SCIENCE, `→` is a no-op; at 88 TOP, `←`
  is a no-op.

### Meta strip (`.meta`)
- Footer.
- Contents: `UNIT SN-7042 · STATUS LIVE · ambient ● on`.
- The ambient `●` indicator is clickable to mute/unmute. Keyboard shortcut
  `m` toggles the same.

## Data

A hardcoded JS object inline in `index.html`:

```js
const STATIONS = {
  top:      { freq: 88.0,  label: 'TOP',      headlines: [...] },
  world:    { freq: 92.0,  label: 'WORLD',    headlines: [...] },
  tech:     { freq: 96.0,  label: 'TECH',     headlines: [...] },
  business: { freq: 100.0, label: 'BUSINESS', headlines: [...] },
  sports:   { freq: 104.0, label: 'SPORTS',   headlines: [...] },
  science:  { freq: 108.0, label: 'SCIENCE',  headlines: [...] },
};
```

Each headline is `{ title, source, age }` — for example
`{ title: 'OpenAI ships GPT-5.5...', source: 'Reuters', age: '2h ago' }`.
Six to eight mock headlines per station, plausible for May 2026.

## Interactions

- **Tuning** updates the status bar, slides the indicator, and triggers a
  ~400ms amber "static sweep" across the ticker before the new station's
  headline string takes over.
- **Ambient toggle** swaps the `●` indicator state and starts/stops a single
  short looping audio file (warm hum / room tone). If the audio file is
  missing or fails to load, the toggle still works visually with no error
  UI — silent fallback.
- **No play, skip, or pause anywhere.** Tuning is the only available
  navigation.

## Aesthetic

Reuses `radio.html`'s palette tokens verbatim — `--cream`, `--crt-bg`,
`--crt-amber`, `--rust`, `--ink`, `--metal`, and friends — plus IBM Plex
Mono. Paper grain overlay on the body. Subtle bevels on metal panels using
the existing `--cream-shadow` / `--cream-edge` tokens. The ticker uses the
amber CRT with the scan-line and glow effects already defined in
`radio.html`. No new fonts, no new colors.

## Error handling

- Ambient audio file missing → silent fallback, indicator still toggles.
- No async fetches, no network errors to handle.
- Unsupported browser features (e.g. very old browsers without CSS custom
  properties) are out of scope.

## Testing

Manual visual verification in a modern browser:
- Open `index.html` directly from disk.
- Tune in, confirm ambient plays.
- Tune to each of the six stations via click, drag, and arrow keys.
- Confirm ticker swaps with the static-sweep transition.
- Confirm ambient toggles on/off via click and `m`.
- Confirm `prefers-reduced-motion` swap-mode by toggling the OS setting.

No automated tests. This is a static UI demo.

## Out of scope (explicit)

- Real RSS fetching from Google News (current MVP uses mock data).
- Any backend, serverless function, or build step.
- TTS / spoken voice broadcast.
- Multiple ambient beds, generative audio, or audio routing.
- Accessibility audit beyond keyboard tuning and reduced-motion support.
- Mobile-first redesign — the layout targets desktop first; mobile is a
  graceful degrade only.
- Replacing or modifying `radio.html` (it stays untouched as a reference).
