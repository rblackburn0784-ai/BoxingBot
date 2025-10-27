import json, os, time
from typing import Any, Dict
from ..config import SETTINGS

def load_db() -> Dict[str, Any]:
    path = SETTINGS.DB_FILE
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                print(f"[DB] Corrupt JSON at {path}. Starting fresh.")
    return {"boxers": {}}

def save_db(data: Dict[str, Any]) -> None:
    path = SETTINGS.DB_FILE
    tmp = f"{path}.tmp.{int(time.time())}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)

DB = load_db()
