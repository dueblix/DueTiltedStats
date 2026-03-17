"""
watcher.py — Monitors game CSV files and drives the processing pipeline.

Uses watchdog's PollingObserver which works on both native Windows filesystems
and Windows filesystems mounted in WSL (/mnt/c/...). Polling also avoids
inotify limits and is safe inside PyInstaller bundles.
"""

import os
from pathlib import Path

from watchdog.observers.polling import PollingObserver
from watchdog.events import FileSystemEventHandler

import db
import processor


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def resolve_save_dir() -> str:
    """
    Locate the MarblesOnStream save-game directory.

    Resolution order:
      1. MARBLES_SAVE_DIR env var — explicit override, set this for WSL dev:
             export MARBLES_SAVE_DIR="/mnt/c/Users/<you>/AppData/Local/MarblesOnStream/Saved/SaveGames"
      2. LOCALAPPDATA env var — set automatically on Windows and in PyInstaller bundles.
      3. EnvironmentError with instructions.
    """
    override = os.getenv("MARBLES_SAVE_DIR")
    if override:
        return override
    localappdata = os.getenv("LOCALAPPDATA")
    if localappdata:
        return os.path.join(localappdata, "MarblesOnStream", "Saved", "SaveGames")
    raise EnvironmentError(
        "Cannot locate MarblesOnStream save directory.\n"
        "Set LOCALAPPDATA (Windows default) or MARBLES_SAVE_DIR to the full path.\n"
        "Example for WSL:\n"
        '  export MARBLES_SAVE_DIR="/mnt/c/Users/<username>/AppData/Local'
        '/MarblesOnStream/Saved/SaveGames"'
    )


# ---------------------------------------------------------------------------
# Watcher
# ---------------------------------------------------------------------------

class Watcher:
    """
    Polls LastTiltLevelPlayers.csv for changes and drives the full
    processing pipeline on each level completion.

    Intended usage:
        watcher = Watcher(db_path="tilted.db", streamer_username="dueblix")
        watcher.start()       # call before Flask
        flask_app.run(...)    # blocks main thread
        watcher.stop()        # called on shutdown
    """

    def __init__(
        self,
        db_path: str,
        streamer_username: str,
        save_dir: str | None = None,
    ):
        self.db_path = db_path
        self.streamer_username = streamer_username

        save_dir = save_dir or resolve_save_dir()
        self.players_csv = os.path.join(save_dir, "LastTiltLevelPlayers.csv")
        self.level_csv   = os.path.join(save_dir, "LastTiltLevel.csv")
        self.sav_file    = os.path.join(save_dir, "Sessions", "New tilts.sav")

        # colours is read by Flask and written here; dict replacement is
        # GIL-atomic in CPython so no lock is needed for this use case.
        self.colours: dict = {}

        self._last_mtime: float | None = None
        self._sav_mtime:  float | None = None
        self._observer:   PollingObserver | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start(self) -> None:
        """
        Initialise the database, catch any level that completed while the
        watcher was down, then begin polling.
        """
        db.init_db(self.db_path)
        self._refresh_colours()

        try:
            players_df = processor.parse_players_csv(self.players_csv)
            with db.get_conn(self.db_path) as conn:
                if processor.should_process_on_startup(conn, players_df, self.streamer_username):
                    level_df = processor.parse_level_csv(self.level_csv)
                    level_id = processor.process_level_update(
                        conn, players_df, level_df,
                        processor.now_iso(), self.streamer_username,
                    )
                    print(f"[watcher] Startup catch-up: recorded level id={level_id}")
        except FileNotFoundError:
            print("[watcher] Game CSVs not found — waiting for game to start.")

        self._last_mtime = _safe_mtime(self.players_csv)

        handler = _CSVHandler(self)
        self._observer = PollingObserver(timeout=0.5)
        self._observer.schedule(
            handler,
            path=str(Path(self.players_csv).parent),
            recursive=False,
        )
        self._observer.start()
        print("[watcher] Polling started.")

    def stop(self) -> None:
        """Stop polling and close the open session."""
        if self._observer:
            self._observer.stop()
            self._observer.join()

        with db.get_conn(self.db_path) as conn:
            open_session = db.get_open_session(conn, self.streamer_username)
            if open_session:
                db.close_session(conn, open_session["id"], processor.now_iso())
                print("[watcher] Session closed.")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_players_csv_changed(self) -> None:
        """Called by the watchdog handler when a real change is detected."""
        completed_at = processor.now_iso()
        self._refresh_colours()

        try:
            players_df = processor.parse_players_csv(self.players_csv)
            level_df   = processor.parse_level_csv(self.level_csv)
        except Exception as exc:
            print(f"[watcher] Error reading CSVs: {exc}")
            return

        with db.get_conn(self.db_path) as conn:
            try:
                level_id = processor.process_level_update(
                    conn, players_df, level_df, completed_at, self.streamer_username,
                )
                level_number = int(players_df["LastLevelJoined"].max())
                print(f"[watcher] Level {level_number} recorded (id={level_id})")
            except Exception as exc:
                print(f"[watcher] Error processing level: {exc}")

    def _refresh_colours(self) -> None:
        """Reload player colours from the .sav file only when it has changed."""
        if not os.path.exists(self.sav_file):
            return
        mtime = _safe_mtime(self.sav_file)
        if mtime == self._sav_mtime:
            return
        try:
            self.colours = processor.generate_colours(self.sav_file)
            self._sav_mtime = mtime
        except Exception as exc:
            print(f"[watcher] Could not parse colour data: {exc}")


# ---------------------------------------------------------------------------
# Watchdog event handler
# ---------------------------------------------------------------------------

class _CSVHandler(FileSystemEventHandler):
    """
    Filters directory-level watchdog events down to changes on the
    players CSV, with an mtime guard to deduplicate polling artifacts.
    """

    def __init__(self, watcher: Watcher):
        self._watcher = watcher

    def on_modified(self, event) -> None:
        if event.is_directory:
            return
        if os.path.normpath(event.src_path) != os.path.normpath(self._watcher.players_csv):
            return

        # Deduplicate: PollingObserver can emit multiple events per write.
        new_mtime = _safe_mtime(self._watcher.players_csv)
        if new_mtime == self._watcher._last_mtime:
            return
        self._watcher._last_mtime = new_mtime

        self._watcher._on_players_csv_changed()


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _safe_mtime(path: str) -> float | None:
    """Return mtime without raising if the file doesn't exist yet."""
    try:
        return os.path.getmtime(path)
    except OSError:
        return None
