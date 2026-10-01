import json, os, time, shutil
from pathlib import Path
from typing import Any, Dict
from ..config import SETTINGS

def read(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {"boxers": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {"boxers": {}}
    except (json.JSONDecodeError, OSError) as exc:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = f"{path}.corrupt-{stamp}.bak"
        try:
            shutil.copy2(path, backup)
        except OSError:
            backup = "(backup failed)"
        raise RuntimeError(f"Database is unreadable: {path}. Preserved copy: {backup}") from exc

def write(path: str, data: Dict[str, Any]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}.{time.time_ns()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)

def load_db() -> Dict[str, Any]:
    return read(SETTINGS.DB_FILE)

def save_db(data: Dict[str, Any]) -> None:
    write(SETTINGS.DB_FILE, data)

DB = load_db()
