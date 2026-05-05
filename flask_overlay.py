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

import os
import sys
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, send_file

import db


def get_app_dir() -> str:
    """Return the directory of the exe (frozen) or project root (dev)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def create_app(watcher, db_path: str) -> Flask:
    app = Flask(__name__)

    @app.route("/overlay")
    def overlay():
        custom = os.path.join(get_app_dir(), "overlay_custom.html")
        if os.path.exists(custom):
            return send_file(custom)
        return render_template("overlay.html")

    @app.route("/config")
    def config_page():
        return render_template("config.html")

    @app.route("/history")
    def history():
        with db.get_conn(db_path) as conn:
            sessions = db.get_all_closed_sessions(conn, watcher.streamer_username)
            history_data = []
            for s in sessions:
                leaderboard = db.get_session_leaderboard(conn, s["id"])
                top_tiltees = db.get_session_top_tiltees(conn, s["id"])
                level_count = db.get_session_level_count(conn, s["id"])
                history_data.append({
                    "session":     dict(s),
                    "leaderboard": [dict(r) for r in leaderboard],
                    "top_tiltees": [dict(r) for r in top_tiltees],
                    "level_count": level_count,
                })
        return render_template("history.html", sessions=history_data)

    @app.route("/api/state")
    def api_state():
        with db.get_conn(db_path) as conn:
            open_run     = db.get_open_run(conn, watcher.streamer_username)
            open_session = db.get_open_session(conn, watcher.streamer_username)

            if open_run and open_session:
                status         = "active"
                run_id         = open_run["id"]
                last_level     = db.get_last_level(conn, run_id)
                leaderboard    = db.get_run_leaderboard(conn, run_id)
                summary        = db.get_level_summary(conn, last_level["id"]) if last_level else None
                # Fetch more rows than any realistic display limit; overlay JS slices as needed.
                run_history    = db.get_run_level_history(conn, run_id, 50)
                run_totals_row = db.get_run_totals(conn, run_id)
            else:
                last_session = db.get_last_closed_session(conn, watcher.streamer_username)
                if not last_session:
                    return jsonify({"status": "waiting"})
                status         = "idle"
                last_run_id    = db.get_last_run_id_in_session(conn, last_session["id"])
                last_level     = db.get_last_level(conn, last_run_id) if last_run_id else None
                leaderboard    = db.get_session_leaderboard(conn, last_session["id"])
                summary        = db.get_level_summary(conn, last_level["id"]) if last_level else None
                run_history    = db.get_run_level_history(conn, last_run_id, 50) if last_run_id else []
                run_totals_row = db.get_run_totals(conn, last_run_id) if last_run_id else None

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

        history_list = [
            {
                "level_number":  row["level_number"],
                "elapsed_time":  row["elapsed_time"],
                "level_exp":     row["level_exp"],
                "level_passed":  bool(row["level_passed"]),
                "survivors":     row["survivors"],
                "total_players": row["total_players"],
            }
            for row in run_history
        ]

        totals_data = None
        if run_totals_row:
            totals_data = {
                "level_count":     run_totals_row["level_count"],
                "total_survivors": run_totals_row["total_survivors"],
                "total_players":   run_totals_row["total_players"],
                "total_exp":       run_totals_row["total_exp"],
                "run_started_at":  run_totals_row["started_at"],
                "run_ended_at":    run_totals_row["ended_at"],
            }

        players = [
            {
                "username":        row["username"],
                "display_name":    row["display_name"],
                "levels_played":   row["levels_played"],
                "levels_survived": row["levels_survived"],
                "exp_earned":      row["exp_earned"],
            }
            for row in leaderboard
        ]

        return jsonify({
            "status":          status,
            "last_level":      level_data,
            "run_leaderboard": players,
            "run_history":     history_list,
            "run_totals":      totals_data,
            # Update OverlayConfigGuideline.md dummy payloads whenever this response shape changes.
            "server_time":     datetime.now(timezone.utc).isoformat(),
        })

    return app
