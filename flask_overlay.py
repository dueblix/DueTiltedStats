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

from flask import Flask, jsonify, render_template, request

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
# Flask app factory
# ---------------------------------------------------------------------------

def create_app(watcher, db_path: str, config_path: str | None = None) -> Flask:
    app = Flask(__name__)
    _cfg_path = config_path  # overrides CONFIG_PATH; pass a tmp path in tests

    @app.route("/overlay")
    def overlay():
        return render_template("overlay.html")

    @app.route("/config")
    def config_page():
        return render_template("config.html")

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
