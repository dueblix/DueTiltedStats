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
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, request

import db


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "global": {
        "font_family": "Courier New, monospace",
        "sav_filename": "New tilts.sav",
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
        "header_text_transform": "uppercase",
        "header_font_weight": "normal",
        "row_height": 54,
        "cell_padding_v": 4,
        "cell_padding_h": 6,
        "panel_border_radius": 0,
        "row_separator": "none",
        "show_session_label": True,
        "columns": [
            {"key": "rank",     "label": "#",      "visible": True},
            {"key": "name",     "label": "Player",  "visible": True},
            {"key": "points",   "label": "P",       "visible": True},
            {"key": "survived", "label": "S",       "visible": True},
            {"key": "races",    "label": "R",       "visible": True},
        ],
        "position": {
            "mode": "tiled",
            "zone": "right",
            "fill": True,
            "anchor": "top-right",
            "offset_x": 0,
            "offset_y": 0,
        },
    },
    "level_history": {
        "enabled": True,
        "font_size": 20,
        "font_colour": "#ffffff",
        "opacity": 0.75,
        "history_rows": 5,
        "recent_at_bottom": True,
        "show_total_row": True,
        "cells": [
            {"key": "level",  "label": "Level",  "visible": True},
            {"key": "time",   "label": "Time",   "visible": True},
            {"key": "saved",  "label": "Saved",  "visible": True},
            {"key": "points", "label": "Points", "visible": True},
        ],
        "position": {
            "mode": "tiled",
            "zone": "bottom",
            "fill": False,
            "anchor": "bottom-right",
            "offset_x": 0,
            "offset_y": 0,
        },
    },
    "player_colours": {},
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
# Flask app factory
# ---------------------------------------------------------------------------

def create_app(watcher, db_path: str, config_path: str | None = None) -> Flask:
    app = Flask(__name__)
    _cfg_path = config_path  # overrides CONFIG_PATH; pass a tmp path in tests
    # Give the watcher the authoritative config path so _get_sav_path() resolves
    # the user-configured filename on every colour refresh.
    watcher.config_path = _cfg_path or CONFIG_PATH
    _cfg_cache: dict | None = None
    _cfg_mtime: float | None = None

    def _get_config_cached() -> dict:
        """Return config, re-reading from disk only when the file has changed."""
        nonlocal _cfg_cache, _cfg_mtime
        p = _cfg_path or CONFIG_PATH
        try:
            mtime = os.path.getmtime(p)
        except OSError:
            mtime = None
        if _cfg_cache is not None and mtime == _cfg_mtime:
            return copy.deepcopy(_cfg_cache)
        result = get_config(path=_cfg_path)
        _cfg_cache = result
        _cfg_mtime = mtime
        return copy.deepcopy(result)

    @app.route("/overlay")
    def overlay():
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
                    "session":    dict(s),
                    "leaderboard": [dict(r) for r in leaderboard],
                    "top_tiltees": [dict(r) for r in top_tiltees],
                    "level_count": level_count,
                })
        return render_template("history.html", sessions=history_data)

    @app.route("/api/config", methods=["GET"])
    def api_config_get():
        return jsonify(_get_config_cached())

    @app.route("/api/config", methods=["POST"])
    def api_config_post():
        payload = request.get_json(silent=True)
        if payload is None:
            return jsonify({"error": "invalid JSON"}), 400
        current = get_config(path=_cfg_path)
        # Only merge known top-level keys
        known = {k: v for k, v in payload.items() if k in DEFAULT_CONFIG}
        merged = _deep_merge(current, known)
        # player_colours is a flat name→hex mapping: replace entirely so deletions take effect
        if "player_colours" in known and isinstance(known["player_colours"], dict):
            merged["player_colours"] = copy.deepcopy(known["player_colours"])
        try:
            save_config(merged, path=_cfg_path)
        except OSError as exc:
            return jsonify({"error": f"could not save config: {exc}"}), 500
        nonlocal _cfg_cache
        _cfg_cache = None  # invalidate so next read picks up the saved file
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
                run_id      = open_run["id"]
                last_level  = db.get_last_level(conn, run_id)
                leaderboard = db.get_run_leaderboard(conn, run_id)
                summary     = db.get_level_summary(conn, last_level["id"]) if last_level else None
                # Fetch more rows than any realistic history_rows setting; the
                # overlay JS slices to cfg.level_history.history_rows before display.
                run_history = db.get_run_level_history(conn, run_id, 50)
                run_totals_row = db.get_run_totals(conn, run_id)
            else:
                last_session = db.get_last_closed_session(conn, watcher.streamer_username)
                if not last_session:
                    return jsonify({"status": "waiting"})
                status      = "idle"
                last_run_id = db.get_last_run_id_in_session(conn, last_session["id"])
                last_level  = db.get_last_level(conn, last_run_id) if last_run_id else None
                leaderboard = db.get_session_leaderboard(conn, last_session["id"])
                summary     = db.get_level_summary(conn, last_level["id"]) if last_level else None
                run_history = db.get_run_level_history(conn, last_run_id, 50) if last_run_id else []  # see active branch comment
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

        player_colours = _get_config_cached().get("player_colours", {})
        players = [
            {
                "username":        row["username"],
                "display_name":    row["display_name"],
                "levels_played":   row["levels_played"],
                "levels_survived": row["levels_survived"],
                "exp_earned":      row["exp_earned"],
                "colour":          player_colours.get(row["display_name"])
                                   or _rgba_to_css(watcher.colours.get(row["display_name"])),
            }
            for row in leaderboard
        ]

        return jsonify({
            "status":          status,
            "last_level":      level_data,
            "run_leaderboard": players,
            "run_history":     history_list,
            "run_totals":      totals_data,
            "server_time":     datetime.now(timezone.utc).isoformat(),
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
