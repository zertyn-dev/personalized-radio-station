/* global React, ReactDOM */
const { useState, useEffect, useRef } = React;

const FREQ_MIN = 88.0;
const FREQ_MAX = 108.0;

const TIMER_MAX_SEC = 60 * 60;
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const pad = (n) => String(Math.floor(n)).padStart(2, "0");
const pad2 = (n) => String(n).padStart(2, "0");
const DEFAULT_BACKEND_BASE = "http://127.0.0.1:8765";
const SAVED_FREQUENCIES = [88.3, 91.4, 94.7, 98.1, 101.2, 104.6, 106.8, 107.6];
const PLAYER_ACTIVE_STATES = new Set(["starting", "generating", "playing"]);
const APP_MODE = "real";

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
    try { body = JSON.parse(text); }
    catch { body = { error: text }; }
  }
  if (!response.ok) {
    const error = new Error(body.error || `Request failed: ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return body;
}

function shouldTryFallbackApi(error) {
  return !error?.status || [404, 405, 501].includes(error.status);
}

function candidateApiBases(primary) {
  const bases = [cleanApiBase(primary), DEFAULT_BACKEND_BASE];
  return bases.filter((base, index) => base && bases.indexOf(base) === index);
}

async function requestJsonFromAnyApi(primaryApiBase, path, options = {}) {
  let lastError = null;
  for (const base of candidateApiBases(primaryApiBase)) {
    try {
      return { data: await requestJson(base, path, options), apiBase: base };
    } catch (error) {
      lastError = error;
      if (!shouldTryFallbackApi(error)) {
        break;
      }
    }
  }
  throw lastError || new Error("API request failed");
}

function frequencyForIndex(index) {
  if (index < SAVED_FREQUENCIES.length) return SAVED_FREQUENCIES[index];
  const offset = (index - SAVED_FREQUENCIES.length + 1) * 1.7;
  return Math.round((88.1 + (offset % 19.2)) * 10) / 10;
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
    length: 2,
    freq: "on-demand",
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
  const toneStyle =
    station.tone >= 50
      ? "professional, crisp, source-aware radio with confident framing"
      : "casual, warm, already-on-air radio with useful pacing and a little texture";
  const hostLabel = station.hosts === 2 ? "two-host handoff" : "solo host";
  const voiceLabel = station.voiceA === "M" ? "male-led" : "female-led";
  return `${toneStyle}; ${voiceLabel}; ${hostLabel}`;
}

function rssFeedsFromStation(station, sourcePresets) {
  const selected = new Set(station.sourcePresetIds || []);
  const presetUrls = (sourcePresets || [])
    .filter((preset) => selected.has(preset.id))
    .map((preset) => preset.url);
  return Array.from(new Set([...presetUrls, ...(station.urls || [])]));
}

function episodePayloadFromStation(station, mode, durationSeconds, sourcePresets) {
  const durationMinutes = Math.max(1, Math.round(durationSeconds / 60));
  if (station.backendId) {
    return {
      mode,
      vibe_id: station.backendId,
      replace_topics: true,
      replace_rss_feeds: true,
      duration: `${durationMinutes} minutes`,
      duration_minutes: durationMinutes,
    };
  }

  const vibe = vibePayloadFromStation(station);
  return {
    mode,
    station_name: vibe.name,
    style: styleFromStation(station),
    rss_feeds: rssFeedsFromStation(station, sourcePresets),
    replace_topics: true,
    replace_rss_feeds: true,
    source_preset_ids: vibe.source_preset_ids,
    host_tone: vibe.tone,
    voice_gender: vibe.voice_gender,
    host_format: vibe.host_format,
    duration: `${durationMinutes} minutes`,
    duration_minutes: durationMinutes,
  };
}

function humanEpisodeStatus(status) {
  return {
    queued: "QUEUED",
    checking_runtime: "CHECKING",
    fetching_sources: "SOURCES",
    generating_script: "SCRIPTING",
    rendering_audio: "RENDERING",
    audio_disabled: "NO AUDIO",
    complete: "COMPLETE",
    failed: "FAILED",
  }[status] || String(status || "WORKING").toUpperCase();
}

function formatTimerSeconds(value) {
  const total = Math.max(0, Math.round(value || 0));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${pad(minutes)}:${pad(seconds)}`;
}

/* ---------- Tuner strip (frequency scanner) ---------- */
function TunerStrip({ freq, stations, onSeek }) {
  const MIN = 87.5, MAX = 108;
  const pct = (v) => ((v - MIN) / (MAX - MIN)) * 100;
  const dragRef = useRef(null);

  const ticks = [];
  for (let f = 88; f <= 108; f += 1) ticks.push({ f, major: f % 5 === 0 });

  const seekFromEvent = (e) => {
    const el = e.currentTarget;
    const rect = el.getBoundingClientRect();
    const x = clamp((e.clientX - rect.left) / rect.width, 0, 1);
    const v = Math.round((MIN + x * (MAX - MIN)) * 10) / 10;
    onSeek(v);
  };
  const onDown = (e) => {
    dragRef.current = true;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    seekFromEvent(e);
  };
  const onMove = (e) => { if (dragRef.current) seekFromEvent(e); };
  const onUp = (e) => {
    dragRef.current = false;
    e.currentTarget.releasePointerCapture?.(e.pointerId);
  };

  return (
    <div className="tuner-strip">
      <div className="tuner-numbers">
        {[90, 95, 100, 105].map((f) => (
          <span key={f} className="tnum" style={{ left: `${pct(f)}%` }}>{f}</span>
        ))}
      </div>
      <div
        className="tuner-rule"
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerCancel={onUp}
      >
        {ticks.map(({ f, major }) => (
          <span key={f} className={"ttick" + (major ? " major" : "")} style={{ left: `${pct(f)}%` }} />
        ))}
        <div className="tpointer" style={{ left: `${pct(freq)}%` }}>
          <span className="tpoint-tip" />
          <span className="tpoint-rod" />
        </div>
      </div>
      <div className="tuner-stations">
        {stations.map((s) => {
          const active = Math.abs(s.mhz - freq) < 0.4;
          return (
            <button key={s.id} className={"tst" + (active ? " active" : "")}
                    style={{ left: `${pct(s.mhz)}%` }}
                    onClick={() => onSeek(s.mhz)}>
              <span className="tst-dot" />
              <span className="tst-lbl">{s.name}</span>
            </button>
          );
        })}
      </div>
      <div className="tuner-foot">
        <span>· 87.5 — 108 MHz</span>
        <span>FM</span>
      </div>
    </div>
  );
}

/* ---------- Frequency analyzer ---------- */
function Analyzer({ playing, columns = 32, rows = 7 }) {
  const [levels, setLevels] = useState(() => Array(columns).fill(0));
  useEffect(() => {
    if (!playing) { setLevels(Array(columns).fill(0)); return; }
    let raf, t = 0;
    const tick = () => {
      t += 0.13;
      setLevels(() => {
        const out = new Array(columns);
        for (let i = 0; i < columns; i++) {
          // smooth bandshape with a couple of moving lobes + bias toward middle
          const mid = columns / 2;
          const bias = 1 - Math.abs(i - mid) / mid * 0.55;
          const v = 0.42
            + 0.30 * Math.sin(t * 1.0 + i * 0.32)
            + 0.18 * Math.sin(t * 1.7 + i * 0.71 + 1.3)
            + 0.10 * Math.sin(t * 2.4 + i * 0.18 + 2.7);
          const jitter = (Math.random() - 0.5) * 0.08;
          out[i] = Math.max(0, Math.min(1, v * bias + jitter));
        }
        return out;
      });
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, columns]);

  return (
    <div className="analyzer" style={{ gridTemplateColumns: `repeat(${columns}, 1fr)` }}>
      {levels.map((lvl, i) => {
        const litRows = Math.round(lvl * rows);
        return (
          <div key={i} className="an-col">
            {Array.from({ length: rows }).map((_, r) => {
              const fromBottom = rows - 1 - r;
              const lit = fromBottom < litRows;
              const hi = lit && fromBottom === litRows - 1;
              return <span key={r} className={"an-cell" + (lit ? " lit" : "") + (hi ? " hi" : "")} />;
            })}
          </div>
        );
      })}
    </div>
  );
}

/* ---------- Knob ---------- */
function Knob({ value, max, onChange, color = "#1a140a", size = 88, step, ariaLabel = "Rotary control", ariaValueText, disabled = false }) {
  const safeMax = Math.max(1, max || 1);
  const boundedValue = clamp(value || 0, 0, safeMax);
  const angle = -135 + (boundedValue / safeMax) * 270;
  const drag = useRef(false);
  const [dragging, setDragging] = useState(false);
  const keyStep = step || safeMax / 100;

  const valueFromPointer = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const dx = e.clientX - (rect.left + rect.width / 2);
    const dy = e.clientY - (rect.top + rect.height / 2);
    if (Math.hypot(dx, dy) < rect.width * 0.08) return null;
    const rawAngle = Math.atan2(dx, -dy) * 180 / Math.PI;
    return ((clamp(rawAngle, -135, 135) + 135) / 270) * safeMax;
  };

  const applyPointerValue = (e) => {
    const next = valueFromPointer(e);
    if (next != null) onChange(clamp(next, 0, safeMax));
  };

  const onDown = (e) => {
    if (disabled) return;
    e.preventDefault();
    drag.current = true;
    setDragging(true);
    e.currentTarget.setPointerCapture?.(e.pointerId);
    applyPointerValue(e);
  };
  const onMove = (e) => {
    if (!drag.current || disabled) return;
    e.preventDefault();
    applyPointerValue(e);
  };
  const onUp = (e) => {
    drag.current = false;
    setDragging(false);
    e.currentTarget.releasePointerCapture?.(e.pointerId);
  };
  const onWheel = (e) => {
    if (disabled) return;
    e.preventDefault();
    onChange(clamp(boundedValue - (e.deltaY * safeMax) / 8000, 0, safeMax));
  };
  const onKeyDown = (e) => {
    if (disabled) return;
    const changeBy = (amount) => onChange(clamp(boundedValue + amount, 0, safeMax));
    if (e.key === "ArrowUp" || e.key === "ArrowRight") {
      e.preventDefault(); changeBy(keyStep);
    } else if (e.key === "ArrowDown" || e.key === "ArrowLeft") {
      e.preventDefault(); changeBy(-keyStep);
    } else if (e.key === "PageUp") {
      e.preventDefault(); changeBy(keyStep * 10);
    } else if (e.key === "PageDown") {
      e.preventDefault(); changeBy(-keyStep * 10);
    } else if (e.key === "Home") {
      e.preventDefault(); onChange(0);
    } else if (e.key === "End") {
      e.preventDefault(); onChange(safeMax);
    }
  };

  const tickCount = 21;
  const ticks = Array.from({ length: tickCount }).map((_, i) => {
    const a = -135 + (i / (tickCount - 1)) * 270;
    const lit = i / (tickCount - 1) <= boundedValue / safeMax + 0.001;
    const r1 = 46, r2 = 49.5;
    const x1 = 50 + r1 * Math.sin((a * Math.PI) / 180);
    const y1 = 50 - r1 * Math.cos((a * Math.PI) / 180);
    const x2 = 50 + r2 * Math.sin((a * Math.PI) / 180);
    const y2 = 50 - r2 * Math.cos((a * Math.PI) / 180);
    return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2}
      stroke={lit ? color : "rgba(232,216,182,0.18)"}
      strokeWidth={i % 5 === 0 ? 1.6 : 0.8} strokeLinecap="round" />;
  });

  return (
    <div
      className={"knob" + (dragging ? " dragging" : "") + (disabled ? " disabled" : "")}
      style={{ width: size, height: size }}
      role="slider"
      tabIndex={disabled ? -1 : 0}
      aria-label={ariaLabel}
      aria-valuemin="0"
      aria-valuemax={safeMax}
      aria-valuenow={Math.round(boundedValue)}
      aria-valuetext={ariaValueText}
      aria-disabled={disabled}
      onPointerDown={onDown} onPointerMove={onMove}
      onPointerUp={onUp} onPointerCancel={onUp} onWheel={onWheel}
      onKeyDown={onKeyDown}>
      <svg viewBox="0 0 100 100">
        <defs>
          <radialGradient id={`capG${size}`} cx="0.4" cy="0.3" r="0.8">
            <stop offset="0%" stopColor="#f0d399" />
            <stop offset="55%" stopColor="#a87f3a" />
            <stop offset="100%" stopColor="#2a1c08" />
          </radialGradient>
          <linearGradient id={`bezG${size}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#d8c8a4" />
            <stop offset="100%" stopColor="#3a2c14" />
          </linearGradient>
        </defs>
        {ticks}
        <circle cx="50" cy="50" r="40" fill={`url(#bezG${size})`} />
        <circle cx="50" cy="50" r="34" fill={`url(#capG${size})`} stroke="rgba(0,0,0,0.45)" strokeWidth="0.5" />
        {Array.from({ length: 24 }).map((_, i) => {
          const a = (i / 24) * 360;
          const x1 = 50 + 34 * Math.sin((a * Math.PI) / 180);
          const y1 = 50 - 34 * Math.cos((a * Math.PI) / 180);
          const x2 = 50 + 38 * Math.sin((a * Math.PI) / 180);
          const y2 = 50 - 38 * Math.cos((a * Math.PI) / 180);
          return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke="rgba(0,0,0,0.4)" strokeWidth="0.7" />;
        })}
        <g transform={`rotate(${angle} 50 50)`}>
          <line x1="50" y1="50" x2="50" y2="20" stroke={color} strokeWidth="2.5" strokeLinecap="round" />
          <circle cx="50" cy="20" r="1.6" fill={color} />
        </g>
        <circle cx="50" cy="50" r="5" fill="#3a2c14" />
      </svg>
    </div>
  );
}

/* ---------- Segmented control ---------- */
function Segmented({ value, options, onChange }) {
  return (
    <div className="seg">
      {options.map(([v, label]) => (
        <button key={v} className={"seg-btn" + (v === value ? " active" : "")}
                onClick={() => onChange(v)}>{label}</button>
      ))}
    </div>
  );
}

/* ---------- Settings tabs ---------- */
function feedDomain(u) {
  try { return new URL(u).hostname.replace(/^www\./, ""); }
  catch { return u; }
}

function RssChips({ value, onChange, placeholder }) {
  const [draft, setDraft] = useState("");
  const list = value || [];
  const add = () => {
    const v = draft.trim();
    if (!v) return;
    if (list.includes(v)) { setDraft(""); return; }
    onChange([...list, v]);
    setDraft("");
  };
  const remove = (i) => onChange(list.filter((_, j) => j !== i));
  return (
    <div className="rss-chips">
      <div className="rss-input">
        <input value={draft}
               onChange={(e) => setDraft(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }}
               placeholder={placeholder || "paste a feed URL…"} />
        <button type="button" className="rss-add" onClick={add} disabled={!draft.trim()}>+</button>
      </div>
      {list.length > 0 && (
        <div className="rss-list">
          {list.map((u, i) => (
            <span key={i} className="rss-chip" title={u}>
              <span className="rss-dot" />
              <span className="rss-chip-name">{feedDomain(u)}</span>
              <button type="button" className="rss-x" onClick={() => remove(i)} aria-label="Remove">×</button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function SourcePresets({ presets, value, onChange }) {
  const selected = new Set(value || []);
  const toggle = (id) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onChange((presets || []).filter((preset) => next.has(preset.id)).map((preset) => preset.id));
  };

  return (
    <div className="source-presets">
      {(presets || []).map((preset) => {
        const active = selected.has(preset.id);
        return (
          <button
            key={preset.id}
            type="button"
            className={"source-chip" + (active ? " active" : "")}
            onClick={() => toggle(preset.id)}
          >
            <span className="source-dot" />
            <span>{preset.label}</span>
          </button>
        );
      })}
    </div>
  );
}

function StationsTab({ stations, selected, sourcePresets, onSelect, onChange, onNew, onDelete }) {
  const update = (k, v) => onChange({ ...selected, [k]: v });
  return (
    <div className="stations-tab">
      <div className="vibe-picker">
        <label className="vp-label">VIBE</label>
        <div className="vp-select-wrap">
          <select className="vp-select"
                  value={selected ? selected.id : ""}
                  onChange={(e) => onSelect(e.target.value)}>
            {stations.length === 0 && <option value="">NO VIBES</option>}
            {stations.map((s, i) => (
              <option key={s.id} value={s.id}>
                {pad2(i + 1)} — {s.name} · {s.hosts}H
              </option>
            ))}
          </select>
          <span className="vp-caret">▾</span>
        </div>
        <button className="vp-new" onClick={onNew}>+ NEW</button>
      </div>

      {!selected ? (
        <div className="station-edit empty">NO VIBES SAVED</div>
      ) : (
        <div className="station-edit">
          <div className="edit-grid">
            <div className="row">
              <div className="field grow">
                <label>NAME</label>
                <input value={selected.name}
                       onChange={(e) => update("name", e.target.value.toUpperCase())} />
              </div>
              <div className="field grow-2">
                <label>CUSTOM RSS · {(selected.urls || []).length}</label>
                <RssChips value={selected.urls} onChange={(v) => update("urls", v)} />
              </div>
            </div>

            <div className="field">
              <label>SOURCES</label>
              <SourcePresets
                presets={sourcePresets}
                value={selected.sourcePresetIds}
                onChange={(v) => update("sourcePresetIds", v)}
              />
            </div>

            <div className="row">
              <div className="field">
                <label>HOSTS</label>
                <Segmented value={selected.hosts} options={[[1, "Solo"], [2, "Duo"]]}
                           onChange={(v) => update("hosts", v)} />
              </div>
              <div className="field">
                <label>TONE</label>
                <Segmented value={selected.tone < 50 ? "casual" : "pro"}
                           options={[["casual", "Casual"], ["pro", "Professional"]]}
                           onChange={(v) => update("tone", v === "casual" ? 25 : 75)} />
              </div>
              <div className="field">
                <label>VOICES</label>
                <div className="voices-row compact">
                  <div className="voice-cell">
                    <span className="vc-tag">A</span>
                    <Segmented value={selected.voiceA} options={[["M", "M"], ["F", "F"]]}
                               onChange={(v) => update("voiceA", v)} />
                  </div>
                  <div className={"voice-cell" + (selected.hosts === 2 ? "" : " disabled")}>
                    <span className="vc-tag">B</span>
                    <Segmented value={selected.voiceB} options={[["M", "M"], ["F", "F"]]}
                               onChange={(v) => selected.hosts === 2 && update("voiceB", v)} />
                  </div>
                </div>
              </div>
            </div>

            <div className="field actions">
              <button className="delete-btn" onClick={() => onDelete(selected.id)}>DELETE VIBE</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function CreateVibeTab({ sourcePresets, onCreate }) {
  const [name, setName] = useState("");
  const [hosts, setHosts] = useState(1);
  const [voiceA, setVoiceA] = useState("F");
  const [voiceB, setVoiceB] = useState("M");
  const [tone, setTone] = useState("casual");
  const [urls, setUrls] = useState([]);
  const [sourcePresetIds, setSourcePresetIds] = useState([]);
  const [presetTouched, setPresetTouched] = useState(false);
  const [saving, setSaving] = useState(false);

  const valid = name.trim().length > 0 && !saving;

  useEffect(() => {
    if (presetTouched || sourcePresetIds.length > 0) return;
    setSourcePresetIds((sourcePresets || []).map((preset) => preset.id));
  }, [presetTouched, sourcePresetIds.length, sourcePresets]);

  const submit = async () => {
    if (!valid) return;
    setSaving(true);
    try {
      await onCreate({
        name: name.toUpperCase(),
        tag: "",
        hosts, voiceA, voiceB,
        tone: tone === "casual" ? 25 : 75,
        urls,
        sourcePresetIds,
        freq: "on-demand",
      });
      setName(""); setUrls([]); setHosts(1); setVoiceA("F"); setVoiceB("M"); setTone("casual");
      setSourcePresetIds((sourcePresets || []).map((preset) => preset.id));
      setPresetTouched(false);
    } catch (error) {
      console.error(error);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="create-tab">
      <div className="create-grid">
        <div className="row">
          <div className="field grow">
            <label>NAME</label>
            <input value={name} onChange={(e) => setName(e.target.value.toUpperCase())}
                   placeholder="E.G. MORNING BRIEF" />
          </div>
          <div className="field grow-2">
            <label>CUSTOM RSS · {urls.length}</label>
            <RssChips value={urls} onChange={setUrls} />
          </div>
        </div>

        <div className="field">
          <label>SOURCES</label>
          <SourcePresets
            presets={sourcePresets}
            value={sourcePresetIds}
            onChange={(v) => {
              setPresetTouched(true);
              setSourcePresetIds(v);
            }}
          />
        </div>

        <div className="row">
          <div className="field">
            <label>HOSTS</label>
            <Segmented value={hosts} options={[[1, "Solo"], [2, "Duo"]]}
                       onChange={setHosts} />
          </div>
          <div className="field">
            <label>TONE</label>
            <Segmented value={tone}
                       options={[["casual", "Casual"], ["pro", "Professional"]]}
                       onChange={setTone} />
          </div>
          <div className="field">
            <label>VOICES</label>
            <div className="voices-row compact">
              <div className="voice-cell">
                <span className="vc-tag">A</span>
                <Segmented value={voiceA} options={[["M", "M"], ["F", "F"]]}
                           onChange={setVoiceA} />
              </div>
              <div className={"voice-cell" + (hosts === 2 ? "" : " disabled")}>
                <span className="vc-tag">B</span>
                <Segmented value={voiceB} options={[["M", "M"], ["F", "F"]]}
                           onChange={(v) => hosts === 2 && setVoiceB(v)} />
              </div>
            </div>
          </div>
        </div>

        <div className="field actions">
          <button className={"create-btn" + (valid ? "" : " disabled")}
                  disabled={!valid} onClick={submit}>{saving ? "SAVING" : "CREATE VIBE"}</button>
        </div>
      </div>
    </div>
  );
}

function ApiTab({ apiBase, onApiBaseChange, apiStatus }) {
  return (
    <div className="simple-tab">
      <div className="api-grid">
        <div className="field grow-2">
          <label>Backend</label>
          <input type="url" value={apiBase} onChange={(e) => onApiBaseChange(e.target.value)} />
        </div>
        <div className="field">
          <label>Mode</label>
          <div className="mode-pill">REAL</div>
        </div>
        <div className={"api-status " + apiStatus}>
          <span className="api-dot" />
          <span>{apiStatus === "ready" ? "API READY" : apiStatus === "checking" ? "CHECKING" : "API OFFLINE"}</span>
        </div>
      </div>
    </div>
  );
}

function VoicesTab() {
  const voices = [
    { name: "AURA",     gender: "F", desc: "warm · curious · low-mid" },
    { name: "ATLAS",    gender: "M", desc: "dry · steady · baritone" },
    { name: "VESPER",   gender: "F", desc: "cool · precise · alto" },
    { name: "ORION",    gender: "M", desc: "bright · animated · tenor" },
    { name: "TRACE",    gender: "N", desc: "neutral · soft · mid" },
    { name: "CINDER",   gender: "F", desc: "smoky · slow · contralto" },
  ];
  return (
    <div className="simple-tab">
      <p className="tab-lead">Six factory voices. Tap any to preview.</p>
      <div className="voice-grid">
        {voices.map((v) => (
          <button key={v.name} className="voice-card">
            <span className="voice-name">{v.name}</span>
            <span className="voice-gender">{v.gender}</span>
            <span className="voice-desc">{v.desc}</span>
            <span className="voice-play">▸</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function AudioTab() {
  const [bands, setBands] = useState([60, 55, 70, 65, 50]);
  return (
    <div className="simple-tab">
      <p className="tab-lead">Per-device audio shaping. Applies to all stations.</p>
      <div className="eq-row">
        {["60Hz", "230Hz", "910Hz", "3.6kHz", "14kHz"].map((label, i) => (
          <div key={label} className="eq-col">
            <input type="range" min="0" max="100" value={bands[i]} orient="vertical"
                   onChange={(e) => setBands(bands.map((b, j) => j === i ? +e.target.value : b))} />
            <span className="eq-label">{label}</span>
          </div>
        ))}
      </div>
      <div className="audio-toggles">
        <label><input type="checkbox" defaultChecked /> Loudness normalization (-14 LUFS)</label>
        <label><input type="checkbox" /> Voice ducking under music</label>
        <label><input type="checkbox" defaultChecked /> Crossfade between segments</label>
      </div>
    </div>
  );
}

function AboutTab() {
  return (
    <div className="simple-tab about-tab">
      <div className="about-row"><span>MODEL</span><span>VibeFM / MK II</span></div>
      <div className="about-row"><span>SERIAL</span><span>SN-7042-3081</span></div>
      <div className="about-row"><span>FIRMWARE</span><span>2.1.4 (stable)</span></div>
      <div className="about-row"><span>VIBES</span><span>API STORED</span></div>
      <div className="about-row"><span>UPTIME</span><span>14d 03h 22m</span></div>
      <div className="about-row"><span>STORAGE</span><span>2.4 / 8.0 GB</span></div>
      <p className="about-foot">VibeFM — personal AI radio. Built for one listener.</p>
    </div>
  );
}

function SettingsPanel(props) {
  const [tab, setTab] = useState("vibes");
  const tabs = [
    ["vibes",  "My Vibes"],
    ["create", "Create Vibe"],
    ["api",    "API"],
  ];
  return (
    <div className="settings">
      <div className="settings-head">
        <div className="settings-title">VibeFM · SETTINGS</div>
        <div className="tabs">
          {tabs.map(([k, l]) => (
            <button key={k} className={"tab" + (tab === k ? " active" : "")}
                    onClick={() => setTab(k)}>{l}</button>
          ))}
        </div>
      </div>
      <div className="settings-body">
        {tab === "vibes"  && <StationsTab {...props} onNew={() => setTab("create")} />}
        {tab === "create" && <CreateVibeTab sourcePresets={props.sourcePresets} onCreate={props.onCreate} />}
        {tab === "api"    && <ApiTab {...props} />}
      </div>
    </div>
  );
}

/* ---------- App ---------- */
function App() {
  const [freqMHz, setFreqMHz] = useState(88.3);
  const [durationSec, setDurationSec] = useState(2 * 60);
  const [remainingSec, setRemainingSec] = useState(0);
  const [stations, setStations] = useState([]);
  const [editingId, setEditingId] = useState("");
  const [sourcePresets, setSourcePresets] = useState([]);
  const [isOpen, setIsOpen] = useState(false);
  const [apiBase, setApiBase] = useState(() => {
    try { return localStorage.getItem("vibefm.apiBase") || defaultApiBase(); }
    catch { return defaultApiBase(); }
  });
  const [apiStatus, setApiStatus] = useState("checking");
  const [playerState, setPlayerState] = useState("idle");
  const [playerText, setPlayerText] = useState("STANDBY");
  const [segmentProgress, setSegmentProgress] = useState({ queued: 0, played: 0, total: 0 });
  const [generationComplete, setGenerationComplete] = useState(false);

  const audioContextRef = useRef(null);
  const eventSourceRef = useRef(null);
  const activeApiBaseRef = useRef("");
  const nextStartTimeRef = useRef(0);
  const sourceRefs = useRef([]);
  const runRef = useRef(0);

  const playing = PLAYER_ACTIVE_STATES.has(playerState);

  // closest station to the current dial position
  let closestIdx = 0, closestDist = Infinity;
  stations.forEach((s, i) => {
    const d = Math.abs(s.mhz - freqMHz);
    if (d < closestDist) { closestDist = d; closestIdx = i; }
  });
  const station = stations[closestIdx] || null;
  const tuned = Boolean(station) && closestDist < 0.4;

  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => setRemainingSec((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(id);
  }, [playing]);

  useEffect(() => {
    try { localStorage.setItem("vibefm.apiBase", apiBase); }
    catch {}
    let alive = true;
    const id = setTimeout(async () => {
      setApiStatus("checking");
      try {
        const { data, apiBase: resolvedApiBase } = await requestJsonFromAnyApi(apiBase, "/api/vibes");
        if (!alive) return;
        if (resolvedApiBase !== cleanApiBase(apiBase)) {
          setApiBase(resolvedApiBase);
        }
        const presets = Array.isArray(data.presets) ? data.presets : [];
        const saved = Array.isArray(data.vibes)
          ? data.vibes.map((vibe, index) => stationFromVibe(vibe, index))
          : [];
        setSourcePresets(presets);
        setStations(saved);
        setEditingId(saved[0]?.id || "");
        if (saved[0]) setFreqMHz(saved[0].mhz);
        setApiStatus("ready");
      } catch (error) {
        if (!alive) return;
        setApiStatus("offline");
      }
    }, 300);
    return () => {
      alive = false;
      clearTimeout(id);
    };
  }, [apiBase]);

  useEffect(() => {
    return () => {
      closePlaybackHardware();
    };
  }, []);

  useEffect(() => {
    if (!generationComplete || segmentProgress.total === 0) return;
    if (segmentProgress.played >= segmentProgress.total) {
      finishPlayback();
    }
  }, [generationComplete, segmentProgress]);

  useEffect(() => {
    const fit = () => {
      const w = Math.max(window.innerWidth - 80, 100);
      const h = Math.max(window.innerHeight - 80, 100);
      const scale = Math.max(0.3, Math.min(w / 720, h / 720, 1));
      document.documentElement.style.setProperty("--device-scale", scale);
    };
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, []);

  const updateStation = (s) => setStations((list) => list.map((x) => x.id === s.id ? { ...s, backendId: null } : x));
  const createStation = async (partial) => {
    const id = Date.now();
    const base = { id, name: "NEW VIBE", tag: "", mhz: 99.0, hosts: 1, voiceA: "F", voiceB: "M", tone: 50, urls: [], length: 2, freq: "on-demand" };
    const next = { ...base, ...(partial || {}), id };
    // assign next free MHz slot if not specified
    if (!partial || partial.mhz == null) {
      let m = 88.5;
      while (stations.some((s) => Math.abs(s.mhz - m) < 0.6) && m < 107.5) m += 1.0;
      next.mhz = Math.round(m * 10) / 10;
    }

    try {
      const { data, apiBase: resolvedApiBase } = await requestJsonFromAnyApi(apiBase, "/api/vibes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(vibePayloadFromStation(next)),
      });
      if (resolvedApiBase !== cleanApiBase(apiBase)) {
        setApiBase(resolvedApiBase);
      }
      const saved = stationFromVibe(data.vibe, stations.length);
      setStations((list) => [...list, saved]);
      setEditingId(saved.id);
      setFreqMHz(saved.mhz);
      setApiStatus("ready");
      setPlayerState("idle");
      setPlayerText("VIBE SAVED");
    } catch (error) {
      setApiStatus("offline");
      setPlayerState("failed");
      setPlayerText(error.message || "SAVE FAILED");
      throw error;
    }
  };
  const deleteStation = (id) => {
    setStations((list) => {
      const next = list.filter((s) => s.id !== id);
      setEditingId(next[0]?.id || "");
      return next;
    });
  };

  function isCurrentRun(runId) {
    return runId === runRef.current;
  }

  function closePlaybackHardware() {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    sourceRefs.current.forEach((source) => {
      try { source.stop(); }
      catch {}
    });
    sourceRefs.current = [];
    if (audioContextRef.current && audioContextRef.current.state !== "closed") {
      audioContextRef.current.close().catch(() => {});
    }
    audioContextRef.current = null;
    activeApiBaseRef.current = "";
  }

  async function stopPlayback(label = "STOPPED") {
    runRef.current += 1;
    closePlaybackHardware();
    setGenerationComplete(false);
    setSegmentProgress({ queued: 0, played: 0, total: 0 });
    setRemainingSec(0);
    setPlayerState("idle");
    setPlayerText(label);
  }

  function finishPlayback() {
    if (!PLAYER_ACTIVE_STATES.has(playerState) && playerState !== "complete") return;
    closePlaybackHardware();
    setPlayerState("complete");
    setPlayerText("PLAYBACK COMPLETE");
    setRemainingSec(0);
  }

  async function startEpisode() {
    if (playing) {
      await stopPlayback();
      return;
    }
    if (!station) {
      setPlayerState("failed");
      setPlayerText("NO VIBE");
      setIsOpen(true);
      return;
    }

    const stationToPlay = station;
    const selectedDuration = Math.max(60, Math.round(durationSec || 120));
    await stopPlayback("STANDBY");
    const runId = runRef.current + 1;
    runRef.current = runId;
    setGenerationComplete(false);
    setSegmentProgress({ queued: 0, played: 0, total: 0 });
    setRemainingSec(selectedDuration);
    setPlayerState("starting");
    setPlayerText("STARTING");

    try {
      const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
      audioContextRef.current = new AudioContextCtor();
      await audioContextRef.current.resume();
      nextStartTimeRef.current = audioContextRef.current.currentTime + 0.18;

      const { data: job, apiBase: resolvedApiBase } = await requestJsonFromAnyApi(apiBase, "/api/episodes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(episodePayloadFromStation(stationToPlay, APP_MODE, selectedDuration, sourcePresets)),
      });
      if (!isCurrentRun(runId)) return;
      if (resolvedApiBase !== cleanApiBase(apiBase)) {
        setApiBase(resolvedApiBase);
      }
      activeApiBaseRef.current = resolvedApiBase;

      setPlayerState("generating");
      setPlayerText(job.vibe ? `TUNED ${job.vibe.name}` : `TUNED ${stationToPlay.name}`);
      const stream = new EventSource(`${resolvedApiBase}${job.events_url}`);
      eventSourceRef.current = stream;
      stream.addEventListener("status", (event) => handleStatus(event, runId));
      stream.addEventListener("script_ready", (event) => handleScriptReady(event, runId));
      stream.addEventListener("segment_ready", (event) => handleSegmentReady(event, runId));
      stream.addEventListener("complete", (event) => handleComplete(event, runId));
      stream.addEventListener("failed", (event) => handleFailed(event, runId));
      stream.onerror = () => {
        if (isCurrentRun(runId) && !generationComplete) {
          setPlayerText("SIGNAL RETRY");
        }
      };
    } catch (error) {
      if (!isCurrentRun(runId)) return;
      closePlaybackHardware();
      setPlayerState("failed");
      setPlayerText(error.message || "PLAY FAILED");
      setRemainingSec(0);
    }
  }

  function handleStatus(event, runId) {
    if (!isCurrentRun(runId)) return;
    const data = JSON.parse(event.data);
    setPlayerState(data.status === "rendering_audio" ? "playing" : "generating");
    setPlayerText(humanEpisodeStatus(data.status));
  }

  function handleScriptReady(event, runId) {
    if (!isCurrentRun(runId)) return;
    const data = JSON.parse(event.data);
    setSegmentProgress((progress) => ({ ...progress, total: data.segment_count || 0 }));
    setPlayerText(`${data.segment_count || 0} SEGMENTS`);
  }

  async function handleSegmentReady(event, runId) {
    if (!isCurrentRun(runId)) return;
    const segment = JSON.parse(event.data);
    try {
      await queueSegment(segment, runId);
    } catch (error) {
      if (!isCurrentRun(runId)) return;
      setPlayerState("failed");
      setPlayerText(error.message || "AUDIO FAILED");
    }
  }

  async function queueSegment(segment, runId) {
    const context = audioContextRef.current;
    if (!context) return;

    const segmentApiBase = activeApiBaseRef.current || cleanApiBase(apiBase);
    const response = await fetch(`${segmentApiBase}${segment.audio_url}`);
    if (!response.ok) {
      throw new Error(`SEGMENT ${response.status}`);
    }
    const bytes = await response.arrayBuffer();
    const buffer = await context.decodeAudioData(bytes);
    if (!isCurrentRun(runId)) return;

    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);
    const startAt = Math.max(nextStartTimeRef.current, context.currentTime + 0.06);
    source.start(startAt);
    nextStartTimeRef.current = startAt + buffer.duration + 0.04;
    sourceRefs.current.push(source);
    setPlayerState("playing");
    setPlayerText(`PLAYING ${segment.index + 1}`);
    setSegmentProgress((progress) => ({ ...progress, queued: progress.queued + 1 }));
    source.onended = () => {
      if (!isCurrentRun(runId)) return;
      setSegmentProgress((progress) => ({ ...progress, played: progress.played + 1 }));
    };
  }

  function handleComplete(event, runId) {
    if (!isCurrentRun(runId)) return;
    const data = JSON.parse(event.data);
    setGenerationComplete(true);
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    if (!data.audio_url && segmentProgress.queued === 0) {
      setPlayerState("complete");
      setPlayerText("COMPLETE");
      setRemainingSec(0);
    } else {
      setPlayerText("ALL QUEUED");
    }
  }

  function handleFailed(event, runId) {
    if (!isCurrentRun(runId)) return;
    const data = JSON.parse(event.data);
    closePlaybackHardware();
    setPlayerState("failed");
    setPlayerText(data.error || "FAILED");
    setRemainingSec(0);
  }

  const timerDisplay = formatTimerSeconds(playing ? remainingSec : durationSec);
  const transportLabel = playing ? "STOP" : "PLAY";
  const statusLabel = playerText.length > 22 ? `${playerText.slice(0, 21)}...` : playerText;
  const editing = stations.find((s) => s.id === editingId) || stations[0] || null;

  return (
    <div className="viewport">
      <div className="device">
        <div className="mount"></div>
        <div className="antenna"></div>

        {/* SETTINGS push button — top right of body */}
        <button className={"settings-btn" + (isOpen ? " active" : "")}
                onClick={() => setIsOpen((o) => !o)}>
          {isOpen ? "CLOSE" : "SETTINGS"}
        </button>

        <div className="body">
          <div className="top-bar">
            <div className="knob-cell">
              <Knob
                value={playing ? remainingSec : durationSec}
                max={TIMER_MAX_SEC}
                onChange={(v) => !playing && setDurationSec(Math.max(60, Math.round(v / 60) * 60))}
                color="#c5481e"
                step={60}
                ariaLabel="Episode length"
                ariaValueText={timerDisplay}
                disabled={playing}
              />
              <span className="knob-label">LENGTH</span>
              <span className="knob-value">{timerDisplay}</span>
            </div>

            <div className="display">
              <div className="display-analyzer" aria-hidden="true">
                <Analyzer playing={playing} columns={28} rows={9} />
              </div>
              <div className="disp-row">
                <span className="disp-eyebrow">
                  {playing ? "▸ ON AIR" : playerState === "failed" ? "ERROR" : playerState === "complete" ? "COMPLETE" : "STANDBY"}
                </span>
                <span className={"power-dot" + (playing ? " on" : "")}></span>
              </div>
              <div className="disp-row">
                <span className="disp-station">
                  {tuned ? station.name : station ? `${freqMHz.toFixed(1)} FM` : "NO VIBES"}
                </span>
                <span className="disp-time">{timerDisplay}</span>
              </div>
              <TunerStrip freq={freqMHz} stations={stations} onSeek={(v) => setFreqMHz(v)} />
            </div>

            <div className="knob-cell">
              <Knob
                value={freqMHz - FREQ_MIN}
                max={FREQ_MAX - FREQ_MIN}
                onChange={(v) => setFreqMHz(Math.round((v + FREQ_MIN) * 10) / 10)}
                color="#e8d8b6"
                step={0.1}
                ariaLabel="Tuning frequency"
                ariaValueText={`${freqMHz.toFixed(1)} MHz`}
              />
              <span className="knob-label">TUNE · MHz</span>
              <span className="knob-value">{freqMHz.toFixed(1)}</span>
            </div>
          </div>

          {/* grille area — opens to settings */}
          <div className={"grille-area" + (isOpen ? " open" : "")}>
            <div className="cabinet">
              {[14, 32, 50, 68, 86].map((x, i) => (
                <span key={i} className={"glow" + (playing ? " on" : "")}
                      style={{ left: `${x}%`, animationDelay: `${i * 0.32}s`, top: i === 2 ? "55%" : "45%" }}></span>
              ))}
            </div>

            <SettingsPanel
              stations={stations}
              sourcePresets={sourcePresets}
              selected={editing}
              onSelect={setEditingId}
              onChange={updateStation}
              onCreate={createStation}
              onDelete={deleteStation}
              apiBase={apiBase}
              onApiBaseChange={setApiBase}
              apiStatus={apiStatus}
            />

            <div className={"grille-panel" + (isOpen ? " open" : "")}></div>
          </div>

          <div className="foot">
            <span className="brand">VibeFM</span>
            <div className="transport">
              <button className={"play-btn" + (playing ? " active" : "")}
                      type="button"
                      disabled={!station && !playing}
                      onClick={startEpisode}>
                {transportLabel}
              </button>
              <div className="led">
                <span className={"lamp" + (playing ? " on" : "")}></span>
                <span>{statusLabel}</span>
              </div>
            </div>
            <span>SN-7042</span>
          </div>

          <div className="feet"><span></span><span></span></div>
        </div>
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
