const FREQ_MIN = 87.5;
const FREQ_MAX = 108.0;
const DURATION_MIN = 0;
const DURATION_MAX = 30;
const DEFAULT_BACKEND_BASE = "http://127.0.0.1:8765";
const ACTIVE_STATES = new Set(["starting", "generating", "playing"]);
const KEY_ENV_NAMES = {
  openrouter: "OPENROUTER_API_KEY",
  elevenlabs: "ELEVENLABS_API_KEY",
};

function loadStoredKeys() {
  const out = { openrouter: "", elevenlabs: "" };
  try {
    out.openrouter = localStorage.getItem("vibefm.keys.openrouter") || "";
    out.elevenlabs = localStorage.getItem("vibefm.keys.elevenlabs") || "";
  } catch {}
  return out;
}

function loadStoredStations() {
  try {
    const raw = localStorage.getItem("vibefm.stations");
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed) || parsed.length === 0) return null;
    return parsed;
  } catch {
    return null;
  }
}

function persistStations() {
  try {
    localStorage.setItem("vibefm.stations", JSON.stringify(state.stations));
  } catch {}
}

function persistKey(name, value) {
  try {
    if (value) localStorage.setItem(`vibefm.keys.${name}`, value);
    else localStorage.removeItem(`vibefm.keys.${name}`);
  } catch {}
}

function buildApiKeys() {
  const out = {};
  for (const [name, env] of Object.entries(KEY_ENV_NAMES)) {
    const value = (state.keys?.[name] || "").trim();
    if (value) out[env] = value;
  }
  return out;
}

const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
const pad = (value) => String(Math.floor(value)).padStart(2, "0");
const pad2 = (value) => String(value).padStart(2, "0");

const fallbackSourcePresets = [
  { id: "google_news", label: "Google News", url: "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en" },
  { id: "hacker_news", label: "Hacker News", url: "https://hnrss.org/frontpage" },
  { id: "techcrunch", label: "TechCrunch", url: "https://techcrunch.com/feed/" },
  { id: "product_hunt", label: "Product Hunt", url: "https://www.producthunt.com/feed" },
];

const fallbackStations = [
  ["DEEP FOCUS", "ambient lab loops", 88.3, "Pavilion 04 - Lake Theta"],
  ["LOFI MEMORY", "nostalgic recompositions", 91.4, "Camcorder Sun"],
  ["SOLAR DRIFT", "sun-warmed synthwave", 94.7, "Topanga FM"],
  ["NIGHTCREW", "midnight conversations", 98.1, "Late-shift roundtable"],
  ["ARCHIVE BLOOM", "found sound, restored", 101.9, "Lecture 7 recombined"],
  ["SIGNAL / NOISE", "experimental cuts", 104.6, "Generator Alpha"],
  ["LONG WAVE", "drone meditation", 107.2, "Thalassa"],
].map(([name, tag, mhz, track], index) => ({
  id: `factory-${index + 1}`,
  backendId: null,
  name,
  tag,
  mhz,
  hosts: 1,
  voiceA: "F",
  voiceB: "M",
  tone: 25,
  urls: [],
  sourcePresetIds: fallbackSourcePresets.map((preset) => preset.id),
  tracks: [track],
}));

const state = {
  freqMHz: fallbackStations[0].mhz,
  volume: 72,
  durationSec: 0,
  remainingSec: 0,
  mode: "mock",
  apiBase: defaultApiBase(),
  apiStatus: "checking",
  playerState: "idle",
  playerText: "STANDBY",
  segmentProgress: { queued: 0, played: 0, total: 0 },
  generationComplete: false,
  stations: fallbackStations,
  sourcePresets: fallbackSourcePresets,
  editingId: fallbackStations[0].id,
  settingsOpen: false,
  settingsTab: "vibes",
  keys: { openrouter: "", elevenlabs: "" },
};

const playback = {
  audioContext: null,
  gainNode: null,
  eventSource: null,
  sourceRefs: [],
  activeApiBase: "",
  nextStartTime: 0,
  runId: 0,
};

const els = {};
let frequencyDial;
let durationDial;
let analyzerColumns = [];
let barVisualizerColumns = [];
let analyzerLevels = [];
let barVisualizerLevels = [];
let apiCheckTimer = null;
let tunerDragging = false;
let durationPulseTimer = null;

function defaultApiBase() {
  if (window.location.protocol === "http:" || window.location.protocol === "https:") {
    return window.location.origin;
  }
  return DEFAULT_BACKEND_BASE;
}

function cleanApiBase(value) {
  return String(value || "").trim().replace(/\/+$/, "");
}

async function requestJson(apiBase, path, options = {}) {
  const response = await fetch(`${cleanApiBase(apiBase)}${path}`, options);
  const text = await response.text();
  let body = {};
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = { error: text };
    }
  }
  if (!response.ok) {
    const error = new Error(body.error || `Request failed: ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return body;
}

async function requestJsonFromAnyApi(primaryApiBase, path, options = {}) {
  let lastError = null;
  const bases = [cleanApiBase(primaryApiBase), DEFAULT_BACKEND_BASE].filter(
    (base, index, list) => base && list.indexOf(base) === index,
  );
  for (const base of bases) {
    try {
      return { data: await requestJson(base, path, options), apiBase: base };
    } catch (error) {
      lastError = error;
      if (error?.status && ![404, 405, 501].includes(error.status)) break;
    }
  }
  throw lastError || new Error("API request failed");
}

function frequencyForIndex(index) {
  const saved = [88.3, 91.4, 94.7, 98.1, 101.2, 104.6, 106.8, 107.6];
  if (index < saved.length) return saved[index];
  return Math.round((88.1 + (((index - saved.length + 1) * 1.7) % 19.2)) * 10) / 10;
}

function stationFromVibe(vibe, index) {
  const hostFormat = vibe.host_format || vibe.host?.format || "solo";
  const voiceGender = vibe.voice_gender || vibe.host?.voice_gender || "female";
  const sourceCount = (vibe.rss_feeds || []).length;
  return {
    id: vibe.id,
    backendId: vibe.id,
    name: String(vibe.name || "VIBE").toUpperCase(),
    tag: sourceCount ? `${sourceCount} sources` : "default sources",
    mhz: frequencyForIndex(index),
    hosts: hostFormat === "duo" ? 2 : 1,
    voiceA: voiceGender === "male" ? "M" : "F",
    voiceB: voiceGender === "male" ? "F" : "M",
    tone: vibe.tone === "professional" ? 75 : 25,
    urls: vibe.custom_rss_feeds || [],
    sourcePresetIds: vibe.source_preset_ids || [],
    tracks: ["Saved personal vibe"],
  };
}

function vibePayloadFromStation(station) {
  return {
    name: String(station.name || "VIBE").trim() || "VIBE",
    custom_rss_feeds: station.urls || [],
    source_preset_ids: station.sourcePresetIds || [],
    tone: station.tone >= 50 ? "professional" : "casual",
    voice_gender: station.voiceA === "M" ? "male" : "female",
    host_format: station.hosts === 2 ? "duo" : "solo",
  };
}

function styleFromStation(station) {
  const tone =
    station.tone >= 50
      ? "professional, crisp, source-aware radio with confident framing"
      : "casual, warm, already-on-air radio with useful pacing";
  const hostLabel = station.hosts === 2 ? "two-host handoff" : "solo host";
  const voiceLabel = station.voiceA === "M" ? "male-led" : "female-led";
  return `${tone}; ${voiceLabel}; ${hostLabel}`;
}

function rssFeedsFromStation(station) {
  const selected = new Set(station.sourcePresetIds || []);
  const presetUrls = (state.sourcePresets || [])
    .filter((preset) => selected.has(preset.id))
    .map((preset) => preset.url);
  return Array.from(new Set([...presetUrls, ...(station.urls || [])]));
}

function episodePayloadFromStation(station) {
  const durationMinutes = Math.max(1, Math.round(state.durationSec / 60));
  if (station.backendId) {
    return {
      mode: state.mode,
      vibe_id: station.backendId,
      replace_topics: true,
      replace_rss_feeds: true,
      duration: `${durationMinutes} minutes`,
      duration_minutes: durationMinutes,
    };
  }
  return {
    mode: state.mode,
    station_name: station.name,
    style: styleFromStation(station),
    rss_feeds: rssFeedsFromStation(station),
    replace_topics: true,
    replace_rss_feeds: true,
    source_preset_ids: station.sourcePresetIds || [],
    host_tone: station.tone >= 50 ? "professional" : "casual",
    voice_gender: station.voiceA === "M" ? "male" : "female",
    host_format: station.hosts === 2 ? "duo" : "solo",
    duration: `${durationMinutes} minutes`,
    duration_minutes: durationMinutes,
  };
}

function humanStatus(status) {
  return (
    {
      queued: "QUEUED",
      checking_runtime: "CHECKING",
      fetching_sources: "SOURCES",
      generating_script: "SCRIPTING",
      rendering_audio: "RENDERING",
      audio_disabled: "NO AUDIO",
      complete: "COMPLETE",
      failed: "FAILED",
    }[status] || String(status || "WORKING").toUpperCase()
  );
}

function formatTimer(value) {
  const total = Math.max(0, Math.round(value || 0));
  return `${pad(total / 60)}:${pad(total % 60)}`;
}

function active() {
  return ACTIVE_STATES.has(state.playerState);
}

function closestStation() {
  let station = state.stations[0] || null;
  let index = 0;
  let dist = Infinity;
  state.stations.forEach((candidate, i) => {
    const next = Math.abs(candidate.mhz - state.freqMHz);
    if (next < dist) {
      station = candidate;
      index = i;
      dist = next;
    }
  });
  return { station, index, dist, tuned: Boolean(station) && dist <= 0.4 };
}

function selectedStation() {
  return state.stations.find((station) => station.id === state.editingId) || state.stations[0] || null;
}

function pctForFreq(freq) {
  return ((freq - FREQ_MIN) / (FREQ_MAX - FREQ_MIN)) * 100;
}

function setFrequency(value) {
  state.freqMHz = Math.round(clamp(value, FREQ_MIN, FREQ_MAX) * 10) / 10;
  frequencyDial?.setValue(state.freqMHz, false);
  render();
}

function setDurationMinutes(value) {
  const minutes = Math.round(clamp(value, DURATION_MIN, DURATION_MAX));
  state.durationSec = minutes * 60;
  durationDial?.setValue(minutes, false);
  render();
}

function setVolume(value) {
  state.volume = Math.round(clamp(value, 0, 100));
  if (playback.gainNode && playback.audioContext) {
    playback.gainNode.gain.setTargetAtTime(state.volume / 100, playback.audioContext.currentTime, 0.015);
  }
  try {
    localStorage.setItem("vibefm.volume", String(state.volume));
  } catch {}
  render();
}

function setPlayer(playerState, text) {
  state.playerState = playerState;
  state.playerText = text || state.playerText;
  render();
}

function knobSvg(element, color) {
  const key = element.id.replace(/[^a-z0-9_-]/gi, "");
  const tickLines = Array.from({ length: 21 })
    .map((_, index) => {
      const angle = -135 + (index / 20) * 270;
      const r1 = 46;
      const r2 = 49.5;
      const x1 = 50 + r1 * Math.sin((angle * Math.PI) / 180);
      const y1 = 50 - r1 * Math.cos((angle * Math.PI) / 180);
      const x2 = 50 + r2 * Math.sin((angle * Math.PI) / 180);
      const y2 = 50 - r2 * Math.cos((angle * Math.PI) / 180);
      return `<line class="knob-progress-tick" data-ratio="${index / 20}" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="rgba(232,216,182,0.18)" stroke-width="${index % 5 === 0 ? 1.6 : 0.8}" stroke-linecap="round" />`;
    })
    .join("");
  const gripLines = Array.from({ length: 24 })
    .map((_, index) => {
      const angle = (index / 24) * 360;
      const x1 = 50 + 34 * Math.sin((angle * Math.PI) / 180);
      const y1 = 50 - 34 * Math.cos((angle * Math.PI) / 180);
      const x2 = 50 + 38 * Math.sin((angle * Math.PI) / 180);
      const y2 = 50 - 38 * Math.cos((angle * Math.PI) / 180);
      return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="rgba(0,0,0,0.4)" stroke-width="0.7" />`;
    })
    .join("");

  element.innerHTML = `
    <svg viewBox="0 0 100 100" aria-hidden="true">
      <defs>
        <radialGradient id="capG-${key}" cx="0.4" cy="0.3" r="0.8">
          <stop offset="0%" stop-color="#f0d399" />
          <stop offset="55%" stop-color="#a87f3a" />
          <stop offset="100%" stop-color="#2a1c08" />
        </radialGradient>
        <linearGradient id="bezG-${key}" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#d8c8a4" />
          <stop offset="100%" stop-color="#3a2c14" />
        </linearGradient>
      </defs>
      ${tickLines}
      <circle cx="50" cy="50" r="40" fill="url(#bezG-${key})" />
      <circle cx="50" cy="50" r="34" fill="url(#capG-${key})" stroke="rgba(0,0,0,0.45)" stroke-width="0.5" />
      ${gripLines}
      <g class="knob-pointer">
        <line x1="50" y1="50" x2="50" y2="20" stroke="${color}" stroke-width="2.5" stroke-linecap="round" />
        <circle cx="50" cy="20" r="1.6" fill="${color}" />
      </g>
      <circle cx="50" cy="50" r="5" fill="#3a2c14" />
    </svg>
  `;
}

function bindDial(element, config) {
  const range = config.max - config.min;
  let value = config.value;
  let dragging = false;
  const normalize = (raw) => Math.round(raw / config.step) * config.step;

  knobSvg(element, config.color);

  function angleFor(next) {
    const ratio = range === 0 ? 0 : (next - config.min) / range;
    return -135 + clamp(ratio, 0, 1) * 270;
  }

  function setValue(nextValue, notify = true) {
    value = clamp(normalize(nextValue), config.min, config.max);
    const ratio = range === 0 ? 0 : (value - config.min) / range;
    element.querySelector(".knob-pointer")?.setAttribute("transform", `rotate(${angleFor(value)} 50 50)`);
    element.querySelectorAll(".knob-progress-tick").forEach((tick) => {
      const lit = Number(tick.dataset.ratio) <= ratio + 0.001;
      tick.setAttribute("stroke", lit ? config.color : "rgba(232,216,182,0.18)");
    });
    element.setAttribute("aria-valuenow", String(Math.round(value * 10) / 10));
    element.setAttribute("aria-valuetext", config.format(value));
    if (notify) config.onChange(value);
  }

  function valueFromPointer(event) {
    const rect = element.getBoundingClientRect();
    const dx = event.clientX - (rect.left + rect.width / 2);
    const dy = event.clientY - (rect.top + rect.height / 2);
    if (Math.hypot(dx, dy) < rect.width * 0.08) return null;
    const rawAngle = Math.atan2(dx, -dy) * (180 / Math.PI);
    if (rawAngle < -135 || rawAngle > 135) return null;
    return config.min + ((rawAngle + 135) / 270) * range;
  }

  function applyPointer(event) {
    const next = valueFromPointer(event);
    if (next == null) return;
    event.preventDefault();
    setValue(next);
  }

  element.addEventListener("pointerdown", (event) => {
    dragging = true;
    element.setPointerCapture?.(event.pointerId);
    applyPointer(event);
  });
  element.addEventListener("pointermove", (event) => {
    if (dragging) applyPointer(event);
  });
  element.addEventListener("pointerup", (event) => {
    dragging = false;
    element.releasePointerCapture?.(event.pointerId);
  });
  element.addEventListener("pointercancel", () => {
    dragging = false;
  });
  element.addEventListener("wheel", (event) => {
    event.preventDefault();
    setValue(value - Math.sign(event.deltaY) * config.step);
  });
  element.addEventListener("keydown", (event) => {
    const keys = {
      ArrowUp: config.step,
      ArrowRight: config.step,
      ArrowDown: -config.step,
      ArrowLeft: -config.step,
      PageUp: config.step * 10,
      PageDown: -config.step * 10,
    };
    if (event.key in keys) {
      event.preventDefault();
      setValue(value + keys[event.key]);
    } else if (event.key === "Home") {
      event.preventDefault();
      setValue(config.min);
    } else if (event.key === "End") {
      event.preventDefault();
      setValue(config.max);
    }
  });

  setValue(value, false);
  return { setValue };
}

function buildTuner() {
  els.tunerNumbers.innerHTML = "";
  [90, 95, 100, 105].forEach((freq) => {
    const label = document.createElement("span");
    label.className = "tnum";
    label.style.left = `${pctForFreq(freq)}%`;
    label.textContent = String(freq);
    els.tunerNumbers.appendChild(label);
  });

  els.tunerRule.querySelectorAll(".ttick").forEach((tick) => tick.remove());
  for (let freq = 88; freq <= 108; freq += 1) {
    const tick = document.createElement("span");
    tick.className = `ttick${freq % 5 === 0 ? " major" : ""}`;
    tick.style.left = `${pctForFreq(freq)}%`;
    els.tunerRule.appendChild(tick);
  }

  const seekFromEvent = (event) => {
    const rect = els.tunerRule.getBoundingClientRect();
    const x = clamp((event.clientX - rect.left) / rect.width, 0, 1);
    setFrequency(Math.round((FREQ_MIN + x * (FREQ_MAX - FREQ_MIN)) * 10) / 10);
  };

  els.tunerRule.addEventListener("pointerdown", (event) => {
    tunerDragging = true;
    els.tunerRule.setPointerCapture?.(event.pointerId);
    seekFromEvent(event);
  });
  els.tunerRule.addEventListener("pointermove", (event) => {
    if (tunerDragging) seekFromEvent(event);
  });
  els.tunerRule.addEventListener("pointerup", (event) => {
    tunerDragging = false;
    els.tunerRule.releasePointerCapture?.(event.pointerId);
  });
  els.tunerRule.addEventListener("pointercancel", () => {
    tunerDragging = false;
  });
}

function buildAnalyzer() {
  els.analyzer.classList.add("analyzer");
  els.analyzer.innerHTML = "";
  const columns = window.matchMedia("(max-width: 540px)").matches ? 20 : 28;
  analyzerLevels = new Array(columns).fill(0);
  analyzerColumns = [];
  for (let i = 0; i < columns; i += 1) {
    const col = document.createElement("span");
    col.className = "an-col";
    const cells = [];
    for (let row = 0; row < 9; row += 1) {
      const cell = document.createElement("span");
      cell.className = "an-cell";
      cells.push(cell);
      col.appendChild(cell);
    }
    analyzerColumns.push(cells);
    els.analyzer.appendChild(col);
  }
}

function buildBarVisualizer() {
  if (!els.barVisualizer) return;
  els.barVisualizer.innerHTML = "";
  const columns = window.matchMedia("(max-width: 540px)").matches ? 28 : 42;
  barVisualizerLevels = new Array(columns).fill(0);
  barVisualizerColumns = [];
  for (let i = 0; i < columns; i += 1) {
    const col = document.createElement("span");
    col.className = "an-col";
    const cells = [];
    for (let row = 0; row < 12; row += 1) {
      const cell = document.createElement("span");
      cell.className = "an-cell";
      cells.push(cell);
      col.appendChild(cell);
    }
    barVisualizerColumns.push(cells);
    els.barVisualizer.appendChild(col);
  }
}

function targetBarLevel(index, totalColumns, t, isOn, idleLevel) {
  const midpoint = (totalColumns - 1) / 2;
  const distanceFromCenter = Math.abs(index - midpoint) / Math.max(1, midpoint);
  const bias = 0.54 + (1 - distanceFromCenter) * 0.46;
  if (!isOn) return idleLevel * bias;
  const wave =
    0.48 +
    0.22 * Math.sin(t + index * 0.31) +
    0.16 * Math.sin(t * 1.42 + index * 0.57 + 1.2) +
    0.08 * Math.sin(t * 0.64 - index * 0.2 + 2.4);
  return clamp(wave * bias, 0.04, 0.98);
}

function paintBarCells(cells, level) {
  const litHeight = level * cells.length;
  cells.forEach((cell, row) => {
    const fromBottom = cells.length - 1 - row;
    const alpha = clamp((litHeight - fromBottom) * 0.76, 0, 1);
    const onLeadingEdge = alpha > 0.12 && fromBottom > litHeight - 1.36;
    cell.style.setProperty("--cell-alpha", alpha.toFixed(3));
    cell.style.setProperty("--cell-scale", (0.42 + alpha * 0.58).toFixed(3));
    cell.classList.toggle("lit", alpha > 0.07);
    cell.classList.toggle("hi", onLeadingEdge && level > 0.22);
  });
}

function animateBarSet(columns, levels, t, isOn, idleLevel) {
  if (levels.length !== columns.length) levels.splice(0, levels.length, ...new Array(columns.length).fill(0));
  columns.forEach((cells, index) => {
    const current = levels[index] || 0;
    const target = targetBarLevel(index, columns.length, t, isOn, idleLevel);
    const easing = target > current ? 0.18 : 0.1;
    const next = current + (target - current) * easing;
    levels[index] = next;
    paintBarCells(cells, next);
  });
}

function animateAnalyzer() {
  const isOn = active();
  const t = performance.now() / 620;
  animateBarSet(analyzerColumns, analyzerLevels, t, isOn, 0.08);
  animateBarSet(barVisualizerColumns, barVisualizerLevels, t * 0.9, isOn, 0.18);
  requestAnimationFrame(animateAnalyzer);
}

function pulseDurationControl() {
  if (!els.durationControl) return;
  clearTimeout(durationPulseTimer);
  els.durationControl.classList.remove("needs-length");
  void els.durationControl.offsetWidth;
  els.durationControl.classList.add("needs-length");
  durationPulseTimer = setTimeout(() => {
    els.durationControl?.classList.remove("needs-length");
  }, 900);
}

function updateStation(id, patch) {
  state.stations = state.stations.map((station) =>
    station.id === id ? { ...station, ...patch } : station,
  );
  persistStations();
  render();
}

function createLocalStation(partial = {}) {
  const id = `local-${Date.now()}`;
  let mhz = 88.5;
  while (state.stations.some((station) => Math.abs(station.mhz - mhz) < 0.6) && mhz < 107.5) {
    mhz += 1.0;
  }
  return {
    id,
    backendId: null,
    name: "NEW VIBE",
    tag: "local draft",
    mhz: Math.round(mhz * 10) / 10,
    hosts: 1,
    voiceA: "F",
    voiceB: "M",
    tone: 25,
    urls: [],
    sourcePresetIds: state.sourcePresets.map((preset) => preset.id),
    tracks: ["Ready for a generated test signal."],
    ...partial,
  };
}

async function createStation() {
  const local = createLocalStation();
  // Best-effort POST so the backend has a copy; localStorage is the source
  // of truth so subsequent edits survive reload.
  try {
    const { data, apiBase } = await requestJsonFromAnyApi(state.apiBase, "/api/vibes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(vibePayloadFromStation(local)),
    });
    state.apiBase = apiBase;
    state.apiStatus = "ready";
    const saved = stationFromVibe(data.vibe, state.stations.length);
    saved.mhz = local.mhz;
    state.stations = [...state.stations, saved];
    state.editingId = saved.id;
    state.freqMHz = saved.mhz;
    setPlayer("idle", "VIBE SAVED");
  } catch (error) {
    state.apiStatus = "offline";
    state.stations = [...state.stations, local];
    state.editingId = local.id;
    state.freqMHz = local.mhz;
    setPlayer("idle", "LOCAL VIBE");
  }
  persistStations();
  frequencyDial?.setValue(state.freqMHz, false);
  render();
}

function deleteSelectedStation() {
  const selected = selectedStation();
  if (!selected) return;
  state.stations = state.stations.filter((station) => station.id !== selected.id);
  state.editingId = state.stations[0]?.id || "";
  if (state.stations[0]) state.freqMHz = state.stations[0].mhz;
  persistStations();
  setPlayer("idle", "VIBE REMOVED");
  render();
}

function addRssFeed() {
  const selected = selectedStation();
  const url = els.rssDraftInput.value.trim();
  if (!selected || !url) return;
  if (!(selected.urls || []).includes(url)) {
    updateStation(selected.id, { urls: [...(selected.urls || []), url] });
  }
  els.rssDraftInput.value = "";
}

function removeRssFeed(index) {
  const selected = selectedStation();
  if (!selected) return;
  updateStation(selected.id, { urls: (selected.urls || []).filter((_, i) => i !== index) });
}

function feedDomain(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function renderTunerStations(current) {
  els.tunerPointer.style.left = `${pctForFreq(state.freqMHz)}%`;
  els.tunerStations.innerHTML = "";
  state.stations.forEach((station) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `tst${Math.abs(station.mhz - state.freqMHz) < 0.4 ? " active" : ""}`;
    button.style.left = `${pctForFreq(station.mhz)}%`;
    button.title = `${station.name} ${station.mhz.toFixed(1)} MHz`;
    button.innerHTML = `<span class="tst-dot"></span><span class="tst-lbl">${station.name}</span>`;
    button.addEventListener("click", () => {
      state.editingId = station.id;
      setFrequency(station.mhz);
    });
    els.tunerStations.appendChild(button);
  });

  if (current && !state.editingId) {
    state.editingId = current.id;
  }
}

function renderSettings() {
  els.grilleArea.classList.toggle("open", state.settingsOpen);
  els.grillePanel.classList.toggle("open", state.settingsOpen);
  els.settingsButton.classList.toggle("active", state.settingsOpen);
  els.settingsButton.textContent = state.settingsOpen ? "CLOSE" : "SETTINGS";
  els.settingsButton.setAttribute("aria-expanded", String(state.settingsOpen));

  document.querySelectorAll("[data-tab]").forEach((button) => {
    const activeTab = button.dataset.tab === state.settingsTab;
    button.classList.toggle("active", activeTab);
    button.setAttribute("aria-selected", String(activeTab));
  });
  document.querySelectorAll("[data-panel]").forEach((panel) => {
    panel.hidden = panel.dataset.panel !== state.settingsTab;
  });

  const selected = selectedStation();
  els.vibeSelect.innerHTML = "";
  if (state.stations.length === 0) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "NO VIBES";
    els.vibeSelect.appendChild(option);
  } else {
    state.stations.forEach((station, index) => {
      const option = document.createElement("option");
      option.value = station.id;
      option.textContent = `${pad2(index + 1)} - ${station.name} - ${station.hosts}H`;
      els.vibeSelect.appendChild(option);
    });
  }
  els.vibeSelect.value = selected?.id || "";
  els.stationEditor.classList.toggle("empty", !selected);
  els.deleteVibeButton.disabled = !selected;

  if (selected) {
    if (document.activeElement !== els.vibeNameInput) {
      els.vibeNameInput.value = selected.name;
    }
    els.rssList.innerHTML = "";
    (selected.urls || []).forEach((url, index) => {
      const chip = document.createElement("span");
      chip.className = "rss-chip";
      chip.title = url;
      chip.innerHTML = `<span class="rss-dot"></span><span class="rss-chip-name">${feedDomain(url)}</span>`;
      const close = document.createElement("button");
      close.type = "button";
      close.className = "rss-x";
      close.setAttribute("aria-label", "Remove RSS feed");
      close.textContent = "x";
      close.addEventListener("click", () => removeRssFeed(index));
      chip.appendChild(close);
      els.rssList.appendChild(chip);
    });

    els.sourcePresets.innerHTML = "";
    const selectedPresets = new Set(selected.sourcePresetIds || []);
    state.sourcePresets.forEach((preset) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `source-chip${selectedPresets.has(preset.id) ? " active" : ""}`;
      button.dataset.sourcePreset = preset.id;
      button.innerHTML = `<span class="source-dot"></span><span>${preset.label}</span>`;
      els.sourcePresets.appendChild(button);
    });

    document.querySelectorAll("[data-hosts]").forEach((button) => {
      button.classList.toggle("active", Number(button.dataset.hosts) === selected.hosts);
    });
    document.querySelectorAll("[data-tone]").forEach((button) => {
      const isCasual = selected.tone < 50;
      button.classList.toggle("active", Number(button.dataset.tone) < 50 ? isCasual : !isCasual);
    });
    document.querySelectorAll("[data-voice-a]").forEach((button) => {
      button.classList.toggle("active", button.dataset.voiceA === selected.voiceA);
    });
    document.querySelectorAll("[data-voice-b]").forEach((button) => {
      button.classList.toggle("active", button.dataset.voiceB === selected.voiceB);
    });
    els.voiceBCell.classList.toggle("disabled", selected.hosts !== 2);
  }

  els.apiBaseInput.value = state.apiBase;
  els.apiStatus.className = `api-status ${state.apiStatus}`;
  els.apiStatus.querySelector("span:last-child").textContent =
    state.apiStatus === "ready" ? "API ready" : state.apiStatus === "checking" ? "Checking" : "API offline";
  els.modeMock.classList.toggle("active", state.mode === "mock");
  els.modeReal.classList.toggle("active", state.mode === "real");
  els.volumeRange.value = String(state.volume);
  els.volumeValue.textContent = String(state.volume);
  els.aboutMode.textContent = state.mode === "real" ? "Real" : "Demo";
}

function render() {
  const lock = closestStation();
  const station = lock.station;
  const isOn = active();
  const timer = formatTimer(isOn ? state.remainingSec : state.durationSec);
  const displayStatus =
    isOn ? "ON AIR" : state.playerState === "failed" ? "ERROR" : state.playerState === "complete" ? "COMPLETE" : "STANDBY";
  const statusLabel = state.playerText.length > 22 ? `${state.playerText.slice(0, 21)}...` : state.playerText;
  const hasLength = state.durationSec > 0;

  els.stationName.textContent = station ? (lock.tuned ? station.name : `${state.freqMHz.toFixed(1)} FM`) : "NO VIBES";
  els.screenStatus.textContent = displayStatus;
  els.timerReadout.textContent = timer;
  els.durationValue.textContent = timer;
  els.freqValue.textContent = state.freqMHz.toFixed(1);
  els.topStatus.textContent = statusLabel;
  els.playButton.textContent = isOn ? "STOP" : "PLAY";
  els.playButton.disabled = !station && !isOn;
  els.playButton.classList.toggle("active", isOn);
  els.powerLed.classList.toggle("on", isOn);
  els.statusLamp.classList.toggle("on", isOn);
  els.durationLamp.classList.toggle("ready", hasLength);
  els.durationLamp.classList.toggle("empty", !hasLength);
  document.querySelectorAll(".glow").forEach((glow) => glow.classList.toggle("on", isOn));

  renderTunerStations(lock.tuned ? station : null);
  renderSettings();
}

function isCurrentRun(runId) {
  return runId === playback.runId;
}

function closePlaybackHardware() {
  if (playback.eventSource) playback.eventSource.close();
  playback.eventSource = null;
  playback.sourceRefs.forEach((source) => {
    try {
      source.stop();
    } catch {}
  });
  playback.sourceRefs = [];
  if (playback.audioContext && playback.audioContext.state !== "closed") {
    playback.audioContext.close().catch(() => {});
  }
  playback.audioContext = null;
  playback.gainNode = null;
  playback.activeApiBase = "";
}

async function stopPlayback(label = "STOPPED") {
  playback.runId += 1;
  closePlaybackHardware();
  state.generationComplete = false;
  state.segmentProgress = { queued: 0, played: 0, total: 0 };
  state.remainingSec = 0;
  setPlayer("idle", label);
}

function finishPlayback(label = "PLAYBACK COMPLETE") {
  closePlaybackHardware();
  state.generationComplete = false;
  state.segmentProgress = { queued: 0, played: 0, total: 0 };
  state.remainingSec = 0;
  setPlayer("complete", label);
}

async function startEpisode() {
  if (active()) {
    await stopPlayback();
    return;
  }
  if (state.durationSec <= 0) {
    pulseDurationControl();
    setPlayer("idle", "SET LENGTH");
    return;
  }
  const lock = closestStation();
  const station = lock.station;
  if (!station) {
    state.settingsOpen = true;
    setPlayer("failed", "NO VIBE");
    return;
  }
  if (!lock.tuned) setFrequency(station.mhz);

  await stopPlayback("STANDBY");
  const runId = playback.runId + 1;
  playback.runId = runId;
  state.remainingSec = Math.max(60, state.durationSec);
  state.segmentProgress = { queued: 0, played: 0, total: 0 };
  state.generationComplete = false;
  setPlayer("starting", "STARTING");

  try {
    const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextCtor) throw new Error("AUDIO UNSUPPORTED");
    playback.audioContext = new AudioContextCtor();
    playback.gainNode = playback.audioContext.createGain();
    playback.gainNode.gain.value = state.volume / 100;
    playback.gainNode.connect(playback.audioContext.destination);
    await playback.audioContext.resume();
    playback.nextStartTime = playback.audioContext.currentTime + 0.18;

    const apiKeys = buildApiKeys();
    const payload = episodePayloadFromStation(station);
    if (Object.keys(apiKeys).length > 0) payload.api_keys = apiKeys;
    const { data: job, apiBase } = await requestJsonFromAnyApi(state.apiBase, "/api/episodes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!isCurrentRun(runId)) return;
    state.apiBase = apiBase;
    state.apiStatus = "ready";
    playback.activeApiBase = apiBase;
    setPlayer("generating", job.vibe ? `TUNED ${job.vibe.name}` : `TUNED ${station.name}`);

    const stream = new EventSource(`${apiBase}${job.events_url}`);
    playback.eventSource = stream;
    stream.addEventListener("status", (event) => {
      if (!isCurrentRun(runId)) return;
      const data = JSON.parse(event.data);
      setPlayer(data.status === "rendering_audio" ? "playing" : "generating", humanStatus(data.status));
    });
    stream.addEventListener("script_ready", (event) => {
      if (!isCurrentRun(runId)) return;
      const data = JSON.parse(event.data);
      state.segmentProgress = { ...state.segmentProgress, total: data.segment_count || 0 };
      setPlayer("generating", `${data.segment_count || 0} SEGMENTS`);
    });
    stream.addEventListener("segment_ready", (event) => queueSegment(JSON.parse(event.data), runId));
    stream.addEventListener("complete", (event) => {
      if (!isCurrentRun(runId)) return;
      const data = JSON.parse(event.data);
      state.generationComplete = true;
      if (playback.eventSource) playback.eventSource.close();
      playback.eventSource = null;
      if (state.segmentProgress.total > 0 && state.segmentProgress.played >= state.segmentProgress.total) finishPlayback();
      else if (!data.audio_url && state.segmentProgress.queued === 0) finishPlayback("COMPLETE");
      else setPlayer("playing", "ALL QUEUED");
    });
    stream.addEventListener("failed", (event) => {
      if (!isCurrentRun(runId)) return;
      const data = JSON.parse(event.data);
      closePlaybackHardware();
      state.remainingSec = 0;
      setPlayer("failed", data.error || "FAILED");
    });
    stream.onerror = () => {
      if (isCurrentRun(runId) && !state.generationComplete) {
        state.playerText = "SIGNAL RETRY";
        render();
      }
    };
  } catch (error) {
    if (!isCurrentRun(runId)) return;
    closePlaybackHardware();
    state.apiStatus = error?.status ? state.apiStatus : "offline";
    state.remainingSec = 0;
    setPlayer("failed", error.message || "PLAY FAILED");
  }
}

async function queueSegment(segment, runId) {
  const context = playback.audioContext;
  if (!context || !playback.gainNode) return;
  try {
    const response = await fetch(`${playback.activeApiBase || cleanApiBase(state.apiBase)}${segment.audio_url}`);
    if (!response.ok) throw new Error(`SEGMENT ${response.status}`);
    const buffer = await context.decodeAudioData(await response.arrayBuffer());
    if (!isCurrentRun(runId)) return;
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(playback.gainNode);
    const startAt = Math.max(playback.nextStartTime, context.currentTime + 0.06);
    source.start(startAt);
    playback.nextStartTime = startAt + buffer.duration + 0.04;
    playback.sourceRefs.push(source);
    state.segmentProgress = { ...state.segmentProgress, queued: state.segmentProgress.queued + 1 };
    setPlayer("playing", `PLAYING ${segment.index + 1}`);
    source.onended = () => {
      if (!isCurrentRun(runId)) return;
      state.segmentProgress = { ...state.segmentProgress, played: state.segmentProgress.played + 1 };
      if (state.generationComplete && state.segmentProgress.total > 0 && state.segmentProgress.played >= state.segmentProgress.total) {
        finishPlayback();
      } else {
        render();
      }
    };
  } catch (error) {
    if (isCurrentRun(runId)) setPlayer("failed", error.message || "AUDIO FAILED");
  }
}

function startTimer() {
  setInterval(() => {
    if (!active()) return;
    state.remainingSec = Math.max(0, state.remainingSec - 1);
    if (state.remainingSec <= 0) stopPlayback("TIMER DONE");
    else render();
  }, 1000);
}

async function checkApi() {
  state.apiStatus = "checking";
  render();
  try {
    const { data, apiBase } = await requestJsonFromAnyApi(state.apiBase, "/api/vibes");
    state.apiBase = apiBase;
    state.sourcePresets = Array.isArray(data.presets) && data.presets.length > 0 ? data.presets : fallbackSourcePresets;
    // Only seed stations from server when the user has nothing saved
    // locally yet — otherwise the localStorage source of truth wins so
    // edits survive reload.
    const hasLocal = !!loadStoredStations();
    const saved = Array.isArray(data.vibes) ? data.vibes.map(stationFromVibe) : [];
    if (saved.length > 0 && !hasLocal) {
      state.stations = saved;
      state.editingId = saved[0].id;
      state.freqMHz = saved[0].mhz;
      frequencyDial?.setValue(state.freqMHz, false);
      persistStations();
    }
    state.apiStatus = "ready";
  } catch {
    state.sourcePresets = fallbackSourcePresets;
    state.apiStatus = "offline";
  }
  render();
}

function wireSettings() {
  els.settingsButton.addEventListener("click", () => {
    state.settingsOpen = !state.settingsOpen;
    render();
  });

  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      state.settingsTab = button.dataset.tab;
      render();
    });
  });

  els.vibeSelect.addEventListener("change", () => {
    state.editingId = els.vibeSelect.value;
    const selected = selectedStation();
    if (selected) setFrequency(selected.mhz);
    render();
  });
  els.newVibeButton.addEventListener("click", createStation);
  els.deleteVibeButton.addEventListener("click", deleteSelectedStation);
  els.vibeNameInput.addEventListener("input", () => {
    const selected = selectedStation();
    if (!selected) return;
    updateStation(selected.id, { name: els.vibeNameInput.value.toUpperCase() });
  });
  els.rssAddButton.addEventListener("click", addRssFeed);
  els.rssDraftInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      addRssFeed();
    }
  });
  els.sourcePresets.addEventListener("click", (event) => {
    const button = event.target.closest("[data-source-preset]");
    const selected = selectedStation();
    if (!button || !selected) return;
    const preset = button.dataset.sourcePreset;
    const next = new Set(selected.sourcePresetIds || []);
    if (next.has(preset)) next.delete(preset);
    else next.add(preset);
    updateStation(selected.id, { sourcePresetIds: Array.from(next) });
  });
  document.querySelectorAll("[data-hosts]").forEach((button) => {
    button.addEventListener("click", () => {
      const selected = selectedStation();
      if (selected) updateStation(selected.id, { hosts: Number(button.dataset.hosts) });
    });
  });
  document.querySelectorAll("[data-tone]").forEach((button) => {
    button.addEventListener("click", () => {
      const selected = selectedStation();
      if (selected) updateStation(selected.id, { tone: Number(button.dataset.tone) });
    });
  });
  document.querySelectorAll("[data-voice-a]").forEach((button) => {
    button.addEventListener("click", () => {
      const selected = selectedStation();
      if (selected) updateStation(selected.id, { voiceA: button.dataset.voiceA });
    });
  });
  document.querySelectorAll("[data-voice-b]").forEach((button) => {
    button.addEventListener("click", () => {
      const selected = selectedStation();
      if (selected && selected.hosts === 2) updateStation(selected.id, { voiceB: button.dataset.voiceB });
    });
  });

  els.apiBaseInput.addEventListener("input", () => {
    state.apiBase = cleanApiBase(els.apiBaseInput.value);
    try {
      localStorage.setItem("vibefm.apiBase", state.apiBase);
    } catch {}
    clearTimeout(apiCheckTimer);
    apiCheckTimer = setTimeout(checkApi, 350);
  });
  els.modeMock.addEventListener("click", () => {
    state.mode = "mock";
    try {
      localStorage.setItem("vibefm.mode", state.mode);
    } catch {}
    render();
  });
  els.modeReal.addEventListener("click", () => {
    state.mode = "real";
    try {
      localStorage.setItem("vibefm.mode", state.mode);
    } catch {}
    render();
  });

  state.keys = loadStoredKeys();

  const storedStations = loadStoredStations();
  if (storedStations) {
    state.stations = storedStations;
    state.editingId = storedStations[0].id;
    state.freqMHz = storedStations[0].mhz;
    frequencyDial?.setValue(state.freqMHz, false);
  }

  function renderKeysStatus() {
    if (!els.keysStatus) return;
    const count = Object.keys(buildApiKeys()).length;
    const span = els.keysStatus.querySelector("span:last-child");
    if (span) span.textContent = `${count} of 2 keys`;
    els.keysStatus.classList.toggle("ready", count === 2);
    els.keysStatus.classList.toggle("checking", count === 0);
  }
  if (els.keyOpenRouter) {
    els.keyOpenRouter.value = state.keys.openrouter;
    els.keyOpenRouter.addEventListener("input", () => {
      state.keys.openrouter = els.keyOpenRouter.value.trim();
      persistKey("openrouter", state.keys.openrouter);
      renderKeysStatus();
    });
  }
  if (els.keyElevenLabs) {
    els.keyElevenLabs.value = state.keys.elevenlabs;
    els.keyElevenLabs.addEventListener("input", () => {
      state.keys.elevenlabs = els.keyElevenLabs.value.trim();
      persistKey("elevenlabs", state.keys.elevenlabs);
      renderKeysStatus();
    });
  }
  renderKeysStatus();
  els.volumeRange.addEventListener("input", () => setVolume(Number(els.volumeRange.value)));
}

function fitDevice() {
  const edgeGap = window.innerWidth > 720 ? 12 : 28;
  const radioWidth = els.device?.offsetWidth || 920;
  const radioHeight = (els.device?.offsetHeight || 548) + 44;
  const width = Math.max(window.innerWidth - edgeGap * 2, 120);
  const height = Math.max(window.innerHeight - edgeGap * 2, 120);
  const scale = Math.max(0.46, Math.min(width / radioWidth, height / radioHeight, 1.55));
  document.documentElement.style.setProperty("--device-scale", scale.toFixed(3));
}

function boot() {
  [
    "device",
    "settingsButton",
    "grilleArea",
    "settingsDrawer",
    "grillePanel",
    "durationControl",
    "durationDial",
    "durationValue",
    "durationLamp",
    "mainDisplay",
    "analyzer",
    "screenStatus",
    "powerLed",
    "stationName",
    "timerReadout",
    "tunerNumbers",
    "tunerRule",
    "tunerPointer",
    "tunerStations",
    "frequencyDial",
    "freqValue",
    "barVisualizer",
    "playButton",
    "statusLamp",
    "topStatus",
    "vibeSelect",
    "newVibeButton",
    "stationEditor",
    "vibeNameInput",
    "rssDraftInput",
    "rssAddButton",
    "rssList",
    "sourcePresets",
    "voiceBCell",
    "deleteVibeButton",
    "apiBaseInput",
    "apiStatus",
    "modeMock",
    "modeReal",
    "volumeRange",
    "volumeValue",
    "aboutMode",
    "keyOpenRouter",
    "keyElevenLabs",
    "keysStatus",
  ].forEach((id) => {
    els[id] = document.getElementById(id);
  });

  try {
    const storedVolume = localStorage.getItem("vibefm.volume");
    const storedMode = localStorage.getItem("vibefm.mode");
    const storedApi = localStorage.getItem("vibefm.apiBase");
    if (storedVolume != null) state.volume = Math.round(clamp(Number(storedVolume) || state.volume, 0, 100));
    if (storedMode) state.mode = storedMode === "real" ? "real" : "mock";
    if (storedApi) state.apiBase = storedApi;
    localStorage.removeItem("vibefm.durationSec");
  } catch {}

  frequencyDial = bindDial(els.frequencyDial, {
    min: FREQ_MIN,
    max: FREQ_MAX,
    step: 0.1,
    value: state.freqMHz,
    color: "#e8d8b6",
    format: (value) => `${value.toFixed(1)} MHz`,
    onChange: setFrequency,
  });
  durationDial = bindDial(els.durationDial, {
    min: DURATION_MIN,
    max: DURATION_MAX,
    step: 1,
    value: Math.round(state.durationSec / 60),
    color: "#c5481e",
    format: (value) => `${Math.round(value)} minutes`,
    onChange: setDurationMinutes,
  });

  els.apiBaseInput.value = state.apiBase;
  els.playButton.addEventListener("click", startEpisode);
  wireSettings();
  buildTuner();
  buildAnalyzer();
  buildBarVisualizer();
  fitDevice();
  window.addEventListener("resize", () => {
    fitDevice();
    buildAnalyzer();
    buildBarVisualizer();
  });
  render();
  startTimer();
  requestAnimationFrame(animateAnalyzer);
  checkApi();
}

document.addEventListener("DOMContentLoaded", boot);
