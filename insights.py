"""Instagram insights günlük kaydı + haftalık iç rapor.

Günlük (bekçi 06:00 TSİ'den sonra günde bir kez çağırır; `python insights.py`):
  - records/instagram.jsonl'daki paylaşımlar için medya ölçümleri: karusel ve reels son 14 gün, story'ler son 2 gün
    (gönderi: erişim, görüntülenme, beğeni, yorum, paylaşım, kaydetme, etkileşim, profil ziyareti, takip;
     reels: + ortalama ve toplam izleme süresi; story: erişim, görüntülenme, yanıt, paylaşım, gezinme kırılımı ileri/geri/çıkış)
  - etiketler: takım, kademe (clubs.tier), lig, tür, paylaşım saati (TSİ), gün, maça kalan saat, piyasa favori yüzdesi
  - hesap: takipçi, takip edilen, medya sayısı; günlük erişim, görüntülenme, profil ziyareti, etkileşen hesap, takipçi değişimi
  Çıktı: records/insights/media_YYYY-MM.jsonl (her gün her paylaşım için bir satır → zaman serisi),
         records/insights/account.jsonl (günde bir satır).
Haftalık (`python insights.py --report [YYYY-Www]`): records/insights/rapor_YYYY-Www.md — tür, saat, kademe, lig ve favori
  gücüne göre ortalama erişim / kaydetme / etkileşim oranı, takipçi değişimi, en iyi paylaşımlar. Yorum içermez; veri özeti.
Reklam: records/insights/ads.jsonl (elle; post_id, day, budget_tl, days) → satırlara boosted/ad_tl etiketi; raporda saat/tür/kademe
  tabloları yalnız organik gönderilerle kurulur, reklamlılar ayrı tabloda. (Reklam gösterimleri medya insights'a girmez, hesap erişimine girer.)
Belirteç hiçbir satıra yazılmaz (API'nin sayfalama bağlantıları atılır)."""
import glob, json, os, sys, urllib.error, urllib.parse, urllib.request
from collections import defaultdict
from datetime import datetime, timezone, timedelta, date
import config, clubs  # noqa: F401  (.env)

TOKEN = os.environ.get("IG_TOKEN", "")
USER_ID = os.environ.get("IG_USER_ID", "")
API = "https://graph.instagram.com/v21.0" if TOKEN.startswith("IG") else "https://graph.facebook.com/v21.0"
LOG = "records/instagram.jsonl"
OUT = "records/insights"
TR = timezone(timedelta(hours=3))
MEDIA_DAYS, STORY_DAYS = 14, 2
METRICS = {
    "carousel": ["reach", "views", "likes", "comments", "shares", "saved", "total_interactions", "follows", "profile_visits"],
    "reels": ["views", "reach", "likes", "comments", "shares", "saved", "total_interactions", "ig_reels_avg_watch_time", "ig_reels_video_view_total_time"],
    "story": ["reach", "views", "replies", "shares", "follows", "profile_visits"],
}
GUN = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]


def get(path, **params):
    params["access_token"] = TOKEN
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read())["error"]["message"]
        except Exception:
            msg = str(e)
        return None, msg
    d.pop("paging", None)   # sayfalama bağlantıları belirteci taşır: asla kaydedilmez
    return d, None


def media_insights(pid, metrics, **extra):
    """Ölçümleri çeker; desteklenmeyenleri hata metninden ayıklayıp bir kez daha dener."""
    metrics = list(metrics)
    for _ in range(3):
        if not metrics:
            return {}, None
        d, err = get(f"{pid}/insights", metric=",".join(metrics), **extra)
        if d is not None:
            out = {}
            for it in d.get("data", []):
                tv = it.get("total_value")
                out[it["name"]] = tv["value"] if tv and "value" in tv and not it.get("values") else (it.get("values") or [{}])[0].get("value")
            return out, None
        if "does not support" in err or "not supported" in err or "must be one of" in err:
            bad = [m for m in metrics if m in err]
            if not bad:
                return {}, err
            metrics = [m for m in metrics if m not in bad]
            continue
        return {}, err
    return {}, "tekrar sınırı"


def kind(row):
    t = str(row.get("type", "carousel"))
    return "story" if t.startswith("story") else ("reels" if t == "reels" else "carousel")


def ai_index():
    idx = {}
    for p in sorted(glob.glob("records/claude/*.jsonl")):
        for line in open(p, encoding="utf-8"):
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("code") is not None:
                idx[r["code"]] = r
    return idx


def nesine_lookup(code, day):
    """Yapay zekâ kaydı olmayan maç için lig, başlangıç ve MS oranları: paylaşım gününün (ve öncesinin) Nesine dosyasından."""
    out = {}
    for d in (day, day - timedelta(days=1)):
        p = f"records/nesine/{d.isoformat()}.jsonl"
        if not os.path.exists(p):
            continue
        key = f'"code": {code},'
        for line in open(p, encoding="utf-8"):
            if key not in line:
                continue
            r = json.loads(line)
            out.setdefault("league", r.get("league")); out.setdefault("sport", r.get("sport")); out.setdefault("start", r.get("start"))
            if r.get("market") == "MS" and r.get("price"):
                out.setdefault("ms", {})[r["outcome"]] = r["price"]
        if out:
            break
    if out.get("ms"):
        inv = {k: 1 / v for k, v in out["ms"].items() if v}
        tot = sum(inv.values()) or 1
        out["market"] = {"MS": {k: v / tot for k, v in inv.items()}}
    return out


def tags_for(row, ai):
    """Etiketler: takım, kademe, lig, tür, saat, gün, maça kalan saat, piyasa favorisi."""
    posted = datetime.fromisoformat(row["t"]).astimezone(TR)
    m = {"home": row.get("home", ""), "away": row.get("away", "")}
    r = ai.get(row.get("code")) or (nesine_lookup(row["code"], posted.date()) if row.get("code") else {})
    tg = {"type": str(row.get("type", "carousel")), "kind": kind(row), "home": m["home"], "away": m["away"],
          "tier": clubs.tier(m), "league": r.get("league"), "sport": r.get("sport"),
          "posted_at": posted.isoformat(timespec="minutes"), "post_hour": posted.hour, "weekday": GUN[posted.weekday()]}
    if r.get("start"):
        ko = datetime.fromisoformat(r["start"])
        tg["kickoff"] = ko.astimezone(TR).isoformat(timespec="minutes")
        tg["lead_h"] = round((ko - posted).total_seconds() / 3600, 1)
    ms = (r.get("market") or {}).get("MS") or {}
    if ms:
        fav = max(ms, key=ms.get)
        tg["fav"] = {"1": "ev", "2": "dep", "X": "ber"}.get(fav, fav); tg["fav_pct"] = round(ms[fav] * 100)
    bl = r.get("blind") or {}
    if bl.get("p_home") is not None:
        tg["ai_home_pct"] = round(bl["p_home"] * 100)
    return tg


def ads_index():
    p = f"{OUT}/ads.jsonl"
    return {a["post_id"]: a for a in (json.loads(l) for l in open(p, encoding="utf-8") if l.strip())} if os.path.exists(p) else {}


def collect_media(now):
    rows = [json.loads(l) for l in open(LOG, encoding="utf-8") if l.strip()] if os.path.exists(LOG) else []
    ai = ai_index(); ads = ads_index()
    out, errs = [], []
    for row in rows:
        pid = row.get("post_id")
        if not pid:
            continue
        t = datetime.fromisoformat(row["t"])
        age_h = (now - t).total_seconds() / 3600
        k = kind(row)
        if age_h > (STORY_DAYS if k == "story" else MEDIA_DAYS) * 24:
            continue
        met, err = media_insights(pid, METRICS[k])
        if err and not met:
            errs.append(f"{pid} ({k}): {err[:120]}"); continue
        rec = {"day": now.astimezone(TR).date().isoformat(), "t": now.isoformat(timespec="seconds"), "post_id": pid,
               "code": row.get("code"), "age_h": round(age_h, 1)}
        rec.update(tags_for(row, ai)); rec.update(met)
        if pid in ads:
            rec["boosted"] = True; rec["ad_tl"] = ads[pid].get("budget_tl"); rec["ad_days"] = ads[pid].get("days")
        if k == "story":
            nav, _ = get(f"{pid}/insights", metric="navigation", breakdown="story_navigation_action_type")
            if nav:
                for it in nav.get("data", []):
                    for br in (it.get("total_value") or {}).get("breakdowns", []):
                        rec["nav"] = {x["dimension_values"][0]: x["value"] for x in br.get("results", [])}
        if rec.get("reach") and k != "story":
            rec["int_rate"] = round((rec.get("total_interactions") or 0) / rec["reach"], 4)
            rec["save_rate"] = round((rec.get("saved") or 0) / rec["reach"], 4)
        out.append(rec)
    return out, errs


def collect_account(now):
    rec = {"day": now.astimezone(TR).date().isoformat(), "t": now.isoformat(timespec="seconds")}
    d, err = get(USER_ID, fields="followers_count,follows_count,media_count")
    if d:
        rec.update(followers=d.get("followers_count"), follows=d.get("follows_count"), media=d.get("media_count"))
    d, _ = get(f"{USER_ID}/insights", metric="reach,follower_count", period="day")
    if d:
        for it in d.get("data", []):
            rec[it["name"]] = {v["end_time"][:10]: v["value"] for v in it.get("values", []) if "value" in v}
    d, _ = get(f"{USER_ID}/insights", metric="views,profile_views,accounts_engaged,total_interactions,website_clicks", period="day", metric_type="total_value")
    if d:
        for it in d.get("data", []):
            rec[it["name"] + "_today"] = (it.get("total_value") or {}).get("value")
    return rec, err


def append(path, rows):
    os.makedirs(OUT, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def daily():
    if not (TOKEN and USER_ID):
        print("IG_TOKEN/IG_USER_ID yok"); return
    now = datetime.now(timezone.utc)
    media, errs = collect_media(now)
    acct, err = collect_account(now)
    append(f"{OUT}/media_{now.astimezone(TR):%Y-%m}.jsonl", media)
    append(f"{OUT}/account.jsonl", [acct])
    print(f"insights: {len(media)} medya satırı, takipçi={acct.get('followers')}" + (f"; hatalar: {' | '.join(errs)}" if errs else "") + (f"; hesap hatası: {err}" if err else ""))


# ---------------- haftalık rapor ----------------
def load_media():
    rows = []
    for p in sorted(glob.glob(f"{OUT}/media_*.jsonl")):
        rows += [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    return rows


def latest_per_post(rows):
    best = {}
    for r in rows:
        if r["post_id"] not in best or r["t"] > best[r["post_id"]]["t"]:
            best[r["post_id"]] = r
    return list(best.values())


def mean(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return (sum(xs) / len(xs)) if xs else None


def fmt(x, pct=False):
    if x is None:
        return "-"
    return f"%{x * 100:.1f}" if pct else (f"{x:.0f}" if abs(x) >= 10 else f"{x:.1f}")


def group_table(rows, key_fn, title):
    g = defaultdict(list)
    for r in rows:
        g[key_fn(r)].append(r)
    lines = [f"### {title}", "", "| Grup | n | Erişim | Görüntülenme | Kaydetme | Etkileşim/erişim | Kaydetme/erişim |", "|---|---|---|---|---|---|---|"]
    for k in sorted(g, key=lambda x: str(x)):
        rs = g[k]
        lines.append(f"| {k} | {len(rs)} | {fmt(mean([r.get('reach') for r in rs]))} | {fmt(mean([r.get('views') for r in rs]))} | "
                     f"{fmt(mean([r.get('saved') for r in rs]))} | {fmt(mean([r.get('int_rate') for r in rs]), True)} | {fmt(mean([r.get('save_rate') for r in rs]), True)} |")
    return lines + [""]


def hour_bucket(h):
    return "sabah 06-12" if 6 <= h < 12 else "öğle 12-15" if 12 <= h < 15 else "ikindi 15-18" if 15 <= h < 18 else "akşam 18-22" if 18 <= h < 22 else "gece 22-06"


def fav_bucket(p):
    return "favori yok/bilinmiyor" if p is None else "zayıf favori <50" if p < 50 else "orta favori 50-65" if p < 65 else "güçlü favori 65+"


def report(week=None):
    today = date.today()
    if week:
        y, w = week.split("-W"); monday = date.fromisocalendar(int(y), int(w), 1)
    else:
        monday = today - timedelta(days=today.weekday() + 7)   # geçen hafta
    sunday = monday + timedelta(days=6)
    label = f"{monday.isocalendar()[0]}-W{monday.isocalendar()[1]:02d}"
    rows = latest_per_post(load_media())
    week_rows = [r for r in rows if monday.isoformat() <= r["posted_at"][:10] <= sunday.isoformat()]
    posts_all = [r for r in week_rows if r["kind"] != "story"]
    posts = [r for r in posts_all if not r.get("boosted")]
    boosted = [r for r in posts_all if r.get("boosted")]
    stories = [r for r in week_rows if r["kind"] == "story"]
    acct = [json.loads(l) for l in open(f"{OUT}/account.jsonl", encoding="utf-8")] if os.path.exists(f"{OUT}/account.jsonl") else []
    acct_w = [a for a in acct if monday.isoformat() <= a["day"] <= (sunday + timedelta(days=1)).isoformat()]
    L = [f"# Haftalık iç rapor {label} ({monday:%d.%m}–{sunday:%d.%m.%Y})", "", "İç kullanım; veri özeti, yorum yok. Ölçümler paylaşımın son çekildiği andaki birikimli değerler "
         f"(karusel/reels en çok {MEDIA_DAYS} gün, story {STORY_DAYS} gün izlenir).", ""]
    if acct_w:
        f0, f1 = acct_w[0].get("followers"), acct_w[-1].get("followers")
        L += ["## Hesap", "", f"- Takipçi: {f0} → {f1} ({(f1 or 0) - (f0 or 0):+d})"]
        reach_days = {}
        for a in acct:
            for d, v in (a.get("reach") or {}).items():
                reach_days[d] = v
        wk = {d: v for d, v in sorted(reach_days.items()) if monday.isoformat() <= d <= (sunday + timedelta(days=1)).isoformat()}
        if wk:
            L.append("- Günlük hesap erişimi (Instagram günü, UTC bitiş): " + ", ".join(f"{d[5:]}: {v}" for d, v in wk.items()))
        L.append("")
    L += ["## Gönderiler (karusel + reels)", "", f"Toplam {len(posts_all)} gönderi ({len(boosted)} reklamlı, aşağıdaki tablolar yalnız {len(posts)} organik gönderiyle), {len(stories)} story.", ""]
    if posts:
        L += group_table(posts, lambda r: r["kind"], "Türe göre")
        L += group_table(posts, lambda r: hour_bucket(r["post_hour"]), "Paylaşım saatine göre (TSİ)")
        L += group_table(posts, lambda r: f"kademe {r.get('tier')}", "Kulüp kademesine göre (0 Türk dörtlüsü, 1 dünya devleri, 2 büyük, 9 diğer; -0.5 iki büyük karşı karşıya)")
        L += group_table(posts, lambda r: r.get("league") or "bilinmiyor", "Lige göre")
        L += group_table(posts, lambda r: fav_bucket(r.get("fav_pct")), "Piyasa favorisinin gücüne göre")
        L += group_table(posts, lambda r: r["weekday"], "Haftanın gününe göre")
        L += ["### En çok erişen 5 gönderi", "", "| Gönderi | Tür | Saat | Erişim | Kaydetme | Etkileşim |", "|---|---|---|---|---|---|"]
        for r in sorted(posts, key=lambda r: r.get("reach") or 0, reverse=True)[:5]:
            L.append(f"| {r['home']}–{r['away']} | {r['kind']} | {r['posted_at'][5:16]} | {r.get('reach', '-')} | {r.get('saved', '-')} | {r.get('total_interactions', '-')} |")
        L.append("")
    if boosted:
        L += ["## Reklamlı gönderiler (organik ölçümler; reklam gösterimleri burada görünmez, hesap erişimine yansır)", "",
              "| Gönderi | Tür | Saat | Bütçe | Erişim | Kaydetme | Etkileşim | Profil ziyareti | Takip |", "|---|---|---|---|---|---|---|---|---|"]
        for r in sorted(boosted, key=lambda r: r["posted_at"]):
            L.append(f"| {r['home']}–{r['away']} | {r['kind']} | {r['posted_at'][5:16]} | {r.get('ad_tl', '-')} TL / {r.get('ad_days', '-')} gün | {r.get('reach', '-')} | "
                     f"{r.get('saved', '-')} | {r.get('total_interactions', '-')} | {r.get('profile_visits', '-')} | {r.get('follows', '-')} |")
        L.append("")
    if stories:
        L += ["## Story'ler", "", "| Story | Tür | Saat | Erişim | Görüntülenme | İleri | Geri | Çıkış | Yanıt |", "|---|---|---|---|---|---|---|---|---|"]
        for r in sorted(stories, key=lambda r: r["posted_at"]):
            nav = r.get("nav") or {}
            L.append(f"| {r['home']}–{r['away']} | {r['type']} | {r['posted_at'][5:16]} | {r.get('reach', '-')} | {r.get('views', '-')} | "
                     f"{(nav.get('tap_forward') or 0) + (nav.get('swipe_forward') or 0)} | {nav.get('tap_back', 0)} | {nav.get('tap_exit', 0)} | {r.get('replies', '-')} |")
        L.append("")
    os.makedirs(OUT, exist_ok=True)
    path = f"{OUT}/rapor_{label}.md"
    open(path, "w", encoding="utf-8").write("\n".join(L))
    print(f"rapor yazıldı: {path} ({len(posts)} gönderi, {len(stories)} story)")
    return path


if __name__ == "__main__":
    if "--report" in sys.argv:
        i = sys.argv.index("--report")
        report(sys.argv[i + 1] if i + 1 < len(sys.argv) and sys.argv[i + 1].startswith("20") else None)
    else:
        daily()
