"""GitHub Pages sayfasını üretir: records/ içindeki kayıtlardan docs/index.html.

API çağrısı yapmaz, kota harcamaz. Herkese açık sayfa olduğu için kişisel hiçbir bilgi içermez;
yatırım tutarı TL değil kasa yüzdesi olarak gösterilir.

Kullanım: python build_site.py
"""
import glob, html, json, os, collections
from datetime import datetime, timezone
import match, odds, prob, value

MARKET_TR = {"MS": "Maç Sonucu", "AU25": "Alt/Üst 2.5", "KG": "KG Var/Yok"}


def read_jsonl(pattern):
    rows = []
    for path in sorted(glob.glob(pattern)):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


def latest_snapshot(rows):
    if not rows:
        return None, []
    t = max(r["t"] for r in rows)
    return t, [r for r in rows if r["t"] == t]


def nesine_matches(rows):
    """Kayıt satırlarını nesine.parse çıktısı biçimine çevirir."""
    by = {}
    for r in rows:
        m = by.setdefault(r["code"], {"code": r["code"], "home": r["home"], "away": r["away"], "league": r["league"],
                                      "sport_key": r["sport"], "start": datetime.fromisoformat(r["start"]), "mbs": r["mbs"], "markets": {}})
        m["markets"].setdefault(r["market"], {"odds": {}, "mbs": r["mbs"]})["odds"][r["outcome"]] = r["price"]
    return list(by.values())


def pinnacle_events(rows):
    """Kayıt satırlarını Odds API etkinlik biçimine (odds.pinnacle_h2h'nin beklediği) çevirir."""
    by = {}
    for r in rows:
        ev = by.setdefault(r["event_id"], {"id": r["event_id"], "sport_key": r["sport"], "commence_time": r["start"],
                                           "home_team": r["home"], "away_team": r["away"], "_mk": {}})
        name = {"home": r["home"], "away": r["away"], "draw": "Draw", "over": "Over", "under": "Under"}.get(r["outcome"], r["outcome"])
        ev["_mk"].setdefault(r["market"], []).append({"name": name, "price": r["price"], "point": r.get("point")})
    out = []
    for ev in by.values():
        ev["bookmakers"] = [{"key": "pinnacle", "markets": [{"key": k, "outcomes": v} for k, v in ev.pop("_mk").items()]}]
        out.append(ev)
    return out


def nesine_changes(rows, limit=25):
    """Nesine oranı değişimleri: (zaman, maç, market, sonuç, eski→yeni, maça kalan dk)."""
    series = collections.defaultdict(list)
    for r in rows:
        series[(r["code"], r["market"], r["outcome"])].append(r)
    changes = []
    n_series = 0
    for key, rs in series.items():
        rs.sort(key=lambda x: x["t"])
        n_series += 1
        for a, b in zip(rs, rs[1:]):
            if a["price"] != b["price"]:
                t = datetime.fromisoformat(b["t"]); start = datetime.fromisoformat(b["start"])
                changes.append({"t": b["t"], "home": b["home"], "away": b["away"], "market": b["market"], "outcome": b["outcome"],
                                "old": a["price"], "new": b["price"], "mins_before": int((start - t).total_seconds() // 60)})
    changes.sort(key=lambda c: c["t"], reverse=True)
    return changes, n_series


def fmt(dt):
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    return dt.strftime("%d.%m %H:%M")  # UTC; sayfada belirtilir


def build():
    nes_rows = read_jsonl("records/nesine/*.jsonl")
    pin_rows = read_jsonl("records/pinnacle/*.jsonl")
    status = {}
    if os.path.exists("records/status.json"):
        status = json.load(open("records/status.json", encoding="utf-8"))
    t_nes, nes_last = latest_snapshot(nes_rows)
    t_pin, pin_last = latest_snapshot(pin_rows)
    now = datetime.now(timezone.utc)
    nm = [m for m in nesine_matches(nes_last) if m["start"] > now]
    events = pinnacle_events(pin_last)
    aliases = json.load(open("aliases.json", encoding="utf-8")) if os.path.exists("aliases.json") else {}
    pairs = match.match_all(nm, events, aliases)
    pin_age_min = int((now - datetime.fromisoformat(t_pin)).total_seconds() // 60) if t_pin else None

    all_bets, cards = [], []
    n_matched = 0
    for m, ev, score in pairs:
        if not ev:
            continue
        h2h = odds.pinnacle_h2h(ev)
        if not h2h:
            continue
        n_matched += 1
        probs = prob.market_probs(h2h, odds.pinnacle_totals(ev))
        for b in value.evaluate(m, probs, h2h, bankroll=100.0, threshold=None):  # kasa=100 → stake = yüzde
            b["match_score"] = score
            all_bets.append(b)
            if b["ev_pct"] >= value.EV_THRESHOLD and b["nesine_odds"] < value.MAX_ODDS:
                cards.append(b)
    all_bets.sort(key=lambda x: -x["ev_pct"])
    cards.sort(key=lambda x: -x["ev_pct"])
    changes, n_series = nesine_changes(nes_rows)

    stale = pin_age_min is None or pin_age_min > 10

    def card_html(b):
        flag = '<span class="warn">Pinnacle eski — oynanmaz, bilgi amaçlı</span>' if stale else '<span class="ok">✅</span>'
        mbs = f' · <span class="warn">MBS {b["mbs"]}</span>' if b["mbs"] > 1 else " · MBS 1"
        return f"""<div class="card"><div class="head"><b>{html.escape(b['home'])} – {html.escape(b['away'])}</b>
<span class="muted">{fmt(b['start'])} UTC · {html.escape(b['league'])} · kod {b['code']}{mbs}</span></div>
<table><tr><td>Tahmin</td><td><b>{MARKET_TR[b['market']]}: {b['pick']}</b></td></tr>
<tr><td>Gelme ihtimali</td><td>%{b['fair_prob']*100:.0f}</td></tr>
<tr><td>Nesine oranı</td><td><b>{b['nesine_odds']}</b></td></tr>
<tr><td>Adil oran</td><td>{b['fair_odds']}</td></tr>
<tr><td>Değer</td><td class="ok">+{b['ev_pct']:.1f}%</td></tr>
<tr><td>Önerilen yatırım</td><td>kasanın %{b['stake']:.1f}'i</td></tr>
<tr><td>Durum</td><td>{flag}</td></tr></table></div>"""

    cards_html = "".join(card_html(b) for b in cards) or "<p>Şu an eşik üstü (≥ %3, oran &lt; 3.0) fırsat yok.</p>"
    near = "".join(f"<tr><td>{b['ev_pct']:+.1f}%</td><td>{html.escape(b['home'])} – {html.escape(b['away'])}</td>"
                   f"<td>{MARKET_TR[b['market']]} {b['pick']}</td><td>{b['nesine_odds']}</td><td>{b['fair_odds']}</td></tr>"
                   for b in all_bets[:15])
    ch_rows = "".join(f"<tr><td>{fmt(c['t'])}</td><td>{html.escape(c['home'])} – {html.escape(c['away'])}</td>"
                      f"<td>{MARKET_TR.get(c['market'], c['market'])} {c['outcome']}</td><td>{c['old']} → {c['new']}</td>"
                      f"<td>{c['mins_before']//60}s {c['mins_before']%60}dk</td></tr>" for c in changes[:25])
    n_snapshots = len({r["t"] for r in nes_rows})
    avg_ev = sum(b["ev_pct"] for b in all_bets) / len(all_bets) if all_bets else 0

    return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>İddia Bot</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:900px;margin:24px auto;padding:0 16px;background:#f6f7f9;color:#222}}
.card{{background:#fff;border-radius:10px;padding:14px 16px;margin:12px 0;box-shadow:0 1px 4px rgba(0,0,0,.08)}}
.head{{display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:8px}}
table{{border-collapse:collapse;width:100%}} td,th{{padding:4px 10px 4px 0;text-align:left}} .wide td{{border-bottom:1px solid #eee}}
.ok{{color:#1a7f37;font-weight:bold}} .warn{{color:#b35900;font-weight:bold}} .muted{{color:#666;font-size:.9em}} h2{{margin-top:32px}}
</style></head><body>
<h1>İddia Bot <span class="muted">— Nesine value tarayıcı (gölge test)</span></h1>
<p class="muted">Sayfa üretildi: {fmt(now)} UTC · Nesine kaydı: {fmt(t_nes) if t_nes else '—'} · Pinnacle kaydı: {fmt(t_pin) if t_pin else '—'}
({pin_age_min} dk önce) · gelecek maç {len(nm)} · Pinnacle'lı {n_matched} · ort. EV %{avg_ev:+.1f} · Odds API kalan kota {status.get('quota', '?')}</p>
<p class="warn">{'Pinnacle verisi 10 dakikadan eski: kartlar bilgi amaçlıdır, oynanmaz.' if stale else ''}</p>
<h2>Fırsat kartları</h2>{cards_html}
<h2>Eşiğe en yakın 15 bahis <span class="muted">(bilgi için)</span></h2>
<table class="wide"><tr><th>EV</th><th>Maç</th><th>Bahis</th><th>Nesine</th><th>Adil</th></tr>{near or '<tr><td colspan=5>—</td></tr>'}</table>
<h2>Nesine oran değişimleri <span class="muted">(son 25 · {len(changes)} değişim / {n_snapshots} kayıt / {n_series} oran serisi)</span></h2>
<table class="wide"><tr><th>Zaman (UTC)</th><th>Maç</th><th>Bahis</th><th>Oran</th><th>Maça kalan</th></tr>{ch_rows or '<tr><td colspan=5>Henüz değişim gözlenmedi.</td></tr>'}</table>
<p class="muted">Bu sayfa otomatik üretilir; yatırım tavsiyesi değildir. Hedef uzun vadede yatırılan paranın %2-5'i; günde 0-5 fırsat normal, sıfır gün de normal.</p>
</body></html>"""


if __name__ == "__main__":
    os.makedirs("docs", exist_ok=True)
    page = build()
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(page)
    print(f"docs/index.html yazıldı ({len(page)} bayt)")
