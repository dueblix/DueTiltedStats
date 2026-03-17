"""
Tests for db.py — all run against an in-memory SQLite connection.
"""
import sqlite3
import pytest
import db


def make_conn() -> sqlite3.Connection:
    """Return a fresh in-memory connection with the schema applied."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    conn.executescript(db.SCHEMA)
    return conn


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class TestSchema:
    def test_init_creates_all_tables(self, tmp_path):
        path = str(tmp_path / "test.db")
        db.init_db(path)
        conn = sqlite3.connect(path)
        tables = {
            row[0] for row in
            conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        conn.close()
        assert {"session", "run", "level", "player_level"}.issubset(tables)

    def test_init_is_idempotent(self, tmp_path):
        path = str(tmp_path / "test.db")
        db.init_db(path)
        db.init_db(path)  # must not raise


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

class TestSession:
    def test_insert_and_get_open(self):
        conn = make_conn()
        sid = db.insert_session(conn, "streamer1", "2024-01-01T00:00:00")
        row = db.get_open_session(conn, "streamer1")
        assert row["id"] == sid
        assert row["ended_at"] is None

    def test_close_removes_from_open(self):
        conn = make_conn()
        sid = db.insert_session(conn, "streamer1", "2024-01-01T00:00:00")
        db.close_session(conn, sid, "2024-01-01T01:00:00")
        assert db.get_open_session(conn, "streamer1") is None

    def test_get_open_session_none_when_empty(self):
        conn = make_conn()
        assert db.get_open_session(conn, "streamer1") is None

    def test_get_last_closed_session(self):
        conn = make_conn()
        sid = db.insert_session(conn, "streamer1", "2024-01-01T00:00:00")
        db.close_session(conn, sid, "2024-01-01T01:00:00")
        row = db.get_last_closed_session(conn, "streamer1")
        assert row["id"] == sid

    def test_get_last_closed_session_none_when_still_open(self):
        conn = make_conn()
        db.insert_session(conn, "streamer1", "2024-01-01T00:00:00")
        assert db.get_last_closed_session(conn, "streamer1") is None


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

class TestRun:
    def test_insert_and_get_open(self):
        conn = make_conn()
        rid = db.insert_run(conn, "streamer1", "2024-01-01T00:00:00")
        row = db.get_open_run(conn, "streamer1")
        assert row["id"] == rid
        assert row["ended_at"] is None

    def test_close_removes_from_open(self):
        conn = make_conn()
        rid = db.insert_run(conn, "streamer1", "2024-01-01T00:00:00")
        db.close_run(conn, rid, "2024-01-01T01:00:00")
        assert db.get_open_run(conn, "streamer1") is None

    def test_get_open_run_none_when_empty(self):
        conn = make_conn()
        assert db.get_open_run(conn, "streamer1") is None


# ---------------------------------------------------------------------------
# Level
# ---------------------------------------------------------------------------

class TestLevel:
    def _insert_session_and_run(self, conn):
        sid = db.insert_session(conn, "streamer1", "2024-01-01T00:00:00")
        rid = db.insert_run(conn, "streamer1", "2024-01-01T00:00:00")
        return sid, rid

    def test_insert_level_returns_id(self):
        conn = make_conn()
        sid, rid = self._insert_session_and_run(conn)
        lid = db.insert_level(conn, rid, sid, 1, 45.5, "2024-01-01T00:01:00", 100, True, None)
        assert lid is not None

    def test_get_last_level_returns_highest(self):
        conn = make_conn()
        sid, rid = self._insert_session_and_run(conn)
        db.insert_level(conn, rid, sid, 1, 45.5, "2024-01-01T00:01:00", 100, True, None)
        lid2 = db.insert_level(conn, rid, sid, 2, 30.0, "2024-01-01T00:02:00", 150, True, None)
        row = db.get_last_level(conn, rid)
        assert row["id"] == lid2
        assert row["level_number"] == 2

    def test_get_last_recorded_level_across_runs(self):
        conn = make_conn()
        sid, rid = self._insert_session_and_run(conn)
        db.insert_level(conn, rid, sid, 1, 45.5, "2024-01-01T00:01:00", 100, True, None)
        lid2 = db.insert_level(conn, rid, sid, 2, 30.0, "2024-01-01T00:02:00", 150, True, None)
        row = db.get_last_recorded_level(conn, "streamer1")
        assert row["id"] == lid2


# ---------------------------------------------------------------------------
# PlayerLevel + Leaderboards
# ---------------------------------------------------------------------------

class TestLeaderboard:
    def _setup(self, conn):
        sid = db.insert_session(conn, "streamer1", "2024-01-01T00:00:00")
        rid = db.insert_run(conn, "streamer1", "2024-01-01T00:00:00")
        lid = db.insert_level(conn, rid, sid, 1, 45.0, "2024-01-01T00:01:00", 100, True, None)
        db.insert_player_levels(conn, lid, [
            {"username": "alice", "display_name": "Alice", "survived": True},
            {"username": "bob",   "display_name": "Bob",   "survived": False},
        ])
        return sid, rid, lid

    def test_run_leaderboard_exp_earned(self):
        conn = make_conn()
        _, rid, _ = self._setup(conn)
        rows = {r["username"]: r for r in db.get_run_leaderboard(conn, rid)}
        assert rows["alice"]["exp_earned"] == 100
        assert rows["bob"]["exp_earned"]   == 0

    def test_run_leaderboard_ordered_by_exp(self):
        conn = make_conn()
        _, rid, _ = self._setup(conn)
        rows = db.get_run_leaderboard(conn, rid)
        assert rows[0]["username"] == "alice"

    def test_session_leaderboard_aggregates(self):
        conn = make_conn()
        sid, _, _ = self._setup(conn)
        rows = {r["username"]: r for r in db.get_session_leaderboard(conn, sid)}
        assert rows["alice"]["exp_earned"]      == 100
        assert rows["alice"]["levels_played"]   == 1
        assert rows["alice"]["levels_survived"] == 1
        assert rows["bob"]["exp_earned"]        == 0
        assert rows["bob"]["levels_survived"]   == 0

    def test_level_summary_counts(self):
        conn = make_conn()
        _, _, lid = self._setup(conn)
        summary = db.get_level_summary(conn, lid)
        assert summary["total_players"] == 2
        assert summary["survivors"]     == 1

    def test_get_last_run_id_in_session(self):
        conn = make_conn()
        sid, rid, _ = self._setup(conn)
        assert db.get_last_run_id_in_session(conn, sid) == rid
