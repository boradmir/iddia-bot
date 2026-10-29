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
import nesine

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


def maybe_results(s, now):
    day = now.strftime("%Y-%m-%d")
    if (now.hour, now.minute) >= (4, 30) and s.get("results_day") != day:
        if True:
            if dispatch("results.yml"):
                s["results_day"] = day; save_status(s)


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
