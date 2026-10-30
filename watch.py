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
import json, os, subprocess, sys, time, calendar, threading
from datetime import datetime, timezone, timedelta
import config, nesine, odds, match, prob, value, build_site, claude_check, espn

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
QUOTA = "records/quota.json"      # yalnızca gözcü yazar (Bekçi status.json'u ezebiliyor)
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
    """Bugün harcanabilecek Odds API isteği. status = quota.json içeriği."""
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


def git_setup(dry):
    if dry:
        return
    subprocess.run(["git", "config", "user.name", "iddia-bot"], check=False)
    subprocess.run(["git", "config", "user.email", "actions@users.noreply.github.com"], check=False)


GIT_LOCK = __import__("threading").RLock()   # arka plan story akışları ile ana döngü aynı anda git çalıştırmasın


def git_publish(msg, dry):
    """Kayıtları ve sayfayı repoya yazar. Rebase takılırsa iptal eder, sonraki döngüde yeniden dener."""
    if dry:
        return
    with GIT_LOCK:
        return _git_publish(msg)


def _git_publish(msg):
    subprocess.run(["git", "add", "records/", "docs/"], check=False)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], check=False).returncode == 0:
        return  # değişiklik yok
    if subprocess.run(["git", "commit", "-q", "-m", msg], check=False).returncode != 0:
        log("UYARI: commit başarısız"); return
    for _ in range(3):
        if subprocess.run(["git", "pull", "--rebase", "-X", "theirs", "-q", "origin", "master"], check=False).returncode != 0:
            subprocess.run(["git", "rebase", "--abort"], check=False)
            time.sleep(5); continue
        if subprocess.run(["git", "push", "-q", "origin", "master"], check=False).returncode == 0:
            return
        time.sleep(5)
    log("UYARI: push başarısız (commit yerelde duruyor, sonraki turda tekrar denenecek)")


CLAUDE_LOCK = threading.Lock()


def story_async(m, rec, events_for_sport, aliases, dry):
    """Kadro açıklandı → (büyük kulüp + sabah yorumu varsa) kadro notu → story kartı → yayın → Instagram story."""
    def run():
        try:
            import clubs, story, instagram
            if clubs.tier(m) > clubs.ANALYZE_MAX_TIER or not claude_check.find_prev(m["code"]):
                return
            if claude_check.kadro_before(m["code"]):
                return
            pm = None
            for mm, ev, sc in match.match_all([m], events_for_sport or [], aliases):
                if ev and odds.pinnacle_h2h(ev):
                    pm = prob.market_probs(odds.pinnacle_h2h(ev), odds.pinnacle_totals(ev))
            with CLAUDE_LOCK:
                log(f"Kadro notu başlıyor: {m['home']}-{m['away']}")
                row = claude_check.lineup_note_and_store(m, rec["rosters"], pm)
            if not row:
                log(f"Kadro notu yapılmadı (sınır/tekrar/boş): {m['home']}-{m['away']}"); return
            log(f"Kadro notu: {m['home']}-{m['away']} ${row.get('cost_usd')}")
            day = m["start"].astimezone(timezone(timedelta(hours=3))).strftime("%Y-%m-%d")
            os.makedirs(f"docs/social/{day}", exist_ok=True)
            path = f"docs/social/{day}/story_{m['code']}.jpg"
            story.story_card(m, rec["rosters"], row["kadro"]["note"], pm, path, er=rec)
            with GIT_LOCK:
                rebuild_page()
                git_publish(f"story {m['home']}-{m['away']}", dry)
            if dry or not os.environ.get("IG_TOKEN"):
                return
            url = f"{instagram.RAW}/social/{day}/story_{m['code']}.jpg"
            pid = instagram.post_story_for(m, url, size=os.path.getsize(path))
            log(f"Instagram story: {m['home']}-{m['away']} → {pid}" if pid else f"Story gönderilmedi (sınır/tekrar): {m['home']}-{m['away']}")
        except Exception as e:
            log(f"Story akışı hatası {m['home']}-{m['away']}: {type(e).__name__}: {e}")
    threading.Thread(target=run, daemon=True).start()


def claude_async(m, probs, force=False):
    """Claude analizini ana döngüyü (Nesine/Pinnacle/kapanış kaydı) bekletmeden arka planda çalıştırır."""
    def run():
        with CLAUDE_LOCK:  # aynı anda tek analiz: günlük sayaç ve dosya yazımı tutarlı kalsın
            log(f"Claude analizi başlıyor: {m['home']}-{m['away']}{' (uyarı)' if force else ''}")
            try:
                r = claude_check.analyze_and_store(m, probs, force=force)
                if r:
                    ob = r["objection"]["verdict"] if r.get("objection") else "-"
                    log(f"Claude{' (uyarı)' if force else ''}: {m['home']}-{m['away']} kör tahmin ev %{r['blind']['p_home']*100:.0f} · itiraz {ob} · ${r.get('cost_usd')}")
                else:
                    log(f"Claude analizi yapılmadı (sınır/tekrar/boş): {m['home']}-{m['away']}")
            except Exception as e:
                log(f"Claude hatası: {type(e).__name__}: {e}")
    threading.Thread(target=run, daemon=True).start()


INPLAY = {}   # code → thread (maç içi takip: devre arası / maç sonu story'si)


def inplay_async(m, event_id, dry):
    """Kademe 0 maçı başladı: 43. dakikadan itibaren 30 sn'de bir ESPN; devre arasında ve maç sonunda skor story'si."""
    import clubs, story, instagram
    if m["code"] in INPLAY or clubs.tier(m) > 0 or not event_id:
        return

    def post(kind, lv):
        day = m["start"].astimezone(timezone(timedelta(hours=3))).strftime("%Y-%m-%d")
        os.makedirs(f"docs/social/{day}", exist_ok=True)
        path = f"docs/social/{day}/{kind}_{m['code']}.jpg"
        story.score_card(m, lv, "ht" if kind == "devre" else "ft", path)
        size = os.path.getsize(path)
        with GIT_LOCK:
            git_publish(f"{kind} {m['home']}-{m['away']} {lv['score'].get('home')}-{lv['score'].get('away')}", dry)
        if dry or not os.environ.get("IG_TOKEN"):
            return
        url = f"{instagram.RAW}/social/{day}/{kind}_{m['code']}.jpg"
        pid = instagram.post_story_for(m, url, kind="story_ht" if kind == "devre" else "story_ft", size=size)
        log(f"Instagram {kind} story: {m['home']}-{m['away']} → {pid}" if pid else f"{kind} story gönderilmedi (sınır/tekrar)")

    def run():
        """Planlanan saate değil ESPN'in durumuna/dakikasına göre: gecikmeli başlangıç, uzatmalar sorun değil.
        Sorgu sıklığı: normalde 60 sn; ilk yarı 40'+ ve ikinci yarı 85'+ iken 15 sn (düdükten sonra ~30 sn içinde yakalar)."""
        try:
            ko = m["start"]
            done = {"ht": False, "ft": False}
            last_st = None
            while True:
                mins = (datetime.now(timezone.utc) - ko).total_seconds() / 60
                if mins > 210:   # 3,5 saat: uzatma + gecikme payı
                    break
                try:
                    lv = espn.live(m["sport_key"], event_id)
                except Exception as e:
                    log(f"ESPN canlı hatası {m['home']}-{m['away']}: {e}"); time.sleep(30); continue
                st = (lv or {}).get("status") or ""
                clock = (lv or {}).get("clock") or ""
                try:
                    minute = int("".join(ch for ch in clock.split("+")[0] if ch.isdigit()) or 0)
                except ValueError:
                    minute = 0
                if st != last_st:
                    log(f"ESPN durum {m['home']}-{m['away']}: {st} {clock} {lv.get('score')}")
                    last_st = st
                if st == "STATUS_HALFTIME":
                    if not done["ht"]:
                        done["ht"] = True
                        log(f"Devre arası: {m['home']}-{m['away']} {lv['score']}"); post("devre", lv)
                    wait = 60
                elif st in ("STATUS_FULL_TIME", "STATUS_FINAL", "STATUS_FINAL_PEN", "STATUS_FINAL_AET"):
                    if not done["ft"]:
                        done["ft"] = True
                        log(f"Maç sonu: {m['home']}-{m['away']} {lv['score']}"); post("macsonu", lv)
                    break
                elif st in ("STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_ABANDONED", "STATUS_SUSPENDED"):
                    log(f"Maç içi takip bitti ({st}): {m['home']}-{m['away']}"); break
                elif st == "STATUS_SECOND_HALF":
                    done["ht"] = True   # devre arası görülmediyse artık geçti
                    wait = 15 if minute >= 85 else 60
                elif st == "STATUS_FIRST_HALF":
                    wait = 15 if minute >= 40 else 60
                else:   # SCHEDULED / DELAYED / bilinmeyen: başlamayı bekle
                    wait = 60
                time.sleep(wait)
        except Exception as e:
            log(f"Maç içi takip hatası {m['home']}-{m['away']}: {type(e).__name__}: {e}")
    t = threading.Thread(target=run, daemon=True); t.start()
    INPLAY[m["code"]] = t
    log(f"Maç içi takip başladı: {m['home']}-{m['away']}")


def rebuild_page():
    try:
        os.makedirs("docs", exist_ok=True)
        with open("docs/index.html", "w", encoding="utf-8") as f:
            f.write(build_site.build())
    except Exception as e:  # sayfa hatası gözcüyü durdurmasın
        log(f"sayfa üretilemedi: {type(e).__name__}: {e}")


def main():
    dry = "--dry" in sys.argv
    git_setup(dry)
    max_minutes = float(sys.argv[sys.argv.index("--max-minutes") + 1]) if "--max-minutes" in sys.argv else 340
    deadline = time.time() + max_minutes * 60
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(minutes=max_minutes + WINDOW_MIN)

    data = nesine.fetch(save_path=None)
    targets = [m for m in nesine.parse(data) if now < m["start"] <= horizon]
    # başlamış kademe 0 maçları (bülten düşürmüş olabilir): son Nesine kaydından; maç içi takip için
    try:
        import clubs
        # bülten başlayan maçı düşürür → son 6 saatin TÜM kayıtlarına bak (nesine_matches koda göre tekilleştirir)
        _cut = (now - timedelta(hours=6)).isoformat()
        _rows = [r for r in build_site.read_jsonl("records/nesine/*.jsonl") if r.get("t", "") >= _cut]
        started0 = [m for m in build_site.nesine_matches(_rows) if clubs.tier(m) == 0 and now - timedelta(minutes=100) < m["start"] <= now]
        if started0:
            log("başlamış kademe 0 maçları: " + ", ".join(f"{m['home']}-{m['away']}" for m in started0))
    except Exception as e:
        log(f"başlamış maçlar okunamadı: {e}"); started0 = []
    if not targets:
        log("İzlenecek maç yok; çıkılıyor.")
        save_json(WSTATUS, {"active": False, "note": "", "updated": now.isoformat(timespec="seconds")})
        return
    targets.sort(key=lambda m: m["start"])
    log(f"{len(targets)} maç izlenecek; ilki {targets[0]['home']}-{targets[0]['away']} {targets[0]['start']:%H:%M} UTC")

    aliases = load_json("aliases.json", {})
    status = load_json(QUOTA, {})
    budget, remaining = daily_budget(status, now)
    log(f"Kota: kalan {remaining}, bugünkü bütçe {budget} istek")

    pin_events = {}          # sport → (fetched_at, events)
    last_poll = {}           # sport → epoch
    alerted = {}             # (code, market, pick) → alert dict
    claude_done = set()      # bu çalışmada Claude'a sorulan maçlar
    espn_last, espn_ids, espn_done = {}, {}, set()   # ESPN kadro takibi
    last_publish = 0
    day = now.strftime("%Y-%m-%d")
    spent_today = status.get("spent_today", 0) if status.get("spent_day") == day else 0

    while time.time() < deadline:
        now = datetime.now(timezone.utc)
        ts = now.isoformat(timespec="seconds")
        live = [m for m in targets if m["start"] > now]
        # kademe 0 maçı başladıysa maç içi takibe al (devre arası / maç sonu story'si); ESPN kimliği kadro adımından gelir
        for m in targets + started0:
            if m["start"] <= now and (now - m["start"]) < timedelta(minutes=150) and m["code"] not in INPLAY:
                eid = espn_ids.get(m["code"])
                if not eid and not dry:
                    try:
                        r = espn.fetch_match(m, None); eid = r["event_id"] if r else None
                        if eid:
                            espn_ids[m["code"]] = eid
                    except Exception as e:
                        log(f"ESPN kimlik hatası: {e}")
                inplay_async(m, eid, dry)
        if not live and not any(t.is_alive() for t in INPLAY.values()):
            log("Tüm maçlar başladı ve maç içi takip yok; bitiriliyor.")
            break
        if not live:
            time.sleep(30); continue
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
        next_poll = {}   # lig → bir sonraki Pinnacle sorgusunun zamanı (sayfada "sonraki güncelleme" için)
        for s in sports:
            if dry or budget < 2:
                break
            # pencere uzunluğuna göre aralık: bütçeyi pencereye yay (en sık 3 dk)
            n_left = sum(1 for m in window if m["sport_key"] == s)
            mins_left = max(5, min((m["start"] - now).total_seconds() / 60 for m in window if m["sport_key"] == s))
            interval = max(MIN_POLL_SEC, (mins_left * 60) / max(1, budget / (2 * len(sports))))
            next_poll[s] = last_poll.get(s, 0) + interval
            if time.time() - last_poll.get(s, 0) < interval:
                continue
            try:
                events, rem = odds.fetch(s, markets="h2h,totals")
                budget -= 2; spent_today += 2; polled_any = True
                last_poll[s] = time.time()
                pin_events[s] = (now, events)
                append_jsonl(f"records/pinnacle/{day}.jsonl", pinnacle_rows(ts, s, events))
                status.update(quota=rem, last_pinnacle=ts, spent_day=day, spent_today=spent_today)
                save_json(QUOTA, status)
                log(f"Pinnacle {s}: {len(events)} maç, kalan kota {rem}, bugün kalan bütçe {budget}")
            except Exception as e:
                log(f"Odds API hatası {s}: {e}")

        # 2b) ESPN kadro: penceredeki maçlar için açıklanana kadar 5 dk'da bir (ücretsiz)
        for m in window:
            if time.time() - espn_last.get(m["code"], 0) < 300 or m["code"] in espn_done:
                continue
            espn_last[m["code"]] = time.time()
            try:
                rec = espn.fetch_match(m, espn_ids.get(m["code"]))
                if rec:
                    espn_ids[m["code"]] = rec["event_id"]
                    if rec["lineup"]:
                        espn_done.add(m["code"]); log(f"Kadro açıklandı: {m['home']}-{m['away']}")
                        ev_s = pin_events.get(m["sport_key"], (None, []))[1]
                        story_async(m, rec, ev_s, aliases, dry)
            except Exception as e:
                log(f"ESPN hatası: {e}")

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
                if not dry and m["code"] not in claude_done:
                    claude_done.add(m["code"])
                    claude_async(m, probs)
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
                    if not dry:
                        claude_async(m, probs, force=True)
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
        nxt = datetime.fromtimestamp(max(time.time() + NESINE_SEC, min(next_poll.values())), tz=timezone.utc).isoformat(timespec="seconds") if next_poll else None
        save_json(WSTATUS, {"active": True, "note": note, "updated": ts, "alerts_today": len(alerted), "next_pinnacle": nxt})
        # yayın: uyarı varsa hemen, yoksa 10 dk'da bir (her push bir Pages derlemesi; saatte 10 derleme sınırı)
        if new_alerts or time.time() - last_publish > 600:
            rebuild_page()
            git_publish(f"gözcü {now:%H:%M}" + (f" – {len(new_alerts)} uyarı" if new_alerts else ""), dry)
            last_publish = time.time()
        time.sleep(NESINE_SEC)

    for _ in range(60):  # süren Claude analizleri varsa bitsin (en fazla 5 dk)
        if not CLAUDE_LOCK.locked():
            break
        time.sleep(5)
    save_json(WSTATUS, {"active": False, "note": "", "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    rebuild_page()
    git_publish("gözcü bitti", dry)


if __name__ == "__main__":
    main()
