"""
test_config.py — tests for config helpers and config-related Flask routes.
"""

import json
import sys

import pytest

import db
from flask_overlay import get_app_dir, get_config, save_config, DEFAULT_CONFIG, _deep_merge, _rgba_to_css


# ---------------------------------------------------------------------------
# get_app_dir()
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# _rgba_to_css()
# ---------------------------------------------------------------------------

def test_rgba_to_css_normal():
    c = {"red": 1.0, "green": 0.5, "blue": 0.0, "alpha": 0.8}
    assert _rgba_to_css(c) == "rgba(255,128,0,0.8)"


def test_rgba_to_css_none_returns_white():
    assert _rgba_to_css(None) == "rgba(255,255,255,1)"


def test_rgba_to_css_missing_keys_default_to_one():
    assert _rgba_to_css({}) == "rgba(255,255,255,1)"


# ---------------------------------------------------------------------------
# get_app_dir()
# ---------------------------------------------------------------------------

def test_get_app_dir_dev():
    """In dev (not frozen) returns the directory of flask_overlay.py."""
    import flask_overlay
    import os
    expected = os.path.dirname(os.path.abspath(flask_overlay.__file__))
    assert get_app_dir() == expected


def test_get_app_dir_frozen(monkeypatch, tmp_path):
    """When sys.frozen is set, returns directory of sys.executable."""
    fake_exe = str(tmp_path / "app.exe")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", fake_exe)
    assert get_app_dir() == str(tmp_path)


# ---------------------------------------------------------------------------
# _deep_merge()
# ---------------------------------------------------------------------------

def test_deep_merge_shallow():
    base     = {"a": 1, "b": 2}
    override = {"b": 99, "c": 3}
    result   = _deep_merge(base, override)
    assert result == {"a": 1, "b": 99, "c": 3}


def test_deep_merge_nested_dict_merges_not_replaces():
    base     = {"section": {"x": 1, "y": 2}}
    override = {"section": {"y": 99}}
    result   = _deep_merge(base, override)
    assert result["section"] == {"x": 1, "y": 99}


def test_deep_merge_deeply_nested():
    base     = {"a": {"b": {"c": 1, "d": 2}}}
    override = {"a": {"b": {"d": 99}}}
    result   = _deep_merge(base, override)
    assert result["a"]["b"] == {"c": 1, "d": 99}


def test_deep_merge_does_not_mutate_base():
    base     = {"a": {"x": 1}}
    override = {"a": {"x": 2}}
    _deep_merge(base, override)
    assert base["a"]["x"] == 1


def test_deep_merge_ignores_non_dict_overriding_dict():
    """A scalar/null override must not clobber a dict section."""
    base     = {"section": {"x": 1}}
    override = {"section": "bad"}
    result   = _deep_merge(base, override)
    assert result["section"] == {"x": 1}


def test_deep_merge_ignores_non_list_overriding_list():
    """A null/scalar override must not clobber a list (e.g. columns)."""
    base     = {"items": [1, 2, 3]}
    override = {"items": None}
    result   = _deep_merge(base, override)
    assert result["items"] == [1, 2, 3]


def test_deep_merge_allows_list_replacing_list():
    base     = {"items": [1, 2, 3]}
    override = {"items": [4, 5]}
    result   = _deep_merge(base, override)
    assert result["items"] == [4, 5]


# ---------------------------------------------------------------------------
# get_config()
# ---------------------------------------------------------------------------

def test_get_config_defaults_when_no_file(tmp_path):
    cfg = get_config(path=str(tmp_path / "config.json"))
    assert cfg == DEFAULT_CONFIG


def test_get_config_has_expected_top_level_sections(tmp_path):
    cfg = get_config(path=str(tmp_path / "config.json"))
    for section in ("global", "leaderboard", "bottom_bar"):
        assert section in cfg


def test_get_config_partial_file_fills_missing_sections(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"leaderboard": {"panel_width": 400}}))
    cfg = get_config(path=str(p))
    assert cfg["leaderboard"]["panel_width"] == 400
    assert "global" in cfg
    assert "bottom_bar" in cfg


def test_get_config_partial_section_fills_missing_keys(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"global": {"font_family": "Consolas"}}))
    cfg = get_config(path=str(p))
    assert cfg["global"]["font_family"] == "Consolas"


def test_get_config_partial_nested_section_fills_missing_keys(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"leaderboard": {"header_font_override": {"enabled": True}}}))
    cfg = get_config(path=str(p))
    hdr = cfg["leaderboard"]["header_font_override"]
    assert hdr["enabled"] is True
    assert "font_size" in hdr
    assert "font_colour" in hdr


def test_get_config_old_schema_falls_back_to_defaults(tmp_path):
    """Old-format config files (layout/typography/colours) silently reset to defaults."""
    p = tmp_path / "config.json"
    old = {"layout": {"panel_width": 999}, "typography": {"row_font_size": 50},
           "colours": {"panel_opacity": 0.9}, "columns": [], "advanced": {}}
    p.write_text(json.dumps(old))
    cfg = get_config(path=str(p))
    assert cfg == DEFAULT_CONFIG


def test_get_config_empty_file_returns_full_defaults(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{}")
    cfg = get_config(path=str(p))
    assert cfg == DEFAULT_CONFIG


def test_get_config_corrupt_json_returns_defaults(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("not valid json {{{{")
    cfg = get_config(path=str(p))
    assert cfg == DEFAULT_CONFIG


def test_get_config_non_dict_root_returns_defaults(tmp_path):
    """JSON arrays or scalars at the root must not crash — return defaults."""
    for payload in ("[1, 2, 3]", '"a string"', "42"):
        p = tmp_path / "config.json"
        p.write_text(payload)
        assert get_config(path=str(p)) == DEFAULT_CONFIG


def test_get_config_permission_error_returns_defaults(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{}")
    p.chmod(0o000)
    try:
        cfg = get_config(path=str(p))
        assert cfg == DEFAULT_CONFIG
    finally:
        p.chmod(0o644)  # restore so tmp_path cleanup works


# ---------------------------------------------------------------------------
# save_config()
# ---------------------------------------------------------------------------

def test_save_config_roundtrip(tmp_path):
    p = str(tmp_path / "config.json")
    cfg = get_config(path=p)
    cfg["leaderboard"]["panel_width"] = 999
    save_config(cfg, path=p)
    loaded = get_config(path=p)
    assert loaded["leaderboard"]["panel_width"] == 999


def test_save_config_writes_to_expected_path(tmp_path):
    p = tmp_path / "config.json"
    save_config(DEFAULT_CONFIG, path=str(p))
    assert p.exists()
    data = json.loads(p.read_text())
    assert data == DEFAULT_CONFIG


# ---------------------------------------------------------------------------
# Column behaviour
# ---------------------------------------------------------------------------

def test_columns_order_preserved(tmp_path):
    p = str(tmp_path / "config.json")
    cfg = get_config(path=p)
    cfg["leaderboard"]["columns"] = [
        {"key": "races",    "label": "R", "visible": True},
        {"key": "points",   "label": "P", "visible": True},
        {"key": "survived", "label": "S", "visible": True},
    ]
    save_config(cfg, path=p)
    loaded = get_config(path=p)
    assert [c["key"] for c in loaded["leaderboard"]["columns"]] == ["races", "points", "survived"]


# ---------------------------------------------------------------------------
# Flask routes — /api/config and /config
# ---------------------------------------------------------------------------

def test_api_config_get_returns_200_and_json(client):
    resp = client.get("/api/config")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data is not None
    for section in ("global", "leaderboard", "bottom_bar"):
        assert section in data


def test_api_config_get_returns_defaults_when_no_file(client):
    resp = client.get("/api/config")
    data = resp.get_json()
    assert data["leaderboard"]["panel_width"] == DEFAULT_CONFIG["leaderboard"]["panel_width"]


def test_api_config_post_valid_saves_and_returns_200(client):
    payload = {"leaderboard": {"panel_width": 400}}
    resp = client.post("/api/config",
                       data=json.dumps(payload),
                       content_type="application/json")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["leaderboard"]["panel_width"] == 400


def test_api_config_post_returns_saved_values_on_get(client):
    client.post("/api/config",
                data=json.dumps({"leaderboard": {"panel_width": 350}}),
                content_type="application/json")
    resp = client.get("/api/config")
    assert resp.get_json()["leaderboard"]["panel_width"] == 350


def test_api_config_post_partial_merges(client):
    client.post("/api/config",
                data=json.dumps({"leaderboard": {"font_size": 32}}),
                content_type="application/json")
    data = client.get("/api/config").get_json()
    assert data["leaderboard"]["font_size"] == 32
    # other sections untouched
    assert data["leaderboard"]["panel_width"] == DEFAULT_CONFIG["leaderboard"]["panel_width"]


def test_api_config_post_deep_merges_nested_dict(client):
    """Posting a partial nested dict preserves sibling keys."""
    resp = client.post("/api/config",
                       data=json.dumps({"leaderboard": {"header_font_override": {"enabled": True}}}),
                       content_type="application/json")
    assert resp.status_code == 200
    hdr = resp.get_json()["leaderboard"]["header_font_override"]
    assert hdr["enabled"] is True
    assert "font_size" in hdr
    assert "font_colour" in hdr


def test_api_config_post_invalid_json_returns_400(client):
    resp = client.post("/api/config",
                       data="not json",
                       content_type="application/json")
    assert resp.status_code == 400


def test_api_config_post_unknown_keys_ignored(client):
    payload = {"unknown_section": {"foo": "bar"}}
    resp = client.post("/api/config",
                       data=json.dumps(payload),
                       content_type="application/json")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "unknown_section" not in data


def test_api_config_post_returns_500_on_save_failure(client, monkeypatch):
    import flask_overlay
    def boom(config, path=None):
        raise OSError("disk full")
    monkeypatch.setattr(flask_overlay, "save_config", boom)
    resp = client.post("/api/config",
                       data=json.dumps({"leaderboard": {"panel_width": 400}}),
                       content_type="application/json")
    assert resp.status_code == 500
    assert "error" in resp.get_json()


def test_api_config_defaults_returns_200_and_default_values(client):
    resp = client.get("/api/config/defaults")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == DEFAULT_CONFIG


def test_config_page_returns_200(client):
    resp = client.get("/config")
    assert resp.status_code == 200


def test_overlay_page_returns_200(client):
    resp = client.get("/overlay")
    assert resp.status_code == 200


def test_history_page_returns_200(client):
    resp = client.get("/history")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Player colours
# ---------------------------------------------------------------------------

def test_default_config_has_player_colours():
    assert "player_colours" in DEFAULT_CONFIG
    assert DEFAULT_CONFIG["player_colours"] == {}


def test_api_config_post_player_colours_replaces_not_merges(client):
    """Posting player_colours should replace the whole dict, not merge into it."""
    client.post("/api/config", json={"player_colours": {"Alice": "#ff0000"}})
    client.post("/api/config", json={"player_colours": {"Bob": "#0000ff"}})
    data = client.get("/api/config").get_json()
    assert "Bob" in data["player_colours"]
    assert "Alice" not in data["player_colours"]


def test_api_state_uses_player_colour_override(client_and_db):
    c, db_path = client_and_db
    with db.get_conn(db_path) as conn:
        sid = db.insert_session(conn, "testuser", "2024-01-01T00:00:00")
        rid = db.insert_run(conn, "testuser", "2024-01-01T00:00:00")
        lid = db.insert_level(conn, rid, sid, 1, 30.0, "2024-01-01T00:01:00", 100, True, None)
        db.insert_player_levels(conn, lid, [
            {"username": "alice", "display_name": "Alice", "survived": True}
        ])
    c.post("/api/config", json={"player_colours": {"Alice": "#abcdef"}})
    data = c.get("/api/state").get_json()
    assert data["run_leaderboard"][0]["colour"] == "#abcdef"


def test_api_state_falls_back_to_watcher_colour(client_and_db):
    """When no override is set, the watcher colour is used."""
    c, db_path = client_and_db
    with db.get_conn(db_path) as conn:
        sid = db.insert_session(conn, "testuser", "2024-01-01T00:00:00")
        rid = db.insert_run(conn, "testuser", "2024-01-01T00:00:00")
        lid = db.insert_level(conn, rid, sid, 1, 30.0, "2024-01-01T00:01:00", 100, True, None)
        db.insert_player_levels(conn, lid, [
            {"username": "alice", "display_name": "Alice", "survived": True}
        ])
    data = c.get("/api/state").get_json()
    # _StubWatcher.colours is {}, so _rgba_to_css(None) → "rgba(255,255,255,1)"
    assert data["run_leaderboard"][0]["colour"] == "rgba(255,255,255,1)"


# ---------------------------------------------------------------------------
# Default config — bottom_bar schema
# ---------------------------------------------------------------------------

def test_default_config_bottom_bar_has_history_settings():
    bb = DEFAULT_CONFIG["bottom_bar"]
    assert bb["history_rows"] == 5
    assert bb["recent_at_bottom"] is True
    assert bb["show_total_row"] is True
    assert isinstance(bb["cells"], list)
    assert len(bb["cells"]) == 4
    keys = [c["key"] for c in bb["cells"]]
    assert keys == ["level", "time", "saved", "points"]


def test_get_config_bottom_bar_partial_file_fills_new_keys(tmp_path):
    """Old config with only the original bottom_bar keys gets new keys from defaults."""
    p = tmp_path / "config.json"
    p.write_text('{"bottom_bar": {"font_size": 24}}')
    cfg = get_config(path=str(p))
    bb = cfg["bottom_bar"]
    assert bb["font_size"] == 24
    assert bb["history_rows"] == 5
    assert "cells" in bb


# ---------------------------------------------------------------------------
# /api/state — run_history + run_totals fields
# ---------------------------------------------------------------------------

def test_api_state_returns_run_history_and_totals(client_and_db):
    c, db_path = client_and_db
    with db.get_conn(db_path) as conn:
        sid = db.insert_session(conn, "testuser", "2024-01-01T00:00:00")
        rid = db.insert_run(conn, "testuser", "2024-01-01T00:00:00")
        lid = db.insert_level(conn, rid, sid, 1, 30.0, "2024-01-01T00:01:00", 100, True, None)
        db.insert_player_levels(conn, lid, [
            {"username": "alice", "display_name": "Alice", "survived": True}
        ])
    data = c.get("/api/state").get_json()
    assert "run_history" in data
    assert "run_totals" in data
    assert "server_time" in data
    assert len(data["run_history"]) == 1
    assert data["run_history"][0]["level_number"] == 1
    assert data["run_history"][0]["survivors"] == 1
    assert data["run_history"][0]["total_players"] == 1
    assert data["run_totals"]["level_count"] == 1
    assert data["run_totals"]["total_exp"] == 100
    assert data["run_totals"]["run_started_at"] == "2024-01-01T00:00:00"


def test_api_state_server_time_is_utc(client_and_db):
    """server_time must include UTC offset so JS Date() parses it correctly."""
    c, db_path = client_and_db
    with db.get_conn(db_path) as conn:
        sid = db.insert_session(conn, "testuser", "2024-01-01T00:00:00+00:00")
        rid = db.insert_run(conn, "testuser", "2024-01-01T00:00:00+00:00")
        lid = db.insert_level(conn, rid, sid, 1, 30.0, "2024-01-01T00:01:00+00:00", 100, True, None)
        db.insert_player_levels(conn, lid, [
            {"username": "alice", "display_name": "Alice", "survived": True}
        ])
    data = c.get("/api/state").get_json()
    assert "server_time" in data
    assert "+" in data["server_time"] or data["server_time"].endswith("Z"), (
        "server_time must carry timezone info for correct JS Date() parsing"
    )


def test_api_state_waiting_has_no_run_history(client):
    data = client.get("/api/state").get_json()
    assert data["status"] == "waiting"
    assert "run_history" not in data


def test_api_state_idle_no_levels_returns_empty_history(client_and_db):
    """Idle mode where the closed session has no levels: run_history is empty, run_totals is None."""
    c, db_path = client_and_db
    with db.get_conn(db_path) as conn:
        sid = db.insert_session(conn, "testuser", "2024-01-01T00:00:00")
        db.close_session(conn, sid, "2024-01-01T00:10:00")
    data = c.get("/api/state").get_json()
    assert data["status"] == "idle"
    assert data["run_history"] == []
    assert data["run_totals"] is None


def test_api_state_idle_returns_run_history_from_last_run(client_and_db):
    """Idle mode (closed session) surfaces run_history from the session's last run."""
    c, db_path = client_and_db
    with db.get_conn(db_path) as conn:
        sid = db.insert_session(conn, "testuser", "2024-01-01T00:00:00")
        rid = db.insert_run(conn, "testuser", "2024-01-01T00:00:00")
        lid = db.insert_level(conn, rid, sid, 1, 30.0, "2024-01-01T00:01:00", 100, True, None)
        db.insert_player_levels(conn, lid, [
            {"username": "alice", "display_name": "Alice", "survived": True}
        ])
        db.close_run(conn, rid, "2024-01-01T00:10:00")
        db.close_session(conn, sid, "2024-01-01T00:10:00")
    data = c.get("/api/state").get_json()
    assert data["status"] == "idle"
    assert len(data["run_history"]) == 1
    assert data["run_history"][0]["level_number"] == 1
    assert data["run_totals"]["run_ended_at"] == "2024-01-01T00:10:00"
