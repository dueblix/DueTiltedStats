"""
flask_overlay.py — Flask app serving the OBS browser-source overlay
and the JSON API its polling JavaScript consumes.

Usage:
    from watcher import Watcher
    from flask_overlay import create_app

    watcher = Watcher(db_path="tilted.db", streamer_username="dueblix")
    watcher.start()

    app = create_app(watcher, db_path="tilted.db")
    # Optionally pass config_path= to override the default config.json location.
    app.run(host="127.0.0.1", port=5000)
"""

import copy
import json
import os
import sys
import tempfile

from flask import Flask, Response, jsonify, request

import db


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "global": {
        "font_family": "Courier New, monospace",
    },
    "leaderboard": {
        "enabled": True,
        "panel_width": 310,
        "font_size": 40,
        "font_colour": "#ffffff",
        "header_font_override": {
            "enabled": False,
            "font_size": 40,
            "font_colour": "#ffffff",
            "bg_colour": "#000000",
            "bg_opacity": 0.80,
        },
        "opacity": 0.60,
        "row_background_colour": "#1a1a1a",
        "row_background_alt": {
            "enabled": False,
            "colour": "#2a2a2a",
            "opacity": 0.60,
        },
        "row_separator": "none",
        "show_session_label": True,
        "columns": [
            {"key": "points",   "label": "P", "visible": True},
            {"key": "survived", "label": "S", "visible": True},
            {"key": "races",    "label": "R", "visible": True},
        ],
    },
    "bottom_bar": {
        "enabled": True,
        "font_size": 20,
        "font_colour": "#ffffff",
        "opacity": 0.75,
    },
}


def get_app_dir() -> str:
    """Return the directory that contains config.json at runtime.

    When running from source this is the project root (next to flask_overlay.py).
    When packaged with PyInstaller (sys.frozen=True) it is the directory of the
    compiled executable so the config survives alongside the .exe.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


CONFIG_PATH = os.path.join(get_app_dir(), "config.json")


def _deep_merge(base: dict, override: dict) -> dict:
    """Return a new dict: override values recursively merged over base.

    Type safety: if the base value at a key is a dict or list, an override
    value of a different type is silently ignored to prevent structural damage
    from a corrupt or manually-edited config file.
    """
    result = copy.deepcopy(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        elif key in result and isinstance(result[key], dict) and not isinstance(val, dict):
            pass  # don't clobber a dict section with a scalar/null
        elif key in result and isinstance(result[key], list) and not isinstance(val, list):
            pass  # don't clobber a list (e.g. columns) with a scalar/null
        else:
            result[key] = copy.deepcopy(val)
    return result


def get_config(path: str | None = None) -> dict:
    """Load config from *path*, deep-merging over defaults. Falls back to defaults on any error."""
    p = path or CONFIG_PATH
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return copy.deepcopy(DEFAULT_CONFIG)
        # Only keep known top-level keys; old-schema files fall back to defaults
        known = {k: v for k, v in data.items() if k in DEFAULT_CONFIG}
        return _deep_merge(DEFAULT_CONFIG, known)
    except (OSError, json.JSONDecodeError):
        return copy.deepcopy(DEFAULT_CONFIG)


def save_config(config: dict, path: str | None = None) -> None:
    p = path or CONFIG_PATH
    dir_ = os.path.dirname(p) or "."
    with tempfile.NamedTemporaryFile(
        "w", dir=dir_, suffix=".tmp", delete=False, encoding="utf-8"
    ) as f:
        json.dump(config, f, indent=2)
        tmp = f.name
    os.replace(tmp, p)  # atomic on both POSIX and Windows


# ---------------------------------------------------------------------------
# HTML overlay (embedded for PyInstaller compatibility)
# ---------------------------------------------------------------------------

_OVERLAY_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Source+Code+Pro:wght@400;700&family=Roboto+Mono:wght@400;700&family=JetBrains+Mono:wght@400;700&family=Fira+Code:wght@400;700&family=Space+Mono:wght@400;700&family=Inconsolata:wght@400;700&family=IBM+Plex+Mono:wght@400;700&family=Barlow+Condensed:wght@400;700&family=Oswald:wght@400;700&family=Rajdhani:wght@400;600&family=Chakra+Petch:wght@400;700&family=Exo+2:wght@400;700&family=Bebas+Neue&family=Roboto:wght@400;700&family=Inter:wght@400;700&family=Lato:wght@400;700&family=Montserrat:wght@400;700&family=Open+Sans:wght@400;700&family=Nunito:wght@400;700&display=swap">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    --font-family: 'Courier New', monospace;
    --panel-width: 310px;
    --panel-opacity: 0.6;
    --row-font-size: 40px;
    --row-font-colour: #ffffff;
    --header-font-size: 40px;
    --header-font-colour: #ffffff;
    --row-bg: #1a1a1a;
    --row-bg-alt: #2a2a2a;
    --row-separator: none;
    --bottom-bar-opacity: 0.75;
    --bottom-bar-font-size: 20px;
    --bottom-bar-font-colour: #ffffff;

    background: transparent;
    font-family: var(--font-family);
    font-size: 14px;
    color: #ffffff;
    width: 100vw;
    height: 100vh;
    overflow: hidden;
    position: relative;
  }

  /* ---- Right panel: leaderboard ---- */
  #right-panel {
    position: absolute;
    top: 0;
    bottom: 0;
    right: 0;
    width: var(--panel-width);
    z-index: 1;
  }

  #status {
    background: rgba(0, 0, 0, var(--panel-opacity));
    color: #aaaaaa;
    font-size: 11px;
    padding: 6px 10px;
    text-align: center;
    letter-spacing: 0.06em;
  }

  #leaderboard {
    width: 100%;
    border-collapse: collapse;
    table-layout: auto;
  }

  #leaderboard thead tr {
    background: var(--header-bg);
  }

  #leaderboard thead th {
    color: var(--header-font-colour);
    font-size: var(--header-font-size);
    font-weight: normal;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    padding: 4px 6px;
    text-align: center;
    white-space: nowrap;
  }

  #leaderboard thead th.name {
    text-align: center;
    width: 100%;
  }

  #leaderboard tbody tr {
    background: var(--row-bg);
    border-bottom: var(--row-separator);
    height: 54px;
  }

  #leaderboard tbody tr:nth-child(odd) {
    background: var(--row-bg-alt);
  }

  #leaderboard tbody td {
    padding: 4px 6px;
    vertical-align: middle;
    white-space: nowrap;
    text-align: center;
    font-size: var(--row-font-size);
    color: var(--row-font-colour);
  }

  #leaderboard tbody td.name {
    text-align: left;
    width: 100%;
    max-width: 0;
    overflow: hidden;
    text-overflow: clip;
    font-size: var(--row-font-size);
    font-weight: bold;
    color: #ffffff;
    padding-right: 10px;
  }

  /* ---- Bottom bar: level recap ---- */
  #bottom-bar {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    background: rgba(0, 0, 0, var(--bottom-bar-opacity));
    display: none;
  }

  #level-info {
    display: flex;
    align-items: center;
    gap: 24px;
    padding: 6px 12px;
    letter-spacing: 0.04em;
  }

  #level-info .cell {
    display: flex;
    flex-direction: column;
    align-items: center;
  }

  #level-info .cell .label {
    color: #aaaaaa;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.1em;
  }

  #level-info .cell .value {
    color: var(--bottom-bar-font-colour);
    font-size: var(--bottom-bar-font-size);
  }
</style>
</head>
<body>

  <div id="right-panel">
    <div id="status">Waiting for game...</div>
    <table id="leaderboard">
      <thead>
        <tr id="lb-head">
          <th class="name">Player</th>
        </tr>
      </thead>
      <tbody id="lb-body"></tbody>
    </table>
  </div>

  <div id="bottom-bar">
    <div id="level-info">
      <div class="cell">
        <span class="label">Level</span>
        <span class="value" id="li-level">—</span>
      </div>
      <div class="cell">
        <span class="label">Time</span>
        <span class="value" id="li-time">—</span>
      </div>
      <div class="cell">
        <span class="label">Saved</span>
        <span class="value" id="li-saved">—</span>
      </div>
      <div class="cell">
        <span class="label">Points</span>
        <span class="value" id="li-pts">—</span>
      </div>
    </div>
  </div>

<script>
  const POLL_INTERVAL = 2000;

  let rowCount = null;
  let activeColumns = [];  // [{key, label}] for visible columns in order
  let currentConfig = null;
  let lastLayoutSig = null;  // detects layout-affecting config changes

  function layoutSig(lb) {
    // Captures fields that affect row height or column structure, so the header
    // and rowCount are rebuilt only when something layout-relevant changes.
    //   font_size        — body row height
    //   headerFontSize   — thead height (header_font_override may differ from body)
    //   cols             — visible column set and labels
    // Excluded: panel_width, colours, opacity — none affect row or header height.
    const hdr = lb.header_font_override || {};
    const headerFontSize = hdr.enabled ? hdr.font_size : lb.font_size;
    const cols = lb.columns.filter(c => c.visible).map(c => `${c.key}:${c.label}`).join(',');
    return `${lb.font_size}|${headerFontSize}|${cols}`;
  }

  // Maps each config column key to the matching field name in the /api/state
  // player objects. When a new column type is added to DEFAULT_CONFIG, a
  // corresponding entry must be added here AND the /api/state route must
  // include that field in each player dict.
  const COL_FIELD = {
    points:   'exp_earned',
    survived: 'levels_survived',
    races:    'levels_played',
  };

  // Lighten each RGB channel by 16/255 (~6%) to produce the automatic
  // alternating row colour when row_background_alt.enabled is false.
  // Fallback '#2a2a2a' matches the default alt colour in DEFAULT_CONFIG.
  function deriveAltColour(hex) {
    if (!hex || hex.length < 7) return '#2a2a2a';
    const r = Math.min(255, parseInt(hex.slice(1, 3), 16) + 16);
    const g = Math.min(255, parseInt(hex.slice(3, 5), 16) + 16);
    const b = Math.min(255, parseInt(hex.slice(5, 7), 16) + 16);
    return '#' + [r, g, b].map(v => v.toString(16).padStart(2, '0')).join('');
  }

  function hexToRgba(hex, alpha) {
    if (!hex || hex.length < 7) return `rgba(0,0,0,${alpha})`;
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return `rgba(${r},${g},${b},${alpha})`;
  }

  async function applyConfig() {
    let cfg;
    try {
      const resp = await fetch('/api/config');
      if (!resp.ok) return;
      cfg = await resp.json();
    } catch (_) {
      return;
    }

    currentConfig = cfg;
    const body = document.body;
    const lb   = cfg.leaderboard;
    const bb   = cfg.bottom_bar;

    // leaderboard.enabled is config-only: hide the panel regardless of game state.
    // (bottom_bar.enabled is handled in refresh() where game state is also checked.)
    document.getElementById('right-panel').style.display = lb.enabled ? '' : 'none';

    // --- Global + leaderboard layout ---
    body.style.setProperty('--font-family',     cfg.global.font_family);
    body.style.setProperty('--panel-width',      lb.panel_width + 'px');
    body.style.setProperty('--panel-opacity',    lb.opacity);
    body.style.setProperty('--row-font-size',    lb.font_size + 'px');
    body.style.setProperty('--row-font-colour',  lb.font_colour);

    // --- Header font: use override values when enabled, else inherit from row ---
    // Guard with || {} so a missing nested object degrades to body values.
    const hdr = lb.header_font_override || {};
    body.style.setProperty('--header-font-size',
        (hdr.enabled ? hdr.font_size : lb.font_size) + 'px');
    body.style.setProperty('--header-font-colour',
        hdr.enabled ? hdr.font_colour : lb.font_colour);

    // --- Row backgrounds ---
    const rowBg  = lb.row_background_colour;
    const altCfg = lb.row_background_alt || {};
    const altHex     = altCfg.enabled ? altCfg.colour               : rowBg;
    const altOpacity = altCfg.enabled ? (altCfg.opacity ?? lb.opacity) : lb.opacity;
    body.style.setProperty('--row-bg',     hexToRgba(rowBg,  lb.opacity));
    body.style.setProperty('--row-bg-alt', hexToRgba(altHex, altOpacity));

    // --- Header background ---
    const hdrBgHex     = hdr.enabled ? (hdr.bg_colour  || '#000000') : rowBg;
    const hdrBgOpacity = hdr.enabled ? (hdr.bg_opacity ?? lb.opacity) : lb.opacity;
    body.style.setProperty('--header-bg', hexToRgba(hdrBgHex, hdrBgOpacity));

    body.style.setProperty('--row-separator',
        lb.row_separator === 'line' ? '1px solid rgba(255,255,255,0.1)' : 'none');

    // --- Bottom bar ---
    body.style.setProperty('--bottom-bar-opacity',      bb.opacity);
    body.style.setProperty('--bottom-bar-font-size',    bb.font_size + 'px');
    body.style.setProperty('--bottom-bar-font-colour',  bb.font_colour);

    // Rebuild column header and reset row count only when layout actually changed
    const sig = layoutSig(lb);
    if (sig !== lastLayoutSig) {
      lastLayoutSig  = sig;
      activeColumns  = lb.columns.filter(c => c.visible);
      const headRow  = document.getElementById('lb-head');
      headRow.innerHTML = '<th class="name">Player</th>';
      for (const col of activeColumns) {
        const th = document.createElement('th');
        th.textContent = col.label;
        headRow.appendChild(th);
      }
      rowCount = null;
    }
  }

  function calcRowCount() {
    const panel    = document.getElementById('right-panel');
    const thead    = document.querySelector('#leaderboard thead tr');
    const available = panel.clientHeight - thead.offsetHeight;
    const tbody    = document.getElementById('lb-body');
    // Insert a representative row to measure its rendered height, then remove it.
    const test     = document.createElement('tr');
    const emptyCells = activeColumns.map(() => '<td>0</td>').join('');
    test.innerHTML = `<td class="name">x</td>${emptyCells}`;
    tbody.appendChild(test);
    const rowH = test.offsetHeight || 54;  // 54px matches the CSS row height
    tbody.removeChild(test);
    return Math.max(1, Math.floor(available / rowH));
  }

  function renderRows(players) {
    if (!rowCount) rowCount = calcRowCount();
    const tbody = document.getElementById('lb-body');
    tbody.innerHTML = '';
    for (let i = 0; i < rowCount; i++) {
      const p = players[i];
      const tr = document.createElement('tr');
      if (p) {
        const dataCells = activeColumns.map(col => {
          const field = COL_FIELD[col.key];
          return `<td>${field !== undefined ? p[field] : ''}</td>`;
        }).join('');
        tr.innerHTML = `<td class="name" style="color:${p.colour}">${escHtml(p.display_name)}</td>${dataCells}`;
      } else {
        const emptyCells = activeColumns.map(() => '<td></td>').join('');
        tr.innerHTML = `<td class="name"></td>${emptyCells}`;
      }
      tbody.appendChild(tr);
    }
  }

  async function refresh() {
    let data;
    try {
      const resp = await fetch('/api/state');
      if (!resp.ok) return;
      data = await resp.json();
    } catch (_) {
      return;
    }

    const statusDiv = document.getElementById('status');
    const bottomBar = document.getElementById('bottom-bar');

    if (data.status === 'waiting') {
      renderRows([]);
      bottomBar.style.display = 'none';
      statusDiv.style.display = 'block';
      statusDiv.textContent   = 'Waiting for game...';
      return;
    }

    const showLabel = currentConfig?.leaderboard?.show_session_label !== false;
    statusDiv.textContent   = data.status === 'idle' ? 'PREVIOUS SESSION' : '';
    statusDiv.style.display = data.status === 'idle' && showLabel ? 'block' : 'none';

    // --- Bottom bar ---
    // bottom_bar.enabled is gated by BOTH config AND game state: only show when
    // the config allows it AND there is active level data to display.
    // currentConfig is null only if applyConfig hasn't succeeded yet on first tick.
    if (data.last_level && currentConfig?.bottom_bar.enabled) {
      const ll = data.last_level;

      document.getElementById('li-level').textContent = ll.level_number;

      if (ll.elapsed_time !== null) {
        const m = Math.floor(ll.elapsed_time / 60).toString().padStart(2, '0');
        const s = (ll.elapsed_time % 60).toFixed(3).padStart(6, '0');
        document.getElementById('li-time').textContent = `${m}:${s}`;
      } else {
        document.getElementById('li-time').textContent = '—';
      }

      const pct = ll.total_players > 0
        ? Math.round(ll.survivors / ll.total_players * 100)
        : 0;
      document.getElementById('li-saved').textContent =
        `${ll.survivors}/${ll.total_players} (${pct}%)`;

      document.getElementById('li-pts').textContent =
        ll.level_exp !== null ? ll.level_exp : '—';

      bottomBar.style.display = 'block';
    } else {
      bottomBar.style.display = 'none';
    }

    // --- Leaderboard ---
    renderRows(data.run_leaderboard || []);
  }

  function escHtml(str) {
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // applyConfig must complete before refresh: refresh reads activeColumns
  // (set by applyConfig) to build leaderboard rows. setTimeout (not setInterval)
  // ensures the next tick only starts after the current one finishes, preventing
  // concurrent ticks from interleaving DOM writes on slow connections.
  async function tick() {
    await applyConfig();
    await refresh();
    setTimeout(tick, POLL_INTERVAL);
  }

  tick();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Config page HTML (embedded)
# ---------------------------------------------------------------------------

_CONFIG_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Overlay Config</title>
<style>
  body { font-family: sans-serif; max-width: 640px; margin: 40px auto; padding: 0 16px; }
  h1   { margin-bottom: 24px; }
  label { display: block; margin: 8px 0 2px; font-weight: bold; font-size: 0.9em; }
  input[type=number], input[type=text], select { width: 100%; padding: 6px; box-sizing: border-box; }
  input[type=color] { width: 48px; height: 32px; padding: 2px; border: 1px solid #ccc; cursor: pointer; vertical-align: middle; }
  input[type=checkbox] { cursor: pointer; }
  #font_family { margin-top: 4px; }
  details { border: 1px solid #ddd; border-radius: 4px; margin: 12px 0; }
  details details { margin: 10px 0 4px; }
  summary { padding: 10px 12px; cursor: pointer; font-weight: bold; font-size: 1em; list-style: none; display: flex; align-items: center; gap: 10px; user-select: none; }
  summary::-webkit-details-marker { display: none; }
  summary::marker { display: none; }
  .details-body { padding: 4px 12px 12px; }
  .field-pair { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 8px 0; }
  .inline-row { display: flex; align-items: center; gap: 10px; margin: 8px 0; }
  .inline-row label { margin: 0; }
  .col-row { display: flex; align-items: center; gap: 8px; margin: 4px 0; padding: 4px 0; border-bottom: 1px solid #f0f0f0; }
  .col-row:last-child { border-bottom: none; }
  .col-key { font-size: 0.8em; color: #999; }
  .col-label-input { width: 60px; padding: 4px 6px; font-size: 0.9em; }
  .move-btn { padding: 2px 7px; font-size: 0.85em; cursor: pointer; border: 1px solid #ccc; border-radius: 3px; background: #f8f8f8; }
  .move-btn:hover { background: #e8e8e8; }
  .actions { margin-top: 24px; display: flex; gap: 12px; align-items: center; }
  button { padding: 8px 20px; cursor: pointer; }
  #save-btn { background: #2a7; color: #fff; border: none; border-radius: 4px; }
  #reset-btn { background: none; border: 1px solid #aaa; border-radius: 4px; }
  #msg { color: green; font-size: 0.9em; }
  .note { margin-top: 8px; font-size: 0.85em; color: #666; }
  a { color: #26a; }
</style>
</head>
<body>
<h1>Overlay Config</h1>
<p><a href="/overlay">View overlay</a></p>

<form id="cfg-form">

  <!-- Global -->
  <details id="sec-global">
    <summary>Global</summary>
    <div class="details-body">
      <label for="font_filter">Font family</label>
      <input type="text" id="font_filter" placeholder="Filter fonts…" autocomplete="off">
      <select id="font_family"></select>
    </div>
  </details>

  <!-- Leaderboard -->
  <details id="sec-leaderboard">
    <summary>
      <input type="checkbox" id="lb_enabled"> Leaderboard
    </summary>
    <div class="details-body">
      <label for="lb_panel_width">Panel width (px)</label>
      <input type="number" id="lb_panel_width" min="100" max="800">
      <div class="field-pair">
        <div>
          <label for="lb_font_size">Font size (px)</label>
          <input type="number" id="lb_font_size" min="8" max="120">
        </div>
        <div>
          <label for="lb_font_colour">Font colour</label>
          <input type="color" id="lb_font_colour">
        </div>
      </div>

      <!-- Header override -->
      <details id="sec-header-override">
        <summary>
          <input type="checkbox" id="hdr_override_enabled"> Header override
        </summary>
        <div class="details-body">
          <div class="field-pair">
            <div>
              <label for="hdr_font_size">Font size (px)</label>
              <input type="number" id="hdr_font_size" min="8" max="120">
            </div>
            <div>
              <label for="hdr_font_colour">Font colour</label>
              <input type="color" id="hdr_font_colour">
            </div>
          </div>
          <div class="field-pair">
            <div>
              <label for="hdr_bg_opacity">Opacity (0–1)</label>
              <input type="number" id="hdr_bg_opacity" min="0" max="1" step="0.05">
            </div>
            <div>
              <label for="hdr_bg_colour">Background colour</label>
              <input type="color" id="hdr_bg_colour">
            </div>
          </div>
        </div>
      </details>

      <!-- Row appearance -->
      <details id="sec-rows">
        <summary>Row appearance</summary>
        <div class="details-body">
          <div class="field-pair">
            <div>
              <label for="lb_opacity">Opacity (0–1)</label>
              <input type="number" id="lb_opacity" min="0" max="1" step="0.05">
            </div>
            <div>
              <label for="row_bg_colour">Row background colour</label>
              <input type="color" id="row_bg_colour">
            </div>
          </div>

          <details id="sec-alt-colour">
            <summary>
              <input type="checkbox" id="row_bg_alt_enabled"> Alternating row colour
            </summary>
            <div class="details-body">
              <div class="field-pair">
                <div>
                  <label for="row_bg_alt_opacity">Opacity (0–1)</label>
                  <input type="number" id="row_bg_alt_opacity" min="0" max="1" step="0.05">
                </div>
                <div>
                  <label for="row_bg_alt_colour">Alt row colour</label>
                  <div class="inline-row" style="margin:0">
                    <input type="color" id="row_bg_alt_colour">
                    <button type="button" id="row_bg_alt_reset">Reset to default</button>
                  </div>
                </div>
              </div>
            </div>
          </details>

          <label for="row_separator">Row separator</label>
          <select id="row_separator">
            <option value="none">None</option>
            <option value="line">Line</option>
          </select>
        </div>
      </details>

      <div class="inline-row" style="margin-top:8px">
        <input type="checkbox" id="lb_show_session_label">
        <label for="lb_show_session_label" style="margin:0">Show "Previous Session" label</label>
      </div>

      <label style="margin-top:12px">Columns</label>
      <div id="columns-list"></div>
    </div>
  </details>

  <!-- Bottom Bar -->
  <details id="sec-bottom-bar">
    <summary>
      <input type="checkbox" id="bb_enabled"> Bottom Bar
    </summary>
    <div class="details-body">
      <div class="field-pair">
        <div>
          <label for="bb_font_size">Font size (px)</label>
          <input type="number" id="bb_font_size" min="8" max="120">
        </div>
        <div>
          <label for="bb_opacity">Opacity (0–1)</label>
          <input type="number" id="bb_opacity" min="0" max="1" step="0.05">
        </div>
      </div>
      <div class="inline-row">
        <label for="bb_font_colour" style="margin:0">Font colour</label>
        <input type="color" id="bb_font_colour">
      </div>
    </div>
  </details>

  <div class="actions">
    <button type="submit" id="save-btn">Save</button>
    <button type="button" id="reset-btn">Reset to defaults</button>
    <span id="msg"></span>
  </div>
  <p class="note">Changes are picked up by the overlay automatically within a few seconds.</p>
</form>

<script>
  // NOTE: Adding a Google Font here also requires updating the stylesheet URL in _OVERLAY_HTML.
  const FONTS = [
    // Monospaced
    {label: "Courier New",      value: "Courier New, monospace",           category: "Mono"},
    {label: "Consolas",         value: "Consolas, monospace",              category: "Mono"},
    {label: "Lucida Console",   value: "Lucida Console, monospace",        category: "Mono"},
    {label: "Source Code Pro",  value: "'Source Code Pro', monospace",     category: "Mono"},
    {label: "Roboto Mono",      value: "'Roboto Mono', monospace",         category: "Mono"},
    {label: "JetBrains Mono",   value: "'JetBrains Mono', monospace",      category: "Mono"},
    {label: "Fira Code",        value: "'Fira Code', monospace",           category: "Mono"},
    {label: "Space Mono",       value: "'Space Mono', monospace",          category: "Mono"},
    {label: "Inconsolata",      value: "Inconsolata, monospace",           category: "Mono"},
    {label: "IBM Plex Mono",    value: "'IBM Plex Mono', monospace",       category: "Mono"},
    // Condensed
    {label: "Barlow Condensed", value: "'Barlow Condensed', sans-serif",   category: "Condensed"},
    {label: "Oswald",           value: "Oswald, sans-serif",               category: "Condensed"},
    {label: "Rajdhani",         value: "Rajdhani, sans-serif",             category: "Condensed"},
    {label: "Chakra Petch",     value: "'Chakra Petch', sans-serif",       category: "Condensed"},
    {label: "Exo 2",            value: "'Exo 2', sans-serif",              category: "Condensed"},
    {label: "Bebas Neue",       value: "'Bebas Neue', sans-serif",         category: "Condensed"},
    // Sans-serif
    {label: "Roboto",           value: "Roboto, sans-serif",               category: "Sans-serif"},
    {label: "Inter",            value: "Inter, sans-serif",                category: "Sans-serif"},
    {label: "Lato",             value: "Lato, sans-serif",                 category: "Sans-serif"},
    {label: "Montserrat",       value: "Montserrat, sans-serif",           category: "Sans-serif"},
    {label: "Open Sans",        value: "'Open Sans', sans-serif",          category: "Sans-serif"},
    {label: "Nunito",           value: "Nunito, sans-serif",               category: "Sans-serif"},
  ];

  function buildFontSelect(filter) {
    const sel = document.getElementById('font_family');
    const current = sel.value;
    const query = filter.toLowerCase();
    const visible = FONTS.filter(f =>
      f.label.toLowerCase().includes(query) || f.category.toLowerCase().includes(query)
    );
    if (visible.length === 0) return;  // keep existing options rather than leaving select empty
    sel.innerHTML = '';
    let grp = null, lastCat = null;
    for (const f of visible) {
      if (f.category !== lastCat) {
        grp = document.createElement('optgroup');
        grp.label = f.category;
        sel.appendChild(grp);
        lastCat = f.category;
      }
      const opt = document.createElement('option');
      opt.value = f.value;
      opt.textContent = f.label;
      grp.appendChild(opt);
    }
    if ([...sel.options].find(o => o.value === current)) sel.value = current;
  }

  let currentCfg = null;

  async function loadConfig() {
    try {
      const resp = await fetch('/api/config');
      if (!resp.ok) throw new Error(resp.status);
      currentCfg = await resp.json();
      populateForm(currentCfg);
    } catch (_) {
      document.getElementById('msg').style.color = 'red';
      document.getElementById('msg').textContent = 'Failed to load config. Refresh to retry.';
    }
  }

  function populateForm(cfg) {
    // Global
    document.getElementById('font_filter').value = '';
    buildFontSelect('');
    const sel = document.getElementById('font_family');
    const match = [...sel.options].find(o => o.value === cfg.global.font_family);
    sel.value = match ? cfg.global.font_family : sel.options[0].value;

    // Leaderboard
    document.getElementById('lb_enabled').checked          = cfg.leaderboard.enabled;
    document.getElementById('lb_panel_width').value        = cfg.leaderboard.panel_width;
    document.getElementById('lb_opacity').value            = cfg.leaderboard.opacity;
    document.getElementById('lb_font_size').value          = cfg.leaderboard.font_size;
    document.getElementById('lb_font_colour').value        = cfg.leaderboard.font_colour;

    // Header override
    document.getElementById('hdr_override_enabled').checked = cfg.leaderboard.header_font_override.enabled;
    document.getElementById('hdr_font_size').value           = cfg.leaderboard.header_font_override.font_size;
    document.getElementById('hdr_font_colour').value         = cfg.leaderboard.header_font_override.font_colour;
    document.getElementById('hdr_bg_colour').value           = cfg.leaderboard.header_font_override.bg_colour;
    document.getElementById('hdr_bg_opacity').value          = cfg.leaderboard.header_font_override.bg_opacity;

    // Row background
    document.getElementById('row_bg_colour').value         = cfg.leaderboard.row_background_colour;
    document.getElementById('row_bg_alt_enabled').checked  = cfg.leaderboard.row_background_alt.enabled;
    document.getElementById('row_bg_alt_opacity').value    = cfg.leaderboard.row_background_alt.opacity;
    document.getElementById('row_bg_alt_colour').value     = cfg.leaderboard.row_background_alt.colour;

    // Row separator
    document.getElementById('row_separator').value              = cfg.leaderboard.row_separator;
    document.getElementById('lb_show_session_label').checked    = cfg.leaderboard.show_session_label;

    // Columns
    buildColumnRows(cfg.leaderboard.columns);

    // Bottom bar
    document.getElementById('bb_enabled').checked   = cfg.bottom_bar.enabled;
    document.getElementById('bb_opacity').value     = cfg.bottom_bar.opacity;
    document.getElementById('bb_font_size').value   = cfg.bottom_bar.font_size;
    document.getElementById('bb_font_colour').value = cfg.bottom_bar.font_colour;
  }

  function buildColumnRows(columns) {
    const list = document.getElementById('columns-list');
    list.innerHTML = '';
    for (const col of columns) {
      const row = document.createElement('div');
      row.className = 'col-row';
      row.dataset.key = col.key;
      row.innerHTML = `
        <button type="button" class="move-btn" onclick="moveColumn('${col.key}', -1)">&#9650;</button>
        <button type="button" class="move-btn" onclick="moveColumn('${col.key}', +1)">&#9660;</button>
        <input type="text" class="col-label-input" id="col_label_${col.key}">
        <input type="checkbox" id="col_vis_${col.key}" ${col.visible ? 'checked' : ''}>
        <span class="col-key">${col.key}</span>
      `;
      const labelInput = row.querySelector('.col-label-input');
      labelInput.value = col.label;
      labelInput.dataset.savedLabel = col.label;
      labelInput.addEventListener('blur', function() {
        if (this.value.trim() === '') this.value = this.dataset.savedLabel;
      });
      list.appendChild(row);
    }
  }

  function moveColumn(key, dir) {
    const list = document.getElementById('columns-list');
    const rows = [...list.querySelectorAll('.col-row')];
    const idx = rows.findIndex(r => r.dataset.key === key);
    const target = idx + dir;
    if (target < 0 || target >= rows.length) return;
    if (dir === -1) list.insertBefore(rows[idx], rows[target]);
    else            list.insertBefore(rows[target], rows[idx]);
  }

  function numVal(id, fallback) {
    const v = parseFloat(document.getElementById(id).value);
    return isNaN(v) ? fallback : v;
  }

  function collectPayload() {
    const columns = [];
    for (const row of document.querySelectorAll('#columns-list .col-row')) {
      const key = row.dataset.key;
      const orig = currentCfg.leaderboard.columns.find(c => c.key === key).label;
      columns.push({
        key,
        label:   document.getElementById('col_label_' + key).value.trim() || orig,
        visible: document.getElementById('col_vis_' + key).checked,
      });
    }
    return {
      global: {
        font_family: document.getElementById('font_family').value,
      },
      leaderboard: {
        enabled:     document.getElementById('lb_enabled').checked,
        panel_width: numVal('lb_panel_width', currentCfg.leaderboard.panel_width),
        opacity:     numVal('lb_opacity', currentCfg.leaderboard.opacity),
        font_size:   numVal('lb_font_size', currentCfg.leaderboard.font_size),
        font_colour: document.getElementById('lb_font_colour').value,
        header_font_override: {
          enabled:     document.getElementById('hdr_override_enabled').checked,
          font_size:   numVal('hdr_font_size',   currentCfg.leaderboard.header_font_override.font_size),
          font_colour: document.getElementById('hdr_font_colour').value,
          bg_colour:   document.getElementById('hdr_bg_colour').value,
          bg_opacity:  numVal('hdr_bg_opacity',  currentCfg.leaderboard.header_font_override.bg_opacity),
        },
        row_background_colour: document.getElementById('row_bg_colour').value,
        row_background_alt: {
          enabled: document.getElementById('row_bg_alt_enabled').checked,
          opacity: numVal('row_bg_alt_opacity', currentCfg.leaderboard.row_background_alt.opacity),
          colour:  document.getElementById('row_bg_alt_colour').value,
        },
        row_separator:      document.getElementById('row_separator').value,
        show_session_label: document.getElementById('lb_show_session_label').checked,
        columns,
      },
      bottom_bar: {
        enabled:    document.getElementById('bb_enabled').checked,
        opacity:    numVal('bb_opacity', currentCfg.bottom_bar.opacity),
        font_size:  numVal('bb_font_size', currentCfg.bottom_bar.font_size),
        font_colour: document.getElementById('bb_font_colour').value,
      },
    };
  }

  document.getElementById('cfg-form').addEventListener('submit', async e => {
    e.preventDefault();
    const msg = document.getElementById('msg');
    msg.textContent = '';
    if (!currentCfg) {
      msg.style.color = 'red';
      msg.textContent = 'Config not loaded. Refresh the page.';
      return;
    }
    try {
      const resp = await fetch('/api/config', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(collectPayload()),
      });
      if (resp.ok) {
        currentCfg = await resp.json();
        populateForm(currentCfg);
        msg.style.color = 'green';
        msg.textContent = 'Saved!';
        setTimeout(() => { msg.textContent = ''; }, 3000);
      } else {
        msg.style.color = 'red';
        msg.textContent = 'Save failed.';
      }
    } catch (_) {
      msg.style.color = 'red';
      msg.textContent = 'Save failed (network error).';
    }
  });

  document.getElementById('reset-btn').addEventListener('click', async () => {
    try {
      const resp = await fetch('/api/config/defaults');
      if (resp.ok) {
        currentCfg = await resp.json();
        populateForm(currentCfg);
      }
    } catch (_) {
      // silently ignore — form stays as-is on network error
    }
  });

  // Prevent enable checkboxes inside <summary> from toggling the <details>
  ['lb_enabled', 'bb_enabled', 'hdr_override_enabled', 'row_bg_alt_enabled'].forEach(id => {
    document.getElementById(id).addEventListener('click', e => e.stopPropagation());
  });

  function deriveAltColour(hex) {
    if (!hex || hex.length < 7) return '#2a2a2a';
    const r = Math.min(255, parseInt(hex.slice(1, 3), 16) + 16);
    const g = Math.min(255, parseInt(hex.slice(3, 5), 16) + 16);
    const b = Math.min(255, parseInt(hex.slice(5, 7), 16) + 16);
    return '#' + [r, g, b].map(v => v.toString(16).padStart(2, '0')).join('');
  }

  document.getElementById('row_bg_alt_reset').addEventListener('click', () => {
    const primary = document.getElementById('row_bg_colour').value;
    document.getElementById('row_bg_alt_colour').value  = deriveAltColour(primary);
    document.getElementById('row_bg_alt_opacity').value = document.getElementById('lb_opacity').value;
  });

  document.getElementById('font_filter').addEventListener('input', function() {
    buildFontSelect(this.value);
  });

  loadConfig();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Flask app factory
# ---------------------------------------------------------------------------

def create_app(watcher, db_path: str, config_path: str | None = None) -> Flask:
    app = Flask(__name__)
    _cfg_path = config_path  # overrides CONFIG_PATH; pass a tmp path in tests

    @app.route("/overlay")
    def overlay():
        return Response(_OVERLAY_HTML, mimetype="text/html")

    @app.route("/config")
    def config_page():
        return Response(_CONFIG_HTML, mimetype="text/html")

    @app.route("/api/config", methods=["GET"])
    def api_config_get():
        return jsonify(get_config(path=_cfg_path))

    @app.route("/api/config", methods=["POST"])
    def api_config_post():
        payload = request.get_json(silent=True)
        if payload is None:
            return jsonify({"error": "invalid JSON"}), 400
        current = get_config(path=_cfg_path)
        # Only merge known top-level keys
        known = {k: v for k, v in payload.items() if k in DEFAULT_CONFIG}
        merged = _deep_merge(current, known)
        try:
            save_config(merged, path=_cfg_path)
        except OSError as exc:
            return jsonify({"error": f"could not save config: {exc}"}), 500
        return jsonify(merged)

    @app.route("/api/config/defaults", methods=["GET"])
    def api_config_defaults():
        return jsonify(copy.deepcopy(DEFAULT_CONFIG))

    @app.route("/api/state")
    def api_state():
        with db.get_conn(db_path) as conn:
            open_run     = db.get_open_run(conn, watcher.streamer_username)
            open_session = db.get_open_session(conn, watcher.streamer_username)

            if open_run and open_session:
                status      = "active"
                last_level  = db.get_last_level(conn, open_run["id"])
                leaderboard = db.get_run_leaderboard(conn, open_run["id"])
                summary     = db.get_level_summary(conn, last_level["id"]) if last_level else None
            else:
                last_session = db.get_last_closed_session(conn, watcher.streamer_username)
                if not last_session:
                    return jsonify({"status": "waiting"})
                status      = "idle"
                last_run_id = db.get_last_run_id_in_session(conn, last_session["id"])
                last_level  = db.get_last_level(conn, last_run_id) if last_run_id else None
                leaderboard = db.get_session_leaderboard(conn, last_session["id"])
                summary     = db.get_level_summary(conn, last_level["id"]) if last_level else None

        level_data = None
        if summary:
            level_data = {
                "level_number":        summary["level_number"],
                "elapsed_time":        summary["elapsed_time"],
                "level_exp":           summary["level_exp"],
                "level_passed":        bool(summary["level_passed"]),
                "survivors":           summary["survivors"],
                "total_players":       summary["total_players"],
                "top_tiltee_username": summary["top_tiltee_username"],
            }

        players = [
            {
                "username":        row["username"],
                "display_name":    row["display_name"],
                "levels_played":   row["levels_played"],
                "levels_survived": row["levels_survived"],
                "exp_earned":      row["exp_earned"],
                "colour":          _rgba_to_css(
                    watcher.colours.get(row["display_name"])
                ),
            }
            for row in leaderboard
        ]

        return jsonify({
            "status":          status,
            "last_level":      level_data,
            "run_leaderboard": players,
        })

    return app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rgba_to_css(colour: dict | None) -> str:
    """Convert a generate_colours() RGBA dict to a CSS rgba() string."""
    if not colour:
        return "rgba(255,255,255,1)"
    r = round(colour.get("red",   1.0) * 255)
    g = round(colour.get("green", 1.0) * 255)
    b = round(colour.get("blue",  1.0) * 255)
    a = colour.get("alpha", 1.0)
    return f"rgba({r},{g},{b},{a})"
