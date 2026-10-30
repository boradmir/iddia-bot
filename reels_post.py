"""Reels üretip belirlenen saatte yayınlar.
Kullanım: python reels_post.py --home Fenerbahçe [--at 12:00] [--dry] [--now]
Akış: git pull → günün yapay zekâ paketi (records/claude/<gün>.jsonl) gelene kadar bekle → reels üret (data/reels/<gün>/) →
--at saatine kadar bekle → Instagram'a doğrudan yükle ve yayınla → günlüğe yaz → günlüğü it.
"""
import json, os, subprocess, sys, time
from datetime import datetime, timezone, timedelta
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import config, build_site, espn, odds, prob, match, reels, instagram

TR = timezone(timedelta(hours=3))
arg = lambda k, d=None: sys.argv[sys.argv.index(k) + 1] if k in sys.argv else d
HOME = arg("--home"); AT = arg("--at"); DRY = "--dry" in sys.argv; NOW = "--now" in sys.argv
if not HOME:
    sys.exit("--home gerekli")


def log(msg):
    print(f"{datetime.now(TR):%H:%M:%S} {msg}", flush=True)


def git_pull():
    subprocess.run(["git", "pull", "-q", "--rebase", "-X", "theirs", "--autostash"], capture_output=True)


def todays_match():
    rows = build_site.read_jsonl("records/nesine/*.jsonl"); t, last = build_site.latest_snapshot(rows)
    today = datetime.now(TR).date()
    for m in build_site.nesine_matches(last):
        if HOME.lower() in m["home"].lower() and m["start"].astimezone(TR).date() == today:
            return m
    return None


def package_for(code):
    day = datetime.now(TR).strftime("%Y-%m-%d")
    p = f"records/claude/{day}.jsonl"
    if not os.path.exists(p):
        return None
    for l in open(p, encoding="utf-8"):
        r = json.loads(l)
        if r.get("code") == code and r.get("blind") and r["blind"].get("comment"):
            return r
    return None


def market_probs(m):
    events = build_site.pinnacle_events(build_site.read_jsonl("records/pinnacle/*.jsonl"))
    aliases = json.load(open("aliases.json", encoding="utf-8")) if os.path.exists("aliases.json") else {}
    for mm, ev, sc in match.match_all([m], events, aliases):
        if ev and odds.pinnacle_h2h(ev):
            return prob.market_probs(odds.pinnacle_h2h(ev), odds.pinnacle_totals(ev))
    return None


def main():
    git_pull()
    m = todays_match()
    if not m:
        sys.exit(f"Bugün {HOME} ev sahibi maçı yok")
    log(f"Maç: {m['home']} - {m['away']} {m['start'].astimezone(TR):%H:%M} (kod {m['code']})")
    # 1) paket bekle (bekçi sabah 07:30'dan sonra yazar)
    pkg = package_for(m["code"])
    while not pkg:
        log("Yapay zekâ paketi henüz yok; 5 dk sonra tekrar"); time.sleep(300); git_pull(); pkg = package_for(m["code"])
    bl = pkg["blind"]
    log(f"Paket hazır. Kanca: {bl.get('hook')}")
    # 2) üret
    day = datetime.now(TR).strftime("%Y-%m-%d"); out_dir = f"data/reels/{day}"; os.makedirs(out_dir, exist_ok=True)
    out = f"{out_dir}/reels_{m['code']}.mp4"
    pm = market_probs(m); er = espn.load_all().get(m["code"])
    r = reels.render(m, bl, pm, er, out)
    log(f"Reels üretildi: {out} ({r['seconds']} sn, {r['words']} kelime, {os.path.getsize(out) // 1024} KB)")
    cap = instagram.reels_caption(m, bl, pm)
    open(f"{out_dir}/caption_{m['code']}.txt", "w", encoding="utf-8").write(cap)
    if DRY:
        log("Kuru mod; yayınlanmadı."); print(cap); return
    # 3) saati bekle
    if AT and not NOW:
        hh, mm_ = map(int, AT.split(":"))
        target = datetime.now(TR).replace(hour=hh, minute=mm_, second=0, microsecond=0)
        while datetime.now(TR) < target:
            left = (target - datetime.now(TR)).total_seconds()
            log(f"Yayın saati {AT}; {int(left // 60)} dk kaldı"); time.sleep(min(600, max(5, left)))
    # 4) yayınla
    if any(s.get("type") == "reels" and s.get("code") == m["code"] for s in instagram.load_log()):
        log("Bu maçın reels'i zaten yayınlanmış; çıkılıyor"); return
    pid = instagram.publish_reels_file(out, cap)
    instagram.log_post(m, "reels", pid)
    log(f"YAYINLANDI: {pid}")
    git_pull()
    subprocess.run(["git", "add", "records/instagram.jsonl"], capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", f"reels yayınlandı: {m['home']}-{m['away']}"], capture_output=True)
    subprocess.run(["git", "push", "-q"], capture_output=True)


if __name__ == "__main__":
    main()
