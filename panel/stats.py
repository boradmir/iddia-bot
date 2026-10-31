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


def data():
    return {"account": account(), "media": media(), "ads": ads(), "report": latest_report()}
