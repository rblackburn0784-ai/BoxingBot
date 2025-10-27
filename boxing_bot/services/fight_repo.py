from boxing_bot.storage import db
from boxing_bot.config import SETTINGS

def save_fight(state_dict):
    data = db.read(SETTINGS.DB_FILE)
    data.setdefault("fights", {})[state_dict["id"]] = state_dict
    db.write(SETTINGS.DB_FILE, data)

def load_fight(fid: str):
    data = db.read(SETTINGS.DB_FILE)
    return data.get("fights", {}).get(fid)