"""Bekçi: GitHub cron'una bağımlı olmayan zamanlayıcı. Tek uzun çalışma (≤ ~5.7 saat) içinde:
  - her RECORD_MIN dakikada Nesine kaydı (record_once.py) + sayfa (+ kupon kilitleme) + repoya yazma,
  - günde bir kez (04:30 UTC sonrası) "Sonuçlar ve puanlama" iş akışını tetikler,
  - hedef liglerde 2 saat içinde maç varsa ve gözcü çalışmıyorsa "Maç günü gözcüsü"nü tetikler,
  - süresi bitince KENDİNİ yeniden tetikler (GITHUB_TOKEN, actions:write).
Böylece zincir kopmadıkça kayıt hiç durmaz. Cron çalışmaya başlarsa da zarar vermez (aynı concurrency grubu).

Kullanım: python keeper.py [--max-minutes 340] [--no-chain]
"""
import json, os, subprocess, sys, time
from datetime import datetime, timezone, timedelta
import nesine, espn, claude_check, build_site, odds, prob, match

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


PRIORITY = ["soccer_turkey_super_league", "soccer_epl", "soccer_uefa_champs_league", "soccer_spain_la_liga", "soccer_italy_serie_a",
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
        ms.sort(key=lambda m: (PRIORITY.index(m["sport_key"]) if m["sport_key"] in PRIORITY else 99, m["start"]))
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
        publish(f"kayıt {now:%Y-%m-%d %H:%M}")
        maybe_results(s, now)
        maybe_watch(s, now)
        maybe_espn(now)
        maybe_morning_claude(load_status(), now)
        if now.minute < 20:  # saatte bir: paylaşım kartları (yerel, ücretsiz) + Instagram gönderimi (secret varsa)
            r = sh([sys.executable, "social.py"], capture_output=True, text=True); log((r.stdout or r.stderr).strip()[:200])
            if (now.hour, 0) >= (7, 0) and now.hour <= 19 and os.environ.get("IG_TOKEN"):
                r = sh([sys.executable, "instagram.py"], capture_output=True, text=True); log("instagram: " + (r.stdout or r.stderr).strip()[:300])
        publish(f"espn/kart {now:%H:%M}")
        # yeni kod geldiyse bu çalışma eski kodla devam etmesin (kayıt alındı, şimdi çıkılabilir)
        pull()
        if code_version() != version:
            log("Kod güncellendi; " + ("yeni sürümle yeniden başlıyorum." if chain else "zincir kapalı, çıkıyorum (yedek cron devralır)."))
            break
        if time.time() + RECORD_MIN * 60 > deadline:
            break
        time.sleep(RECORD_MIN * 60)
    if chain:
        dispatch("keeper.yml")
    log("Bekçi bitti.")


if __name__ == "__main__":
    main()
