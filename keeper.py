"""Bekçi: GitHub cron'una bağımlı olmayan zamanlayıcı. Tek uzun çalışma (≤ ~5.7 saat) içinde:
  - her RECORD_MIN dakikada Nesine kaydı (record_once.py) + sayfa (+ kupon kilitleme) + repoya yazma,
  - günde bir kez (04:30 UTC sonrası) "Sonuçlar ve puanlama" iş akışını tetikler,
  - hedef liglerde 2 saat içinde maç varsa ve gözcü çalışmıyorsa "Maç günü gözcüsü"nü tetikler,
  - süresi bitince KENDİNİ yeniden tetikler (GITHUB_TOKEN, actions:write).
Böylece zincir kopmadıkça kayıt hiç durmaz. Cron çalışmaya başlarsa da zarar vermez (aynı concurrency grubu).

Kullanım: python keeper.py [--max-minutes 340] [--no-chain]
"""
import re
import json, os, subprocess, sys, time
from datetime import datetime, timezone, timedelta
import nesine, espn, claude_check, build_site, odds, prob, match, clubs, control

RECORD_MIN = 20
STATUS = "records/status.json"
REPO = os.environ.get("GITHUB_REPOSITORY", "boradmir/iddia-bot")


def log(msg):
    print(f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} {msg}", flush=True)


def sh(args, **kw):
    return subprocess.run(args, check=False, **kw)


def load_status():
    return json.load(open(STATUS, encoding="utf-8")) if os.path.exists(STATUS) else {}


def save_status(s):
    os.makedirs("records", exist_ok=True)
    with open(STATUS, "w", encoding="utf-8") as f:
        json.dump(s, f)


def publish(msg):
    sh(["git", "add", "records/", "docs/"])
    if sh(["git", "diff", "--cached", "--quiet"]).returncode == 0:
        return
    if sh(["git", "commit", "-q", "-m", msg]).returncode != 0:
        log("commit başarısız"); return
    for _ in range(3):
        if not pull():
            time.sleep(5); continue
        if sh(["git", "push", "-q", "origin", "master"]).returncode == 0:
            return
        time.sleep(5)
    log("push başarısız")


def dispatch(workflow, **inputs):
    """gh ile iş akışı tetikle (GH_TOKEN = GITHUB_TOKEN)."""
    args = ["gh", "workflow", "run", workflow, "-R", REPO]
    for k, v in inputs.items():
        args += ["-f", f"{k}={v}"]
    r = sh(args, capture_output=True, text=True)
    log(f"tetikle {workflow} {inputs}: {'ok' if r.returncode == 0 else r.stderr.strip()[:200]}")
    return r.returncode == 0


def workflow_active(workflow):
    r = sh(["gh", "run", "list", "-R", REPO, "--workflow", workflow, "--status", "in_progress", "--json", "databaseId", "-q", "length"],
           capture_output=True, text=True)
    try:
        return int(r.stdout.strip() or 0) > 0
    except ValueError:
        return False


def record_once():
    r = sh([sys.executable, "record_once.py"], capture_output=True, text=True)
    log((r.stdout or r.stderr).strip().replace("\n", " | ")[:300])
    sh([sys.executable, "build_site.py", "--record-coupons"], capture_output=True, text=True)


RESULT_SLOTS = ((4, 30), (13, 0), (19, 30), (22, 40))   # UTC: sabah, öğle, akşam ve gece maçları sonrası


def maybe_results(s, now):
    """Günde birkaç kez skorları çekip puanla: bir dilimin saati geçtiyse ve o dilim bugün çalışmadıysa tetikle."""
    day = now.strftime("%Y-%m-%d")
    done = s.get("results_slots", {})
    if s.get("results_day") != day:
        done = {}
    for h, m in RESULT_SLOTS:
        key = f"{h:02d}:{m:02d}"
        if (now.hour, now.minute) >= (h, m) and key not in done:
            if dispatch("results.yml"):
                done[key] = now.isoformat(timespec="seconds")
                s["results_day"] = day; s["results_slots"] = done; save_status(s)
            break


IG_POST_UTC = (6, 50)   # 09:50 TSİ'den itibaren her turda instagram.py çağrılır; saati gelen gönderi gider (saatler instagram.post_slots)
STANDINGS_NEXT_UTC = None
REELS_NEXT_UTC = None    # panelden hazırlanan reels'in yayın saati (UTC saat, dakika), maybe_reels doldurur
NEXT_SLOT_UTC = None     # instagram.py'nin bildirdiği bir sonraki yayın saati (UTC saat, dakika)
PRIORITY = ["soccer_turkey_super_league", "soccer_uefa_nations_league", "soccer_international_friendlies", "soccer_fifa_world_cup_qualifiers_europe", "soccer_euro_qualifiers", "soccer_epl", "soccer_uefa_champs_league", "soccer_spain_la_liga", "soccer_italy_serie_a",
            "soccer_germany_bundesliga", "soccer_france_ligue_one", "soccer_uefa_europa_league", "soccer_uefa_europa_conference_league", "soccer_uefa_nations_league"]


def maybe_morning_claude(s, now):
    """Maç günü sabahı (04:30 UTC sonrası) günün maçları için yapay zekâ analizi: haberler günler önceden var,
    paketler sabahtan hazır olsun. Günlük sınır claude_check.MAX_PER_DAY; öncelik lig sırasına göre."""
    day = now.strftime("%Y-%m-%d")
    if s.get("claude_morning") == day or (now.hour, now.minute) < (4, 30) or not os.environ.get("ANTHROPIC_API_KEY"):
        return
    s["claude_morning"] = day; save_status(s)
    try:
        from datetime import timezone as _tz, timedelta as _td
        tr = _tz(_td(hours=3))
        ms = [m for m in nesine.parse(nesine.fetch(save_path=None)) if m["start"].astimezone(tr).date() == now.astimezone(tr).date() and m["start"] > now]
        # canlı bültende o an olmayan ama son 12 saatte kayıtlarda görülen maçları da ekle (Nesine ligi geçici çekmiş olabilir)
        try:
            _t, _last = build_site.recent_snapshot(build_site.read_jsonl("records/nesine/*.jsonl"))
            have = {m["code"] for m in ms}
            extra = [m for m in build_site.nesine_matches(_last) if m["code"] not in have and m["start"].astimezone(tr).date() == now.astimezone(tr).date() and m["start"] > now]
            if extra:
                log("Sabah analizi: canlı bültende olmayan " + ", ".join(f"{m['home']}-{m['away']}" for m in extra) + " kayıtlardan eklendi")
            ms += extra
        except Exception as e:
            log(f"Sabah analizi: kayıt birleştirme hatası {e}")
        # yalnız büyük kulüplü maçlar (clubs.py kademe 0-1); yoksa o gün sabah analizi yapılmaz
        ms = [m for m in ms if clubs.tier(m) <= clubs.ANALYZE_MAX_TIER]
        # Instagram'a zaten gitmiş maç için analiz yapma (gönderi değiştirilemez, boşa harcama olur)
        try:
            import instagram
            posted = {s["code"] for s in instagram.load_log()}
            ms = [m for m in ms if m["code"] not in posted]
        except Exception as e:
            log(f"instagram günlüğü okunamadı: {e}")
        if not ms:
            log("Sabah analizi: bugün büyük kulüp maçı yok, analiz yapılmadı"); return
        # sıra: büyük kulüp kademesi (clubs.py) → lig sırası → başlangıç saati
        ms.sort(key=lambda m: (clubs.tier(m), PRIORITY.index(m["sport_key"]) if m["sport_key"] in PRIORITY else 99, m["start"]))
        # en son Pinnacle kaydından piyasa ihtimali (varsa) — itiraz aşaması için
        events = build_site.pinnacle_events(build_site.read_jsonl("records/pinnacle/*.jsonl"))
        aliases = json.load(open("aliases.json", encoding="utf-8")) if os.path.exists("aliases.json") else {}
        pm_by = {}
        for m, ev, sc in match.match_all(ms, events, aliases):
            if ev and odds.pinnacle_h2h(ev):
                pm_by[m["code"]] = prob.market_probs(odds.pinnacle_h2h(ev), odds.pinnacle_totals(ev))
        n = 0
        for m in ms:
            r = claude_check.analyze_and_store(m, pm_by.get(m["code"]))
            if r:
                n += 1; log(f"Sabah analizi: {m['home']}-{m['away']} ${r.get('cost_usd')}")
            if n >= claude_check.MAX_PER_DAY:
                break
        if n:
            sh([sys.executable, "social.py"], capture_output=True, text=True)
    except Exception as e:
        log(f"Sabah analizi hatası: {e}")


INSIGHTS_UTC = (3, 0)   # 06:00 TSİ'den sonra günde bir: Instagram insights kaydı (insights.py); pazartesi ayrıca geçen haftanın iç raporu


def maybe_insights(s, now):
    if not (os.environ.get("IG_TOKEN") and os.environ.get("IG_USER_ID")) or (now.hour, now.minute) < INSIGHTS_UTC:
        return
    day = now.strftime("%Y-%m-%d")
    if s.get("insights_day") != day:
        r = sh([sys.executable, "insights.py"], capture_output=True, text=True)
        log("insights: " + (r.stdout or r.stderr).strip()[:300])
        s["insights_day"] = day; save_status(s)
    week = f"{now.isocalendar()[0]}-W{now.isocalendar()[1]:02d}"
    if now.weekday() == 0 and s.get("insights_report_week") != week:
        r = sh([sys.executable, "insights.py", "--report"], capture_output=True, text=True)
        log("insights rapor: " + (r.stdout or r.stderr).strip()[:200])
        s["insights_report_week"] = week; save_status(s)


def reels_due(rc, now):
    """Panelden hazırlanan reels (status 'ready' + asset) yayın saati geldi mi?
    Döner: (şimdi yayınla?, bekleniyorsa yayın saati UTC (h, m))."""
    if rc.get("status") != "ready" or not rc.get("asset"):
        return False, None
    hm = control.parse_hm(rc.get("at") or "")
    if not hm:
        return True, None
    at = now.astimezone(control.TR).replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
    if now >= at:
        return True, None
    u = at.astimezone(timezone.utc)
    return False, (u.hour, u.minute)


def maybe_reels(s, now):
    """control.reels[bugün] hazırsa ve saati geldiyse: GitHub Release'ten mp4 + açıklamayı indir, Instagram'a yükle, günlüğe yaz.
    Böylece reels yayını için kullanıcının bilgisayarının açık olması gerekmez. Döner: bekleyen yayın saati UTC ya da None."""
    if not (os.environ.get("IG_TOKEN") and os.environ.get("IG_USER_ID")):
        return None
    import instagram
    ctrl = control.load()
    day = now.astimezone(control.TR).strftime("%Y-%m-%d")
    rc = control.reels(ctrl, day)
    due, nxt = reels_due(rc, now)
    if not due:
        return nxt
    if any(x.get("type") == "reels" and x.get("code") == rc.get("code") for x in instagram.load_log()):
        control.set_reels(ctrl, day, status="posted"); control.save(ctrl)
        log("reels: bu maç zaten yayınlanmış, 'posted' işaretlendi"); return None
    try:
        tag, name = rc["asset"].split("/", 1)
        cap_name = (rc.get("caption_asset") or "").split("/", 1)[-1] or f"caption_{rc['code']}.txt"
        dl = "data/reels_in"; os.makedirs(dl, exist_ok=True)
        r = sh(["gh", "release", "download", tag, "-R", REPO, "-p", name, "-p", cap_name, "-D", dl, "--clobber"], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"release indirilemedi: {r.stderr.strip()[:200]}")
        cap = open(f"{dl}/{cap_name}", encoding="utf-8").read()
        cover_url = f"{instagram.RAW}/{rc['cover']}" if rc.get("cover") else None
        pid = instagram.publish_reels_file(f"{dl}/{name}", cap, cover_url=cover_url)
        instagram.log_post({"code": rc["code"], "home": rc.get("home", ""), "away": rc.get("away", "")}, "reels", pid)
        control.set_reels(ctrl, day, status="posted", post_id=pid, posted_at=now.isoformat(timespec="seconds")); control.save(ctrl)
        log(f"reels YAYINLANDI (panel): {rc.get('home')}-{rc.get('away')} {pid}")
    except Exception as e:
        control.set_reels(ctrl, day, status="error", error=str(e)[:300]); control.save(ctrl)
        log(f"reels yayın hatası: {e}")
    return None



STANDINGS_UTC = (9, 0)   # Pazartesi 12:00 TSİ: haftalık puan durumu karuseli (standings.py); kartlar bir tur önce üretilip Pages'e itilir


def maybe_standings(s, now):
    """Pazartesi: 08:30 UTC sonrası kartları üret (bu turun push'u Pages'e taşır), 09:00 UTC sonrası Instagram'a gönder.
    control.json: standings[hafta].skip ya da paused_until varsa gönderilmez. Döner: beklenen yayın saati UTC ya da None."""
    if now.weekday() != 0 or not os.environ.get("IG_TOKEN"):
        return None
    import standings
    week = standings.week_key(now)
    if s.get("standings_cards_week") != week and (now.hour, now.minute) >= (8, 30):
        r = sh([sys.executable, "standings.py"], capture_output=True, text=True)
        log("puan durumu kartları: " + (r.stdout or r.stderr).strip()[:200])
        if r.returncode == 0:
            s["standings_cards_week"] = week; save_status(s)
        return STANDINGS_UTC
    if s.get("standings_cards_week") == week and s.get("standings_post_week") != week:
        if (now.hour, now.minute) < STANDINGS_UTC:
            return STANDINGS_UTC
        ctrl = control.load()
        if control.is_paused(ctrl) or ((ctrl.get("standings") or {}).get(week) or {}).get("skip"):
            log("puan durumu: panel kararıyla atlandı"); s["standings_post_week"] = week; save_status(s); return None
        r = sh([sys.executable, "standings.py", "--post"], capture_output=True, text=True)
        out = (r.stdout or r.stderr).strip(); log("puan durumu gönderimi: " + out[:200])
        if "YAYINLANDI" in out or "zaten" in out:
            s["standings_post_week"] = week; save_status(s)
    return None


STORY_KINDS = {"story": "story", "devre": "story_ht", "macsonu": "story_ft", "ft": "story_ft"}   # dosya öneki → günlük türü (gözcü maç sonunu 'macsonu_' yazar)


def story_due(prefix, start, now):
    """Yedek story için zaman penceresi: kadro maçtan 3 sa önce–başlangıç+20 dk; devre başlangıç+40 dk–+2 sa; maç sonu +95 dk–+4 sa."""
    d = (now - start).total_seconds() / 60
    if prefix == "story":
        return -180 <= d <= 20
    if prefix == "devre":
        return 40 <= d <= 120
    if prefix in ("ft", "macsonu"):
        return 95 <= d <= 240
    return False


def maybe_story_fallback(s, now):
    """Gözcü story kartını üretip repoya yazmış ama yayınlayamamışsa (çökme, zaman aşımı) bekçi yayınlar:
    docs/social/<gün>/{story,devre,ft}_<kod>.jpg var, günlükte yok, dosya en az 5 dk önce commit edilmiş, zaman penceresi uygun.
    Panel kararlarına (story skip, duraklatma) uyar. Kullanıcı sürekli başında olmadığı için otomasyonun yedeği."""
    if not (os.environ.get("IG_TOKEN") and os.environ.get("IG_USER_ID")):
        return
    import glob, instagram
    tr = control.TR
    day = now.astimezone(tr).strftime("%Y-%m-%d")
    files = sum((glob.glob(f"docs/social/{day}/{p}_*.jpg") for p in STORY_KINDS), [])
    if not files:
        return
    # gözcü az önce yayınlayıp günlüğü ittiyse görelim (çift gönderi olmasın): rebase yapmadan uzak günlüğü oku
    # (tur ortasında records/ değişmiş olduğundan pull --rebase 'unstaged changes' ile reddediyordu)
    log_rows = instagram.load_log()
    try:
        sh(["git", "fetch", "-q", "origin", "master"], capture_output=True)
        r = sh(["git", "show", "origin/master:records/instagram.jsonl"], capture_output=True, text=True, encoding="utf-8")
        if r.returncode == 0:
            seen = {(x.get("type"), x.get("code")) for x in log_rows}
            for l in r.stdout.splitlines():
                try:
                    x = json.loads(l)
                except ValueError:
                    continue
                if (x.get("type"), x.get("code")) not in seen:
                    log_rows.append(x)
    except Exception as e:
        log(f"story yedeği: uzak günlük okunamadı ({e})")
    ctrl = control.load()
    if control.is_paused(ctrl):
        return
    ms = None
    for p in files:
        name = os.path.basename(p)[:-4]
        prefix, _, code_s = name.partition("_")
        if prefix not in STORY_KINDS or not code_s.isdigit():
            continue
        code, kind = int(code_s), STORY_KINDS[prefix]
        if any(x.get("type") == kind and x.get("code") == code for x in log_rows):
            continue
        if control.story_skip(ctrl, day, code):
            continue
        r = sh(["git", "log", "-1", "--format=%ct", "--", p], capture_output=True, text=True)
        try:
            committed = datetime.fromtimestamp(int(r.stdout.strip()), timezone.utc)
        except ValueError:
            continue   # henüz commit edilmemiş (gözcü bu turda yazıyor olabilir)
        if (now - committed).total_seconds() < 300:
            continue   # gözcünün kendi yayın denemesi en çok 3 dk sürer (wait_public 180 sn); 5 dk geçtiyse vazgeçmiştir
        if ms is None:
            _t, last = build_site.recent_snapshot(build_site.read_jsonl("records/nesine/*.jsonl"))
            ms = {m["code"]: m for m in build_site.nesine_matches(last)}
        m = ms.get(code)
        if not m or not story_due(prefix, m["start"], now):
            continue
        try:
            url = f"{instagram.RAW}/social/{day}/{name}.jpg"
            pid = instagram.post_story_for(m, url, kind=kind, size=os.path.getsize(p))
            log(f"story yedeği ({prefix}) yayınlandı: {m['home']}-{m['away']} → {pid}" if pid else f"story yedeği ({prefix}) gönderilmedi (sınır/tekrar): {m['home']}-{m['away']}")
            log_rows = instagram.load_log()
        except Exception as e:
            log(f"story yedeği hatası ({name}): {e}")


def fix_watch_status():
    """Gözcü çalışmıyorken 'active: true' kalmışsa (yarım kalan çalışma) sıfırla; sayfa yanlış 'Gözcü açık' demesin."""
    p = "records/watch_status.json"
    if not os.path.exists(p):
        return
    try:
        w = json.load(open(p, encoding="utf-8"))
    except ValueError:
        return
    if w.get("active") and not workflow_active("watch.yml"):
        w.update(active=False, note="")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(w, f, ensure_ascii=False)
        log("Bayat gözcü durumu sıfırlandı")


def maybe_espn(now):
    """48 saat içindeki maçlar için ESPN golcü/son-5 verisi (ücretsiz). Kadro yakınken gözcü günceller."""
    try:
        have = espn.load_all()
        ms = [m for m in nesine.parse(nesine.fetch(save_path=None)) if now < m["start"] <= now + timedelta(hours=48)]
        n = 0
        for m in ms:
            old = have.get(m["code"])
            if old and old.get("leaders"):
                continue
            if espn.fetch_match(m):
                n += 1
            if n >= 25:
                break
        if n:
            log(f"ESPN: {n} maç için golcü/son-5 verisi alındı")
    except Exception as e:
        log(f"ESPN hatası: {e}")


def maybe_watch(s, now):
    """3 saat içinde hedef maç varsa ve gözcü çalışmıyorsa tetikle (gözcü kendi penceresini kendi yönetir; saatlik kontrol
    olduğu için 3 saat, 100 dk'lık izleme penceresinin başını kaçırmamayı garanti eder)."""
    key = now.strftime("%Y-%m-%d-%H")
    if s.get("watch_check") == key:
        return
    s["watch_check"] = key; save_status(s)
    try:
        ms = [m for m in nesine.parse(nesine.fetch(save_path=None)) if now < m["start"] <= now + timedelta(hours=3)]
    except Exception as e:
        log(f"Nesine okunamadı: {e}"); return
    if ms and not workflow_active("watch.yml"):
        dispatch("watch.yml", max_minutes="340")


def code_version():
    """Takip edilen kod dosyalarının (py + iş akışları + alias json) blob özetleri; değişirse yeni kodla yeniden başlamak için.
    Not: ls-tree joker kabul etmez; tüm ağacı alıp Python tarafında süzüyoruz."""
    r = sh(["git", "ls-tree", "-r", "HEAD"], capture_output=True, text=True)
    keep = [l for l in r.stdout.splitlines()
            if l.endswith(".py") or ".github/workflows/" in l or l.endswith("aliases.json")]
    return "\n".join(sorted(keep))


def pull():
    """Uzak değişiklikleri al; rebase takılırsa iptal et (repo yarım kalmasın)."""
    if sh(["git", "pull", "--rebase", "-X", "theirs", "-q", "origin", "master"]).returncode != 0:
        sh(["git", "rebase", "--abort"])
        return False
    return True


def main():
    max_minutes = float(sys.argv[sys.argv.index("--max-minutes") + 1]) if "--max-minutes" in sys.argv else 340
    chain = "--no-chain" not in sys.argv
    sh(["git", "config", "user.name", "iddia-bot"]); sh(["git", "config", "user.email", "actions@users.noreply.github.com"])
    deadline = time.time() + max_minutes * 60
    version = code_version()
    log(f"Bekçi başladı, {max_minutes:.0f} dk çalışacak, zincir={'açık' if chain else 'kapalı'}")
    while True:
        now = datetime.now(timezone.utc)
        s = load_status()
        fix_watch_status()
        record_once()
        s = load_status(); s["keeper_last"] = now.isoformat(timespec="seconds"); save_status(s)
        # Tur başına TEK push: her push bir Pages derlemesi tetikliyor (saatte 10 derleme sınırı var); ara adımlar hata verse de kayıt gider
        global NEXT_SLOT_UTC, REELS_NEXT_UTC, STANDINGS_NEXT_UTC
        NEXT_SLOT_UTC = None; REELS_NEXT_UTC = None; STANDINGS_NEXT_UTC = None
        try:
            maybe_results(s, now)
            maybe_watch(s, now)
            maybe_espn(now)
            maybe_morning_claude(load_status(), now)
            maybe_insights(load_status(), now)
            REELS_NEXT_UTC = maybe_reels(load_status(), now)
            STANDINGS_NEXT_UTC = maybe_standings(load_status(), now)
            maybe_story_fallback(load_status(), now)
            if now.minute < 20:  # saatte bir: paylaşım kartları (yerel, ücretsiz)
                r = sh([sys.executable, "social.py"], capture_output=True, text=True); log((r.stdout or r.stderr).strip()[:200])
            # Instagram gönderimi (secret varsa): 09:50 TSİ'den sonra her turda; saati gelen gönderi gider, gelmeyen "planlı" diye bildirilir
            if os.environ.get("IG_TOKEN") and (now.hour, now.minute) >= IG_POST_UTC:
                r = sh([sys.executable, "instagram.py"], capture_output=True, text=True); out = (r.stdout or r.stderr).strip()
                log("instagram: " + out[:300])
                mm = re.search(r"NEXT_SLOT_UTC=(\d\d):(\d\d)", out)
                if mm:
                    NEXT_SLOT_UTC = (int(mm.group(1)), int(mm.group(2)))
        except Exception as e:
            log(f"Tur içi hata (kayıt yine de gönderiliyor): {e}")
        publish(f"kayıt {now:%Y-%m-%d %H:%M}")
        # yeni kod geldiyse bu çalışma eski kodla devam etmesin (kayıt alındı, şimdi çıkılabilir)
        pull()
        if code_version() != version:
            log("Kod güncellendi; " + ("yeni sürümle yeniden başlıyorum." if chain else "zincir kapalı, çıkıyorum (yedek cron devralır)."))
            break
        if time.time() + RECORD_MIN * 60 > deadline:
            break
        wait = RECORD_MIN * 60
        # gönderi tam saatinde gitsin: bir sonraki yayın saati (ya da ilk kontrol saati) bu turun içindeyse o saate kadar bekle
        for hm in (NEXT_SLOT_UTC, REELS_NEXT_UTC, STANDINGS_NEXT_UTC, IG_POST_UTC):
            if hm:
                nxt = datetime.now(timezone.utc).replace(hour=hm[0], minute=hm[1], second=10, microsecond=0)
                left = (nxt - datetime.now(timezone.utc)).total_seconds()
                if 0 < left < wait:
                    wait = left
        time.sleep(wait)
    if chain:
        dispatch("keeper.yml")
    log("Bekçi bitti.")


if __name__ == "__main__":
    main()
