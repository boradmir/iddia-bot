"""Panel kararları: records/control.json. Panel yazar; bekçi, gözcü ve instagram her döngüde okur.
Yalnız zararsız kararlar içerir (durdur, atla, saat, reels seçimi); sır asla girmez. Bozuksa tüketiciler yok sayar."""
import json, os
from datetime import datetime, timezone, timedelta

PATH = os.environ.get("CONTROL_PATH", "records/control.json")
TR = timezone(timedelta(hours=3))


def load(path=None):
    p = path or PATH
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"control.json okunamadı, yok sayıldı: {e}")
        return {}


def save(d, path=None):
    """Atomik yazım (tmp + replace); 'updated' alanını doldurur."""
    p = path or PATH
    d["updated"] = datetime.now(TR).isoformat(timespec="seconds")
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def key(day, code):
    return f"{day}:{code}"


def parse_hm(s):
    """'16:30' → (16, 30); geçersizse None."""
    try:
        h, m = str(s).strip().split(":")
        h, m = int(h), int(m)
        return (h, m) if 0 <= h < 24 and 0 <= m < 60 else None
    except (ValueError, AttributeError):
        return None


def is_paused(d, now=None):
    pu = d.get("paused_until")
    if not pu:
        return False
    try:
        t = datetime.fromisoformat(pu)
    except (ValueError, TypeError):
        return False
    if t.tzinfo is None:
        t = t.replace(tzinfo=TR)
    return (now or datetime.now(TR)) < t


def post(d, day, code):
    return (d.get("posts") or {}).get(key(day, code)) or {}


def story_skip(d, day, code):
    return bool(((d.get("stories") or {}).get(key(day, code)) or {}).get("skip"))


def reels(d, day):
    return (d.get("reels") or {}).get(str(day)) or {}


def set_post(d, day, code, at=None, skip=None, note=None):
    row = d.setdefault("posts", {}).setdefault(key(day, code), {})
    if at is not None:
        row["at"] = at
    if skip is not None:
        row["skip"] = bool(skip)
    if note is not None:
        row["note"] = note
    return row


def set_story_skip(d, day, code, skip):
    d.setdefault("stories", {})[key(day, code)] = {"skip": bool(skip)}


def set_pause(d, until):
    """until: datetime (TR) ya da None (aç)."""
    d["paused_until"] = until.isoformat(timespec="seconds") if until else None


def set_reels(d, day, **fields):
    row = d.setdefault("reels", {}).setdefault(str(day), {})
    row.update({k: v for k, v in fields.items() if v is not None})
    return row
