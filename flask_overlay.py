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
    padding: 12px;
  }

  #level-info {
    background: rgba(0, 0, 0, 0.70);
    border-left: 3px solid #ffffff;
    padding: 6px 10px;
    margin-bottom: 8px;
    font-size: 15px;
    letter-spacing: 0.04em;
  }

  #level-info .label {
    color: #aaaaaa;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.1em;
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
    font-size: 10px;
    font-weight: normal;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    padding: 4px 6px;
    text-align: center;
    white-space: nowrap;
  }

  #leaderboard thead th.name {
    text-align: left;
    width: 100%;
  }

  #leaderboard tbody tr {
    background: rgba(0, 0, 0, 0.60);
  }

  #leaderboard tbody tr:nth-child(odd) {
    background: rgba(0, 0, 0, 0.70);
  }

  #leaderboard tbody td {
    padding: 3px 6px;
    vertical-align: middle;
    white-space: nowrap;
    text-align: center;
    font-size: 12px;
    color: #cccccc;
  }

  #leaderboard tbody td.name {
    text-align: left;
    width: 100%;
    max-width: 0;
    overflow: hidden;
    text-overflow: clip;
    font-size: 13px;
    font-weight: bold;
    color: #ffffff;
    padding-right: 10px;
  }

  #status {
    background: rgba(0, 0, 0, 0.60);
    color: #aaaaaa;
    font-size: 11px;
    padding: 6px 10px;
    text-align: center;
    letter-spacing: 0.06em;
  }
</style>
</head>
<body>
  <div id="level-info" style="display:none">
    <div class="label">Level <span id="level-num"></span></div>
    <span id="level-stats"></span>
  </div>

  <table id="leaderboard" style="display:none">
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

  <div id="status">Waiting for game...</div>

<script>
  async function refresh() {
    let data;
    try {
      const resp = await fetch('/api/state');
      data = await resp.json();
    } catch (_) {
      return;
    }

    const levelInfo   = document.getElementById('level-info');
    const leaderboard = document.getElementById('leaderboard');
    const statusDiv   = document.getElementById('status');

    if (data.status === 'waiting') {
      levelInfo.style.display   = 'none';
      leaderboard.style.display = 'none';
      statusDiv.style.display   = 'block';
      statusDiv.textContent     = 'Waiting for game...';
      return;
    }

    if (data.status === 'idle') {
      statusDiv.textContent   = 'PREVIOUS SESSION';
      statusDiv.style.display = 'block';
    } else {
      statusDiv.style.display = 'none';
    }

    // --- Level info bar ---
    if (data.last_level) {
      const ll = data.last_level;
      document.getElementById('level-num').textContent = ll.level_number;

      const pct = ll.total_players > 0
        ? Math.round(ll.survivors / ll.total_players * 100)
        : 0;

      let timeStr = '';
      if (ll.elapsed_time !== null) {
        const m = Math.floor(ll.elapsed_time / 60).toString().padStart(2, '0');
        const s = (ll.elapsed_time % 60).toFixed(3).padStart(6, '0');
        timeStr = `${m}:${s}  `;
      }

      const ptsStr = ll.level_exp !== null ? `  ${ll.level_exp} pts` : '';
      document.getElementById('level-stats').textContent =
        `${timeStr}${ll.survivors}/${ll.total_players} saved (${pct}%)${ptsStr}`;

      levelInfo.style.display = 'block';
    }

    // --- Leaderboard ---
    if (data.run_leaderboard && data.run_leaderboard.length > 0) {
      const tbody = document.getElementById('lb-body');
      tbody.innerHTML = '';
      data.run_leaderboard.forEach((p) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td class="name" style="color:${p.colour}">${escHtml(p.display_name)}</td>
          <td>${p.exp_earned}</td>
          <td>${p.levels_survived}</td>
          <td>${p.levels_played}</td>
        `;
        tbody.appendChild(tr);
      });
      leaderboard.style.display = 'table';
    }
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


