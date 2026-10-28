"""Modül 2 – The Odds API: Pinnacle (ve diğer EU bookmaker) oranlarını çeker, SQLite'a yazar.

Kota: her istek = market sayısı × bölge sayısı. Ücretsiz plan 500/ay.
Yanıt başlığı x-requests-remaining kalan kotayı verir.
"""
import json, sys, urllib.request, urllib.parse
from datetime import datetime, timezone
import config

BASE = "https://api.the-odds-api.com/v4"
# Odds API market adı → bizim market kodu, sonuç adı eşlemesi
MARKET_MAP = {"h2h": "MS", "totals": "AU25", "btts": "KG"}


def fetch(sport_key, markets="h2h", regions="eu"):
    """Bir lig için yaklaşan maçların oranlarını çeker. (events, kalan_kota) döner."""
    q = urllib.parse.urlencode({"apiKey": config.ODDS_API_KEY, "regions": regions, "markets": markets,
                                "oddsFormat": "decimal", "dateFormat": "iso"})
    req = urllib.request.Request(f"{BASE}/sports/{sport_key}/odds?{q}", headers={"User-Agent": "iddia-bot"})
    with urllib.request.urlopen(req, timeout=60) as r:
        remaining = r.headers.get("x-requests-remaining")
        events = json.loads(r.read())
    return events, remaining


def save_snapshots(con, sport_key, events):
    """Her bookmaker/market/sonuç için bir satır yazar."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []
    for ev in events:
        for bk in ev.get("bookmakers", []):
            for mk in bk.get("markets", []):
                for o in mk.get("outcomes", []):
                    name = o["name"]
                    if mk["key"] == "h2h":
                        name = "home" if name == ev["home_team"] else "away" if name == ev["away_team"] else "draw"
                    rows.append((now, sport_key, ev["id"], ev["commence_time"], ev["home_team"], ev["away_team"],
                                 bk["key"], mk["key"], name.lower(), o["price"], o.get("point")))
    con.executemany("INSERT INTO odds_snapshots (fetched_at,sport_key,event_id,commence,home,away,bookmaker,market,outcome,price,point) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    return len(rows)


def _pinnacle_market(ev, key):
    for bk in ev.get("bookmakers", []):
        if bk["key"] == "pinnacle":
            for mk in bk["markets"]:
                if mk["key"] == key:
                    return mk
    return None


def pinnacle_h2h(ev):
    """Pinnacle 1/X/2 oranları {'1','X','2'}; yoksa None."""
    mk = _pinnacle_market(ev, "h2h")
    if not mk:
        return None
    d = {}
    for o in mk["outcomes"]:
        d["1" if o["name"] == ev["home_team"] else "2" if o["name"] == ev["away_team"] else "X"] = o["price"]
    return d if len(d) == 3 else None


def pinnacle_totals(ev):
    """Pinnacle toplam gol ana çizgisi: {'line': 2.5, 'Alt': oran, 'Üst': oran}; yoksa None."""
    mk = _pinnacle_market(ev, "totals")
    if not mk:
        return None
    by_line = {}
    for o in mk["outcomes"]:
        by_line.setdefault(o.get("point"), {})["Üst" if o["name"] == "Over" else "Alt"] = o["price"]
    # Ana çizgi = Alt/Üst oranı en dengeli olan (Pinnacle genelde tek çizgi verir: 2.25, 2.5, 2.75, 3.0 ...)
    candidates = [(ln, d) for ln, d in by_line.items() if ln is not None and len(d) == 2 and round(ln % 1, 2) in (0.0, 0.25, 0.5, 0.75)]
    if not candidates:
        return None
    ln, d = min(candidates, key=lambda c: abs(c[1]["Alt"] - c[1]["Üst"]))
    return {"line": ln, **d}


if __name__ == "__main__":
    sports = sys.argv[1:] or ["soccer_italy_serie_a"]
    import db
    con = db.connect()
    for s in sports:
        events, remaining = fetch(s)
        n = save_snapshots(con, s, events)
        with_pin = sum(1 for e in events if pinnacle_h2h(e))
        print(f"{s}: {len(events)} maç, {with_pin} tanesinde Pinnacle var, {n} satır yazıldı, kalan kota {remaining}")
