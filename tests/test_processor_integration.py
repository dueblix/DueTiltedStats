"""
Integration tests for processor.py + db.py working together.
Uses real CSV fixtures and an in-memory SQLite database.
"""
import sqlite3
import pytest
from pathlib import Path

import db
import processor

FIXTURES = Path(__file__).parent / "fixtures"


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    conn.executescript(db.SCHEMA)
    return conn


def load_level1():
    return (
        processor.parse_players_csv(FIXTURES / "players.csv"),
        processor.parse_level_csv(FIXTURES / "level.csv"),
    )


def load_level2():
    return (
        processor.parse_players_csv(FIXTURES / "players_level2.csv"),
        processor.parse_level_csv(FIXTURES / "level2.csv"),
    )


def load_failed():
    return (
        processor.parse_players_csv(FIXTURES / "players.csv"),
        processor.parse_level_csv(FIXTURES / "level_failed.csv"),
    )


TS1 = "2024-01-01T00:00:00"
TS2 = "2024-01-01T00:01:00"


# ---------------------------------------------------------------------------
# process_level_update
# ---------------------------------------------------------------------------

class TestProcessLevelUpdate:
    def test_level1_creates_new_run(self):
        conn = make_conn()
        p, l = load_level1()
        processor.process_level_update(conn, p, l, TS1, "streamer1")
        assert db.get_open_run(conn, "streamer1") is not None

    def test_level1_creates_session_if_none_exists(self):
        conn = make_conn()
        p, l = load_level1()
        processor.process_level_update(conn, p, l, TS1, "streamer1")
        assert db.get_open_session(conn, "streamer1") is not None

    def test_level1_closes_existing_open_run(self):
        conn = make_conn()
        old_rid = db.insert_run(conn, "streamer1", TS1)
        p, l = load_level1()
        processor.process_level_update(conn, p, l, TS2, "streamer1")
        old_run = conn.execute("SELECT * FROM run WHERE id = ?", (old_rid,)).fetchone()
        assert old_run["ended_at"] is not None

    def test_failed_level_closes_run(self):
        conn = make_conn()
        p, l = load_failed()
        processor.process_level_update(conn, p, l, TS1, "streamer1")
        assert db.get_open_run(conn, "streamer1") is None

    def test_level_gt1_continues_same_run(self):
        conn = make_conn()
        p1, l1 = load_level1()
        processor.process_level_update(conn, p1, l1, TS1, "streamer1")
        run_id_after_l1 = db.get_open_run(conn, "streamer1")["id"]

        p2, l2 = load_level2()
        processor.process_level_update(conn, p2, l2, TS2, "streamer1")
        run_id_after_l2 = db.get_open_run(conn, "streamer1")["id"]

        assert run_id_after_l1 == run_id_after_l2

    def test_recovery_run_created_when_no_open_run(self):
        # Simulates watcher restarting mid-run (level > 1, no existing run)
        conn = make_conn()
        p2, l2 = load_level2()
        processor.process_level_update(conn, p2, l2, TS1, "streamer1")
        assert db.get_open_run(conn, "streamer1") is not None

    def test_player_levels_recorded_for_current_level(self):
        conn = make_conn()
        p, l = load_level1()
        lid = processor.process_level_update(conn, p, l, TS1, "streamer1")
        rows = conn.execute(
            "SELECT username FROM player_level WHERE level_id = ?", (lid,)
        ).fetchall()
        usernames = {r["username"] for r in rows}
        assert usernames == {"player1", "player2"}

    def test_reuses_existing_open_session(self):
        conn = make_conn()
        existing_sid = db.insert_session(conn, "streamer1", TS1)
        p, l = load_level1()
        lid = processor.process_level_update(conn, p, l, TS2, "streamer1")
        level_row = conn.execute("SELECT session_id FROM level WHERE id = ?", (lid,)).fetchone()
        assert level_row["session_id"] == existing_sid


# ---------------------------------------------------------------------------
# should_process_on_startup
# ---------------------------------------------------------------------------

class TestShouldProcessOnStartup:
    def test_level1_always_true(self):
        conn = make_conn()
        p, _ = load_level1()  # all players on level 1 → max = 1
        assert processor.should_process_on_startup(conn, p, "streamer1") is True

    def test_level_gt1_no_history_false(self):
        conn = make_conn()
        p2, _ = load_level2()  # max LastLevelJoined = 2
        assert processor.should_process_on_startup(conn, p2, "streamer1") is False

    def test_level_ahead_of_history_true(self):
        conn = make_conn()
        p1, l1 = load_level1()
        processor.process_level_update(conn, p1, l1, TS1, "streamer1")
        # Startup with level 2 — ahead of recorded level 1
        p2, _ = load_level2()
        assert processor.should_process_on_startup(conn, p2, "streamer1") is True

    def test_level_matches_history_false(self):
        conn = make_conn()
        p1, l1 = load_level1()
        processor.process_level_update(conn, p1, l1, TS1, "streamer1")
        p2, l2 = load_level2()
        processor.process_level_update(conn, p2, l2, TS2, "streamer1")
        # Startup again with the same level 2 — already recorded
        assert processor.should_process_on_startup(conn, p2, "streamer1") is False
