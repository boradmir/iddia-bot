"""ESPN açık servisi: oyuncu/kadro VERİSİ (yapay zekâ yorumu değil).

Bir Nesine maçı için:
  - leaders  : takım başına sezon golcüleri/asistçileri/şut liderleri (maç, gol, şut)
  - rosters  : açıklanan kadro (ilk 11, yedekler, diziliş) — genelde maçtan ~60 dk önce gelir
  - last5    : takımların son 5 maçı (tarih, sonuç, skor)
Kayıt: records/espn/GÜN.jsonl (maç kodu başına son hâl; aynı gün dosyasında üzerine yazılır).

Kullanım: python espn.py            → 48 saat içindeki maçlar için liderleri çeker (kota yok, ücretsiz)
          espn.fetch_match(m, want_lineup=True)
"""
import glob, json, os, re, urllib.request
from datetime import datetime, timezone, timedelta
import match, results

OUT = "records/espn"
SLUG = results.ESPN


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def find_event(sport, home, away, start):
    """Nesine maçı → ESPN etkinlik id (aynı gün skor tablosu, isim benzerliği ≥0.6)."""
    slug = SLUG.get(sport)
    if not slug:
        return None
    best, score = None, 0.0
    for day in (start.date(), (start + timedelta(hours=12)).date()):
        try:
            d = _get(f"https://site.api.espn.com/apis/soccer/{slug}/scoreboard?dates={day:%Y%m%d}".replace("/apis/soccer", "/apis/site/v2/sports/soccer"))
        except Exception:
            continue
        for e in d.get("events", []):
            c = e["competitions"][0]; t = {x["homeAway"]: x["team"]["displayName"] for x in c["competitors"]}
            try:
                dt = datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
            except ValueError:
                continue
            if abs((dt - start).total_seconds()) > 3 * 3600:
                continue
            s = (match.similarity(home, t.get("home", "")) + match.similarity(away, t.get("away", ""))) / 2
            if s > score:
                best, score = e["id"], s
    return best if score >= 0.6 else None


def _num(s, key):
    m = re.search(rf"{key}:\s*(\d+)", s or "")
    return int(m.group(1)) if m else None


def extract(summary):
    out = {"leaders": {}, "rosters": {}, "last5": {}}
    for t in summary.get("leaders", []) or []:
        team = t.get("team", {}).get("displayName")
        rows = {}
        for cat in t.get("leaders", []):
            for x in cat.get("leaders", []):
                name = x.get("athlete", {}).get("displayName")
                if not name:
                    continue
                r = rows.setdefault(name, {"player": name, "matches": None, "goals": 0, "assists": 0, "shots": 0})
                dv = x.get("displayValue", "")
                if cat.get("name") == "goalsLeaders":
                    r["goals"] = _num(dv, "Goals") or 0; r["matches"] = _num(dv, "Matches")
                elif cat.get("name") == "assistsLeaders":
                    r["assists"] = _num(dv, "Assists") or 0; r["matches"] = r["matches"] or _num(dv, "Matches")
                elif cat.get("name") == "totalShots":
                    try:
                        r["shots"] = int(dv)
                    except ValueError:
                        pass
        out["leaders"][team] = sorted(rows.values(), key=lambda r: (-r["goals"], -r["shots"]))[:6]
    for r in summary.get("rosters", []) or []:
        team = r.get("team", {}).get("displayName"); roster = r.get("roster", []) or []
        if not roster:
            continue
        out["rosters"][team] = {"formation": r.get("formation"),
                               "starters": [{"player": p.get("athlete", {}).get("displayName"), "pos": p.get("position", {}).get("abbreviation"), "no": p.get("jersey")} for p in roster if p.get("starter")],
                               "bench": [p.get("athlete", {}).get("displayName") for p in roster if not p.get("starter")]}
    try:
        for comp in (summary.get("header", {}) or {}).get("competitions", []) or []:
            for c in comp.get("competitors", []) or []:
                t = c.get("team", {}) or {}
                if t.get("displayName"):
                    out.setdefault("teams", {})[t["displayName"]] = {"abbr": t.get("abbreviation"), "color": t.get("color"), "alt": t.get("alternateColor"), "home": c.get("homeAway") == "home"}
    except Exception:
        pass
    for t in summary.get("lastFiveGames", []) or []:
        team = t.get("team", {}).get("displayName")
        out["last5"][team] = [{"date": g.get("gameDate", "")[:10], "result": g.get("gameResult"), "score": g.get("score"), "opponent": g.get("opponent", {}).get("displayName"), "home": g.get("atVs") == "vs"} for g in t.get("events", [])[:5]]
    return out


def load_all():
    by = {}
    for p in sorted(glob.glob(f"{OUT}/*.jsonl")):
        with open(p, encoding="utf-8") as f:
            for l in f:
                if l.strip():
                    r = json.loads(l); by[r["code"]] = r
    return by


def save(rec):
    """Maç kodu başına tek kayıt: günün dosyasında varsa değiştir, yoksa ekle."""
    os.makedirs(OUT, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = f"{OUT}/{day}.jsonl"
    rows = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            rows = [json.loads(l) for l in f if l.strip() and json.loads(l)["code"] != rec["code"]]
    rows.append(rec)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


STAT_KEYS = {"possessionPct": "Topla oynama", "totalShots": "Şut", "shotsOnTarget": "İsabetli şut", "wonCorners": "Korner",
             "foulsCommitted": "Faul", "offsides": "Ofsayt"}


def live(sport_key, event_id):
    """Canlı durum: {"status": STATUS_*, "clock", "score": {"home","away"}, "goals": [...], "cards": [...], "stats": {takım: {ad: değer}}}.
    Kaynak: summary (header + keyEvents + boxscore); keyEvents boşsa scoreboard details."""
    import html as _h
    slug = SLUG.get(sport_key)
    if not slug or not event_id:
        return None
    s = _get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/summary?event={event_id}")
    comp = (s.get("header") or {}).get("competitions", [{}])[0]
    st = comp.get("status", {}).get("type", {})
    out = {"status": st.get("name"), "state": st.get("state"), "clock": comp.get("status", {}).get("displayClock"),
           "score": {}, "goals": [], "cards": [], "stats": {}, "teams": {}}
    for c in comp.get("competitors", []):
        side = c.get("homeAway")
        out["teams"][side] = c.get("team", {}).get("displayName")
        try:
            out["score"][side] = int(c.get("score"))
        except (TypeError, ValueError):
            out["score"][side] = None
    name_to_side = {v: k for k, v in out["teams"].items()}
    for k in s.get("keyEvents") or []:
        typ = (k.get("type") or {}).get("text", "") or ""
        who = [_h.unescape(p.get("athlete", {}).get("displayName", "")) for p in k.get("participants", []) if p.get("athlete")]
        side = name_to_side.get((k.get("team") or {}).get("displayName"))
        minute = (k.get("clock") or {}).get("displayValue", "")
        if k.get("scoringPlay") or "Goal" in typ:
            out["goals"].append({"side": side, "player": who[0] if who else "", "minute": minute,
                                 "own": "Own" in typ, "pen": "Penalty" in typ})
        elif "Red" in typ:
            out["cards"].append({"side": side, "player": who[0] if who else "", "minute": minute, "kind": "red"})
    for t in (s.get("boxscore") or {}).get("teams", []):
        side = name_to_side.get(t.get("team", {}).get("displayName"))
        if side:
            out["stats"][side] = {STAT_KEYS[x["name"]]: x.get("displayValue") for x in t.get("statistics", []) if x.get("name") in STAT_KEYS}
    return out


def fetch_match(m, event_id=None):
    """Nesine maçı için ESPN verisini çek ve kaydet. Döner: kayıt | None."""
    eid = event_id or find_event(m["sport_key"], m["home"], m["away"], m["start"])
    if not eid:
        return None
    slug = SLUG[m["sport_key"]]
    data = extract(_get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/summary?event={eid}"))
    rec = {"code": m["code"], "event_id": eid, "home": m["home"], "away": m["away"], "sport": m["sport_key"], "start": m["start"].isoformat(),
           "t": datetime.now(timezone.utc).isoformat(timespec="seconds"), "lineup": bool(data["rosters"]), **data}
    save(rec)
    return rec


if __name__ == "__main__":
    import nesine
    now = datetime.now(timezone.utc)
    have = load_all()
    ms = [m for m in nesine.parse(nesine.fetch(save_path=None)) if now < m["start"] <= now + timedelta(hours=48)]
    n = 0
    for m in ms:
        old = have.get(m["code"])
        if old and old.get("leaders") and (old.get("lineup") or (m["start"] - now) > timedelta(minutes=90)):
            continue
        try:
            r = fetch_match(m, old.get("event_id") if old else None)
            if r:
                n += 1
        except Exception as e:
            print(f"{m['home']}-{m['away']}: {e}")
    print(f"ESPN: {len(ms)} maç tarandı, {n} kayıt güncellendi")
