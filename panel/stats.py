"""İstatistik ekranı: records/insights (hesap serisi, gönderi tablosu, haftalık iç rapor) ve reklam kaydı (ads.jsonl)."""
import glob, json, os, re, html
from datetime import datetime, timezone, timedelta

TR = timezone(timedelta(hours=3))
ADS = "records/insights/ads.jsonl"


def _rows(pattern):
    out = []
    for p in sorted(glob.glob(pattern)):
        for l in open(p, encoding="utf-8"):
            try:
                out.append(json.loads(l))
            except ValueError:
                pass
    return out


def account(days=30):
    rows = _rows("records/insights/account.jsonl")
    by_day = {}
    for r in rows:
        by_day[r["day"]] = r   # günde son kayıt
    reach = {}
    for r in rows:
        for d, v in (r.get("reach") or {}).items():
            reach[d] = v
    days_sorted = sorted(by_day)[-days:]
    return {"days": days_sorted, "followers": [by_day[d].get("followers") for d in days_sorted],
            "reach_days": sorted(reach)[-days:], "reach": [reach[d] for d in sorted(reach)[-days:]],
            "latest": by_day[days_sorted[-1]] if days_sorted else {}}


def media():
    """Her gönderi için en son günün satırı (zaman serisinin son noktası)."""
    rows = _rows("records/insights/media_*.jsonl")
    latest = {}
    for r in rows:
        k = r.get("post_id")
        if k and (k not in latest or r["t"] > latest[k]["t"]):
            latest[k] = r
    out = sorted(latest.values(), key=lambda r: r.get("posted_at") or "", reverse=True)
    keys = ("post_id", "day", "type", "kind", "home", "away", "tier", "league", "posted_at", "post_hour", "weekday", "lead_h", "fav", "fav_pct",
            "views", "reach", "likes", "comments", "shares", "saved", "total_interactions", "follows", "profile_visits", "int_rate", "save_rate",
            "boosted", "ad_tl", "age_h", "ig_reels_avg_watch_time")
    return [{k: r.get(k) for k in keys} for r in out]


def ads():
    return _rows(ADS)


def latest_report():
    files = sorted(glob.glob("records/insights/rapor_*.md"))
    if not files:
        return {"name": None, "html": "<p>Henüz haftalık rapor yok. Bekçi her pazartesi geçen haftanın raporunu yazar.</p>"}
    p = files[-1]
    return {"name": os.path.basename(p), "html": md_to_html(open(p, encoding="utf-8").read())}


def md_to_html(md):
    """Küçük markdown çevirici: başlık, tablo, liste, kalın. Dış bağımlılık yok."""
    out, table, lst = [], [], False
    def flush_table():
        nonlocal table
        if not table:
            return
        rows = [r for r in table if not re.match(r"^\|?\s*:?-{2,}", r)]
        h = []
        for i, r in enumerate(rows):
            cells = [html.escape(c.strip()) for c in r.strip().strip("|").split("|")]
            tag = "th" if i == 0 else "td"
            h.append("<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in cells) + "</tr>")
        out.append("<table>" + "".join(h) + "</table>")
        table = []
    def inline(s):
        s = html.escape(s)
        return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    for line in md.splitlines():
        if line.strip().startswith("|"):
            table.append(line); continue
        flush_table()
        if lst and not line.strip().startswith(("-", "*")):
            out.append("</ul>"); lst = False
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if m:
            out.append(f"<h{len(m.group(1)) + 1}>{inline(m.group(2))}</h{len(m.group(1)) + 1}>"); continue
        if line.strip().startswith(("-", "*")):
            if not lst:
                out.append("<ul>"); lst = True
            out.append(f"<li>{inline(line.strip()[1:].strip())}</li>"); continue
        if line.strip():
            out.append(f"<p>{inline(line)}</p>")
    flush_table()
    if lst:
        out.append("</ul>")
    return "\n".join(out)


def add_ad(post_id, budget_tl, days, note=""):
    """Reklam kaydı satırı: insights raporu bu gönderiyi 'reklamlı' sayar, organik tablolara sokmaz."""
    row = next((r for r in media() if r["post_id"] == post_id), None)
    if not row:
        raise ValueError("gönderi insights kayıtlarında yok")
    if any(a.get("post_id") == post_id for a in ads()):
        raise ValueError("bu gönderi için reklam kaydı zaten var")
    rec = {"post_id": post_id, "day": datetime.now(TR).strftime("%Y-%m-%d"), "type": row.get("type"), "home": row.get("home"), "away": row.get("away"),
           "budget_tl": float(budget_tl), "days": int(days), "note": note, "t": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    os.makedirs(os.path.dirname(ADS), exist_ok=True)
    with open(ADS, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def account_table(days=30):
    """Günlük hesap ölçümleri tablosu (son kayıt o günün değeri)."""
    rows = _rows("records/insights/account.jsonl")
    by_day = {}
    for r in rows:
        by_day[r["day"]] = r
    keys = ("followers", "follows", "media", "views_today", "profile_views_today", "accounts_engaged_today", "total_interactions_today", "website_clicks_today")
    out = []
    for d in sorted(by_day)[-days:]:
        r = by_day[d]
        out.append({"day": d, **{k: r.get(k) for k in keys}, "reach_day": (r.get("reach") or {}).get(d)})
    return out[::-1]


def series(post_id):
    """Bir gönderinin gün gün ölçümleri (yaşa göre erişim/görüntü/beğeni/kaydet/paylaş)."""
    rows = sorted([r for r in _rows("records/insights/media_*.jsonl") if r.get("post_id") == post_id], key=lambda r: r["t"])
    keys = ("day", "age_h", "reach", "views", "likes", "comments", "saved", "shares", "total_interactions", "follows", "profile_visits", "replies", "int_rate")
    return [{k: r.get(k) for k in keys} for r in rows]


def stories():
    rows = _rows("records/insights/media_*.jsonl")
    latest = {}
    for r in rows:
        if r.get("kind") == "story" and (r["post_id"] not in latest or r["t"] > latest[r["post_id"]]["t"]):
            latest[r["post_id"]] = r
    out = []
    for r in sorted(latest.values(), key=lambda r: r.get("posted_at") or "", reverse=True):
        nav = r.get("nav") or {}
        out.append({"post_id": r["post_id"], "type": {"story": "kadro", "story_ht": "devre", "story_ft": "maç sonu"}.get(r.get("type"), r.get("type")),
                    "home": r.get("home"), "away": r.get("away"), "posted_at": r.get("posted_at"), "reach": r.get("reach"), "views": r.get("views"),
                    "replies": r.get("replies"), "shares": r.get("shares"), "follows": r.get("follows"), "profile_visits": r.get("profile_visits"),
                    "forward": (nav.get("tap_forward") or 0) + (nav.get("swipe_forward") or 0), "back": nav.get("tap_back", 0), "exit": nav.get("tap_exit", 0)})
    return out


def by_group():
    """Tür / saat / gün / kademe ortalamaları (organik gönderiler, her gönderinin son ölçümü)."""
    posts = [m for m in media() if m.get("kind") != "story" and not m.get("boosted")]
    def grp(key, label):
        g = {}
        for m in posts:
            g.setdefault(key(m), []).append(m)
        return [{"grup": k, "n": len(v), "erisim": round(sum(x.get("reach") or 0 for x in v) / len(v)), "goruntu": round(sum(x.get("views") or 0 for x in v) / len(v)),
                 "kaydet": round(sum(x.get("saved") or 0 for x in v) / len(v), 1), "etk": round(100 * sum(x.get("int_rate") or 0 for x in v) / len(v), 1)} for k, v in sorted(g.items(), key=lambda kv: str(kv[0]))]
    return {"Tür": grp(lambda m: m.get("kind") or "karusel", "tür"), "Saat": grp(lambda m: f"{m.get('post_hour', 0):02d}:00", "saat"),
            "Gün": grp(lambda m: m.get("weekday") or "?", "gün"), "Kademe": grp(lambda m: f"kademe {m.get('tier')}", "kademe"),
            "Favori gücü": grp(lambda m: "favori ≥%65" if (m.get("fav_pct") or 0) >= 65 else "favori %50-64" if (m.get("fav_pct") or 0) >= 50 else "dengeli", "fav")}


def data():
    med = media()
    return {"account": account(), "account_table": account_table(), "media": med, "stories": stories(), "groups": by_group(),
            "series": {m["post_id"]: series(m["post_id"]) for m in med[:30]}, "ads": ads(), "report": latest_report()}
