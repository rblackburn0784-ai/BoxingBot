"""Simple JSON backed storage for BoxingBot."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

from ..config import SETTINGS

DEFAULT_DB: Dict[str, Any] = {"boxers": {}}


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError:
        print(f"[DB] Corrupt JSON at {path}. Starting fresh.")
        return DEFAULT_DB.copy()
    except FileNotFoundError:
        return DEFAULT_DB.copy()
    except OSError as exc:
        print(f"[DB] Unable to read database at {path}: {exc}. Starting fresh.")
        return DEFAULT_DB.copy()

    if isinstance(data, dict):
        return data

    print(f"[DB] Unexpected data in {path!s}; resetting database.")
    return DEFAULT_DB.copy()


def load_db() -> Dict[str, Any]:
    """Load the database from disk.

    Any errors encountered will result in a fresh in-memory database being
    returned. Callers are expected to persist changes with :func:`save_db`.
    """

    db_path = Path(SETTINGS.DB_FILE)
    return _read_json(db_path)


def save_db(data: Dict[str, Any]) -> None:
    """Persist the database to disk in an atomic fashion."""

    db_path = Path(SETTINGS.DB_FILE)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = db_path.with_name(f"{db_path.name}.tmp.{os.getpid()}")

    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())

    os.replace(tmp_path, db_path)


DB = load_db()

__all__ = ["DB", "load_db", "save_db"]