"""
app.py — Entry point. Wires the CSV watcher and Flask overlay together.

Run:
    python app.py

Overlay available at:  http://127.0.0.1:5000/overlay
Config available at:   http://127.0.0.1:5000/config
History available at:  http://127.0.0.1:5000/history
API state at:          http://127.0.0.1:5000/api/state

Required environment variables:
    MARBLES_STREAMER   Your Twitch username (lowercase).
                       Example: export MARBLES_STREAMER=dueblix
    MARBLES_SAVE_DIR   Path to MarblesOnStream SaveGames folder (WSL only).
                       On Windows this is resolved automatically via LOCALAPPDATA.
"""

import os

from watcher import Watcher
from flask_overlay import create_app

DB_PATH      = "tilted.db"
FLASK_HOST   = "127.0.0.1"
FLASK_PORT   = 5000


def _resolve_streamer() -> str:
    username = os.getenv("MARBLES_STREAMER")
    if not username:
        raise EnvironmentError(
            "MARBLES_STREAMER is not set.\n"
            "Set it to your Twitch username before running.\n"
            "Example: export MARBLES_STREAMER=dueblix"
        )
    return username.lower().strip()


def main() -> None:
    streamer = _resolve_streamer()
    watcher = Watcher(db_path=DB_PATH, streamer_username=streamer)
    watcher.start()

    app = create_app(watcher, db_path=DB_PATH)

    print(f"[app] Overlay  at http://{FLASK_HOST}:{FLASK_PORT}/overlay")
    print(f"[app] Config   at http://{FLASK_HOST}:{FLASK_PORT}/config")
    print(f"[app] History  at http://{FLASK_HOST}:{FLASK_PORT}/history")
    print("[app] Press Ctrl+C to stop.")

    try:
        app.run(host=FLASK_HOST, port=FLASK_PORT, use_reloader=False)
    except KeyboardInterrupt:
        pass
    finally:
        watcher.stop()
        print("[app] Stopped.")


if __name__ == "__main__":
    main()
