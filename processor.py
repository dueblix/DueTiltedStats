"""
processor.py — Pure data logic.

No file I/O, no Qt, no network. The watcher feeds parsed DataFrames in;
this module calls db.py to persist results and manages run/session lifecycle.
"""

from datetime import datetime, timezone

import pandas as pd

import db

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# LastTiltLevelPlayers.csv has a trailing comma on every data row but NOT
# on the header row.  Pandas sees 6 header fields vs 7 data fields and
# silently infers an unnamed index column, shifting every named column one
# position to the right.  We work around this by supplying all 7 column
# names ourselves (skiprows=1 drops the original header) so the mapping
# is always correct regardless of pandas version.
#
# Actual columns: Username, DisplayName, PointsEarned, TimeOnBoard,
#                 LastLevelJoined, TopTiltee, <trailing-empty>
# TimeOnBoard  — skipped: sentinel values (-1) make it unreliable.
# TopTiltee    — skipped: CurrentTopTiltee in LastTiltLevel.csv is authoritative.
# _trailing    — skipped: artefact of the trailing comma.
_PLAYERS_ALL_COLS  = ["Username", "DisplayName", "PointsEarned", "TimeOnBoard",
                      "LastLevelJoined", "TopTiltee", "_trailing"]
PLAYERS_USECOLS    = ["Username", "DisplayName", "PointsEarned", "LastLevelJoined"]

# Actual game file headers (LastTiltLevel.csv):
#   CurrentLevel, ElapsedTime, CurrentTopTiltee, LevelExp, TotalExp, Live, LevelPassed
#
# TotalExp and Live are skipped — TotalExp is derived, Live is not needed for recording.
LEVEL_USECOLS = ["CurrentLevel", "ElapsedTime", "CurrentTopTiltee", "LevelExp", "LevelPassed"]


# ---------------------------------------------------------------------------
# CSV helpers  (carried forward from main.py)
# ---------------------------------------------------------------------------

def read_csv_encoding(path, **kwargs):
    """Read a game CSV, handling UTF-16 BOM vs plain UTF-8."""
    with open(path, "rb") as f:
        bom = f.read(1)
    encoding = "utf-16" if bom == b"\xff" else "utf-8"
    return pd.read_csv(path, encoding=encoding, **kwargs)


def parse_players_csv(path) -> pd.DataFrame:
    """
    Read LastTiltLevelPlayers.csv.

    Returns a DataFrame indexed by Username (Twitch username, lowercase) with columns:
        DisplayName, PointsEarned, LastLevelJoined
    """
    df = read_csv_encoding(
        path,
        names=_PLAYERS_ALL_COLS,
        skiprows=1,
        index_col=0,
        usecols=PLAYERS_USECOLS,
    )
    return df


def parse_level_csv(path) -> pd.DataFrame:
    """
    Read LastTiltLevel.csv.

    Returns a single-row DataFrame with columns:
        CurrentLevel, ElapsedTime, CurrentTopTiltee, LevelExp, LevelPassed
    """
    return read_csv_encoding(
        path,
        usecols=LEVEL_USECOLS,
        true_values=["true"],
        false_values=["false"],
    )


def parse_elapsed_time(elapsed_str) -> float | None:
    """
    Convert game elapsed time string "MM:SS.mmm" to total seconds.
    Returns None for missing/sentinel values.
    """
    if elapsed_str is None:
        return None
    s = str(elapsed_str).strip()
    if not s or s.lstrip("-").lower() in {"1", "tag doesnt exist"}:
        return None
    try:
        minutes, rest = s.split(":")
        return int(minutes) * 60 + float(rest)
    except (ValueError, AttributeError):
        return None



# ---------------------------------------------------------------------------
# Core level processing
# ---------------------------------------------------------------------------

def _extract_level_data(players_df: pd.DataFrame, level_df: pd.DataFrame) -> dict:
    """
    Derive structured level data from the two game DataFrames.

    Returns a dict consumed by process_level_update(); not written to DB here.
    """
    row = level_df.iloc[0]

    level_number = int(row["CurrentLevel"])
    elapsed_time = parse_elapsed_time(row["ElapsedTime"])
    level_exp    = int(row["LevelExp"])
    level_passed = bool(row["LevelPassed"])

    top_tiltee_raw      = row["CurrentTopTiltee"]
    top_tiltee_username = str(top_tiltee_raw) if pd.notna(top_tiltee_raw) and str(top_tiltee_raw).strip() else None

    # Players present at this level.
    level_mask   = players_df["LastLevelJoined"] == level_number
    level_players = players_df.loc[level_mask]

    players = [
        {
            "username":     str(p.Index),
            "display_name": str(p.DisplayName),
            "survived":     bool(p.PointsEarned > 0),
        }
        for p in level_players.itertuples()
    ]

    return {
        "level_number":       level_number,
        "elapsed_time":       elapsed_time,
        "level_exp":          level_exp,
        "level_passed":       level_passed,
        "top_tiltee_username": top_tiltee_username,
        "players":            players,
    }


def process_level_update(
    conn,
    players_df: pd.DataFrame,
    level_df: pd.DataFrame,
    completed_at: str,
    streamer_username: str,
) -> int:
    """
    Main entry point. Called by the watcher for each CSV change.

    Inserts a Level + PlayerLevel rows and manages Run/Session lifecycle.
    Returns the new level_id.
    """
    data = _extract_level_data(players_df, level_df)
    level_number = data["level_number"]

    open_session = db.get_open_session(conn, streamer_username)
    open_run = db.get_open_run(conn, streamer_username)

    # --- Session ---
    # A session persists across runs until explicitly closed (e.g. on watcher shutdown).
    if open_session:
        session_id = open_session["id"]
    else:
        session_id = db.insert_session(conn, streamer_username, completed_at)

    # --- Run ---
    if level_number == 1:
        # Level 1 means a new run has started (game reset or fresh start).
        # Close any run that was left open from a previous attempt.
        if open_run:
            db.close_run(conn, open_run["id"], completed_at)
        run_id = db.insert_run(conn, streamer_username, completed_at)
    else:
        if open_run:
            run_id = open_run["id"]
        else:
            # Watcher restarted mid-run — create a recovery run so data isn't lost.
            run_id = db.insert_run(conn, streamer_username, completed_at)

    # --- Level ---
    level_id = db.insert_level(
        conn,
        run_id=run_id,
        session_id=session_id,
        level_number=level_number,
        elapsed_time=data["elapsed_time"],
        completed_at=completed_at,
        level_exp=data["level_exp"],
        level_passed=data["level_passed"],
        top_tiltee_username=data["top_tiltee_username"],
    )

    # --- Players ---
    db.insert_player_levels(conn, level_id, data["players"])

    # --- Run lifecycle ---
    # Close the run if LevelPassed=false — the game will reset to level 1.
    if not data["level_passed"]:
        db.close_run(conn, run_id, completed_at)

    return level_id


# ---------------------------------------------------------------------------
# Startup state check  (replaces stored_data_load logic from main.py)
# ---------------------------------------------------------------------------

def should_process_on_startup(
    conn,
    players_df: pd.DataFrame,
    streamer_username: str,
) -> bool:
    """
    Called once when the watcher starts. Determines whether the current game
    CSV represents a level that hasn't been recorded yet.

    Returns True  → process the current CSV immediately (missed an update).
    Returns False → CSV matches or precedes the last recorded level; just wait.
    """
    current_level = int(players_df["LastLevelJoined"].max())

    # Level 1 always signals a fresh run — process immediately.
    if current_level == 1:
        return True

    # For level > 1, compare against the last recorded level across all runs
    # (open or closed). If the game has advanced past what we recorded, we
    # missed an update while the watcher was down.
    last = db.get_last_recorded_level(conn, streamer_username)
    if last is None:
        # No history at all — don't create a partial run; wait for level 1.
        return False
    return current_level > last["level_number"]


def now_iso() -> str:
    """Return the current UTC time as an ISO8601 string."""
    return datetime.now(timezone.utc).isoformat()
