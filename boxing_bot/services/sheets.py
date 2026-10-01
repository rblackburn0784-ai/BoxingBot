# boxing_bot/services/sheets.py
from __future__ import annotations

import os, re, urllib.parse, csv, io
from typing import Dict, Any, Tuple, List, Optional

import requests  # pip install requests
import gspread   # pip install gspread google-auth
from google.oauth2.service_account import Credentials
from ..models import Boxer, _weight_kg_from_class
from ..services.roster import save_boxer, get_boxer  # upsert + lookup
from ..config import SETTINGS
import re

EXPECTED_HEADERS = {
    "boxer's_name": "name",
    "gender": "gender",
    "ring_introduction": "intro",
    "ring_music": "intro_music",
    "weight_class": "weight_kg",
    "boxer_stats_60_point_max_power": "power",
    "boxer_stats_60_point_max_speed": "speed",
    "boxer_stats_60_point_max_accuracy": "accuracy",
    "boxer_stats_60_point_max_defense": "defense",
    "boxer_stats_60_point_max_footwork": "footwork",
    "boxer_stats_60_point_max_stamina": "stamina",
    "boxer_stats_60_point_max_chin": "chin",
    "boxer_stats_60_point_max_body": "body",
    "unique_trait": "trait",
}

_STAT_PATTERNS = {
    "power": re.compile(r"\bpower\b", re.I),
    "speed": re.compile(r"\bspeed\b", re.I),
    "accuracy": re.compile(r"\baccuracy\b", re.I),
    "defense": re.compile(r"\bdefen[cs]e\b", re.I),
    "footwork": re.compile(r"\bfootwork\b", re.I),
    "stamina": re.compile(r"\bstamina\b", re.I),
    "chin": re.compile(r"\bchin\b", re.I),
    "body": re.compile(r"\bbody\b", re.I),
}

# Strings we will ignore if present as columns
_IGNORE_COLS = [
    "timestamp",
    "total stats",
    "boxers logo/sponsor",
    "logo/sponsor",
    "righty or a lefty",   # not in model
    "backstory",           # not in model (we use intro + trait)
]

def _build_header_map(headers: List[str]) -> Dict[int, str]:
    """
    Map your verbose headers to canonical fields expected by the importer.
    """
    out: Dict[int, str] = {}

    for idx, raw in enumerate(headers):
        h = (raw or "").strip()
        h_low = h.lower()

        # skip ignorable columns
        if any(tok in h_low for tok in _IGNORE_COLS):
            continue

        # name
        if "boxer" in h_low and "name" in h_low:
            out[idx] = "name"; continue
        if h_low == "name":
            out[idx] = "name"; continue

        # gender
        if "gender" in h_low:
            out[idx] = "gender"; continue

        # intro (your “Ring Introduction”)
        if "ring introduction" in h_low or (("intro" in h_low) and ("music" not in h_low)):
            out[idx] = "intro"; continue

        # intro music
        if "ring music" in h_low or "intro music" in h_low:
            out[idx] = "intro_music"; continue

        # trait (“Unique Trait”)
        if "unique trait" in h_low or h_low == "trait":
            out[idx] = "trait"; continue

        # weight: either direct kg/weight or a Weight Class label we will convert later
        if "weight_kg" in h_low or h_low == "weight (kg)" or h_low == "weight":
            out[idx] = "weight_kg"; continue
        if "weight class" in h_low:
            out[idx] = "weight_class"; continue

        # stats: any header that ends with [Power] etc.
        matched = False
        for field, pat in _STAT_PATTERNS.items():
            if pat.search(h):
                out[idx] = field
                matched = True
                break
        if matched:
            continue

        # leave others unmapped (ignored)
    return out

# ─────────────────────────────────────────────────────────────────────────────
# Helpers: creds / ids / gid / csv
def _has_google_creds() -> bool:
    return bool(os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"))

def _sheet_id_from_input(sheet_id_or_url: str) -> str:
    m = re.search(r"/spreadsheets/d/([^/]+)/", sheet_id_or_url)
    return m.group(1) if m else sheet_id_or_url.strip()

def _gid_from_url(url: str) -> Optional[int]:
    try:
        u = urllib.parse.urlparse(url)
        for part in (u.fragment, u.query):
            q = urllib.parse.parse_qs(part)
            if "gid" in q and q["gid"]:
                return int(q["gid"][0])
    except Exception:
        pass
    return None

def _try_public_csv(sheet_url: str) -> Optional[Tuple[List[str], List[List[str]]]]:
    gid = _gid_from_url(sheet_url) or 0
    sid = _sheet_id_from_input(sheet_url)
    csv_url = f"https://docs.google.com/spreadsheets/d/{sid}/export?format=csv&gid={gid}"
    r = requests.get(csv_url, timeout=20)
    if r.status_code != 200 or not r.text.strip():
        return None
    reader = csv.reader(io.StringIO(r.text))
    rows = list(reader)
    if not rows:
        return None
    return rows[0], rows[1:]

def _auth_client() -> gspread.Client:
    json_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    inline_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    if json_path:
        creds = Credentials.from_service_account_file(json_path, scopes=scopes)
    elif inline_json:
        import json
        data = json.loads(inline_json)
        creds = Credentials.from_service_account_info(data, scopes=scopes)
    else:
        raise RuntimeError("No service account credentials found. Set GOOGLE_APPLICATION_CREDENTIALS or GOOGLE_SERVICE_ACCOUNT_JSON.")
    return gspread.authorize(creds)

def _worksheet_by_gid(sh, gid: int):
    for ws in sh.worksheets():
        if getattr(ws, "id", None) == gid:
            return ws
    return None

# ─────────────────────────────────────────────────────────────────────────────
# Fetch rows (prefers CSV when no creds)
def fetch_sheet_rows(sheet_id_or_url: str, tab_name_or_range: str = "Sheet1!A1:Z") -> Tuple[List[str], List[List[str]]]:
    # 0) If no creds, go straight to public CSV (you confirmed it works)
    if not _has_google_creds():
        alt = _try_public_csv(sheet_id_or_url)
        if alt:
            return alt
        # If CSV not available, fall through to raise the standard error below.

    # 1) Try authenticated path
    try:
        client = _auth_client()
        sid = _sheet_id_from_input(sheet_id_or_url)
        sh = client.open_by_key(sid)

        if "!" in tab_name_or_range:
            tab, rng = tab_name_or_range.split("!", 1)
            ws = sh.worksheet(tab)
            values = ws.get(rng)
        else:
            gid = _gid_from_url(sheet_id_or_url)
            if gid is not None and (tab_name_or_range == "Sheet1!A1:Z" or not tab_name_or_range):
                ws = _worksheet_by_gid(sh, gid) or sh.sheet1
                values = ws.get_all_values()
            else:
                ws = sh.worksheet(tab_name_or_range)
                values = ws.get_all_values()

        if not values:
            return [], []
        return values[0], values[1:] if len(values) > 1 else []

    except Exception:
        # 2) On any API failure, try the public CSV fallback
        alt = _try_public_csv(sheet_id_or_url)
        if alt:
            return alt
        raise

# ─────────────────────────────────────────────────────────────────────────────
# Row parsing

def _parse_int(x: Any, lo=0, hi=100) -> int:
    try:
        v = int(float(str(x).strip()))
    except Exception:
        v = 0
    return max(lo, min(hi, v))

def _parse_float(x: Any, default=66.7) -> float:
    try:
        return float(str(x).strip())
    except Exception:
        return float(default)

def _clean_str(x: Any) -> str:
    return (str(x).strip()) if x is not None else ""

def _row_to_boxer(row: List[Any], hmap: Dict[int, str]) -> Optional[Boxer]:
    data: Dict[str, Any] = {}
    for col_idx, field in hmap.items():
        if col_idx < len(row):
            data[field] = row[col_idx]

    name = _clean_str(data.get("name"))
    if not name:
        return None

    # Weight: prefer explicit kg, otherwise derive from class
    if "weight_kg" in data and str(data["weight_kg"]).strip():
        wkg = _parse_float(data.get("weight_kg", 66.7))
    elif "weight_class" in data and str(data["weight_class"]).strip():
        wkg = _weight_kg_from_class(str(data["weight_class"]))
    else:
        wkg = 66.7

    return Boxer(
        name=name,
        power=_parse_int(data.get("power", 0), lo=SETTINGS.MIN_PER_STAT, hi=SETTINGS.MAX_PER_STAT),
        speed=_parse_int(data.get("speed", 0), lo=SETTINGS.MIN_PER_STAT, hi=SETTINGS.MAX_PER_STAT),
        accuracy=_parse_int(data.get("accuracy", 0), lo=SETTINGS.MIN_PER_STAT, hi=SETTINGS.MAX_PER_STAT),
        defense=_parse_int(data.get("defense", 0), lo=SETTINGS.MIN_PER_STAT, hi=SETTINGS.MAX_PER_STAT),
        footwork=_parse_int(data.get("footwork", 0), lo=SETTINGS.MIN_PER_STAT, hi=SETTINGS.MAX_PER_STAT),
        stamina=_parse_int(data.get("stamina", 0), lo=SETTINGS.MIN_PER_STAT, hi=SETTINGS.MAX_PER_STAT),
        chin=_parse_int(data.get("chin", 0), lo=SETTINGS.MIN_PER_STAT, hi=SETTINGS.MAX_PER_STAT),
        body=_parse_int(data.get("body", 0), lo=SETTINGS.MIN_PER_STAT, hi=SETTINGS.MAX_PER_STAT),
        gender=_clean_str(data.get("gender") or "male"),
        weight_kg=wkg,
        intro=_clean_str(data.get("intro") or ""),
        intro_music=_clean_str(data.get("intro_music") or ""),
        trait=_clean_str(data.get("trait") or ""),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Upsert
def upsert_boxers_from_sheet(sheet_id_or_url: str, tab_name_or_range: str = "Sheet1!A1:Z") -> Dict[str, int]:
    headers, rows = fetch_sheet_rows(sheet_id_or_url, tab_name_or_range)
    if not headers:
        return {"inserted": 0, "updated": 0, "skipped": 0}

    hmap = _build_header_map(headers)
    if "name" not in hmap.values():
        raise RuntimeError("Sheet must include a 'Name' column.")

    inserted = updated = skipped = 0

    for r in rows:
        boxer = _row_to_boxer(r, hmap)
        if not boxer:
            skipped += 1
            continue

        if boxer.total_points() != SETTINGS.BASE_STAT_POINT_CAP:
            skipped += 1
            continue
        existed = get_boxer(boxer.name) is not None
        save_boxer(boxer)  # normalizes + persists
        if existed:
            updated += 1
        else:
            inserted += 1

    return {"inserted": inserted, "updated": updated, "skipped": skipped}
