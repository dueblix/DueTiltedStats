"""
conftest.py — shared pytest fixtures for Flask route tests.
"""

import pytest

import db
from flask_overlay import create_app


class _StubWatcher:
    streamer_username = "testuser"
    colours = {}


@pytest.fixture
def client(tmp_path):
    """Flask test client with an isolated config path and an initialised DB."""
    db_path = str(tmp_path / "tilted.db")
    db.init_db(db_path)
    app = create_app(_StubWatcher(), db_path=db_path,
                     config_path=str(tmp_path / "config.json"))
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
