"""
conftest.py — shared pytest fixtures for Flask route tests.
"""

import pytest

from flask_overlay import create_app


class _StubWatcher:
    streamer_username = "testuser"
    colours = {}


@pytest.fixture
def client(tmp_path):
    """Flask test client with an isolated config path and no real DB."""
    app = create_app(_StubWatcher(), db_path=str(tmp_path / "tilted.db"),
                     config_path=str(tmp_path / "config.json"))
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
