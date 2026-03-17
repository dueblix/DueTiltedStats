"""
flask_overlay.py — Flask app serving the OBS browser-source overlay
and the JSON API its polling JavaScript consumes.

Usage:
    from watcher import Watcher
    from flask_overlay import create_app

    watcher = Watcher(db_path="tilted.db", streamer_username="dueblix")
    watcher.start()

    app = create_app(watcher, db_path="tilted.db")
    app.run(host="127.0.0.1", port=5000)
"""

from flask import Flask, jsonify, render_template_string

import db


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
    font-family: 'Courier New', monospace;
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
    width: 260px;
    z-index: 1;
  }

  #status {
    background: rgba(0, 0, 0, 0.60);
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
    font-size: 13px;
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
    background: rgba(0, 0, 0, 0.60);
  }

  #leaderboard tbody tr:nth-child(odd) {
    background: rgba(0, 0, 0, 0.70);
  }

  #leaderboard tbody td {
    padding: 4px 6px;
    vertical-align: middle;
    white-space: nowrap;
    text-align: center;
    font-size: 15px;
    color: #cccccc;
  }

  #leaderboard tbody td.name {
    text-align: left;
    width: 100%;
    max-width: 0;
    overflow: hidden;
    text-overflow: clip;
    font-size: 15px;
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
    background: rgba(0, 0, 0, 0.75);
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
        <tr>
          <th class="name">Player</th>
          <th>P</th>
          <th>S</th>
          <th>R</th>
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

  function calcRowCount() {
    const panel = document.getElementById('right-panel');
    const thead = document.querySelector('#leaderboard thead tr');
    const available = panel.clientHeight - thead.offsetHeight;
    const tbody = document.getElementById('lb-body');
    const test = document.createElement('tr');
    test.innerHTML = '<td class="name">x</td><td>0</td><td>0</td><td>0</td>';
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
        tr.innerHTML = `
          <td class="name" style="color:${p.colour}">${escHtml(p.display_name)}</td>
          <td>${p.exp_earned}</td>
          <td>${p.levels_survived}</td>
          <td>${p.levels_played}</td>
        `;
      } else {
        tr.innerHTML = '<td class="name"></td><td></td><td></td><td></td>';
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

  setInterval(refresh, 3000);
  refresh();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Flask app factory
# ---------------------------------------------------------------------------

def create_app(watcher, db_path: str) -> Flask:
    app = Flask(__name__)

    @app.route("/overlay")
    def overlay():
        return render_template_string(_OVERLAY_HTML)

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


