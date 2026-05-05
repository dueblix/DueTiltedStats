"""
test_routes.py — tests for Flask routes and /api/state.
"""

import sys

import pytest

import db
from flask_overlay import get_app_dir


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
# Page routes
# ---------------------------------------------------------------------------

def test_config_page_returns_200(client):
    resp = client.get("/config")
    assert resp.status_code == 200


def test_overlay_serves_builtin_when_no_custom(monkeypatch, tmp_path, client):
    import flask_overlay
    monkeypatch.setattr(flask_overlay, "get_app_dir", lambda: str(tmp_path))
    resp = client.get("/overlay")
    assert resp.status_code == 200


def test_overlay_serves_custom_when_present(monkeypatch, tmp_path, client):
    import flask_overlay
    custom = tmp_path / "overlay_custom.html"
    custom.write_text("<html><body>custom</body></html>")
    monkeypatch.setattr(flask_overlay, "get_app_dir", lambda: str(tmp_path))
    resp = client.get("/overlay")
    assert resp.status_code == 200
    assert b"custom" in resp.data


def test_history_page_returns_200(client):
    resp = client.get("/history")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /api/state — run_history + run_totals + server_time
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
