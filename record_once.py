"""Tek seferlik kayıt (GitHub Actions için): Nesine oranlarını records/ altına JSONL olarak ekler.

  python record_once.py              → sadece Nesine (bedava)
  python record_once.py --pinnacle   → Nesine + Pinnacle (lig başına 2 Odds API isteği)

Dosyalar: records/nesine/YYYY-MM-DD.jsonl, records/pinnacle/YYYY-MM-DD.jsonl (günlük, satır başına bir oran).
Git'e küçük metin dosyaları olarak girer; yerelde import_records.py ile SQLite'a yüklenir.
"""
import json, os, sys
from datetime import datetime, timezone
import nesine, odds


def append(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main():
    now = datetime.now(timezone.utc)
    ts = now.isoformat(timespec="seconds")
    day = now.strftime("%Y-%m-%d")
    data = nesine.fetch(save_path=None)
    nm = nesine.parse(data)
    rows = []
    for m in nm:
        for mk, d in m["markets"].items():
            for outcome, price in d["odds"].items():
                rows.append({"t": ts, "code": m["code"], "start": m["start"].isoformat(), "home": m["home"], "away": m["away"],
                             "league": m["league"], "sport": m["sport_key"], "market": mk, "outcome": outcome, "price": price,
                             "mbs": max(m.get("mbs") or 1, d.get("mbs") or 1)})
    append(f"records/nesine/{day}.jsonl", rows)
    print(f"Nesine: {len(nm)} maç, {len(rows)} oran kaydedildi")

    if "--pinnacle" in sys.argv:
        sports = sorted({m["sport_key"] for m in nm if m["sport_key"] and m["start"] > now})
        prow, remaining = [], None
        for s in sports:
            events, remaining = odds.fetch(s, markets="h2h,totals")
            for ev in events:
                for bk in ev.get("bookmakers", []):
                    if bk["key"] != "pinnacle":
                        continue
                    for mk in bk["markets"]:
                        for o in mk["outcomes"]:
                            name = o["name"]
                            if mk["key"] == "h2h":
                                name = "home" if name == ev["home_team"] else "away" if name == ev["away_team"] else "draw"
                            prow.append({"t": ts, "sport": s, "event_id": ev["id"], "start": ev["commence_time"], "home": ev["home_team"],
                                         "away": ev["away_team"], "market": mk["key"], "outcome": name.lower(), "price": o["price"],
                                         "point": o.get("point")})
        append(f"records/pinnacle/{day}.jsonl", prow)
        print(f"Pinnacle: {len(sports)} lig, {len(prow)} oran kaydedildi, kalan kota {remaining}")


if __name__ == "__main__":
    main()
