"""Maç sonuçları: ESPN herkese açık skor tablosu (anahtar gerektirmez, kota yok).

Takip edilen her lig için verilen günlerin bitmiş maçlarını records/results/GÜN.jsonl'a yazar
(maç id'sine göre tekrar yazmaz). Günde bir çalışır: bugün + önceki 2 gün.

Kullanım: python results.py [--days 3]
"""
import json, os, sys, glob, urllib.request
from datetime import datetime, timezone, timedelta

ESPN = {"soccer_turkey_super_league": "tur.1", "soccer_epl": "eng.1", "soccer_spain_la_liga": "esp.1",
        "soccer_italy_serie_a": "ita.1", "soccer_germany_bundesliga": "ger.1", "soccer_france_ligue_one": "fra.1",
        "soccer_uefa_champs_league": "uefa.champions", "soccer_uefa_europa_league": "uefa.europa",
        "soccer_uefa_europa_conference_league": "uefa.europa.conf", "soccer_uefa_nations_league": "uefa.nations"}
OUT = "records/results"


def fetch(slug, day):
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard?dates={day:%Y%m%d}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def parse(sport, data):
    out = []
    for e in data.get("events", []):
        c = e["competitions"][0]
        if c["status"]["type"].get("name") != "STATUS_FULL_TIME":
            continue
        t = {x["homeAway"]: x for x in c["competitors"]}
        try:
            out.append({"id": e["id"], "date": e["date"], "sport": sport, "home": t["home"]["team"]["displayName"],
                        "away": t["away"]["team"]["displayName"], "hg": int(t["home"]["score"]), "ag": int(t["away"]["score"])})
        except (KeyError, ValueError):
            continue
    return out


def load_all():
    rows = []
    for p in sorted(glob.glob(f"{OUT}/*.jsonl")):
        with open(p, encoding="utf-8") as f:
            rows += [json.loads(l) for l in f if l.strip()]
    return rows


def main():
    days = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 3
    known = {r["id"] for r in load_all()}
    os.makedirs(OUT, exist_ok=True)
    today = datetime.now(timezone.utc).date()
    added = 0
    for d in range(days):
        day = today - timedelta(days=d)
        new = []
        for sport, slug in ESPN.items():
            try:
                new += [r for r in parse(sport, fetch(slug, day)) if r["id"] not in known]
            except Exception as e:
                print(f"{slug} {day}: {e}")
        if new:
            with open(f"{OUT}/{day}.jsonl", "a", encoding="utf-8") as f:
                for r in new:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
                    known.add(r["id"])
            added += len(new)
    print(f"Sonuç: {added} yeni maç yazıldı")


if __name__ == "__main__":
    main()
