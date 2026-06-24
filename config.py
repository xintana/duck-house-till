"""Per-laptop configuration.

Stores the one thing that differs between machines: the path to the shared
SQLite data file inside the cloud-sync folder (PLAN.md §5). Lives next to the
OS user-config dir so it's never inside the synced folder itself.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

APP_NAME = "SalesTracker"

# Config file location: %APPDATA%\SalesTracker\config.json on Windows,
# ~/.config/SalesTracker/config.json elsewhere.
if os.name == "nt":
    _CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
else:
    _CONFIG_DIR = Path.home() / ".config" / APP_NAME

CONFIG_PATH = _CONFIG_DIR / "config.json"


def load() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {}


def save(data: dict) -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_db_path() -> str | None:
    """Return the configured data-file path, or None if not set up yet."""
    return load().get("db_path")


def set_db_path(path: str | Path) -> None:
    data = load()
    data["db_path"] = str(Path(path))
    save(data)
