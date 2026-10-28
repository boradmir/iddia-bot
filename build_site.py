"""GitHub Pages sayfasını üretir: records/ içindeki kayıtlardan docs/index.html.

API çağrısı yapmaz, kota harcamaz. Herkese açık sayfa olduğu için kişisel hiçbir bilgi içermez;
yatırım tutarı TL değil kasa yüzdesi olarak gösterilir. Teknik olmayan okuyucu için yazılmıştır:
jargon yok, saatler Türkiye saati.

Kullanım: python build_site.py
"""
import glob, html, json, os, collections
from datetime import datetime, timezone, timedelta
import match, odds, prob, value

TR = timezone(timedelta(hours=3))
MARKET_TR = {"MS": "Maç sonucu", "AU25": "2.5 gol alt/üst", "KG": "Karşılıklı gol"}
PICK_TR = {("MS", "1"): "Ev sahibi kazanır", ("MS", "X"): "Beraberlik", ("MS", "2"): "Deplasman kazanır",
           ("AU25", "Alt"): "2 veya daha az gol", ("AU25", "Üst"): "3 veya daha fazla gol",
           ("KG", "Var"): "İki takım da gol atar", ("KG", "Yok"): "En az bir takım gol atamaz"}
METER_MIN, METER_MAX = -25.0, 8.0  # değer sayacı ölçeği (%)


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


def nesine_changes(rows):
    """Nesine oranı değişimleri: (zaman, maç, market, sonuç, eski→yeni, maça kalan dk)."""
    series = collections.defaultdict(list)
    for r in rows:
        series[(r["code"], r["market"], r["outcome"])].append(r)
    changes = []
    for key, rs in series.items():
        rs.sort(key=lambda x: x["t"])
        for a, b in zip(rs, rs[1:]):
            if a["price"] != b["price"]:
                t = datetime.fromisoformat(b["t"]); start = datetime.fromisoformat(b["start"])
                changes.append({"t": b["t"], "home": b["home"], "away": b["away"], "market": b["market"], "outcome": b["outcome"],
                                "old": a["price"], "new": b["price"], "mins_before": int((start - t).total_seconds() // 60)})
    changes.sort(key=lambda c: c["t"], reverse=True)
    return changes, len(series)


def tr_time(dt):
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    return dt.astimezone(TR).strftime("%d.%m %H:%M")


def ago(minutes):
    if minutes is None:
        return "henüz yok"
    if minutes < 60:
        return f"{minutes} dk önce"
    if minutes < 48 * 60:
        return f"{minutes // 60} saat önce"
    return f"{minutes // 1440} gün önce"


def esc(s):
    return html.escape(str(s))


def meter(ev_pct):
    """Değer sayacı: −25% … +8% ölçeğinde çubuk; +3% eşik çizgisi CSS'te sabit."""
    x = max(METER_MIN, min(METER_MAX, ev_pct))
    width = 100 * (x - METER_MIN) / (METER_MAX - METER_MIN)
    cls = "hit" if ev_pct >= value.EV_THRESHOLD else ("near" if ev_pct >= -5 else "")
    return f'<div class="meter {cls}"><div class="bar" style="--w:{width:.1f}%"></div><div class="tick"></div></div>'


CSS = """
:root{--pitch:#0B1F17;--pitch-2:#102A20;--line:#1E3A2E;--chalk:#F2F5F0;--chalk-dim:#A9B8AF;--sodium:#F5C04A;
--paper:#FBF7EA;--ink:#1B1B1B;--ink-dim:#6B665C;--signal:#2ED47A;--ember:#F08A4B;--rule:#E5DCC3}
*{box-sizing:border-box}
html{background:var(--pitch)}
body{margin:0;font-family:"Source Sans 3",system-ui,sans-serif;font-size:17px;line-height:1.5;color:var(--chalk);
background:radial-gradient(1200px 600px at 50% -200px,#1B4A36 0%,var(--pitch) 60%)}
.wrap{max-width:860px;margin:0 auto;padding:0 20px 80px}
header{padding:40px 0 8px;display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap}
.brand{font-family:"Barlow Condensed",sans-serif;font-weight:600;font-size:22px;letter-spacing:.08em;text-transform:uppercase;color:var(--sodium)}
.brand small{display:block;font-family:"Source Sans 3",sans-serif;font-weight:400;font-size:14px;letter-spacing:0;text-transform:none;color:var(--chalk-dim)}
.pulse{display:inline-block;width:10px;height:10px;border-radius:50%;background:var(--signal);margin-right:8px;box-shadow:0 0 0 0 rgba(46,212,122,.6);animation:pulse 2.2s infinite}
.pulse.off{background:var(--ember);box-shadow:none;animation:none}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(46,212,122,.6)}70%{box-shadow:0 0 0 12px rgba(46,212,122,0)}100%{box-shadow:0 0 0 0 rgba(46,212,122,0)}}
.hero{padding:36px 0 28px;border-bottom:1px solid var(--line)}
.verdict{font-family:"Barlow Condensed",sans-serif;font-weight:700;font-size:clamp(44px,9vw,84px);line-height:.95;letter-spacing:-.01em;margin:0;
opacity:0;transform:translateY(14px);animation:rise .7s .1s cubic-bezier(.2,.7,.2,1) forwards}
.verdict em{font-style:normal;color:var(--sodium)}
.sub{margin:16px 0 0;color:var(--chalk-dim);font-size:17px;opacity:0;animation:rise .7s .35s forwards}
.sub b{color:var(--chalk);font-weight:600}
@keyframes rise{to{opacity:1;transform:none}}
.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:24px 0 0;padding:0;list-style:none;opacity:0;animation:rise .7s .5s forwards}
.facts li{background:var(--pitch-2);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.facts .n{font-family:"Barlow Condensed",sans-serif;font-size:34px;font-weight:600;line-height:1;color:var(--chalk)}
.facts .l{font-size:14px;color:var(--chalk-dim);margin-top:4px}
h2{font-family:"Barlow Condensed",sans-serif;font-weight:600;font-size:30px;letter-spacing:.02em;margin:48px 0 6px;color:var(--chalk)}
.lead{margin:0 0 18px;color:var(--chalk-dim)}
.lead b{color:var(--chalk);font-weight:600}
/* kupon kartı */
.coupon{position:relative;background:var(--paper);color:var(--ink);border-radius:6px;padding:18px 22px 20px;margin:16px 0;
box-shadow:0 10px 30px rgba(0,0,0,.35);opacity:0;animation:rise .6s forwards}
.coupon::before,.coupon::after{content:"";position:absolute;left:0;right:0;height:8px;background:
radial-gradient(circle at 6px 4px,var(--pitch) 4px,transparent 4.5px) 0 0/16px 8px repeat-x}
.coupon::before{top:-4px}.coupon::after{bottom:-4px;transform:scaleY(-1)}
.coupon .top{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;border-bottom:1px dashed var(--rule);padding-bottom:10px;margin-bottom:12px}
.coupon .teams{font-family:"Barlow Condensed",sans-serif;font-weight:700;font-size:26px;line-height:1.05}
.coupon .meta{font-family:"JetBrains Mono",monospace;font-size:12.5px;color:var(--ink-dim);text-align:right}
.coupon .pick{font-size:19px;font-weight:600;margin:0 0 10px}
.coupon .pick small{display:block;font-weight:400;font-size:14px;color:var(--ink-dim)}
.coupon dl{display:grid;grid-template-columns:1fr auto;gap:6px 16px;margin:0;font-size:15.5px}
.coupon dt{color:var(--ink-dim)}
.coupon dd{margin:0;font-family:"JetBrains Mono",monospace;font-weight:600;text-align:right}
.coupon dd.good{color:#117A45}
.coupon .status{margin-top:12px;padding-top:10px;border-top:1px dashed var(--rule);font-size:14.5px;color:var(--ink-dim)}
.coupon .status.warn{color:#9A4F12}
.empty{background:var(--pitch-2);border:1px dashed var(--line);border-radius:10px;padding:20px 22px;color:var(--chalk-dim)}
.empty b{color:var(--chalk)}
/* değer sayacı listesi */
.list{list-style:none;margin:0;padding:0}
.row{display:grid;grid-template-columns:1fr 150px 64px;gap:14px;align-items:center;padding:11px 0;border-bottom:1px solid var(--line)}
.row .m{min-width:0}
.row .t{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.row .d{font-size:14px;color:var(--chalk-dim)}
.row .d code{font-family:"JetBrains Mono",monospace;font-size:13px;color:var(--chalk)}
.row .v{font-family:"JetBrains Mono",monospace;font-size:15px;text-align:right;color:var(--chalk-dim)}
.row.hit .v{color:var(--signal);font-weight:700}
.meter{position:relative;height:10px;background:#0A1812;border-radius:5px;overflow:visible}
.meter .bar{height:100%;width:0;border-radius:5px;background:#3E5A4D;animation:grow 1.1s cubic-bezier(.2,.7,.2,1) forwards}
.meter.near .bar{background:var(--sodium)}
.meter.hit .bar{background:var(--signal)}
.meter .tick{position:absolute;top:-4px;bottom:-4px;width:2px;background:var(--chalk);opacity:.7;left:calc(100% * (3 - (-25)) / (8 - (-25)))}
@keyframes grow{to{width:var(--w)}}
.legend{display:flex;gap:18px;flex-wrap:wrap;font-size:13.5px;color:var(--chalk-dim);margin:10px 0 0}
.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}
/* değişim listesi */
.changes{list-style:none;margin:0;padding:0}
.changes li{display:grid;grid-template-columns:72px 1fr auto;gap:12px;padding:9px 0;border-bottom:1px solid var(--line);font-size:15.5px;align-items:baseline}
.changes time{font-family:"JetBrains Mono",monospace;font-size:13px;color:var(--chalk-dim)}
.changes .o{font-family:"JetBrains Mono",monospace;white-space:nowrap}
.changes .o.up{color:var(--signal)}.changes .o.down{color:var(--ember)}
.changes small{color:var(--chalk-dim)}
/* nasıl çalışır */
.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px;margin:0;padding:0;list-style:none}
.steps li{background:var(--pitch-2);border:1px solid var(--line);border-radius:10px;padding:16px 18px}
.steps b{display:block;font-family:"Barlow Condensed",sans-serif;font-size:22px;font-weight:600;margin-bottom:4px}
.steps p{margin:0;color:var(--chalk-dim);font-size:15.5px}
footer{margin-top:56px;padding-top:18px;border-top:1px solid var(--line);color:var(--chalk-dim);font-size:14px}
footer a{color:var(--sodium)}
@media (max-width:560px){.row{grid-template-columns:1fr 100px 56px}.changes li{grid-template-columns:60px 1fr}.changes .o{grid-column:2}}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}.verdict,.sub,.facts,.coupon{opacity:1;transform:none}.meter .bar{width:var(--w)}}
"""


def coupon_html(b, i, stale):
    ok = not stale
    status = ('<div class="status">✅ Oynanabilir: değer eşiğin üstünde, dünya piyasası verisi güncel.</div>' if ok else
              '<div class="status warn">⏸ Şimdilik sadece izliyoruz: dünya piyasası verisi eski, deneme aşamasındayız.</div>')
    mbs = f" · bu maç tek başına oynanamaz (en az {b['mbs']} maç)" if b["mbs"] > 1 else ""
    return f"""
<article class="coupon" style="animation-delay:{.55 + i*.12:.2f}s">
  <div class="top"><div class="teams">{esc(b['home'])}<br>{esc(b['away'])}</div>
  <div class="meta">{tr_time(b['start'])}<br>{esc(b['league'])}<br>Nesine kodu {b['code']}{esc(mbs)}</div></div>
  <p class="pick">{esc(PICK_TR.get((b['market'], b['pick']), b['pick']))}<small>{MARKET_TR[b['market']]}</small></p>
  <dl>
    <dt>Nesine'nin verdiği oran</dt><dd>{b['nesine_odds']:.2f}</dd>
    <dt>Dünya piyasasına göre gerçek ihtimal</dt><dd>%{b['fair_prob']*100:.0f}</dd>
    <dt>Bu ihtimale denk gelen adil oran</dt><dd>{b['fair_odds']:.2f}</dd>
    <dt>Nesine'nin fazladan verdiği</dt><dd class="good">+%{b['ev_pct']:.1f}</dd>
    <dt>Önerilen yatırım</dt><dd>kasanın %{b['stake']:.1f}'i</dd>
  </dl>
  {status}
</article>"""


def build():
    nes_rows = read_jsonl("records/nesine/*.jsonl")
    pin_rows = read_jsonl("records/pinnacle/*.jsonl")
    status = json.load(open("records/status.json", encoding="utf-8")) if os.path.exists("records/status.json") else {}
    t_nes, nes_last = latest_snapshot(nes_rows)
    t_pin, pin_last = latest_snapshot(pin_rows)
    now = datetime.now(timezone.utc)
    nm = [m for m in nesine_matches(nes_last) if m["start"] > now]
    events = pinnacle_events(pin_last)
    aliases = json.load(open("aliases.json", encoding="utf-8")) if os.path.exists("aliases.json") else {}
    pairs = match.match_all(nm, events, aliases)
    nes_age = int((now - datetime.fromisoformat(t_nes)).total_seconds() // 60) if t_nes else None
    pin_age = int((now - datetime.fromisoformat(t_pin)).total_seconds() // 60) if t_pin else None

    all_bets, cards, n_matched = [], [], 0
    for m, ev, score in pairs:
        if not ev:
            continue
        h2h = odds.pinnacle_h2h(ev)
        if not h2h:
            continue
        n_matched += 1
        probs = prob.market_probs(h2h, odds.pinnacle_totals(ev))
        for b in value.evaluate(m, probs, h2h, bankroll=100.0, threshold=None):  # kasa=100 → stake = yüzde
            all_bets.append(b)
            if b["ev_pct"] >= value.EV_THRESHOLD and b["nesine_odds"] < value.MAX_ODDS:
                cards.append(b)
    all_bets.sort(key=lambda x: -x["ev_pct"])
    cards.sort(key=lambda x: -x["ev_pct"])
    changes, n_series = nesine_changes(nes_rows)
    n_snapshots = len({r["t"] for r in nes_rows})
    stale = pin_age is None or pin_age > 10
    avg_ev = sum(b["ev_pct"] for b in all_bets) / len(all_bets) if all_bets else 0
    best = all_bets[0] if all_bets else None

    # --- hero
    if cards:
        verdict = f'<em>{len(cards)} fırsat</em> var.' if len(cards) > 1 else '<em>1 fırsat</em> var.'
    else:
        verdict = 'Şu an oynanacak<br><em>fırsat yok.</em>'
    live = nes_age is not None and nes_age <= 45
    sub = (f'<span class="pulse{"" if live else " off"}"></span>Nesine oranları en son <b>{ago(nes_age)}</b> kontrol edildi'
           f'{"" if live else " — kayıt gecikmiş olabilir"}. Dünya piyasası verisi <b>{ago(pin_age)}</b> alındı.')
    if stale:
        sub += ' Bu, <b>deneme aşaması</b>: para oynanmıyor, sadece ölçüyoruz.'
    facts = f"""
<ul class="facts">
  <li><div class="n">{len(nm)}</div><div class="l">yaklaşan maç takipte</div></li>
  <li><div class="n">{n_matched}</div><div class="l">dünya piyasasıyla karşılaştırılan</div></li>
  <li><div class="n">{avg_ev:+.0f}%</div><div class="l">Nesine oranı ortalama bu kadar düşük</div></li>
  <li><div class="n">{len(changes)}</div><div class="l">oran değişimi yakalandı</div></li>
</ul>"""

    # --- kartlar
    if cards:
        cards_html = "".join(coupon_html(b, i, stale) for i, b in enumerate(cards))
    else:
        best_txt = (f' En yakını <b>{esc(best["home"])} – {esc(best["away"])}</b>, {PICK_TR.get((best["market"], best["pick"]), best["pick"]).lower()}: '
                    f'Nesine {best["nesine_odds"]:.2f} veriyor, adil oran {best["fair_odds"]:.2f}; yani hâlâ %{abs(best["ev_pct"]):.1f} geride.' if best else "")
        cards_html = f'<div class="empty"><b>Hiçbir maçta Nesine, dünya piyasasından yüksek oran vermiyor.</b> Bu normaldir; fırsat haber çıkıp dünya piyasası hareket ettiğinde, Nesine geç kaldığında doğar.{best_txt}</div>'

    # --- sayaç listesi
    rows_html = ""
    for b in all_bets[:12]:
        cls = "hit" if b["ev_pct"] >= value.EV_THRESHOLD else ""
        rows_html += (f'<li class="row {cls}"><div class="m"><div class="t">{esc(b["home"])} – {esc(b["away"])}</div>'
                      f'<div class="d">{esc(PICK_TR.get((b["market"], b["pick"]), b["pick"]))} · Nesine <code>{b["nesine_odds"]:.2f}</code> · adil <code>{b["fair_odds"]:.2f}</code></div></div>'
                      f'{meter(b["ev_pct"])}<div class="v">{b["ev_pct"]:+.1f}%</div></li>')

    # --- değişimler
    ch_html = ""
    for c in changes[:20]:
        direction = "up" if c["new"] > c["old"] else "down"
        arrow = "▲" if direction == "up" else "▼"
        ch_html += (f'<li><time>{tr_time(c["t"])}</time><div>{esc(c["home"])} – {esc(c["away"])} '
                    f'<small>· {PICK_TR.get((c["market"], c["outcome"]), c["outcome"]).lower()} · maça {c["mins_before"]//60} sa {c["mins_before"]%60} dk kala</small></div>'
                    f'<div class="o {direction}">{c["old"]:.2f} {arrow} {c["new"]:.2f}</div></li>')
    if changes:
        up = sum(1 for c in changes if c["new"] > c["old"])
        ch_lead = (f'<b>{n_snapshots} kontrolde {len(changes)} oran değişimi</b> gördük ({up} yükseliş, {len(changes)-up} düşüş). '
                   'Oranlar hareket ediyor; sorumuz, dünya piyasasından ne kadar <b>geç</b> hareket ettiği. Veri biriktikçe cevap netleşecek.')
    else:
        ch_lead = "Henüz oran değişimi görmedik; kayıtlar birikiyor."

    return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>İddia Bot</title>
<meta name="description" content="Nesine oranlarını dünya piyasasıyla karşılaştıran deneme sayfası.">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=Source+Sans+3:wght@400;600&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body><div class="wrap">
<header><div class="brand">İddia Bot<small>Nesine oranı dünya piyasasından yüksek mi?</small></div>
<div class="brand" style="color:var(--chalk-dim);font-size:15px;font-weight:600">{tr_time(now)} TSİ</div></header>

<section class="hero">
  <h1 class="verdict">{verdict}</h1>
  <p class="sub">{sub}</p>
  {facts}
</section>

<h2>Fırsatlar</h2>
<p class="lead">Fırsat demek için üç şart: Nesine oranı adil orandan en az <b>%3</b> yüksek, oran <b>3.00'ın altında</b> (sürprizlerde "değer" yanıltıcı çıkıyor) ve dünya piyasası verisi <b>10 dakikadan taze</b>.</p>
{cards_html}

<h2>Eşiğe en yakın bahisler</h2>
<p class="lead">Her çubuk, Nesine oranının adil orana göre nerede durduğunu gösterir. Beyaz çizgi <b>+%3</b> eşiği; çubuk onu geçince yeşil yanar ve yukarıda kart olur.</p>
<ul class="list">{rows_html or '<li class="row"><div class="m"><div class="t">Henüz karşılaştırma yok.</div></div></li>'}</ul>
<div class="legend"><span><i style="background:#3E5A4D"></i>geride</span><span><i style="background:var(--sodium)"></i>yaklaşıyor (−%5 içinde)</span><span><i style="background:var(--signal)"></i>eşiği geçti</span></div>

<h2>İddaa oranları hareket ediyor mu?</h2>
<p class="lead">{ch_lead}</p>
<ul class="changes">{ch_html or '<li><time>—</time><div>Henüz değişim yok.</div></li>'}</ul>

<h2>Bu sayfa ne yapıyor?</h2>
<ul class="steps">
  <li><b>1 · Dünya piyasasını okur</b><p>Pinnacle, dünyanın en keskin bahis borsası sayılır: oranları milyonlarca dolarlık parayla saniyeler içinde düzelir. Onu "gerçek ihtimal" ölçütü olarak kullanıyoruz; orada hesabımız yok.</p></li>
  <li><b>2 · Nesine ile karşılaştırır</b><p>Her maçta Nesine'nin oranı, Pinnacle'dan çıkan adil oranla yan yana konur. Nesine daha yüksek veriyorsa fark bizim lehimize: buna "değer" diyoruz.</p></li>
  <li><b>3 · Sadece matematiğe güvenir</b><p>Tahmin yok, his yok. Geçmiş 5.000 maçta test edildi: değer, 3.00 altı oranlarda gerçek; sürprizlerde yanıltıcı. Şimdi para koymadan canlı ölçüyoruz.</p></li>
</ul>

<footer>Sayfa her 20 dakikada otomatik yenilenir; yatırım tavsiyesi değildir. Gerçekçi hedef: uzun vadede yatırılan paranın %2–5'i. Fırsatsız günler normaldir.
<br>Kaynak kod: <a href="https://github.com/boradmir/iddia-bot">github.com/boradmir/iddia-bot</a></footer>
</div></body></html>"""


if __name__ == "__main__":
    os.makedirs("docs", exist_ok=True)
    page = build()
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(page)
    print(f"docs/index.html yazıldı ({len(page)} bayt)")
