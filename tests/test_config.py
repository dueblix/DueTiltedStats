"""
test_config.py — tests for config helpers and config-related Flask routes.
"""

import json
import sys

import pytest

from flask_overlay import get_app_dir, get_config, save_config, DEFAULT_CONFIG


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
# get_config()
# ---------------------------------------------------------------------------

def test_get_config_defaults_when_no_file(tmp_path):
    cfg = get_config(path=str(tmp_path / "config.json"))
    assert cfg == DEFAULT_CONFIG


def test_get_config_has_expected_top_level_sections(tmp_path):
    cfg = get_config(path=str(tmp_path / "config.json"))
    for section in ("layout", "typography", "colours", "columns", "advanced"):
        assert section in cfg


def test_get_config_partial_file_fills_missing_sections(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"layout": {"panel_width": 400}}))
    cfg = get_config(path=str(p))
    assert cfg["layout"]["panel_width"] == 400
    assert "typography" in cfg
    assert "columns" in cfg


def test_get_config_partial_section_fills_missing_keys(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"typography": {"font_family": "Consolas"}}))
    cfg = get_config(path=str(p))
    assert cfg["typography"]["font_family"] == "Consolas"
    assert "row_font_size" in cfg["typography"]
    assert "header_font_size" in cfg["typography"]


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
    cfg["layout"]["panel_width"] = 999
    save_config(cfg, path=p)
    loaded = get_config(path=p)
    assert loaded["layout"]["panel_width"] == 999


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
    cfg["columns"] = [
        {"key": "races",    "label": "R", "visible": True},
        {"key": "points",   "label": "P", "visible": True},
        {"key": "survived", "label": "S", "visible": True},
    ]
    save_config(cfg, path=p)
    loaded = get_config(path=p)
    assert [c["key"] for c in loaded["columns"]] == ["races", "points", "survived"]


# ---------------------------------------------------------------------------
# Flask routes — /api/config and /config
# ---------------------------------------------------------------------------

def test_api_config_get_returns_200_and_json(client):
    resp = client.get("/api/config")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data is not None
    for section in ("layout", "typography", "colours", "columns", "advanced"):
        assert section in data


def test_api_config_get_returns_defaults_when_no_file(client):
    resp = client.get("/api/config")
    data = resp.get_json()
    assert data["layout"]["panel_width"] == DEFAULT_CONFIG["layout"]["panel_width"]


def test_api_config_post_valid_saves_and_returns_200(client):
    payload = {"layout": {"panel_width": 400}}
    resp = client.post("/api/config",
                       data=json.dumps(payload),
                       content_type="application/json")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["layout"]["panel_width"] == 400


def test_api_config_post_returns_saved_values_on_get(client):
    client.post("/api/config",
                data=json.dumps({"layout": {"panel_width": 350}}),
                content_type="application/json")
    resp = client.get("/api/config")
    assert resp.get_json()["layout"]["panel_width"] == 350


def test_api_config_post_partial_merges(client):
    client.post("/api/config",
                data=json.dumps({"typography": {"row_font_size": 32}}),
                content_type="application/json")
    data = client.get("/api/config").get_json()
    assert data["typography"]["row_font_size"] == 32
    # other sections untouched
    assert data["layout"]["panel_width"] == DEFAULT_CONFIG["layout"]["panel_width"]


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
                       data=json.dumps({"layout": {"panel_width": 400}}),
                       content_type="application/json")
    assert resp.status_code == 500
    assert "error" in resp.get_json()


def test_config_page_returns_200(client):
    resp = client.get("/config")
    assert resp.status_code == 200
