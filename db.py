import sqlite3
from contextlib import contextmanager

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS session (
    id               INTEGER PRIMARY KEY,
    streamer_username TEXT    NOT NULL,
    started_at       TEXT    NOT NULL,
    ended_at         TEXT
);

CREATE TABLE IF NOT EXISTS run (
    id               INTEGER PRIMARY KEY,
    streamer_username TEXT    NOT NULL,
    started_at       TEXT    NOT NULL,
    ended_at         TEXT
);

CREATE TABLE IF NOT EXISTS level (
    id                  INTEGER PRIMARY KEY,
    run_id              INTEGER NOT NULL REFERENCES run(id),
    session_id          INTEGER NOT NULL REFERENCES session(id),
    level_number        INTEGER NOT NULL,
    elapsed_time        REAL,       -- seconds, from game CSV (MM:SS.mmm)
    completed_at        TEXT NOT NULL, -- wall-clock ISO8601, set by file watcher
    level_exp           INTEGER,    -- points awarded this level (0 if level not passed)
    level_passed        INTEGER NOT NULL CHECK (level_passed IN (0, 1)),
    top_tiltee_username TEXT        -- NULL if no TopTiltee flag was set
);

CREATE TABLE IF NOT EXISTS player_level (
    id           INTEGER PRIMARY KEY,
    level_id     INTEGER NOT NULL REFERENCES level(id),
    username     TEXT    NOT NULL,
    display_name TEXT    NOT NULL,
    survived     INTEGER NOT NULL CHECK (survived IN (0, 1))
    -- is_top_tiltee: derived — username = level.top_tiltee_username
    -- points_earned: derived — survived * level.level_exp
);
"""


def init_db(path: str = "tilted.db") -> None:
    """Create tables if they don't exist. Safe to call on every startup."""
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)


@contextmanager
def get_conn(path: str = "tilted.db"):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

def insert_session(conn: sqlite3.Connection, streamer_username: str, started_at: str) -> int:
    cur = conn.execute(
        "INSERT INTO session (streamer_username, started_at) VALUES (?, ?)",
        (streamer_username, started_at),
    )
    return cur.lastrowid


def close_session(conn: sqlite3.Connection, session_id: int, ended_at: str) -> None:
    conn.execute(
        "UPDATE session SET ended_at = ? WHERE id = ?",
        (ended_at, session_id),
    )


def get_open_session(conn: sqlite3.Connection, streamer_username: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM session WHERE streamer_username = ? AND ended_at IS NULL ORDER BY id DESC LIMIT 1",
        (streamer_username,),
    ).fetchone()


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def insert_run(conn: sqlite3.Connection, streamer_username: str, started_at: str) -> int:
    cur = conn.execute(
        "INSERT INTO run (streamer_username, started_at) VALUES (?, ?)",
        (streamer_username, started_at),
    )
    return cur.lastrowid


def close_run(conn: sqlite3.Connection, run_id: int, ended_at: str) -> None:
    conn.execute(
        "UPDATE run SET ended_at = ? WHERE id = ?",
        (ended_at, run_id),
    )


def get_open_run(conn: sqlite3.Connection, streamer_username: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM run WHERE streamer_username = ? AND ended_at IS NULL ORDER BY id DESC LIMIT 1",
        (streamer_username,),
    ).fetchone()


# ---------------------------------------------------------------------------
# Level
# ---------------------------------------------------------------------------

def insert_level(
    conn: sqlite3.Connection,
    run_id: int,
    session_id: int,
    level_number: int,
    elapsed_time: float | None,
    completed_at: str,
    level_exp: int | None,
    level_passed: bool,
    top_tiltee_username: str | None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO level
            (run_id, session_id, level_number, elapsed_time, completed_at,
             level_exp, level_passed, top_tiltee_username)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            session_id,
            level_number,
            elapsed_time,
            completed_at,
            level_exp,
            int(level_passed),
            top_tiltee_username,
        ),
    )
    return cur.lastrowid


def get_last_level(conn: sqlite3.Connection, run_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM level WHERE run_id = ? ORDER BY id DESC LIMIT 1",
        (run_id,),
    ).fetchone()


# ---------------------------------------------------------------------------
# PlayerLevel
# ---------------------------------------------------------------------------

def insert_player_levels(
    conn: sqlite3.Connection,
    level_id: int,
    players: list[dict],
) -> None:
    """
    players: list of dicts with keys: username, display_name, survived (bool)
    """
    conn.executemany(
        """
        INSERT INTO player_level (level_id, username, display_name, survived)
        VALUES (:level_id, :username, :display_name, :survived)
        """,
        [
            {
                "level_id": level_id,
                "username": p["username"],
                "display_name": p["display_name"],
                "survived": int(p["survived"]),
            }
            for p in players
        ],
    )


# ---------------------------------------------------------------------------
# Query helpers (used by flask_overlay / FastAPI)
# ---------------------------------------------------------------------------

def get_session_leaderboard(conn: sqlite3.Connection, session_id: int) -> list[sqlite3.Row]:
    """
    Per-player totals for a session: exp earned, levels played, levels survived.
    exp_earned = SUM(level_exp) for levels where the player survived.
    """
    return conn.execute(
        """
        SELECT
            pl.display_name,
            pl.username,
            COUNT(pl.id)                              AS levels_played,
            SUM(pl.survived)                          AS levels_survived,
            SUM(pl.survived * COALESCE(l.level_exp, 0)) AS exp_earned
        FROM player_level pl
        JOIN level l ON l.id = pl.level_id
        WHERE l.session_id = ?
        GROUP BY pl.username
        ORDER BY exp_earned DESC, levels_survived DESC
        """,
        (session_id,),
    ).fetchall()


def get_run_leaderboard(conn: sqlite3.Connection, run_id: int) -> list[sqlite3.Row]:
    """Same aggregation scoped to a single run."""
    return conn.execute(
        """
        SELECT
            pl.display_name,
            pl.username,
            COUNT(pl.id)                              AS levels_played,
            SUM(pl.survived)                          AS levels_survived,
            SUM(pl.survived * COALESCE(l.level_exp, 0)) AS exp_earned
        FROM player_level pl
        JOIN level l ON l.id = pl.level_id
        WHERE l.run_id = ?
        GROUP BY pl.username
        ORDER BY exp_earned DESC, levels_survived DESC
        """,
        (run_id,),
    ).fetchall()


def get_last_closed_session(conn: sqlite3.Connection, streamer_username: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM session WHERE streamer_username = ? AND ended_at IS NOT NULL ORDER BY id DESC LIMIT 1",
        (streamer_username,),
    ).fetchone()


def get_last_run_id_in_session(conn: sqlite3.Connection, session_id: int) -> int | None:
    row = conn.execute(
        "SELECT run_id FROM level WHERE session_id = ? ORDER BY id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    return row["run_id"] if row else None


def get_last_recorded_level(conn: sqlite3.Connection, streamer_username: str) -> sqlite3.Row | None:
    """Most recently inserted level across all runs (open or closed)."""
    return conn.execute(
        """
        SELECT l.* FROM level l
        JOIN run r ON r.id = l.run_id
        WHERE r.streamer_username = ?
        ORDER BY l.id DESC LIMIT 1
        """,
        (streamer_username,),
    ).fetchone()


def get_all_closed_sessions(conn: sqlite3.Connection, streamer_username: str) -> list[sqlite3.Row]:
    """All closed sessions for a streamer, newest first."""
    return conn.execute(
        "SELECT * FROM session WHERE streamer_username = ? AND ended_at IS NOT NULL ORDER BY id DESC",
        (streamer_username,),
    ).fetchall()


def get_session_top_tiltees(conn: sqlite3.Connection, session_id: int) -> list[sqlite3.Row]:
    """Players ranked by number of times they held top tiltee in the session."""
    return conn.execute(
        """
        SELECT top_tiltee_username, COUNT(*) AS tiltee_count
        FROM level
        WHERE session_id = ? AND top_tiltee_username IS NOT NULL
        GROUP BY top_tiltee_username
        ORDER BY tiltee_count DESC
        """,
        (session_id,),
    ).fetchall()


def get_session_level_count(conn: sqlite3.Connection, session_id: int) -> int:
    """Total number of levels recorded for a session."""
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM level WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return row["cnt"] if row else 0


def get_level_summary(conn: sqlite3.Connection, level_id: int) -> sqlite3.Row | None:
    """Level row joined with survivor/total counts."""
    return conn.execute(
        """
        SELECT
            l.*,
            COUNT(pl.id)      AS total_players,
            SUM(pl.survived)  AS survivors
        FROM level l
        LEFT JOIN player_level pl ON pl.level_id = l.id
        WHERE l.id = ?
        GROUP BY l.id
        """,
        (level_id,),
    ).fetchone()


def get_run_level_history(
    conn: sqlite3.Connection, run_id: int, limit: int
) -> list[sqlite3.Row]:
    """Last *limit* levels for a run, most-recent first, with survivor/player counts."""
    return conn.execute(
        """
        SELECT
            l.*,
            COUNT(pl.id)                     AS total_players,
            COALESCE(SUM(pl.survived), 0)    AS survivors
        FROM level l
        LEFT JOIN player_level pl ON pl.level_id = l.id
        WHERE l.run_id = ?
        GROUP BY l.id
        ORDER BY l.level_number DESC
        LIMIT ?
        """,
        (run_id, limit),
    ).fetchall()


def get_run_totals(conn: sqlite3.Connection, run_id: int) -> sqlite3.Row | None:
    """Aggregate stats for a run: started/ended timestamps, level count, survivor/player counts, total exp."""
    return conn.execute(
        """
        SELECT
            r.started_at,
            r.ended_at,
            COUNT(ls.id)                       AS level_count,
            COALESCE(SUM(ls.survivors), 0)     AS total_survivors,
            COALESCE(SUM(ls.total_players), 0) AS total_players,
            COALESCE(SUM(ls.level_exp), 0)     AS total_exp
        FROM run r
        LEFT JOIN (
            SELECT
                l.id,
                l.run_id,
                COALESCE(l.level_exp, 0)          AS level_exp,
                COALESCE(SUM(pl.survived), 0)     AS survivors,
                COUNT(pl.id)                       AS total_players
            FROM level l
            LEFT JOIN player_level pl ON pl.level_id = l.id
            WHERE l.run_id = ?
            GROUP BY l.id
        ) ls ON ls.run_id = r.id
        WHERE r.id = ?
        GROUP BY r.id
        """,
        (run_id, run_id),
    ).fetchone()
