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


# ---------------------------------------------------------------------------
# History queries
# ---------------------------------------------------------------------------

class TestHistoryQueries:
    def _closed_session(self, conn, username="streamer1",
                        started="2024-01-01T00:00:00", ended="2024-01-01T01:00:00"):
        sid = db.insert_session(conn, username, started)
        db.close_session(conn, sid, ended)
        return sid

    def test_get_all_closed_sessions_returns_only_closed(self):
        conn = make_conn()
        sid = self._closed_session(conn)
        db.insert_session(conn, "streamer1", "2024-01-02T00:00:00")  # open
        rows = db.get_all_closed_sessions(conn, "streamer1")
        assert len(rows) == 1
        assert rows[0]["id"] == sid

    def test_get_all_closed_sessions_ordered_newest_first(self):
        conn = make_conn()
        sid1 = self._closed_session(conn, started="2024-01-01T00:00:00", ended="2024-01-01T01:00:00")
        sid2 = self._closed_session(conn, started="2024-01-02T00:00:00", ended="2024-01-02T01:00:00")
        rows = db.get_all_closed_sessions(conn, "streamer1")
        assert rows[0]["id"] == sid2
        assert rows[1]["id"] == sid1

    def test_get_all_closed_sessions_empty(self):
        conn = make_conn()
        assert db.get_all_closed_sessions(conn, "streamer1") == []

    def test_get_all_closed_sessions_excludes_other_streamer(self):
        conn = make_conn()
        self._closed_session(conn, username="other")
        assert db.get_all_closed_sessions(conn, "streamer1") == []

    def test_get_session_top_tiltees_counts_correctly(self):
        conn = make_conn()
        sid = db.insert_session(conn, "streamer1", "2024-01-01T00:00:00")
        rid = db.insert_run(conn, "streamer1", "2024-01-01T00:00:00")
        db.insert_level(conn, rid, sid, 1, 30.0, "2024-01-01T00:01:00", 100, True, "alice")
        db.insert_level(conn, rid, sid, 2, 30.0, "2024-01-01T00:02:00", 100, True, "alice")
        db.insert_level(conn, rid, sid, 3, 30.0, "2024-01-01T00:03:00", 100, True, "bob")
        counts = {r["top_tiltee_username"]: r["tiltee_count"]
                  for r in db.get_session_top_tiltees(conn, sid)}
        assert counts["alice"] == 2
        assert counts["bob"] == 1

    def test_get_session_top_tiltees_ordered_by_count(self):
        conn = make_conn()
        sid = db.insert_session(conn, "streamer1", "2024-01-01T00:00:00")
        rid = db.insert_run(conn, "streamer1", "2024-01-01T00:00:00")
        db.insert_level(conn, rid, sid, 1, 30.0, "2024-01-01T00:01:00", 100, True, "alice")
        db.insert_level(conn, rid, sid, 2, 30.0, "2024-01-01T00:02:00", 100, True, "alice")
        db.insert_level(conn, rid, sid, 3, 30.0, "2024-01-01T00:03:00", 100, True, "bob")
        rows = db.get_session_top_tiltees(conn, sid)
        assert rows[0]["top_tiltee_username"] == "alice"

    def test_get_session_top_tiltees_ignores_null(self):
        conn = make_conn()
        sid = db.insert_session(conn, "streamer1", "2024-01-01T00:00:00")
        rid = db.insert_run(conn, "streamer1", "2024-01-01T00:00:00")
        db.insert_level(conn, rid, sid, 1, 30.0, "2024-01-01T00:01:00", 100, True, None)
        assert db.get_session_top_tiltees(conn, sid) == []

    def test_get_session_level_count(self):
        conn = make_conn()
        sid = db.insert_session(conn, "streamer1", "2024-01-01T00:00:00")
        rid = db.insert_run(conn, "streamer1", "2024-01-01T00:00:00")
        db.insert_level(conn, rid, sid, 1, 30.0, "2024-01-01T00:01:00", 100, True, None)
        db.insert_level(conn, rid, sid, 2, 30.0, "2024-01-01T00:02:00", 100, True, None)
        assert db.get_session_level_count(conn, sid) == 2

    def test_get_session_level_count_empty_session(self):
        conn = make_conn()
        sid = db.insert_session(conn, "streamer1", "2024-01-01T00:00:00")
        assert db.get_session_level_count(conn, sid) == 0


# ---------------------------------------------------------------------------
# Run history + totals
# ---------------------------------------------------------------------------

class TestRunHistoryAndTotals:
    def _setup(self, conn):
        sid = db.insert_session(conn, "streamer1", "2024-01-01T00:00:00")
        rid = db.insert_run(conn, "streamer1", "2024-01-01T00:00:00")
        for i in range(1, 4):
            lid = db.insert_level(
                conn, rid, sid, i, 30.0 * i, f"2024-01-01T00:{i:02d}:00", 100 * i, True, None
            )
            db.insert_player_levels(conn, lid, [
                {"username": "alice", "display_name": "Alice", "survived": True},
                {"username": "bob",   "display_name": "Bob",   "survived": False},
            ])
        return sid, rid

    def test_get_run_level_history_returns_last_n_most_recent_first(self):
        conn = make_conn()
        _, rid = self._setup(conn)
        rows = db.get_run_level_history(conn, rid, 2)
        assert len(rows) == 2
        assert rows[0]["level_number"] == 3
        assert rows[1]["level_number"] == 2

    def test_get_run_level_history_player_counts(self):
        conn = make_conn()
        _, rid = self._setup(conn)
        rows = db.get_run_level_history(conn, rid, 10)
        assert len(rows) == 3
        for row in rows:
            assert row["total_players"] == 2
            assert row["survivors"] == 1

    def test_get_run_level_history_empty_run(self):
        conn = make_conn()
        db.insert_session(conn, "streamer1", "2024-01-01T00:00:00")
        rid = db.insert_run(conn, "streamer1", "2024-01-01T00:00:00")
        assert db.get_run_level_history(conn, rid, 5) == []

    def test_get_run_totals_aggregates(self):
        conn = make_conn()
        _, rid = self._setup(conn)
        totals = db.get_run_totals(conn, rid)
        assert totals["level_count"]     == 3
        assert totals["total_survivors"] == 3   # 1 survivor per level
        assert totals["total_players"]   == 6   # 2 players per level
        assert totals["total_exp"]       == 600  # 100+200+300
        assert totals["started_at"]      == "2024-01-01T00:00:00"

    def test_get_run_totals_empty_run(self):
        conn = make_conn()
        db.insert_session(conn, "streamer1", "2024-01-01T00:00:00")
        rid = db.insert_run(conn, "streamer1", "2024-01-01T00:00:00")
        totals = db.get_run_totals(conn, rid)
        assert totals["level_count"]     == 0
        assert totals["total_survivors"] == 0
        assert totals["total_players"]   == 0
        assert totals["total_exp"]       == 0

    def test_get_run_totals_includes_ended_at(self):
        conn = make_conn()
        db.insert_session(conn, "streamer1", "2024-01-01T00:00:00")
        rid = db.insert_run(conn, "streamer1", "2024-01-01T00:00:00")
        db.close_run(conn, rid, "2024-01-01T01:00:00")
        totals = db.get_run_totals(conn, rid)
        assert totals["ended_at"] == "2024-01-01T01:00:00"
