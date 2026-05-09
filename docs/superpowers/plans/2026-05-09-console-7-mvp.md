# CONSOLE-7 MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the live ritual radio MVP at `index.html` — a single self-contained HTML file with six tunable Google-News-shaped topic stations, an amber CRT ticker, ambient hum, and no play/skip/pause controls.

**Architecture:** Single self-contained `index.html`. Inline `<style>` + `<script>` blocks, matching the existing `radio.html` pattern. No build step, no backend, no fetches. Mock headline data hardcoded inline. The current `radio.html` stays untouched as a reference. The current marketing-page `index.html` is preserved as `landing.html` before being replaced.

**Tech Stack:** Vanilla HTML / CSS / JS. Google Fonts (`IBM Plex Mono`). Web Audio via a single `<audio>` element. No frameworks, no bundlers, no dependencies.

**Spec:** `docs/superpowers/specs/2026-05-09-console-7-mvp-design.md`

**Verification model:** This is a static UI demo with no automated tests (per spec). Every task ends with a manual visual check by opening `index.html` directly in a modern browser. Each task ends with a commit.

---

## File Structure

- `index.html` — created fresh in Task 1, evolved task by task. Single file containing all CSS, JS, and HTML.
- `landing.html` — the current marketing page, renamed from `index.html` in Task 0 so it's not lost.
- `radio.html` — untouched. Reference for palette and CRT effects.
- `ambient.mp3` — optional; referenced in Task 7. If absent, the toggle works visually with silent fallback.

All work happens on the current `frontend` branch.

---

## Task 0: Preserve baseline and commit existing files

**Why:** The current `index.html` (the CONSOLE-7 marketing page) and `radio.html` are untracked. If we overwrite `index.html` without committing, the marketing page is lost. We rename the marketing page to `landing.html` so it remains accessible, and commit both files as the baseline before any changes.

**Files:**
- Move: `index.html` → `landing.html`
- Commit: `landing.html`, `radio.html`

- [ ] **Step 1: Rename existing index.html to landing.html**

```bash
git mv index.html landing.html 2>/dev/null || mv index.html landing.html
```

(If `git mv` fails because the file is untracked, the plain `mv` runs.)

- [ ] **Step 2: Stage and commit baseline files**

```bash
git add landing.html radio.html
git commit -m "chore: preserve marketing landing page as landing.html

Saves the current CONSOLE-7 marketing page so it remains accessible
while index.html is rebuilt as the live radio product per the MVP
spec."
```

- [ ] **Step 3: Verify state**

```bash
ls *.html
```

Expected output includes `landing.html` and `radio.html`, and no `index.html`.

```bash
git status
```

Expected: clean working tree.

---

## Task 1: Skeleton + design tokens

**Why:** Establish the file shell with the palette tokens copied verbatim from `radio.html`, the body grain overlay, and the empty container divs that subsequent tasks will fill in.

**Files:**
- Create: `index.html`

- [ ] **Step 1: Create `index.html` with the skeleton**

Write the full file content:

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>CONSOLE-7 — Live Personal Broadcast</title>
<meta name="description" content="A live, ritual radio station. Tune in. No play, no skip, no pause." />

<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">

<style>
:root {
  /* Palette — copied verbatim from radio.html */
  --cream:        #d9c7a3;
  --cream-light:  #e8d8b6;
  --cream-edge:   #efe2c4;
  --cream-deep:   #b39d76;
  --cream-shadow: #6f5f43;
  --plate:        #ebdcb8;
  --plate-deep:   #c2b08a;
  --recess:       #8a7c5e;
  --recess-deep:  #6b5d3f;

  --crt-bg:       #1c0e04;
  --crt-bg-2:     #2b1808;
  --crt-amber:    #ffb347;
  --crt-amber-hi: #ffd58a;
  --crt-amber-dim:#a25e16;

  --metal:        #b9a983;
  --metal-dark:   #877856;
  --rust:         #c5481e;
  --rust-deep:    #8d2f10;
  --screw:        #2c2418;
  --ink:          #221a10;
  --label-ink:    #2a2110;
  --label-mid:    #6b5c3f;

  --font-mono: "IBM Plex Mono", ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
}

* { box-sizing: border-box; }
html, body { height: 100%; margin: 0; }
body {
  font-family: var(--font-mono);
  color: var(--cream);
  background:
    radial-gradient(ellipse at 50% 30%, #2a1f14 0%, #14100a 70%),
    #0c0906;
  -webkit-font-smoothing: antialiased;
  font-variant-numeric: tabular-nums;
  overflow: hidden;
}

/* Page film grain — copied from radio.html */
.grain {
  position: fixed; inset: 0;
  pointer-events: none;
  z-index: 9999;
  opacity: 0.18;
  mix-blend-mode: multiply;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='240' height='240'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 0.15 0 0 0 0 0.1 0 0 0 0 0.05 0 0 0 1 0'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>");
}

/* Console — wide broadcast layout */
.console {
  height: 100vh;
  width: 100vw;
  display: grid;
  grid-template-rows: auto 1fr auto auto;
  gap: 24px;
  padding: 28px 40px 24px;
  max-width: 1600px;
  margin: 0 auto;
}

/* Placeholders for components (filled in by later tasks) */
.status,
.ticker,
.band,
.meta {
  border: 1px dashed rgba(255,179,71,0.18);
  min-height: 32px;
  color: var(--crt-amber-dim);
  font-size: 11px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  padding: 8px 12px;
}
.ticker { min-height: 200px; }
.band   { min-height: 110px; }
</style>
</head>
<body>
  <div class="grain" aria-hidden="true"></div>

  <main class="console" aria-label="Console-7 broadcast">
    <header class="status">[ status bar — task 2 ]</header>
    <section class="ticker">[ ticker — task 3 / 4 ]</section>
    <section class="band">[ tuning band — task 5 / 6 ]</section>
    <footer class="meta">[ meta strip — task 7 ]</footer>
  </main>

  <script>
    // Filled in by later tasks.
  </script>
</body>
</html>
```

- [ ] **Step 2: Open `index.html` in a browser and verify**

Run:

```bash
open /Users/pythagoras/Desktop/personalized-radio-station/index.html
```

Expected:
- Dark warm-brown vignette background fills the viewport.
- A subtle film-grain texture is visible.
- Four dashed amber placeholder boxes are stacked vertically, labelled with their task numbers.
- IBM Plex Mono is loaded (placeholders use it).

- [ ] **Step 3: Commit**

```bash
git add index.html
git commit -m "feat(radio): scaffold console-7 index.html with palette tokens

Single-file shell. Reuses radio.html palette verbatim. Sets up
a four-row grid (status / ticker / band / meta) with dashed
placeholders to be replaced in subsequent tasks."
```

---

## Task 2: Status bar

**Why:** The top edge of the console. Shows `ON AIR`, the active station, and a real ticking UTC clock. Also defines `state.activeStationId`, the single source of truth other tasks read from.

**Files:**
- Modify: `index.html`

- [ ] **Step 1: Replace the `.status` CSS placeholder block**

Find the placeholder block in `<style>`:

```css
/* Placeholders for components (filled in by later tasks) */
.status,
.ticker,
.band,
.meta {
  border: 1px dashed rgba(255,179,71,0.18);
  min-height: 32px;
  color: var(--crt-amber-dim);
  font-size: 11px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  padding: 8px 12px;
}
.ticker { min-height: 200px; }
.band   { min-height: 110px; }
```

Replace with:

```css
/* Shared placeholder (still used by ticker / band / meta until their tasks) */
.ticker, .band, .meta {
  border: 1px dashed rgba(255,179,71,0.18);
  min-height: 32px;
  color: var(--crt-amber-dim);
  font-size: 11px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  padding: 8px 12px;
}
.ticker { min-height: 200px; }
.band   { min-height: 110px; }

/* Status bar */
.status {
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 10px 18px;
  border-radius: 4px;
  background: linear-gradient(180deg, var(--plate) 0%, var(--plate-deep) 100%);
  color: var(--label-ink);
  box-shadow:
    inset 0 1px 0 rgba(255,235,190,0.55),
    inset 0 -1px 0 rgba(60,40,15,0.4),
    inset 0 0 0 1px rgba(60,40,15,0.35),
    0 6px 18px -6px rgba(0,0,0,0.6);
  font-size: 12px;
  letter-spacing: 0.22em;
  text-transform: uppercase;
}
.status .dot {
  width: 9px; height: 9px;
  border-radius: 50%;
  background: var(--rust);
  box-shadow: 0 0 10px rgba(197,72,30,0.85);
  animation: live-pulse 1.6s ease-in-out infinite;
}
.status .label-on-air { font-weight: 600; color: var(--rust-deep); }
.status .station {
  margin-left: auto;
  display: flex;
  gap: 14px;
  align-items: center;
}
.status .freq { font-weight: 600; }
.status .name { color: var(--label-mid); }
.status .clock {
  color: var(--label-ink);
  font-weight: 500;
  letter-spacing: 0.16em;
}
.status .sep { opacity: 0.45; }
@keyframes live-pulse {
  0%, 100% { opacity: 1; }
  50%      { opacity: 0.35; }
}
```

- [ ] **Step 2: Replace the `<header class="status">` markup**

Find:

```html
<header class="status">[ status bar — task 2 ]</header>
```

Replace with:

```html
<header class="status">
  <span class="dot" aria-hidden="true"></span>
  <span class="label-on-air">On Air</span>
  <span class="sep">·</span>
  <span class="station">
    <span class="freq" id="status-freq">96.0</span>
    <span class="name" id="status-name">TECH</span>
    <span class="sep">·</span>
    <span class="clock" id="status-clock">00:00 UTC</span>
  </span>
</header>
```

- [ ] **Step 3: Add the clock + initial state to `<script>`**

Find:

```html
<script>
  // Filled in by later tasks.
</script>
```

Replace with:

```html
<script>
  // ───── State ─────
  const state = {
    activeStationId: 'tech',  // default tune-in
  };

  // ───── Clock ─────
  function pad2(n) { return String(n).padStart(2, '0'); }
  function tickClock() {
    const d = new Date();
    const text = `${pad2(d.getUTCHours())}:${pad2(d.getUTCMinutes())} UTC`;
    document.getElementById('status-clock').textContent = text;
  }
  tickClock();
  setInterval(tickClock, 1000);
</script>
```

- [ ] **Step 4: Reload `index.html` in the browser and verify**

Refresh the open tab.

Expected:
- The top row is now a warm cream-metal bar with a pulsing rust dot, `ON AIR` in rust, then `96.0 TECH · HH:MM UTC`.
- The clock matches your current UTC time and ticks within one minute.
- The other three rows are still dashed placeholders.

- [ ] **Step 5: Commit**

```bash
git add index.html
git commit -m "feat(radio): add status bar with on-air dot and ticking UTC clock"
```

---

## Task 3: Ticker visual shell

**Why:** Build the amber CRT panel for the headline ticker — empty content for now, just nail the look (CRT background, scan lines, glow, inner shadow). Real headline data wires up in Task 4.

**Files:**
- Modify: `index.html`

- [ ] **Step 1: Add the ticker CSS**

In `<style>`, replace the line:

```css
.ticker, .band, .meta {
  border: 1px dashed rgba(255,179,71,0.18);
  min-height: 32px;
  color: var(--crt-amber-dim);
  font-size: 11px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  padding: 8px 12px;
}
.ticker { min-height: 200px; }
.band   { min-height: 110px; }
```

with:

```css
.band, .meta {
  border: 1px dashed rgba(255,179,71,0.18);
  min-height: 32px;
  color: var(--crt-amber-dim);
  font-size: 11px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  padding: 8px 12px;
}
.band { min-height: 110px; }

/* Ticker — amber CRT panel */
.ticker {
  position: relative;
  border-radius: 6px;
  padding: 0;
  overflow: hidden;
  background:
    radial-gradient(ellipse at 50% 30%, var(--crt-bg-2) 0%, var(--crt-bg) 65%, #0a0502 100%);
  box-shadow:
    inset 0 0 0 1px rgba(0,0,0,0.65),
    inset 0 6px 20px rgba(0,0,0,0.7),
    inset 0 -6px 20px rgba(0,0,0,0.6),
    0 12px 40px -10px rgba(0,0,0,0.7);
  display: flex;
  align-items: center;
  min-height: 200px;
}
/* Scan lines */
.ticker::before {
  content: "";
  position: absolute; inset: 0;
  pointer-events: none;
  background: repeating-linear-gradient(
    180deg,
    rgba(0,0,0,0.0) 0px,
    rgba(0,0,0,0.0) 2px,
    rgba(0,0,0,0.22) 3px,
    rgba(0,0,0,0.0) 4px
  );
  mix-blend-mode: multiply;
}
/* Vignette + amber glow halo */
.ticker::after {
  content: "";
  position: absolute; inset: 0;
  pointer-events: none;
  background:
    radial-gradient(ellipse at 50% 50%, rgba(255,179,71,0.08), transparent 60%),
    radial-gradient(ellipse at 50% 50%, transparent 55%, rgba(0,0,0,0.55) 100%);
}

.ticker-track {
  white-space: nowrap;
  font-size: 38px;
  line-height: 1;
  font-weight: 500;
  color: var(--crt-amber);
  text-shadow:
    0 0 6px rgba(255,179,71,0.55),
    0 0 18px rgba(255,140,40,0.25);
  padding: 0 32px;
  letter-spacing: 0.04em;
  will-change: transform;
}
.ticker-track .src {
  color: var(--crt-amber-dim);
  font-size: 24px;
  margin-left: 14px;
  margin-right: 8px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}
.ticker-track .age {
  color: var(--crt-amber-dim);
  font-size: 22px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  opacity: 0.75;
}
.ticker-track .gap {
  color: var(--crt-amber-dim);
  margin: 0 22px;
  opacity: 0.6;
}
```

- [ ] **Step 2: Replace the ticker markup**

Find:

```html
<section class="ticker">[ ticker — task 3 / 4 ]</section>
```

Replace with:

```html
<section class="ticker" aria-label="Now broadcasting">
  <div class="ticker-track" id="ticker-track">
    <span class="src">Reuters</span>OpenAI ships GPT-5.5 with 2M-token context<span class="age"> · 14m</span>
    <span class="gap">·</span>
    <span class="src">AP</span>Apple unveils on-device agent runtime at WWDC<span class="age"> · 1h</span>
  </div>
</section>
```

(This is placeholder content for visual verification only — Task 4 replaces it with the real engine.)

- [ ] **Step 3: Reload and verify**

Refresh the browser.

Expected:
- The middle row is now a deep CRT-brown panel with a soft amber halo and visible horizontal scan lines.
- The placeholder headline text glows amber, with smaller dim-amber `Reuters`/`AP` labels and `14m`/`1h` timestamps.
- The text overflows the right edge (it's not yet animated — that comes in Task 4).

- [ ] **Step 4: Commit**

```bash
git add index.html
git commit -m "feat(radio): add amber CRT ticker panel with scan lines and glow"
```

---

## Task 4: Mock data + scrolling ticker engine

**Why:** Wire the ticker to render the active station's headlines as a continuous, slowly scrolling track. This task introduces `STATIONS` (the data store) and the scroll engine, both of which Task 6 (tuning) and Task 9 (reduced-motion) will reuse.

**Files:**
- Modify: `index.html`

- [ ] **Step 1: Add the `STATIONS` data inside `<script>`**

In `<script>`, immediately after the line:

```js
const state = {
  activeStationId: 'tech',  // default tune-in
};
```

Add:

```js
// ───── Mock data (shape matches Google News RSS: title / source / age) ─────
const STATIONS = {
  top: {
    freq: 88.0, label: 'TOP',
    headlines: [
      { title: 'ICJ rules on coastal sovereignty claim', source: 'Reuters', age: '12m' },
      { title: 'Global heat record set for third year running', source: 'AP', age: '38m' },
      { title: 'Markets close mixed after Fed minutes', source: 'Bloomberg', age: '1h' },
      { title: 'Storm warnings issued across coastal regions', source: 'AP', age: '2h' },
      { title: 'UN reaches deal on plastic treaty draft', source: 'Reuters', age: '3h' },
      { title: 'Vaccine trial reports strong phase-3 results', source: 'NYT', age: '5h' },
    ],
  },
  world: {
    freq: 92.0, label: 'WORLD',
    headlines: [
      { title: 'EU finance ministers convene over budget rules', source: 'FT', age: '24m' },
      { title: 'Japan ruling coalition gains in by-elections', source: 'NHK', age: '1h' },
      { title: 'Argentina debt restructuring talks resume', source: 'Reuters', age: '2h' },
      { title: 'India approves new high-speed rail corridor', source: 'BBC', age: '3h' },
      { title: 'Kenya hosts climate adaptation summit', source: 'Al Jazeera', age: '4h' },
      { title: 'Norway sovereign fund posts record return', source: 'Bloomberg', age: '6h' },
    ],
  },
  tech: {
    freq: 96.0, label: 'TECH',
    headlines: [
      { title: 'OpenAI ships GPT-5.5 with 2M-token context', source: 'Reuters', age: '14m' },
      { title: 'Apple unveils on-device agent runtime at WWDC', source: 'AP', age: '1h' },
      { title: 'Anthropic releases Claude Opus 4.7 (1M context)', source: 'TechCrunch', age: '2h' },
      { title: 'Nvidia previews next-gen Rubin architecture', source: 'The Verge', age: '3h' },
      { title: 'GitHub launches multi-agent code review preview', source: 'Wired', age: '5h' },
      { title: 'Meta open-sources real-time vision encoder', source: 'IEEE Spectrum', age: '7h' },
    ],
  },
  business: {
    freq: 100.0, label: 'BUSINESS',
    headlines: [
      { title: 'S&P 500 closes flat as oil ticks higher', source: 'WSJ', age: '20m' },
      { title: 'Boeing reports first profitable quarter in years', source: 'Reuters', age: '1h' },
      { title: 'Stripe valuation reaches $110B in tender offer', source: 'Bloomberg', age: '2h' },
      { title: 'Container shipping rates ease on softer demand', source: 'FT', age: '3h' },
      { title: 'Yen strengthens after BOJ policy hint', source: 'Nikkei', age: '4h' },
      { title: 'Private credit funds raise record fresh capital', source: 'Bloomberg', age: '6h' },
    ],
  },
  sports: {
    freq: 104.0, label: 'SPORTS',
    headlines: [
      { title: 'Champions League final set after late-equaliser drama', source: 'BBC', age: '1h' },
      { title: 'NBA East semifinals go to game seven', source: 'ESPN', age: '2h' },
      { title: 'Formula 1: Verstappen takes pole in Imola', source: 'Sky Sports', age: '3h' },
      { title: 'Wimbledon seedings announced', source: 'Reuters', age: '4h' },
      { title: 'Olympic torch route revealed for 2028 LA Games', source: 'AP', age: '6h' },
      { title: 'Cricket: India clinches series in last over', source: 'Cricinfo', age: '8h' },
    ],
  },
  science: {
    freq: 108.0, label: 'SCIENCE',
    headlines: [
      { title: 'JWST detects organics in TRAPPIST-1e atmosphere', source: 'Nature', age: '30m' },
      { title: 'CRISPR therapy trial restores hearing in mice', source: 'Science', age: '2h' },
      { title: 'New superconductor stable at higher temps', source: 'Phys.org', age: '3h' },
      { title: 'Mars rover finds sulfate-rich layered rock', source: 'NASA', age: '5h' },
      { title: 'Quantum simulator scales to 10,000 qubits', source: 'Nature', age: '7h' },
      { title: 'Genome project maps full human variation', source: 'Cell', age: '12h' },
    ],
  },
};

const STATION_ORDER = ['top', 'world', 'tech', 'business', 'sports', 'science'];
```

- [ ] **Step 2: Add the ticker engine**

Append the following inside `<script>`, after the clock setup (after `setInterval(tickClock, 1000);`):

```js
// ───── Ticker engine ─────
//
// Renders the active station's headlines as a single horizontal track and
// scrolls it right-to-left at a constant pixel-per-second rate. We render
// the headlines twice back-to-back so the loop seam isn't visible. When the
// track scrolls one full copy width, we reset to 0 — the next copy starts
// flush, no flicker.
const TICKER_PX_PER_SEC = 60;  // ~30s for a long headline to cross
const ticker = {
  track: document.getElementById('ticker-track'),
  copyWidth: 0,
  offset: 0,
  lastTs: 0,
  reduced: false,  // wired up in task 9
};

function renderTicker() {
  const station = STATIONS[state.activeStationId];
  // Render the headline list twice for seamless looping
  const oneCopy = station.headlines.map(h =>
    `<span class="src">${h.source}</span>${h.title}<span class="age"> · ${h.age}</span>`
  ).join('<span class="gap">·</span>');
  ticker.track.innerHTML = oneCopy + '<span class="gap">·</span>' + oneCopy;
  ticker.offset = 0;
  ticker.track.style.transform = 'translateX(0)';
  // Measure one copy's width after layout
  requestAnimationFrame(() => {
    ticker.copyWidth = ticker.track.scrollWidth / 2;
  });
}

function tickerStep(ts) {
  if (!ticker.lastTs) ticker.lastTs = ts;
  const dt = (ts - ticker.lastTs) / 1000;
  ticker.lastTs = ts;
  if (!ticker.reduced && ticker.copyWidth > 0) {
    ticker.offset += TICKER_PX_PER_SEC * dt;
    if (ticker.offset >= ticker.copyWidth) ticker.offset -= ticker.copyWidth;
    ticker.track.style.transform = `translateX(${-ticker.offset}px)`;
  }
  requestAnimationFrame(tickerStep);
}

renderTicker();
requestAnimationFrame(tickerStep);
```

- [ ] **Step 3: Replace the placeholder ticker markup**

Find the placeholder track from Task 3:

```html
<section class="ticker" aria-label="Now broadcasting">
  <div class="ticker-track" id="ticker-track">
    <span class="src">Reuters</span>OpenAI ships GPT-5.5 with 2M-token context<span class="age"> · 14m</span>
    <span class="gap">·</span>
    <span class="src">AP</span>Apple unveils on-device agent runtime at WWDC<span class="age"> · 1h</span>
  </div>
</section>
```

Replace with:

```html
<section class="ticker" aria-label="Now broadcasting">
  <div class="ticker-track" id="ticker-track"></div>
</section>
```

(The script populates the track on load.)

- [ ] **Step 4: Reload and verify**

Refresh the browser.

Expected:
- The amber CRT panel now shows the TECH station's headlines scrolling slowly right-to-left.
- A single headline takes roughly half a minute to traverse.
- When the track wraps, there's no visible seam — the loop is continuous.
- The status bar still shows `96.0 TECH`.

- [ ] **Step 5: Commit**

```bash
git add index.html
git commit -m "feat(radio): wire mock station data and scrolling ticker engine"
```

---

## Task 5: Tuning band visual

**Why:** Render the band of six frequency markers below the ticker. Visual only — no interaction yet (Task 6 wires that up). Lays out the markers with their frequencies and topic labels and shows the glowing indicator on the active one.

**Files:**
- Modify: `index.html`

- [ ] **Step 1: Add the band CSS**

In `<style>`, replace the line:

```css
.band, .meta {
  border: 1px dashed rgba(255,179,71,0.18);
  min-height: 32px;
  color: var(--crt-amber-dim);
  font-size: 11px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  padding: 8px 12px;
}
.band { min-height: 110px; }
```

with:

```css
.meta {
  border: 1px dashed rgba(255,179,71,0.18);
  min-height: 32px;
  color: var(--crt-amber-dim);
  font-size: 11px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  padding: 8px 12px;
}

/* Tuning band */
.band {
  position: relative;
  border-radius: 6px;
  padding: 22px 28px 18px;
  background: linear-gradient(180deg, var(--plate) 0%, var(--plate-deep) 100%);
  box-shadow:
    inset 0 1px 0 rgba(255,235,190,0.55),
    inset 0 -1px 0 rgba(60,40,15,0.4),
    inset 0 0 0 1px rgba(60,40,15,0.35),
    0 6px 18px -6px rgba(0,0,0,0.6);
  user-select: none;
}
.band-rail {
  position: relative;
  height: 22px;
  margin: 6px 0 14px;
  border-radius: 11px;
  background:
    linear-gradient(180deg, var(--recess-deep) 0%, var(--recess) 100%);
  box-shadow:
    inset 0 1px 2px rgba(0,0,0,0.6),
    inset 0 -1px 0 rgba(255,225,180,0.15);
}
/* Tick marks along the rail */
.band-rail::before {
  content: "";
  position: absolute;
  left: 1.5%; right: 1.5%; top: 50%;
  height: 1px;
  background: repeating-linear-gradient(
    90deg,
    rgba(255,225,180,0.18) 0 1px,
    transparent 1px 24px
  );
  transform: translateY(-50%);
}
.band-marker {
  position: absolute;
  top: -4px;
  width: 30px;
  height: 30px;
  margin-left: -15px;
  border-radius: 50%;
  background:
    radial-gradient(circle at 30% 30%, var(--crt-amber-hi) 0%, var(--crt-amber) 35%, var(--crt-amber-dim) 75%, #5a3210 100%);
  box-shadow:
    inset 0 1px 0 rgba(255,235,190,0.7),
    0 0 14px rgba(255,179,71,0.55),
    0 0 28px rgba(255,140,40,0.35),
    0 2px 6px rgba(0,0,0,0.5);
  transition: left 220ms cubic-bezier(.6,.05,.3,1);
  cursor: grab;
  z-index: 2;
}
.band-marker:active { cursor: grabbing; }
.band-marker::after {
  content: "";
  position: absolute;
  left: 50%; top: 50%;
  width: 8px; height: 8px;
  margin: -4px 0 0 -4px;
  border-radius: 50%;
  background: rgba(40,18,4,0.55);
}

.band-stations {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 0;
  text-align: center;
  color: var(--label-ink);
  font-size: 11px;
  letter-spacing: 0.22em;
  text-transform: uppercase;
}
.band-stations .stop {
  position: relative;
  padding-top: 10px;
  cursor: pointer;
  color: var(--label-mid);
  transition: color 180ms ease;
}
.band-stations .stop:hover { color: var(--label-ink); }
.band-stations .stop.active { color: var(--rust-deep); }
.band-stations .stop .freq {
  display: block;
  font-size: 14px;
  font-weight: 600;
  color: var(--label-ink);
  letter-spacing: 0.1em;
  margin-bottom: 2px;
}
.band-stations .stop.active .freq {
  color: var(--rust-deep);
}
```

- [ ] **Step 2: Replace the band markup**

Find:

```html
<section class="band">[ tuning band — task 5 / 6 ]</section>
```

Replace with:

```html
<section class="band" aria-label="Tuning band">
  <div class="band-rail" id="band-rail">
    <div class="band-marker" id="band-marker" role="slider"
         tabindex="0"
         aria-label="Tuning"
         aria-valuemin="0" aria-valuemax="5" aria-valuenow="2"></div>
  </div>
  <div class="band-stations" id="band-stations">
    <button type="button" class="stop" data-id="top">      <span class="freq">88.0</span>  TOP</button>
    <button type="button" class="stop" data-id="world">    <span class="freq">92.0</span>  WORLD</button>
    <button type="button" class="stop active" data-id="tech"><span class="freq">96.0</span>  TECH</button>
    <button type="button" class="stop" data-id="business"> <span class="freq">100.0</span> BIZ</button>
    <button type="button" class="stop" data-id="sports">   <span class="freq">104.0</span> SPORT</button>
    <button type="button" class="stop" data-id="science">  <span class="freq">108.0</span> SCI</button>
  </div>
</section>
```

- [ ] **Step 3: Add the marker positioning script**

In `<script>`, append after the ticker engine block:

```js
// ───── Tuning band — visual positioning only (interactions in task 6) ─────
const band = {
  rail: document.getElementById('band-rail'),
  marker: document.getElementById('band-marker'),
  stations: document.getElementById('band-stations'),
};

function positionMarker() {
  const idx = STATION_ORDER.indexOf(state.activeStationId);
  // Six stations, six equal slots: align with the centers of the .stop columns
  const pct = ((idx + 0.5) / 6) * 100;
  band.marker.style.left = pct + '%';
  band.marker.setAttribute('aria-valuenow', String(idx));
}
positionMarker();
window.addEventListener('resize', positionMarker);
```

- [ ] **Step 4: Replace the unwanted dashed `<button>` outline (browsers add one)**

In `<style>`, find the `.band-stations .stop` rule and update to also reset the button defaults. Replace:

```css
.band-stations .stop {
  position: relative;
  padding-top: 10px;
  cursor: pointer;
  color: var(--label-mid);
  transition: color 180ms ease;
}
```

with:

```css
.band-stations .stop {
  position: relative;
  padding-top: 10px;
  cursor: pointer;
  color: var(--label-mid);
  transition: color 180ms ease;
  font-family: inherit;
  background: transparent;
  border: 0;
  letter-spacing: inherit;
  text-transform: inherit;
  font-size: inherit;
}
.band-stations .stop:focus-visible {
  outline: 2px solid var(--rust);
  outline-offset: 2px;
}
```

- [ ] **Step 5: Reload and verify**

Refresh the browser.

Expected:
- A warm cream-metal panel appears below the ticker.
- A dark recessed rail spans across with subtle tick marks.
- A glowing amber knob sits roughly above the third station (`96.0 TECH`).
- Six frequency labels (`88.0 TOP`, `92.0 WORLD`, `96.0 TECH`, `100.0 BIZ`, `104.0 SPORT`, `108.0 SCI`) are evenly spaced under the rail; `TECH` is in rust to indicate active.
- Buttons are not yet interactive — clicking does nothing.

- [ ] **Step 6: Commit**

```bash
git add index.html
git commit -m "feat(radio): add tuning band with six frequency markers"
```

---

## Task 6: Tuning interactions

**Why:** Make the band actually tune. Click a frequency, drag the marker, or use `←`/`→` to switch stations. Switching updates the status bar, slides the marker, retriggers the ticker with a brief amber static-sweep transition, and toggles the `.active` class on the station button.

**Files:**
- Modify: `index.html`

- [ ] **Step 1: Add the static-sweep CSS**

In `<style>`, append after the `.ticker-track ...` rules (after `.ticker-track .gap { ... }`):

```css
/* Static-sweep transition: a brief brightness/blur flash on the ticker
   when the user changes station. Triggered by adding .ticker--sweep. */
.ticker--sweep {
  animation: sweep-flash 400ms ease-in-out;
}
@keyframes sweep-flash {
  0%   { filter: brightness(1)   blur(0); }
  45%  { filter: brightness(1.7) blur(1.5px); }
  100% { filter: brightness(1)   blur(0); }
}
```

- [ ] **Step 2: Add the tuning logic**

In `<script>`, append after the `positionMarker` block:

```js
// ───── Tuning ─────
function tuneTo(stationId) {
  if (!STATIONS[stationId] || stationId === state.activeStationId) return;
  state.activeStationId = stationId;

  // Update status bar
  const s = STATIONS[stationId];
  document.getElementById('status-freq').textContent = s.freq.toFixed(1);
  document.getElementById('status-name').textContent = s.label;

  // Update active button
  band.stations.querySelectorAll('.stop').forEach(el => {
    el.classList.toggle('active', el.dataset.id === stationId);
  });

  // Slide the marker
  positionMarker();

  // Sweep + re-render ticker
  const t = document.querySelector('.ticker');
  t.classList.remove('ticker--sweep');
  // Force reflow so the animation can re-trigger
  void t.offsetWidth;
  t.classList.add('ticker--sweep');
  setTimeout(() => t.classList.remove('ticker--sweep'), 420);
  renderTicker();
}

// Click on a station label
band.stations.addEventListener('click', (e) => {
  const stop = e.target.closest('.stop');
  if (!stop) return;
  tuneTo(stop.dataset.id);
});

// Keyboard arrows — left / right step
window.addEventListener('keydown', (e) => {
  const idx = STATION_ORDER.indexOf(state.activeStationId);
  if (e.key === 'ArrowRight' && idx < STATION_ORDER.length - 1) {
    tuneTo(STATION_ORDER[idx + 1]);
    e.preventDefault();
  } else if (e.key === 'ArrowLeft' && idx > 0) {
    tuneTo(STATION_ORDER[idx - 1]);
    e.preventDefault();
  }
});

// Drag the marker — snaps to nearest station on release
(function setupDrag() {
  let dragging = false;
  let railRect = null;

  function pickStation(clientX) {
    const x = clientX - railRect.left;
    const ratio = Math.max(0, Math.min(1, x / railRect.width));
    const idx = Math.min(STATION_ORDER.length - 1, Math.max(0, Math.round(ratio * 6 - 0.5)));
    return STATION_ORDER[idx];
  }

  band.marker.addEventListener('pointerdown', (e) => {
    dragging = true;
    railRect = band.rail.getBoundingClientRect();
    band.marker.setPointerCapture(e.pointerId);
    band.marker.style.transition = 'none';
  });
  band.marker.addEventListener('pointermove', (e) => {
    if (!dragging) return;
    const x = e.clientX - railRect.left;
    const pct = Math.max(0, Math.min(100, (x / railRect.width) * 100));
    band.marker.style.left = pct + '%';
  });
  band.marker.addEventListener('pointerup', (e) => {
    if (!dragging) return;
    dragging = false;
    band.marker.style.transition = '';
    const target = pickStation(e.clientX);
    tuneTo(target);
    if (target === state.activeStationId) positionMarker(); // snap if already active
  });
  band.marker.addEventListener('pointercancel', () => {
    dragging = false;
    band.marker.style.transition = '';
    positionMarker();
  });
})();
```

- [ ] **Step 3: Reload and verify**

Refresh the browser.

Expected:
- Click `88.0 TOP`: status bar updates to `88.0 TOP`, marker glides left, the ticker briefly shows an amber sweep, then the TOP headlines scroll.
- Click each of the six in turn: each one tunes correctly.
- Press `→` repeatedly: tunes through `world` → `tech` → ... → `science`, then stops.
- Press `←` repeatedly: tunes back, stops at `top`.
- Drag the glowing knob along the rail and release between two stations: snaps to the nearest one.
- Active station's frequency label is highlighted in rust.

- [ ] **Step 4: Commit**

```bash
git add index.html
git commit -m "feat(radio): add click, drag, and keyboard tuning with static sweep"
```

---

## Task 7: Meta strip + ambient toggle

**Why:** Footer with `UNIT SN-7042 · STATUS LIVE · ambient ● on`. The ambient indicator toggles a single short looping audio file. If the file is missing, the toggle still works visually with no error UI. Keyboard `m` toggles the same.

**Files:**
- Modify: `index.html`

- [ ] **Step 1: Add the meta-strip CSS**

In `<style>`, replace the line:

```css
.meta {
  border: 1px dashed rgba(255,179,71,0.18);
  min-height: 32px;
  color: var(--crt-amber-dim);
  font-size: 11px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  padding: 8px 12px;
}
```

with:

```css
.meta {
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 8px 18px;
  border-radius: 4px;
  background: linear-gradient(180deg, var(--cream) 0%, var(--cream-deep) 100%);
  color: var(--label-ink);
  box-shadow:
    inset 0 1px 0 rgba(255,235,190,0.55),
    inset 0 -1px 0 rgba(60,40,15,0.4),
    inset 0 0 0 1px rgba(60,40,15,0.35);
  font-size: 11px;
  letter-spacing: 0.22em;
  text-transform: uppercase;
}
.meta .meta-item b { font-weight: 600; color: var(--label-ink); }
.meta .meta-item .label { color: var(--label-mid); margin-right: 6px; }
.meta .ambient {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: transparent;
  border: 0;
  font: inherit;
  letter-spacing: inherit;
  text-transform: inherit;
  color: var(--label-ink);
  cursor: pointer;
  padding: 4px 6px;
  border-radius: 3px;
}
.meta .ambient:focus-visible {
  outline: 2px solid var(--rust);
  outline-offset: 2px;
}
.meta .ambient .led {
  width: 9px; height: 9px;
  border-radius: 50%;
  background: var(--cream-shadow);
  box-shadow: inset 0 1px 1px rgba(0,0,0,0.4);
  transition: background 180ms, box-shadow 180ms;
}
.meta .ambient.on .led {
  background: var(--crt-amber);
  box-shadow:
    0 0 8px rgba(255,179,71,0.85),
    inset 0 1px 0 rgba(255,235,190,0.6);
}
```

- [ ] **Step 2: Replace the meta markup**

Find:

```html
<footer class="meta">[ meta strip — task 7 ]</footer>
```

Replace with:

```html
<footer class="meta">
  <span class="meta-item"><span class="label">Unit</span><b>SN-7042</b></span>
  <span class="meta-item"><span class="label">Status</span><b>Live</b></span>
  <span class="meta-item"><span class="label">Output</span><b>2.0 Stereo</b></span>
  <button type="button" class="ambient on" id="ambient-toggle" aria-pressed="true">
    <span class="led" aria-hidden="true"></span>
    <span><span class="label">Ambient</span><b id="ambient-state">On</b></span>
  </button>
  <audio id="ambient-audio" src="ambient.mp3" loop preload="auto"></audio>
</footer>
```

- [ ] **Step 3: Add the ambient toggle logic**

In `<script>`, append after the drag setup IIFE:

```js
// ───── Ambient audio ─────
const ambient = {
  audio: document.getElementById('ambient-audio'),
  btn:   document.getElementById('ambient-toggle'),
  state: document.getElementById('ambient-state'),
  on: true,
};

function setAmbient(on) {
  ambient.on = on;
  ambient.btn.classList.toggle('on', on);
  ambient.btn.setAttribute('aria-pressed', String(on));
  ambient.state.textContent = on ? 'On' : 'Off';
  if (on) {
    // Browsers may reject play() if there's no user gesture — that's fine,
    // the splash in task 8 ensures we always have one before this runs.
    const p = ambient.audio.play();
    if (p && typeof p.catch === 'function') p.catch(() => { /* silent */ });
  } else {
    ambient.audio.pause();
  }
}

ambient.btn.addEventListener('click', () => setAmbient(!ambient.on));
window.addEventListener('keydown', (e) => {
  if (e.key === 'm' || e.key === 'M') {
    setAmbient(!ambient.on);
    e.preventDefault();
  }
});
```

- [ ] **Step 4: Reload and verify**

Refresh the browser.

Expected:
- The footer is a warm cream metal strip showing `UNIT SN-7042 · STATUS LIVE · OUTPUT 2.0 STEREO` on the left, with `AMBIENT ● ON` on the right.
- The `●` LED glows amber when on.
- Click the ambient pill: LED dims, label flips to `OFF`. Click again: comes back on.
- Press `m`: toggles the same way.
- Browser console may log a play-promise rejection on first load (no user gesture yet) — silent failure is expected. Task 8 fixes this with the splash.

- [ ] **Step 5: Commit**

```bash
git add index.html
git commit -m "feat(radio): add meta strip and ambient audio toggle"
```

---

## Task 8: Tune-in splash

**Why:** Browsers block audio autoplay without a user gesture. The splash gates the experience: full-bleed amber overlay with a single `TUNE IN` tap target. Tapping starts ambient audio (now allowed because we have a gesture), dismisses the splash with a CRT warm-up sweep, and reveals the console.

**Files:**
- Modify: `index.html`

- [ ] **Step 1: Add the splash CSS**

In `<style>`, append at the end:

```css
/* Tune-in splash — full-bleed overlay, dismissed on first tap */
.tune-in {
  position: fixed; inset: 0;
  z-index: 9000;
  display: grid;
  place-items: center;
  background:
    radial-gradient(ellipse at 50% 50%, var(--crt-bg-2) 0%, var(--crt-bg) 60%, #0a0502 100%);
  cursor: pointer;
  transition: opacity 380ms ease, filter 380ms ease;
}
.tune-in::before {
  /* CRT scanlines while splash is up */
  content: "";
  position: absolute; inset: 0;
  pointer-events: none;
  background: repeating-linear-gradient(
    180deg,
    rgba(0,0,0,0.0) 0px,
    rgba(0,0,0,0.0) 2px,
    rgba(0,0,0,0.22) 3px,
    rgba(0,0,0,0.0) 4px
  );
  mix-blend-mode: multiply;
}
.tune-in .label {
  font-size: 14px;
  letter-spacing: 0.5em;
  text-transform: uppercase;
  color: var(--crt-amber-dim);
  margin-bottom: 18px;
}
.tune-in .cta {
  font-size: 88px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--crt-amber);
  text-shadow:
    0 0 12px rgba(255,179,71,0.6),
    0 0 32px rgba(255,140,40,0.35);
  font-weight: 600;
  user-select: none;
}
.tune-in .hint {
  margin-top: 22px;
  font-size: 11px;
  letter-spacing: 0.4em;
  text-transform: uppercase;
  color: var(--crt-amber-dim);
  opacity: 0.8;
  animation: live-pulse 2.2s ease-in-out infinite;
}
.tune-in.dismissing {
  opacity: 0;
  filter: brightness(2.4) blur(2px);
  pointer-events: none;
}
```

- [ ] **Step 2: Add the splash markup**

In `<body>`, immediately after the `<div class="grain" ...>` line, add:

```html
<div class="tune-in" id="tune-in" role="button" tabindex="0" aria-label="Tune in">
  <div>
    <div class="label">Console-7 · Personal Broadcast</div>
    <div class="cta">Tune In</div>
    <div class="hint">tap to begin</div>
  </div>
</div>
```

- [ ] **Step 3: Add the splash dismissal logic**

In `<script>`, append at the very end:

```js
// ───── Tune-in splash ─────
const splash = document.getElementById('tune-in');
function tuneIn() {
  splash.classList.add('dismissing');
  // Start ambient now that we have a user gesture
  setAmbient(true);
  setTimeout(() => splash.remove(), 420);
}
splash.addEventListener('click', tuneIn, { once: true });
splash.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault();
    tuneIn();
  }
}, { once: true });
```

- [ ] **Step 4: Reload and verify**

Refresh the browser.

Expected:
- A full-bleed dark CRT overlay appears immediately, with `CONSOLE-7 · PERSONAL BROADCAST` in dim amber, a giant glowing `TUNE IN` headline, and a pulsing `TAP TO BEGIN` hint.
- Click anywhere on the splash: the overlay flashes brighter, blurs, and fades, revealing the console underneath.
- Ambient audio starts playing (if `ambient.mp3` exists; silent if not).
- Reload the page: splash returns every time (no persistence).
- Tab to focus the splash and press Enter or Space: same dismissal.

- [ ] **Step 5: Commit**

```bash
git add index.html
git commit -m "feat(radio): add tune-in splash to satisfy autoplay gesture"
```

---

## Task 9: Reduced-motion handling

**Why:** Per spec, the ticker should respect `prefers-reduced-motion`. When the user has the OS setting enabled, the continuous scroll is replaced with a swap-every-10s mode that fades headlines in and out one at a time. This is also kinder on the GPU.

**Files:**
- Modify: `index.html`

- [ ] **Step 1: Add the reduced-motion CSS**

In `<style>`, append after the existing `.ticker--sweep` block:

```css
/* Reduced-motion swap mode — used when OS has prefers-reduced-motion: reduce */
.ticker.ticker--swap .ticker-track {
  transform: none !important;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  white-space: normal;
  padding: 0 48px;
  font-size: 30px;
  line-height: 1.25;
}
.ticker.ticker--swap .ticker-track .swap-headline {
  display: block;
  opacity: 0;
  transition: opacity 600ms ease;
}
.ticker.ticker--swap .ticker-track .swap-headline.shown {
  opacity: 1;
}
```

- [ ] **Step 2: Update the ticker engine to handle swap mode**

In `<script>`, find the `ticker` object and the `renderTicker` function. Replace the `ticker` object:

```js
const ticker = {
  track: document.getElementById('ticker-track'),
  copyWidth: 0,
  offset: 0,
  lastTs: 0,
  reduced: false,
};
```

with:

```js
const ticker = {
  track: document.getElementById('ticker-track'),
  panel: document.querySelector('.ticker'),
  copyWidth: 0,
  offset: 0,
  lastTs: 0,
  reduced: false,
  swapTimer: null,
  swapIdx: 0,
};
```

Then replace the entire `renderTicker` function:

```js
function renderTicker() {
  const station = STATIONS[state.activeStationId];
  const oneCopy = station.headlines.map(h =>
    `<span class="src">${h.source}</span>${h.title}<span class="age"> · ${h.age}</span>`
  ).join('<span class="gap">·</span>');
  ticker.track.innerHTML = oneCopy + '<span class="gap">·</span>' + oneCopy;
  ticker.offset = 0;
  ticker.track.style.transform = 'translateX(0)';
  requestAnimationFrame(() => {
    ticker.copyWidth = ticker.track.scrollWidth / 2;
  });
}
```

with:

```js
function renderTicker() {
  const station = STATIONS[state.activeStationId];
  if (ticker.reduced) {
    // Swap mode: render one headline at a time, fade between them.
    ticker.panel.classList.add('ticker--swap');
    ticker.swapIdx = 0;
    showSwapHeadline();
    if (ticker.swapTimer) clearInterval(ticker.swapTimer);
    ticker.swapTimer = setInterval(() => {
      ticker.swapIdx = (ticker.swapIdx + 1) % station.headlines.length;
      showSwapHeadline();
    }, 10000);
  } else {
    // Scroll mode: render twice for seamless looping.
    ticker.panel.classList.remove('ticker--swap');
    if (ticker.swapTimer) { clearInterval(ticker.swapTimer); ticker.swapTimer = null; }
    const oneCopy = station.headlines.map(h =>
      `<span class="src">${h.source}</span>${h.title}<span class="age"> · ${h.age}</span>`
    ).join('<span class="gap">·</span>');
    ticker.track.innerHTML = oneCopy + '<span class="gap">·</span>' + oneCopy;
    ticker.offset = 0;
    ticker.track.style.transform = 'translateX(0)';
    requestAnimationFrame(() => {
      ticker.copyWidth = ticker.track.scrollWidth / 2;
    });
  }
}

function showSwapHeadline() {
  const station = STATIONS[state.activeStationId];
  const h = station.headlines[ticker.swapIdx];
  const html = `<span class="swap-headline"><span class="src">${h.source}</span>${h.title}<span class="age"> · ${h.age}</span></span>`;
  ticker.track.innerHTML = html;
  // Fade in on next frame
  requestAnimationFrame(() => {
    const el = ticker.track.querySelector('.swap-headline');
    if (el) el.classList.add('shown');
  });
}
```

- [ ] **Step 3: Detect the OS preference**

In `<script>`, find the lines:

```js
renderTicker();
requestAnimationFrame(tickerStep);
```

Replace with:

```js
// Detect reduced-motion preference and re-render on changes
const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
function syncMotionPref() {
  ticker.reduced = motionQuery.matches;
  renderTicker();
}
syncMotionPref();
motionQuery.addEventListener('change', syncMotionPref);
requestAnimationFrame(tickerStep);
```

- [ ] **Step 4: Reload and verify (default)**

Refresh the browser with reduced-motion OFF (default macOS setting).

Expected:
- The ticker still scrolls horizontally as in Task 4.

- [ ] **Step 5: Verify reduced-motion mode**

Enable reduced motion:

- macOS: System Settings → Accessibility → Display → "Reduce motion" → On.

Refresh `index.html`.

Expected:
- The ticker no longer scrolls. One centered headline is visible at a time.
- Every ~10s, the headline fades out and a new one fades in.
- Tuning to a different station immediately swaps to that station's first headline; the swap timer continues from there.

Toggle the OS setting back off. (No refresh required — the page reacts via the `change` listener — but a refresh also works.)

- [ ] **Step 6: Commit**

```bash
git add index.html
git commit -m "feat(radio): respect prefers-reduced-motion with headline swap mode"
```

---

## Task 10: Final polish + visual checklist

**Why:** Walk through the spec one more time and confirm every requirement is visibly satisfied. Fix any small issues found and commit a "v1" milestone.

**Files:**
- Modify: `index.html` (only if issues found)

- [ ] **Step 1: Run the verification checklist**

Open `index.html` in a fresh browser tab. Walk through each line below and tick mentally — anything that fails, fix in `index.html` and re-verify.

- [ ] Splash appears on every page load (try a hard refresh).
- [ ] Splash dismisses on click and on Enter/Space; ambient starts playing (or fails silently if `ambient.mp3` is missing — no error UI).
- [ ] Status bar shows pulsing dot, `ON AIR`, `96.0 TECH`, and a UTC clock that ticks every second.
- [ ] Ticker scrolls right-to-left at a calm pace; the loop seam is invisible.
- [ ] Six stations visible on the band: 88 TOP, 92 WORLD, 96 TECH, 100 BIZ, 104 SPORT, 108 SCI.
- [ ] Click each frequency: status updates, marker glides, ticker sweeps amber and reloads with the new station's headlines.
- [ ] Drag the marker between two stops and release: snaps to the nearer one and tunes.
- [ ] `←` / `→` step through stations and stop cleanly at the ends (no wrap).
- [ ] Ambient pill: clicking toggles the LED and label; `m` does the same.
- [ ] No play, skip, or pause controls anywhere on the page.
- [ ] Reduced-motion OS setting flips the ticker into swap mode without a reload.
- [ ] Page is keyboard-navigable: Tab reaches the splash, then station buttons, then ambient pill; focus rings are visible (rust outline).
- [ ] No console errors when interacting normally.
- [ ] `radio.html` and `landing.html` still work and are unmodified.

- [ ] **Step 2: Sanity-check file count**

```bash
ls *.html
```

Expected: `index.html`, `landing.html`, `radio.html`. No others.

- [ ] **Step 3: Final commit**

If any fixes were made:

```bash
git add index.html
git commit -m "polish(radio): final visual pass on console-7 mvp"
```

If nothing was changed, skip the commit and instead tag the last commit:

```bash
git log --oneline -1
```

---

## Self-Review Notes

- **Spec coverage:** All six spec components are implemented (splash, status, ticker, band, meta), data shape matches RSS, ambient toggle plus `m`, no play/skip/pause anywhere, reduced-motion handled, palette tokens reused verbatim from `radio.html`, no backend, no fetch.
- **Out-of-scope items:** Honored — no real RSS, no TTS, no multiple ambient beds, no mobile-first redesign, no automated tests.
- **Type/identifier consistency:** `STATIONS`, `STATION_ORDER`, `state.activeStationId`, `tuneTo`, `renderTicker`, `setAmbient`, `tuneIn`, `ticker.reduced` — used consistently across tasks.
- **Placeholders:** None — every code block is complete, every command exact, every verification step concrete.
