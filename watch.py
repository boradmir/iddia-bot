"""Maç günü gözcüsü (GitHub Actions'ta uzun süreli iş).

Ne yapar: Önümüzdeki saatlerde hedef liglerde maç varsa, maç saatine yaklaşırken
  - Nesine'yi her NESINE_SEC saniyede okur (bedava),
  - Pinnacle'ı maça WINDOW_MIN dakika kalandan itibaren kota bütçesine göre okur (Odds API),
  - value ≥ eşik, oran < 3.0, Pinnacle taze ise UYARI yazar (records/alerts/GÜN.jsonl),
  - maça ≤ CLOSE_MIN dk kala son Pinnacle okumasını "kapanış" olarak uyarıya işler (CLV için),
  - sayfayı yeniden üretir ve repoya yazar.

Kota bütçesi (ücretsiz 500/ay): bu iş, kalan kotayı ayın kalan gününe böler; günlük payını aşmaz.
Pinnacle sorgusu lig başına 2 istek (h2h + totals). Öncelik: LEAGUE_PRIORITY sırası.

Kullanım: python watch.py [--max-minutes 340] [--dry]   (--dry: Odds API çağırmaz, commit atmaz)
"""
import json, os, subprocess, sys, time, calendar
from datetime import datetime, timezone, timedelta
import config, nesine, odds, match, prob, value, build_site

NESINE_SEC = 60
WINDOW_MIN = 100          # Pinnacle izleme penceresi: maça bu kadar dk kala başlar
CLOSE_MIN = 6             # bu kadar dk kala alınan son okuma = kapanış
MIN_POLL_SEC = 180        # Pinnacle için en sık aralık
QUOTA_RESERVE = 20        # ay sonu için dokunulmaz kota
LEAGUE_PRIORITY = ["soccer_turkey_super_league", "soccer_epl", "soccer_uefa_champs_league", "soccer_spain_la_liga",
                   "soccer_italy_serie_a", "soccer_germany_bundesliga", "soccer_france_ligue_one",
                   "soccer_uefa_europa_league", "soccer_uefa_europa_conference_league", "soccer_uefa_nations_league"]
ALERT_DIR = "records/alerts"
STATUS = "records/status.json"
WSTATUS = "records/watch_status.json"


def log(msg):
    print(f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} {msg}", flush=True)


def load_json(path, default):
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else default


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def append_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def daily_budget(status, now):
    """Bugün harcanabilecek Odds API isteği."""
    remaining = status.get("quota")
    remaining = int(remaining) if remaining not in (None, "?") else 0
    days_left = calendar.monthrange(now.year, now.month)[1] - now.day + 1
    spent_today = status.get("spent_today", 0) if status.get("spent_day") == now.strftime("%Y-%m-%d") else 0
    return max(0, (remaining - QUOTA_RESERVE) // days_left - spent_today), remaining


def pinnacle_rows(ts, sport, events):
    rows = []
    for ev in events:
        for bk in ev.get("bookmakers", []):
            if bk["key"] != "pinnacle":
                continue
            for mk in bk["markets"]:
                for o in mk["outcomes"]:
                    name = o["name"]
                    if mk["key"] == "h2h":
                        name = "home" if name == ev["home_team"] else "away" if name == ev["away_team"] else "draw"
                    rows.append({"t": ts, "sport": sport, "event_id": ev["id"], "start": ev["commence_time"], "home": ev["home_team"],
                                 "away": ev["away_team"], "market": mk["key"], "outcome": name.lower(), "price": o["price"], "point": o.get("point")})
    return rows


def git_publish(msg, dry):
    if dry:
        return
    cmds = [["git", "add", "records/", "docs/"],
            ["git", "-c", "user.name=iddia-bot", "-c", "user.email=actions@users.noreply.github.com", "commit", "-q", "-m", msg]]
    for c in cmds:
        subprocess.run(c, check=False)
    for _ in range(3):
        if subprocess.run(["git", "pull", "--rebase", "-X", "theirs", "-q"], check=False).returncode == 0 and \
           subprocess.run(["git", "push", "-q"], check=False).returncode == 0:
            return
        time.sleep(5)
    log("UYARI: push başarısız")


def rebuild_page():
    try:
        os.makedirs("docs", exist_ok=True)
        with open("docs/index.html", "w", encoding="utf-8") as f:
            f.write(build_site.build())
    except Exception as e:  # sayfa hatası gözcüyü durdurmasın
        log(f"sayfa üretilemedi: {type(e).__name__}: {e}")


def main():
    dry = "--dry" in sys.argv
    max_minutes = float(sys.argv[sys.argv.index("--max-minutes") + 1]) if "--max-minutes" in sys.argv else 340
    deadline = time.time() + max_minutes * 60
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(minutes=max_minutes + WINDOW_MIN)

    data = nesine.fetch(save_path=None)
    targets = [m for m in nesine.parse(data) if now < m["start"] <= horizon]
    if not targets:
        log("İzlenecek maç yok; çıkılıyor.")
        save_json(WSTATUS, {"active": False, "note": "", "updated": now.isoformat(timespec="seconds")})
        return
    targets.sort(key=lambda m: m["start"])
    log(f"{len(targets)} maç izlenecek; ilki {targets[0]['home']}-{targets[0]['away']} {targets[0]['start']:%H:%M} UTC")

    aliases = load_json("aliases.json", {})
    status = load_json(STATUS, {})
    budget, remaining = daily_budget(status, now)
    log(f"Kota: kalan {remaining}, bugünkü bütçe {budget} istek")

    pin_events = {}          # sport → (fetched_at, events)
    last_poll = {}           # sport → epoch
    alerted = {}             # (code, market, pick) → alert dict
    last_publish = 0
    day = now.strftime("%Y-%m-%d")
    spent_today = status.get("spent_today", 0) if status.get("spent_day") == day else 0

    while time.time() < deadline:
        now = datetime.now(timezone.utc)
        ts = now.isoformat(timespec="seconds")
        live = [m for m in targets if m["start"] > now]
        if not live:
            log("Tüm maçlar başladı; bitiriliyor.")
            break
        # 1) Nesine (bedava)
        try:
            data = nesine.fetch(save_path=None)
            fresh = {m["code"]: m for m in nesine.parse(data)}
            for m in live:
                if m["code"] in fresh:
                    m["markets"] = fresh[m["code"]]["markets"]
        except Exception as e:
            log(f"Nesine okunamadı: {e}")

        # 2) Pinnacle: penceredeki ligler, öncelik sırasıyla, bütçe dahilinde
        window = [m for m in live if (m["start"] - now) <= timedelta(minutes=WINDOW_MIN)]
        sports = [s for s in LEAGUE_PRIORITY if any(m["sport_key"] == s for m in window)]
        polled_any = False
        for s in sports:
            if dry or budget < 2:
                break
            # pencere uzunluğuna göre aralık: bütçeyi pencereye yay (en sık 3 dk)
            n_left = sum(1 for m in window if m["sport_key"] == s)
            mins_left = max(5, min((m["start"] - now).total_seconds() / 60 for m in window if m["sport_key"] == s))
            interval = max(MIN_POLL_SEC, (mins_left * 60) / max(1, budget / (2 * len(sports))))
            if time.time() - last_poll.get(s, 0) < interval:
                continue
            try:
                events, rem = odds.fetch(s, markets="h2h,totals")
                budget -= 2; spent_today += 2; polled_any = True
                last_poll[s] = time.time()
                pin_events[s] = (now, events)
                append_jsonl(f"records/pinnacle/{day}.jsonl", pinnacle_rows(ts, s, events))
                status.update(quota=rem, last_pinnacle=ts, spent_day=day, spent_today=spent_today)
                save_json(STATUS, status)
                log(f"Pinnacle {s}: {len(events)} maç, kalan kota {rem}, bugün kalan bütçe {budget}")
            except Exception as e:
                log(f"Odds API hatası {s}: {e}")

        # 3) Value + uyarılar
        new_alerts = []
        for s, (fetched, events) in pin_events.items():
            age_min = (now - fetched).total_seconds() / 60
            ms = [m for m in window if m["sport_key"] == s]
            for m, ev, score in match.match_all(ms, events, aliases):
                if not ev:
                    continue
                h2h = odds.pinnacle_h2h(ev)
                if not h2h:
                    continue
                probs = prob.market_probs(h2h, odds.pinnacle_totals(ev))
                mins_to_ko = (m["start"] - now).total_seconds() / 60
                for b in value.evaluate(m, probs, h2h, bankroll=100.0):
                    key = (b["code"], b["market"], b["pick"])
                    if key in alerted:
                        a = alerted[key]
                        a.update(last_seen=ts, nesine_odds_last=b["nesine_odds"], ev_last=b["ev_pct"])
                        if mins_to_ko <= CLOSE_MIN and age_min <= 10:
                            a["closing_fair_prob"] = b["fair_prob"]
                            a["clv_pct"] = round((a["nesine_odds"] * b["fair_prob"] - 1) * 100, 2)
                        continue
                    if age_min > 10:
                        continue
                    a = {"t": ts, "code": b["code"], "home": b["home"], "away": b["away"], "league": b["league"], "sport": m["sport_key"], "start": m["start"].isoformat(),
                         "market": b["market"], "pick": b["pick"], "nesine_odds": b["nesine_odds"], "fair_prob": round(b["fair_prob"], 4),
                         "fair_odds": b["fair_odds"], "pinnacle_odds": b["pinnacle_odds"], "ev_pct": b["ev_pct"], "stake": b["stake"],
                         "mbs": b["mbs"], "match_score": round(score, 2), "mins_before": int(mins_to_ko), "result": None}
                    alerted[key] = a; new_alerts.append(a)
                    log(f"UYARI +{b['ev_pct']:.1f}% {b['home']}-{b['away']} {b['market']} {b['pick']} Nesine {b['nesine_odds']} adil {b['fair_odds']}")
        if new_alerts or alerted:
            # tüm güncel uyarıları günün dosyasına yaz (üzerine): basit ve çakışmasız
            path = f"{ALERT_DIR}/{day}.jsonl"
            os.makedirs(ALERT_DIR, exist_ok=True)
            existing = [json.loads(l) for l in open(path, encoding="utf-8")] if os.path.exists(path) else []
            keep = [a for a in existing if (a["code"], a["market"], a["pick"]) not in alerted]
            with open(path, "w", encoding="utf-8") as f:
                for a in keep + list(alerted.values()):
                    f.write(json.dumps(a, ensure_ascii=False) + "\n")

        # 4) Durum + sayfa + yayın
        note = f"{len(live)} maç izleniyor, {len(window)} tanesi pencerede; bugün kalan Pinnacle bütçesi {budget} istek"
        save_json(WSTATUS, {"active": True, "note": note, "updated": ts, "alerts_today": len(alerted)})
        if new_alerts or polled_any or time.time() - last_publish > 600:
            rebuild_page()
            git_publish(f"gözcü {now:%H:%M}" + (f" – {len(new_alerts)} uyarı" if new_alerts else ""), dry)
            last_publish = time.time()
        time.sleep(NESINE_SEC)

    save_json(WSTATUS, {"active": False, "note": "", "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    rebuild_page()
    git_publish("gözcü bitti", dry)


if __name__ == "__main__":
    main()
