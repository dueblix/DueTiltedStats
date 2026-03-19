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

from flask import Flask, jsonify, render_template_string, request

import db


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "layout": {
        "panel_width": 310,
    },
    "typography": {
        "font_family": "Courier New, monospace",
        "row_font_size": 40,
        "header_font_size": 20,
    },
    "colours": {
        "panel_opacity": 0.60,
        "bottom_bar_opacity": 0.75,
    },
    "columns": [
        {"key": "points",   "label": "P", "visible": True},
        {"key": "survived", "label": "S", "visible": True},
        {"key": "races",    "label": "R", "visible": True},
    ],
    "advanced": {},
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
    """Return a new dict: override values merged over base (one level deep for dicts)."""
    result = copy.deepcopy(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = {**result[key], **val}
        else:
            result[key] = copy.deepcopy(val)
    return result


def get_config(path: str | None = None) -> dict:
    """Load config from *path*, deep-merging over defaults. Falls back to defaults on any error."""
    p = path or CONFIG_PATH
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Only keep known top-level keys
        known = {k: v for k, v in data.items() if k in DEFAULT_CONFIG}
        return _deep_merge(DEFAULT_CONFIG, known)
    except (OSError, json.JSONDecodeError):
        return copy.deepcopy(DEFAULT_CONFIG)


def save_config(config: dict, path: str | None = None) -> None:
    p = path or CONFIG_PATH
    with open(p, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


# ---------------------------------------------------------------------------
# HTML overlay (embedded for PyInstaller compatibility)
# ---------------------------------------------------------------------------

_OVERLAY_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
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
    background: rgba(0, 0, 0, 0.80);
  }

  #leaderboard thead th {
    color: #aaaaaa;
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
    background: rgba(0, 0, 0, var(--panel-opacity));
    height: 54px;
  }

  #leaderboard tbody tr:nth-child(odd) {
    background: rgba(0, 0, 0, 0.70);
  }

  #leaderboard tbody td {
    padding: 4px 6px;
    vertical-align: middle;
    white-space: nowrap;
    text-align: center;
    font-size: var(--row-font-size);
    color: #cccccc;
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
    font-size: 13px;
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
    color: #ffffff;
    font-size: 14px;
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
  let rowCount = null;
  let activeColumns = [];  // [{key, label}] for visible columns in order

  // Map column key -> player data field
  const COL_FIELD = {
    points:   'exp_earned',
    survived: 'levels_survived',
    races:    'levels_played',
  };

  async function applyConfig() {
    let cfg;
    try {
      const resp = await fetch('/api/config');
      if (!resp.ok) return;  // CSS vars stay unset; overlay invisible until next load
      cfg = await resp.json();
    } catch (_) {
      return;  // network error; same outcome
    }

    const body = document.body;
    body.style.setProperty('--panel-width',       cfg.layout.panel_width + 'px');
    body.style.setProperty('--font-family',        cfg.typography.font_family);
    body.style.setProperty('--row-font-size',      cfg.typography.row_font_size + 'px');
    body.style.setProperty('--header-font-size',   cfg.typography.header_font_size + 'px');
    body.style.setProperty('--panel-opacity',       cfg.colours.panel_opacity);
    body.style.setProperty('--bottom-bar-opacity',  cfg.colours.bottom_bar_opacity);

    // Build visible column list and header
    activeColumns = cfg.columns.filter(c => c.visible);
    const headRow = document.getElementById('lb-head');
    headRow.innerHTML = '<th class="name">Player</th>';
    for (const col of activeColumns) {
      const th = document.createElement('th');
      th.textContent = col.label;
      headRow.appendChild(th);
    }

    rowCount = null;  // force recalc after layout change
  }

  function calcRowCount() {
    const panel  = document.getElementById('right-panel');
    const thead  = document.querySelector('#leaderboard thead tr');
    const available = panel.clientHeight - thead.offsetHeight;
    const tbody  = document.getElementById('lb-body');
    const test   = document.createElement('tr');
    const emptyCells = activeColumns.map(() => '<td>0</td>').join('');
    test.innerHTML = `<td class="name">x</td>${emptyCells}`;
    tbody.appendChild(test);
    const rowH = test.offsetHeight || 29;
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

    statusDiv.textContent   = data.status === 'idle' ? 'PREVIOUS SESSION' : '';
    statusDiv.style.display = data.status === 'idle' ? 'block' : 'none';

    // --- Bottom bar ---
    if (data.last_level) {
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

  applyConfig().finally(() => {
    refresh();
    setInterval(refresh, 3000);
  });
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
  h2   { margin: 24px 0 8px; border-bottom: 1px solid #ccc; padding-bottom: 4px; }
  label { display: block; margin: 8px 0 2px; font-weight: bold; font-size: 0.9em; }
  input[type=number], input[type=text], select { width: 100%; padding: 6px; box-sizing: border-box; }
  .col-row { display: flex; align-items: center; gap: 10px; margin: 6px 0; }
  .col-row label { margin: 0; font-weight: normal; }
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

  <h2>Layout</h2>
  <label for="panel_width">Panel width (px)</label>
  <input type="number" id="panel_width" name="panel_width" min="100" max="800">

  <h2>Typography</h2>
  <label for="font_family">Font family</label>
  <select id="font_family" name="font_family">
    <option value="Courier New, monospace">Courier New</option>
    <option value="Consolas, monospace">Consolas</option>
    <option value="Lucida Console, monospace">Lucida Console</option>
    <option value="monospace">monospace (system default)</option>
  </select>
  <label for="row_font_size">Row font size (px)</label>
  <input type="number" id="row_font_size" name="row_font_size" min="8" max="120">
  <label for="header_font_size">Header font size (px)</label>
  <input type="number" id="header_font_size" name="header_font_size" min="8" max="60">

  <h2>Colours</h2>
  <label for="panel_opacity">Panel opacity (0–1)</label>
  <input type="number" id="panel_opacity" name="panel_opacity" min="0" max="1" step="0.05">
  <label for="bottom_bar_opacity">Bottom bar opacity (0–1)</label>
  <input type="number" id="bottom_bar_opacity" name="bottom_bar_opacity" min="0" max="1" step="0.05">

  <h2>Columns</h2>
  <div id="columns-list"></div>

  <h2>Advanced</h2>
  <p style="color:#888;font-size:0.9em;">Reserved for future options.</p>

  <div class="actions">
    <button type="submit" id="save-btn">Save</button>
    <button type="button" id="reset-btn">Reset to defaults</button>
    <span id="msg"></span>
  </div>
  <p class="note">After saving, refresh the OBS browser source to apply changes.</p>
</form>

<script>
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
    document.getElementById('panel_width').value       = cfg.layout.panel_width;
    document.getElementById('row_font_size').value     = cfg.typography.row_font_size;
    document.getElementById('header_font_size').value  = cfg.typography.header_font_size;
    document.getElementById('panel_opacity').value     = cfg.colours.panel_opacity;
    document.getElementById('bottom_bar_opacity').value = cfg.colours.bottom_bar_opacity;

    // Font family: select matching option or fall back to first
    const sel = document.getElementById('font_family');
    const match = [...sel.options].find(o => o.value === cfg.typography.font_family);
    sel.value = match ? cfg.typography.font_family : sel.options[0].value;

    // Columns
    const list = document.getElementById('columns-list');
    list.innerHTML = '';
    for (const col of cfg.columns) {
      const row = document.createElement('div');
      row.className = 'col-row';
      row.innerHTML = `
        <input type="checkbox" id="col_${col.key}" data-key="${col.key}" ${col.visible ? 'checked' : ''}>
        <label for="col_${col.key}">${col.label} (${col.key})</label>
      `;
      list.appendChild(row);
    }
  }

  function numVal(id, fallback) {
    const v = parseFloat(document.getElementById(id).value);
    return isNaN(v) ? fallback : v;
  }

  function collectPayload() {
    const columns = currentCfg.columns.map(col => ({
      ...col,
      visible: document.getElementById('col_' + col.key)?.checked ?? col.visible,
    }));
    return {
      layout: {
        panel_width: numVal('panel_width', currentCfg.layout.panel_width),
      },
      typography: {
        font_family:       document.getElementById('font_family').value,
        row_font_size:     numVal('row_font_size',    currentCfg.typography.row_font_size),
        header_font_size:  numVal('header_font_size', currentCfg.typography.header_font_size),
      },
      colours: {
        panel_opacity:      numVal('panel_opacity',      currentCfg.colours.panel_opacity),
        bottom_bar_opacity: numVal('bottom_bar_opacity', currentCfg.colours.bottom_bar_opacity),
      },
      columns,
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
        return render_template_string(_OVERLAY_HTML)

    @app.route("/config")
    def config_page():
        return render_template_string(_CONFIG_HTML)

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


