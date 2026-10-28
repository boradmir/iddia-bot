"""GitHub Pages sayfasını üretir: records/ içindeki kayıtlardan docs/index.html.

API çağrısı yapmaz, kota harcamaz. Herkese açık sayfa olduğu için kişisel hiçbir bilgi içermez;
yatırım tutarı TL değil kasa yüzdesi olarak gösterilir. Teknik olmayan okuyucu için yazılmıştır.

Bölümler: durum · uyarılar (gözcü) · fırsat kartları · kupon önerileri · yaklaşan maçlar (üç görüş + neden)
          · eşiğe en yakın bahisler · Nesine oran değişimleri · nasıl çalışır
"""
import glob, html, json, os, collections
from datetime import datetime, timezone, timedelta
import match, odds, prob, value, stats, coupons

TR = timezone(timedelta(hours=3))
RECORD_COUPONS = False   # build_site.py --record-coupons ile açılır (yalnızca kayıtçı iş akışı)
MARKET_TR = {"MS": "Maç sonucu", "AU25": "2.5 gol alt/üst", "KG": "Karşılıklı gol"}
PICK_TR = {("MS", "1"): "Ev sahibi kazanır", ("MS", "X"): "Beraberlik", ("MS", "2"): "Deplasman kazanır",
           ("AU25", "Alt"): "2 veya daha az gol", ("AU25", "Üst"): "3 veya daha fazla gol",
           ("KG", "Var"): "İki takım da gol atar", ("KG", "Yok"): "En az bir takım gol atamaz"}
PICK_SHORT = {("MS", "1"): "Ev", ("MS", "X"): "Beraberlik", ("MS", "2"): "Deplasman",
              ("AU25", "Alt"): "2.5 Alt", ("AU25", "Üst"): "2.5 Üst", ("KG", "Var"): "KG Var", ("KG", "Yok"): "KG Yok"}
METER_MIN, METER_MAX = -25.0, 8.0
DAYS = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]


# ----------------------------------------------------------------- veri
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
    by = {}
    for r in rows:
        m = by.setdefault(r["code"], {"code": r["code"], "home": r["home"], "away": r["away"], "league": r["league"],
                                      "sport_key": r["sport"], "start": datetime.fromisoformat(r["start"]), "mbs": r["mbs"], "markets": {}})
        m["markets"].setdefault(r["market"], {"odds": {}, "mbs": r["mbs"]})["odds"][r["outcome"]] = r["price"]
    return list(by.values())


def pinnacle_events(rows):
    """Her maç için EN SON kayıt (gözcü aynı güne birden çok kez yazar)."""
    by = {}
    for r in rows:
        ev = by.setdefault(r["event_id"], {"id": r["event_id"], "sport_key": r["sport"], "commence_time": r["start"],
                                           "home_team": r["home"], "away_team": r["away"], "_t": r["t"], "_mk": {}})
        if r["t"] > ev["_t"]:
            ev["_t"] = r["t"]; ev["_mk"] = {}
        if r["t"] == ev["_t"]:
            name = {"home": r["home"], "away": r["away"], "draw": "Draw", "over": "Over", "under": "Under"}.get(r["outcome"], r["outcome"])
            ev["_mk"].setdefault(r["market"], []).append({"name": name, "price": r["price"], "point": r.get("point")})
    out = []
    for ev in by.values():
        ev["bookmakers"] = [{"key": "pinnacle", "markets": [{"key": k, "outcomes": v} for k, v in ev.pop("_mk").items()]}]
        ev["fetched_at"] = ev.pop("_t")
        out.append(ev)
    return out


def nesine_changes(rows):
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


# ----------------------------------------------------------------- yardımcı
def tr_time(dt, day=False):
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    dt = dt.astimezone(TR)
    return (DAYS[dt.weekday()] + " " if day else "") + dt.strftime("%d.%m %H:%M")


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


def pct(p):
    return f"%{p*100:.0f}"


def meter(ev_pct):
    x = max(METER_MIN, min(METER_MAX, ev_pct))
    width = 100 * (x - METER_MIN) / (METER_MAX - METER_MIN)
    cls = "hit" if ev_pct >= value.EV_THRESHOLD else ("near" if ev_pct >= -5 else "")
    return f'<div class="meter {cls}"><div class="bar" style="--w:{width:.1f}%"></div><div class="tick"></div></div>'


def form_line(name, f):
    if not f:
        return f"{esc(name)}: yeterli geçmiş maç yok."
    return (f"<b>{esc(name)}</b> son {f['n']} maçta: {f['wins']} galibiyet, maç başı {f['gf']:.1f} gol attı / {f['ga']:.1f} yedi, "
            f"KG %{f['btts_pct']:.0f}, 3+ gol %{f['over25_pct']:.0f}.")


# ----------------------------------------------------------------- CSS
CSS = """
:root{--pitch:#0B1F17;--pitch-2:#102A20;--line:#1E3A2E;--chalk:#F2F5F0;--chalk-dim:#A9B8AF;--sodium:#F5C04A;
--paper:#FBF7EA;--ink:#1B1B1B;--ink-dim:#6B665C;--signal:#2ED47A;--ember:#F08A4B;--rule:#E5DCC3}
*{box-sizing:border-box}
html{background:var(--pitch)}
body{margin:0;font-family:"Source Sans 3",system-ui,sans-serif;font-size:17px;line-height:1.5;color:var(--chalk);
background:radial-gradient(1200px 600px at 50% -200px,#1B4A36 0%,var(--pitch) 60%)}
.wrap{max-width:900px;margin:0 auto;padding:0 20px 80px}
header{padding:40px 0 8px;display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap}
.brand{font-family:"Barlow Condensed",sans-serif;font-weight:600;font-size:22px;letter-spacing:.08em;text-transform:uppercase;color:var(--sodium)}
.brand small{display:block;font-family:"Source Sans 3",sans-serif;font-weight:400;font-size:14px;letter-spacing:0;text-transform:none;color:var(--chalk-dim)}
nav{display:flex;gap:6px 16px;flex-wrap:wrap;font-size:14.5px;margin:6px 0 0}
nav a{color:var(--chalk-dim);text-decoration:none;border-bottom:1px solid transparent}
nav a:hover,nav a:focus{color:var(--sodium);border-color:var(--sodium)}
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
h2 small{font-family:"Source Sans 3",sans-serif;font-size:14px;letter-spacing:0;color:var(--chalk-dim);font-weight:400;margin-left:8px}
.lead{margin:0 0 18px;color:var(--chalk-dim)}
.lead b{color:var(--chalk);font-weight:600}
.note{background:rgba(245,192,74,.08);border-left:3px solid var(--sodium);padding:10px 14px;border-radius:0 8px 8px 0;color:var(--chalk-dim);font-size:15px;margin:0 0 18px}
.note b{color:var(--chalk)}
.plain{margin:0 0 12px;color:var(--chalk-dim);font-size:15.5px;line-height:1.55}
.plain b{color:var(--chalk)}
.sub .plain{display:block;margin-top:10px;font-size:15.5px}
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
.coupon dd.good{color:#117A45}.coupon dd.bad{color:#9A4F12}
.coupon .status{margin-top:12px;padding-top:10px;border-top:1px dashed var(--rule);font-size:14.5px;color:var(--ink-dim)}
.coupon .status.warn{color:#9A4F12}
.coupon .why{margin-top:10px;font-size:14.5px;color:var(--ink-dim)}
.coupon .why b{color:var(--ink)}
.coupon .legs{list-style:none;margin:0 0 10px;padding:0;font-size:15.5px}
.coupon .legs li{display:grid;grid-template-columns:1fr auto auto;gap:10px;padding:5px 0;border-bottom:1px dotted var(--rule)}
.coupon .legs .p{font-family:"JetBrains Mono",monospace;color:var(--ink-dim)}
.coupon .legs .o{font-family:"JetBrains Mono",monospace;font-weight:600}
.coupon .legs small{display:block;color:var(--ink-dim);font-size:13px}
.coupon .title{font-family:"Barlow Condensed",sans-serif;font-weight:700;font-size:22px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:14px}
.grid .coupon{margin:8px 0}
.empty{background:var(--pitch-2);border:1px dashed var(--line);border-radius:10px;padding:20px 22px;color:var(--chalk-dim)}
.empty b{color:var(--chalk)}
/* değer sayacı */
.list{list-style:none;margin:0;padding:0}
.row{display:grid;grid-template-columns:1fr 150px 64px;gap:14px;align-items:center;padding:11px 0;border-bottom:1px solid var(--line)}
.row .m{min-width:0}
.row .t{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.row .d{font-size:14px;color:var(--chalk-dim)}
.row .d code{font-family:"JetBrains Mono",monospace;font-size:13px;color:var(--chalk)}
.row .v{font-family:"JetBrains Mono",monospace;font-size:15px;text-align:right;color:var(--chalk-dim)}
.row.hit .v{color:var(--signal);font-weight:700}
.meter{position:relative;height:10px;background:#0A1812;border-radius:5px}
.meter .bar{height:100%;width:0;border-radius:5px;background:#3E5A4D;animation:grow 1.1s cubic-bezier(.2,.7,.2,1) forwards}
.meter.near .bar{background:var(--sodium)}
.meter.hit .bar{background:var(--signal)}
.meter .tick{position:absolute;top:-4px;bottom:-4px;width:2px;background:var(--chalk);opacity:.7;left:calc(100% * (3 - (-25)) / (8 - (-25)))}
@keyframes grow{to{width:var(--w)}}
.legend{display:flex;gap:18px;flex-wrap:wrap;font-size:13.5px;color:var(--chalk-dim);margin:10px 0 0}
.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}
/* maç detayları: üç görüş */
details.match{background:var(--pitch-2);border:1px solid var(--line);border-radius:10px;margin:10px 0;overflow:hidden}
details.match summary{list-style:none;cursor:pointer;display:grid;grid-template-columns:110px 1fr auto;gap:12px;padding:12px 16px;align-items:center}
details.match summary::-webkit-details-marker{display:none}
details.match summary time{font-family:"JetBrains Mono",monospace;font-size:13px;color:var(--chalk-dim)}
details.match summary .tm{font-weight:600}
details.match summary .lg{font-size:13px;color:var(--chalk-dim)}
details.match summary .tag{font-size:12.5px;padding:3px 8px;border-radius:999px;background:#0A1812;color:var(--chalk-dim);white-space:nowrap}
details.match summary .tag.hit{background:rgba(46,212,122,.15);color:var(--signal)}
details.match summary .tag.miss{background:rgba(240,138,75,.15);color:var(--ember)}
.plainlegs{list-style:none;margin:0;padding:0}.plainlegs li{display:grid;grid-template-columns:1fr auto auto;gap:10px;padding:6px 0;border-bottom:1px solid var(--line);font-size:15px}.plainlegs small{display:block;color:var(--chalk-dim);font-size:13px}.plainlegs .o{font-family:"JetBrains Mono",monospace}
.facts .good{color:var(--signal)}.facts .bad{color:var(--ember)}
details.match[open] summary{border-bottom:1px solid var(--line)}
.views{padding:12px 16px 16px}
.views table{width:100%;border-collapse:collapse;font-size:15px}
.views th{font-weight:600;color:var(--chalk-dim);font-size:13px;text-align:right;padding:6px 8px;border-bottom:1px solid var(--line)}
.views th:first-child,.views td:first-child{text-align:left}
.views td{padding:6px 8px;text-align:right;font-family:"JetBrains Mono",monospace;font-size:14px;border-bottom:1px solid rgba(30,58,46,.5)}
.views td:first-child{font-family:"Source Sans 3",sans-serif;font-size:15px}
.views td.good{color:var(--signal);font-weight:600}
.views td.dim{color:var(--chalk-dim)}
.views .why{margin:12px 0 0;font-size:14.5px;color:var(--chalk-dim)}
.views .why b{color:var(--chalk)}
.views .acc{margin:10px 0 0;font-size:13px;color:var(--chalk-dim)}
.claudebox{margin:12px 0 0;padding:12px 14px;border-radius:8px;background:rgba(245,192,74,.07);border:1px solid rgba(245,192,74,.25);font-size:15px}
.claudebox p{margin:6px 0 0}.claudebox ul{margin:8px 0 0;padding-left:18px;color:var(--chalk-dim);font-size:14px}.claudebox .muted{color:var(--chalk-dim);font-size:13px}
.coupon .claudebox{background:#F3EBD3;border-color:#E0D2A6;color:var(--ink)}.coupon .claudebox ul{color:var(--ink-dim)}
/* uyarılar */
.alerts{list-style:none;margin:0;padding:0}
.alerts li{display:grid;grid-template-columns:90px 1fr auto;gap:12px;padding:10px 0;border-bottom:1px solid var(--line);align-items:baseline}
.alerts time{font-family:"JetBrains Mono",monospace;font-size:13px;color:var(--chalk-dim)}
.alerts .r{font-family:"JetBrains Mono",monospace;font-size:14px;text-align:right}
.alerts .r.good{color:var(--signal)}.alerts .r.bad{color:var(--ember)}
.alerts small{display:block;color:var(--chalk-dim);font-size:13.5px}
/* değişimler */
.changes{list-style:none;margin:0;padding:0}
.changes li{display:grid;grid-template-columns:72px 1fr auto;gap:12px;padding:9px 0;border-bottom:1px solid var(--line);font-size:15.5px;align-items:baseline}
.changes time{font-family:"JetBrains Mono",monospace;font-size:13px;color:var(--chalk-dim)}
.changes .o{font-family:"JetBrains Mono",monospace;white-space:nowrap}
.changes .o.up{color:var(--signal)}.changes .o.down{color:var(--ember)}
.changes small{color:var(--chalk-dim)}
.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px;margin:0;padding:0;list-style:none}
.steps li{background:var(--pitch-2);border:1px solid var(--line);border-radius:10px;padding:16px 18px}
.steps b{display:block;font-family:"Barlow Condensed",sans-serif;font-size:22px;font-weight:600;margin-bottom:4px}
.steps p{margin:0;color:var(--chalk-dim);font-size:15.5px}
footer{margin-top:56px;padding-top:18px;border-top:1px solid var(--line);color:var(--chalk-dim);font-size:14px}
footer a{color:var(--sodium)}
@media (max-width:560px){.row{grid-template-columns:1fr 100px 56px}.changes li,.alerts li{grid-template-columns:60px 1fr}.changes .o,.alerts .r{grid-column:2}
details.match summary{grid-template-columns:1fr auto}details.match summary time{grid-column:1/-1}}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}.verdict,.sub,.facts,.coupon{opacity:1;transform:none}.meter .bar{width:var(--w)}}
"""


# ----------------------------------------------------------------- kupon defteri
COUPON_DIR = "records/coupons"
KIND_TR = {"safest": "En güvenli", "least_loss": "En az kayıplı", "value": "Değerli"}


def coupon_key(kind, c):
    legs = sorted((b["code"], b["market"], b["pick"]) for b in c["legs"])
    first_day = min(b["start"] for b in c["legs"]).astimezone(TR).strftime("%Y-%m-%d")
    return f"{kind}:{c['n']}:{first_day}"


def record_coupons(cps, now):
    """Önerilen kuponları ilk görüldükleri anda kilitler (o an oynanmış gibi). Tür+maç sayısı+gün başına bir kez."""
    existing = {c["key"] for c in read_jsonl(f"{COUPON_DIR}/*.jsonl")}
    new = []
    items = [("value", cps["value"])] if cps.get("value") else []
    items += [("safest", c) for c in cps.get("safest", [])] + [("least_loss", c) for c in cps.get("least_loss", [])]
    for kind, c in items:
        k = coupon_key(kind, c)
        if k in existing:
            continue
        existing.add(k)
        new.append({"key": k, "t": now.isoformat(timespec="seconds"), "kind": kind, "n": c["n"], "odds": round(c["odds"], 2),
                    "prob": round(c["prob"], 4), "ev_pct": round(c["ev_pct"], 1), "result": None,
                    "legs": [{"code": b["code"], "home": b["home"], "away": b["away"], "league": b["league"], "sport": b.get("sport_key"),
                              "start": b["start"].isoformat(), "market": b["market"], "pick": b["pick"], "odds": b["nesine_odds"],
                              "prob": round(b["fair_prob"], 4)} for b in c["legs"]]})
    if new:
        os.makedirs(COUPON_DIR, exist_ok=True)
        with open(f"{COUPON_DIR}/{now:%Y-%m-%d}.jsonl", "a", encoding="utf-8") as f:
            for c in new:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
    return len(new)


def past_coupons_html(rows):
    rows = sorted(rows, key=lambda c: c["t"], reverse=True)
    settled = [c for c in rows if c.get("result") in ("won", "lost")]
    # tür başına özet
    summ = ""
    for kind in ("safest", "least_loss", "value"):
        ks = [c for c in settled if c["kind"] == kind]
        if not ks:
            continue
        won = sum(1 for c in ks if c["result"] == "won")
        pnl = sum((c["odds"] - 1) if c["result"] == "won" else -1 for c in ks)
        summ += (f'<li><div class="n">{won}/{len(ks)}</div><div class="l">{KIND_TR[kind]} kupon tuttu (%{100*won/len(ks):.0f}) · '
                 f'1 birimle oynansa net <b class="{"good" if pnl >= 0 else "bad"}">{pnl:+.1f}</b></div></li>')
    summ = f'<ul class="facts" style="animation:none;opacity:1">{summ}</ul>' if summ else         '<p class="lead">Henüz sonuçlanmış kupon yok. Kuponlar önerildikleri anda kilitlenir, maçlar bitince burada puanlanır.</p>'
    items = ""
    for c in rows[:30]:
        res = c.get("result")
        tag = ('<span class="tag hit">tuttu ✓</span>' if res == "won" else '<span class="tag miss">tutmadı ✗</span>' if res == "lost"
               else f'<span class="tag">bekliyor · {c.get("legs_hit", 0)}/{c["n"]} tuttu</span>')
        legs = "".join(f'<li><div>{esc(l["home"])} – {esc(l["away"])}<small>{esc(PICK_SHORT.get((l["market"], l["pick"]), l["pick"]))} · {tr_time(l["start"], day=True)}'
                       f'{(" · skor " + l["score"]) if l.get("score") else ""}</small></div>'
                       f'<div class="p">{"✓" if l.get("result") == "won" else "✗" if l.get("result") == "lost" else "…"}</div><div class="o">{l["odds"]:.2f}</div></li>' for l in c["legs"])
        items += f"""<details class="match"><summary><time>{tr_time(c['t'], day=True)}</time><div><div class="tm">{KIND_TR.get(c['kind'], c['kind'])} · {c['n']} maç · oran {c['odds']:.2f}</div>
<div class="lg">gelme ihtimali %{c['prob']*100:.0f} · beklenen değer {c['ev_pct']:+.0f}%</div></div>{tag}</summary>
<div class="views"><ul class="legs plainlegs">{legs}</ul></div></details>"""
    return summ + (items or "")


# ----------------------------------------------------------------- parçalar
def coupon_card(b, i, stale, sv, cr=None):
    ok = not stale
    status = ('<div class="status">✅ Oynanabilir: değer eşiğin üstünde, dünya piyasası verisi güncel.</div>' if ok else
              '<div class="status warn">⏸ Şimdilik sadece izliyoruz: dünya piyasası verisi eski, deneme aşamasındayız.</div>')
    mbs = f" · tek başına oynanamaz (en az {b['mbs']} maç)" if b["mbs"] > 1 else ""
    why = ""
    if sv:
        sp = sv["probs"][b["market"]][b["pick"]]
        why = (f'<div class="why"><b>İstatistik görüşü:</b> {pct(sp)} (takım geçmişinden). '
               f'{form_line(b["home"], sv["home_form"])} {form_line(b["away"], sv["away_form"])}</div>')
    return f"""
<article class="coupon" style="animation-delay:{.55 + i*.12:.2f}s">
  <div class="top"><div class="teams">{esc(b['home'])}<br>{esc(b['away'])}</div>
  <div class="meta">{tr_time(b['start'], day=True)}<br>{esc(b['league'])}<br>Nesine kodu {b['code']}{esc(mbs)}</div></div>
  <p class="pick">{esc(PICK_TR.get((b['market'], b['pick']), b['pick']))}<small>{MARKET_TR[b['market']]}</small></p>
  <dl>
    <dt>Nesine'nin verdiği oran</dt><dd>{b['nesine_odds']:.2f}</dd>
    <dt>Dünya piyasasına göre gerçek ihtimal</dt><dd>{pct(b['fair_prob'])}</dd>
    <dt>Bu ihtimale denk gelen adil oran</dt><dd>{b['fair_odds']:.2f}</dd>
    <dt>Nesine'nin fazladan verdiği</dt><dd class="good">+%{b['ev_pct']:.1f}</dd>
    <dt>Önerilen yatırım</dt><dd>kasanın %{b['stake']:.1f}'i</dd>
  </dl>
  {why}
  {claude_box(cr)}
  {status}
</article>"""


def combo_card(title, c, i, kind):
    if not c:
        return ""
    loss = -c["ev_pct"]
    ev_cls = "good" if c["ev_pct"] >= 0 else "bad"
    legs = "".join(f'<li><div>{esc(b["home"])} – {esc(b["away"])}<small>{esc(PICK_SHORT.get((b["market"], b["pick"]), b["pick"]))} · {tr_time(b["start"], day=True)}</small></div>'
                   f'<div class="p">{pct(b["fair_prob"])}</div><div class="o">{b["nesine_odds"]:.2f}</div></li>' for b in c["legs"])
    verdict = (f"Uzun vadede bu kupona yatırılan her 100 TL'nin yaklaşık <b>{loss:.0f} TL'si kaybedilir</b>." if c["ev_pct"] < 0 else
               f"Beklenen değer artı: 100 TL'ye yaklaşık <b>{c['ev_pct']:.0f} TL kazanç</b> beklenir.")
    return f"""
<article class="coupon" style="animation-delay:{.4 + i*.1:.2f}s">
  <div class="top"><div class="title">{title}</div><div class="meta">{c['n']} maç · {kind}</div></div>
  <ul class="legs">{legs}</ul>
  <dl>
    <dt>Toplam oran</dt><dd>{c['odds']:.2f}</dd>
    <dt>Gelme ihtimali</dt><dd>{pct(c['prob'])}</dd>
    <dt>Bu ihtimale denk adil oran</dt><dd>{c['fair_odds']:.2f}</dd>
    <dt>Beklenen değer</dt><dd class="{ev_cls}">{c['ev_pct']:+.0f}%</dd>
  </dl>
  <div class="status{' warn' if c['ev_pct'] < 0 else ''}">{verdict}</div>
</article>"""


def claude_prob(cr, mk, pick):
    if not cr:
        return None
    bl = cr["blind"]
    return {("MS", "1"): bl["p_home"], ("MS", "X"): bl["p_draw"], ("MS", "2"): bl["p_away"],
            ("AU25", "Üst"): bl["p_over25"], ("AU25", "Alt"): 1 - bl["p_over25"],
            ("KG", "Var"): bl["p_btts"], ("KG", "Yok"): 1 - bl["p_btts"]}.get((mk, pick))


def claude_box(cr):
    if not cr:
        return ""
    bl = cr["blind"]; ob = cr.get("objection") or {}
    facts = "".join(f"<li>{esc(x)}</li>" for x in bl.get("facts", [])[:5])
    verdict = ('<span class="tag hit">piyasaya itiraz yok ✓</span>' if ob.get("verdict") == "ok" else
               '<span class="tag miss">⚠ itiraz var</span>' if ob.get("verdict") == "warn" else "")
    html_ = (f'<div class="claudebox"><b>Claude ne diyor?</b> {verdict}<p>{esc(bl.get("comment", ""))}</p>'
             f'<p><b>Risk:</b> {esc(bl.get("risk", ""))} <span class="muted">(güven: {esc(bl.get("confidence", ""))})</span></p>')
    if ob.get("verdict") == "warn":
        html_ += f'<p><b>İtiraz gerekçesi:</b> {esc(ob.get("reason", ""))}</p>'
    html_ += (f"<ul>{facts}</ul>" if facts else '<p class="muted">Somut haber bulunamadı.</p>') + "</div>"
    return html_


def match_details(m, h2h_probs, sv, bets_by_code, cr=None):
    bets = bets_by_code.get(m["code"], [])
    best = max(bets, key=lambda b: b["ev_pct"]) if bets else None
    tag = (f'<span class="tag hit">+%{best["ev_pct"]:.1f} değer</span>' if best and best["ev_pct"] >= value.EV_THRESHOLD
           else f'<span class="tag">en iyisi {best["ev_pct"]:+.1f}%</span>' if best else '<span class="tag">karşılaştırma yok</span>')
    rows = ""
    for mk in ("MS", "AU25", "KG"):
        if mk not in m["markets"]:
            continue
        for pick, o in m["markets"][mk]["odds"].items():
            pm = h2h_probs.get(mk, {}).get(pick) if h2h_probs else None
            ps = sv["probs"][mk][pick] if sv else None
            pc = claude_prob(cr, mk, pick)
            ev = (o * pm - 1) * 100 if pm else None
            ev_cls = "good" if ev is not None and ev >= value.EV_THRESHOLD else ""
            agree = pm is not None and pc is not None and abs(pm - pc) <= 0.05
            pc_cls = "good" if agree else ("dim" if pc is None else "")
            rows += (f'<tr><td>{esc(PICK_TR.get((mk, pick), pick))}</td><td>{o:.2f}</td>'
                     f'<td>{pct(pm) if pm is not None else "—"}</td><td>{pct(ps) if ps is not None else "—"}</td>'
                     f'<td class="{pc_cls}">{pct(pc) if pc is not None else "—"}{" ✓" if agree else ""}</td>'
                     f'<td class="{ev_cls}">{f"{ev:+.1f}%" if ev is not None else "—"}</td></tr>')
    why = (f'<p class="why">{form_line(m["home"], sv["home_form"])} {form_line(m["away"], sv["away_form"])}</p>' if sv else
           '<p class="why">Bu lig için takım geçmişi verisi yok (Avrupa kupaları ve milli maçlar). İstatistik görüşü boş.</p>')
    mbs = f' · <span class="tag">en az {m["mbs"]} maçla oynanır</span>' if m["mbs"] > 1 else ""
    cbox = claude_box(cr)
    return f"""
<details class="match"><summary><time>{tr_time(m['start'], day=True)}</time><div><div class="tm">{esc(m['home'])} – {esc(m['away'])}</div><div class="lg">{esc(m['league'])}{mbs}</div></div>{tag}</summary>
<div class="views"><table><tr><th>Bahis</th><th>Nesine</th><th>Piyasa</th><th>İstatistik</th><th>Claude</th><th>Değer</th></tr>{rows}</table>
{why}
{cbox}
<p class="acc">İsabet geçmişi (5.200 maç): <b>piyasa</b> ±2 puan kalibre · <b>istatistik</b> piyasadan daha az isabetli, tek başına izlenirse geçmişte −12% · <b>Claude</b> henüz ölçülmedi (✓ = piyasayla 5 puan içinde uyuşuyor).</p>
</div></details>"""


# ----------------------------------------------------------------- sayfa
def build():
    nes_rows = read_jsonl("records/nesine/*.jsonl")
    pin_rows = read_jsonl("records/pinnacle/*.jsonl")
    alerts = read_jsonl("records/alerts/*.jsonl")
    claude_rows = {r["code"]: r for r in read_jsonl("records/claude/*.jsonl") if r.get("blind")}
    status = json.load(open("records/status.json", encoding="utf-8")) if os.path.exists("records/status.json") else {}
    watch = json.load(open("records/watch_status.json", encoding="utf-8")) if os.path.exists("records/watch_status.json") else {}
    t_nes, nes_last = latest_snapshot(nes_rows)
    now = datetime.now(timezone.utc)
    nm = sorted([m for m in nesine_matches(nes_last) if m["start"] > now], key=lambda m: m["start"])
    events = pinnacle_events(pin_rows)
    aliases = json.load(open("aliases.json", encoding="utf-8")) if os.path.exists("aliases.json") else {}
    pairs = match.match_all(nm, events, aliases)
    nes_age = int((now - datetime.fromisoformat(t_nes)).total_seconds() // 60) if t_nes else None
    t_pin = max((e["fetched_at"] for e in events), default=None)
    pin_age = int((now - datetime.fromisoformat(t_pin)).total_seconds() // 60) if t_pin else None

    st = stats.Stats().load()
    all_bets, cards, n_matched = [], [], 0
    probs_by_code, sv_by_code, bets_by_code = {}, {}, collections.defaultdict(list)
    for m, ev, score in pairs:
        sv_by_code[m["code"]] = st.view(m)
        if not ev:
            continue
        h2h = odds.pinnacle_h2h(ev)
        if not h2h:
            continue
        n_matched += 1
        probs = prob.market_probs(h2h, odds.pinnacle_totals(ev))
        probs_by_code[m["code"]] = probs
        ev_age = int((now - datetime.fromisoformat(ev["fetched_at"])).total_seconds() // 60)
        for b in value.evaluate(m, probs, h2h, bankroll=100.0, threshold=None):
            b["pin_age"] = ev_age
            all_bets.append(b); bets_by_code[m["code"]].append(b)
            if b["ev_pct"] >= value.EV_THRESHOLD and b["nesine_odds"] < value.MAX_ODDS:
                cards.append(b)
    all_bets.sort(key=lambda x: -x["ev_pct"])
    cards.sort(key=lambda x: -x["ev_pct"])
    changes, n_series = nesine_changes(nes_rows)
    n_snapshots = len({r["t"] for r in nes_rows})
    stale = pin_age is None or pin_age > 10
    avg_ev = sum(b["ev_pct"] for b in all_bets) / len(all_bets) if all_bets else 0
    best = all_bets[0] if all_bets else None
    soon = [m for m in nm if m["start"] <= now + timedelta(hours=48)]
    soon_bets = [b for b in all_bets if b["start"] <= now + timedelta(hours=48)]
    cps = coupons.build_all(soon_bets)
    if RECORD_COUPONS:
        record_coupons(cps, now)
    past = read_jsonl(f"{COUPON_DIR}/*.jsonl")

    # --- hero
    verdict = (f'<em>{len(cards)} fırsat</em> var.' if cards else 'Şu an oynanacak<br><em>fırsat yok.</em>')
    live = nes_age is not None and nes_age <= 45
    sub = (f'<span class="pulse{"" if live else " off"}"></span>Nesine oranları en son <b>{ago(nes_age)}</b> kontrol edildi'
           f'{"" if live else " — kayıt gecikmiş olabilir"}. Dünya piyasası verisi <b>{ago(pin_age)}</b> alındı.')
    if watch.get("active"):
        sub += f' <b>Gözcü açık:</b> {esc(watch.get("note", ""))}'
    elif stale:
        sub += ' Şu an <b>deneme aşamasındayız</b>: para oynanmıyor, sadece ölçüyoruz.'
    sub += ("<br><span class=\"plain\">Kısaca: Bu sayfa, Nesine'nin verdiği oranı dünyadaki en iyi bahis borsasının oranıyla karşılaştırır. "
            "Nesine fazla veriyorsa \"fırsat\" der. Vermiyorsa (çoğu zaman) \"fırsat yok\" der.</span>")
    facts = f"""
<ul class="facts">
  <li><div class="n">{len(nm)}</div><div class="l">yaklaşan maç takipte</div></li>
  <li><div class="n">{n_matched}</div><div class="l">dünya piyasasıyla karşılaştırılan</div></li>
  <li><div class="n">{avg_ev:+.0f}%</div><div class="l">Nesine oranı ortalama bu kadar düşük</div></li>
  <li><div class="n">{len(alerts)}</div><div class="l">gözcü uyarısı (toplam)</div></li>
</ul>"""

    # --- uyarılar
    al_html = ""
    for a in sorted(alerts, key=lambda a: a["t"], reverse=True)[:20]:
        res = a.get("result")
        clv = a.get("clv_pct")
        r_txt = (f'{"kazandı" if res == "won" else "kaybetti" if res == "lost" else "iade"}' if res else "sonuç bekleniyor")
        r_cls = "good" if res == "won" else "bad" if res == "lost" else ""
        clv_txt = f" · kapanışa göre {clv:+.1f}%" if clv is not None else ""
        al_html += (f'<li><time>{tr_time(a["t"])}</time><div>{esc(a["home"])} – {esc(a["away"])}<small>{esc(PICK_TR.get((a["market"], a["pick"]), a["pick"]))} · '
                    f'Nesine {a["nesine_odds"]:.2f} · adil {a["fair_odds"]:.2f} · +%{a["ev_pct"]:.1f} · kasanın %{a["stake"]:.1f}\'i</small></div>'
                    f'<div class="r {r_cls}">{r_txt}{clv_txt}</div></li>')
    settled = [a for a in alerts if a.get("result") in ("won", "lost")]
    if settled:
        pnl = sum((a["nesine_odds"] - 1) if a["result"] == "won" else -1 for a in settled)
        clvs = [a["clv_pct"] for a in settled if a.get("clv_pct") is not None]
        al_lead = (f'<b>{len(settled)} sonuçlanmış uyarı</b>: 1 birimle oynansaydı net {pnl:+.1f} birim (ROI {100*pnl/len(settled):+.0f}%).'
                   + (f' Kapanış oranına göre ortalama <b>{sum(clvs)/len(clvs):+.1f}%</b> — bu, asıl ölçüt: artıysa yöntem çalışıyor.' if clvs else ''))
    else:
        al_lead = ('Gözcü, maç saatine yakın dünya piyasasını izler; Nesine geç kaldığında burada uyarı düşer. '
                   'Her uyarı sonradan maç sonucu ve kapanış oranıyla puanlanır. <b>Henüz uyarı yok.</b>')

    # --- kartlar
    if cards:
        cards_html = "".join(coupon_card(b, i, stale, sv_by_code.get(b["code"]), claude_rows.get(b["code"])) for i, b in enumerate(cards))
    else:
        best_txt = (f' En yakını <b>{esc(best["home"])} – {esc(best["away"])}</b>, {PICK_TR.get((best["market"], best["pick"]), best["pick"]).lower()}: '
                    f'Nesine {best["nesine_odds"]:.2f} veriyor, adil oran {best["fair_odds"]:.2f}; yani hâlâ %{abs(best["ev_pct"]):.1f} geride.' if best else "")
        cards_html = f'<div class="empty"><b>Hiçbir maçta Nesine, dünya piyasasından yüksek oran vermiyor.</b> Bu normaldir; fırsat haber çıkıp dünya piyasası hareket ettiğinde, Nesine geç kaldığında doğar.{best_txt}</div>'

    # --- kuponlar
    cp_html = ""
    if cps.get("value"):
        cp_html += combo_card("Değerli kupon", cps["value"], 0, "sadece eşik üstü maçlar")
    for i, c in enumerate(cps.get("safest", [])):
        cp_html += combo_card("En güvenli", c, i + 1, "en yüksek gelme ihtimali")
    for i, c in enumerate(cps.get("least_loss", [])):
        cp_html += combo_card("En az kayıplı", c, i + 4, "oran/ihtimal dengesi en iyi")
    cp_html = f'<div class="grid">{cp_html}</div>' if cp_html else '<div class="empty">Önümüzdeki 48 saatte kupon kuracak kadar karşılaştırılmış maç yok.</div>'

    # --- yaklaşan maçlar
    md_html = "".join(match_details(m, probs_by_code.get(m["code"]), sv_by_code.get(m["code"]), bets_by_code, claude_rows.get(m["code"])) for m in soon) or \
        '<div class="empty">Önümüzdeki 48 saatte takip edilen liglerde maç yok.</div>'

    # --- sayaç
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
                   'Oranlar hareket ediyor; sorumuz, dünya piyasasından ne kadar <b>geç</b> hareket ettiği.')
    else:
        ch_lead = "Henüz oran değişimi görmedik; kayıtlar birikiyor."

    return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>İddia Bot</title>
<meta name="description" content="Nesine oranlarını dünya piyasasıyla karşılaştıran deneme sayfası.">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=Source+Sans+3:wght@400;600&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body><div class="wrap">
<header><div><div class="brand">İddia Bot<small>Nesine oranı dünya piyasasından yüksek mi?</small></div>
<nav><a href="#uyarilar">Uyarılar</a><a href="#firsatlar">Fırsatlar</a><a href="#kuponlar">Kuponlar</a><a href="#gecmis">Geçmiş kuponlar</a><a href="#maclar">Maçlar</a><a href="#sayac">Sayaç</a><a href="#degisim">Oran hareketi</a><a href="#nasil">Nasıl çalışır</a></nav></div>
<div class="brand" style="color:var(--chalk-dim);font-size:15px;font-weight:600">{tr_time(now)} TSİ</div></header>

<section class="hero">
  <h1 class="verdict">{verdict}</h1>
  <p class="sub">{sub}</p>
  {facts}
</section>

<h2 id="uyarilar">Gözcü uyarıları <small>maç saatine yakın yakalananlar</small></h2>
<p class="plain"><b>Bu ne demek?</b> Maçtan 1-2 saat önce kadrolar açıklanır, sakatlıklar duyulur. Dünya piyasası bunu saniyeler içinde orana yansıtır; Nesine bazen geç kalır. "Gözcü", o anları yakalamak için maç saatine yakın sürekli bakar. Yakaladığında burada bir satır çıkar.</p>
<p class="lead">{al_lead}</p>
<ul class="alerts">{al_html or '<li><time>—</time><div>Henüz uyarı yok.</div></li>'}</ul>

<h2 id="firsatlar">Fırsatlar <small>şu anki kayıtlara göre</small></h2>
<p class="plain"><b>Bu ne demek?</b> Diyelim bir maçta ev sahibinin kazanma ihtimali gerçekte %50. Buna denk gelen "adil oran" 2.00'dır (100 ÷ 50). Nesine 2.10 veriyorsa, bize hak ettiğimizden fazla ödüyor demektir: işte "fırsat" bu. Nesine 1.85 veriyorsa (çoğu zaman öyle) fırsat yoktur.</p>
<p class="lead">Fırsat demek için üç şart: Nesine oranı adil orandan en az <b>%3</b> yüksek, oran <b>3.00'ın altında</b> (yüksek oranlı sürprizlerde bu hesap yanıltıyor, geçmiş veriyle gördük) ve dünya piyasası verisi <b>10 dakikadan taze</b>.</p>
{cards_html}

<h2 id="kuponlar">Kupon önerileri <small>önümüzdeki 48 saat, 3–5 maç</small></h2>
<p class="plain"><b>Bu ne demek?</b> Kombine = birkaç maçı tek kupona yazmak; hepsi tutmalı. Oranlar çarpılır ama ihtimaller de çarpılır: %70 ihtimalli 3 maç bir arada %34 eder. Nesine her maçtan payını aldığı için (buna "marj" denir) kombinede bu pay katlanır.</p>
<p class="note"><b>Açık konuşalım:</b> "En güvenli" kupon en sık tutan kupondur ama uzun vadede en çok kaybettiren de odur. Her kuponun altında 100 TL yatırsanız uzun vadede kaçının gideceği yazıyor. Karar sizin.</p>
{cp_html}

<h2 id="gecmis">Geçmiş kuponlar <small>önerilenler tuttu mu?</small></h2>
<p class="plain"><b>Bu ne demek?</b> Yukarıda önerilen her kupon, ilk göründüğü anda "kilitlenir": o an oynanmış sayılır. Maçlar bitince tuttu mu bakılır. Böylece "en güvenli" denen kuponun gerçekten kazandırıp kazandırmadığını sayılarla görürsünüz; tahmin değil, kayıt.</p>
{past_coupons_html(past)}

<h2 id="maclar">Yaklaşan maçlar <small>üç görüş yan yana · 48 saat</small></h2>
<p class="plain"><b>Bu ne demek?</b> Her maç için "bu sonuç yüzde kaç ihtimalle olur?" sorusuna üç ayrı kaynak cevap verir: <b>Piyasa</b> (dünyanın en keskin bahis borsası Pinnacle'ın oranından hesaplanır), <b>İstatistik</b> (iki takımın son 2-3 sezondaki gollerinden hesaplanır), <b>Claude</b> (maç saatine yakın haberleri ve kadroları okuyan yapay zekâ; oranı görmeden tahmin eder, sonra piyasaya itirazı var mı söyler). "Değer" sütunu: Nesine'nin oranı, piyasanın ihtimaline göre fazla mı az mı. Artıysa iyi.</p>
<p class="lead">Maça tıklayın, tablo açılır. Altında iki takımın son maçları düz yazıyla anlatılır. En makul görüşü siz seçersiniz; hangisinin geçmişte ne kadar tuttuğu da yazıyor.</p>
{md_html}

<h2 id="sayac">Eşiğe en yakın bahisler</h2>
<p class="plain"><b>Bu ne demek?</b> Fırsat yoksa bile "en yakın neresi?" diye bakmak için. Her çubuk bir bahis. Çubuk ne kadar sağdaysa Nesine o kadar cömert. Beyaz çizgiye (+%3) ulaşan yeşil yanar ve yukarıda fırsat kartı olur. Çoğu çubuk solda kalır; bu Nesine'nin normal hâlidir.</p>
<ul class="list">{rows_html or '<li class="row"><div class="m"><div class="t">Henüz karşılaştırma yok.</div></div></li>'}</ul>
<div class="legend"><span><i style="background:#3E5A4D"></i>geride</span><span><i style="background:var(--sodium)"></i>yaklaşıyor (−%5 içinde)</span><span><i style="background:var(--signal)"></i>eşiği geçti</span></div>

<h2 id="degisim">İddaa oranları hareket ediyor mu?</h2>
<p class="plain"><b>Bu ne demek?</b> Nesine'nin oranları sabit değil; her 20 dakikada bir bakıp değişenleri yazıyoruz. Yeşil ▲ oran yükseldi (daha cömert), turuncu ▼ düştü. "Maça kalan" sütunu, değişimin maçtan ne kadar önce olduğunu gösterir: kadro saatine (60-90 dk kala) yakın değişimler bizim için en önemlisi.</p>
<p class="lead">{ch_lead}</p>
<ul class="changes">{ch_html or '<li><time>—</time><div>Henüz değişim yok.</div></li>'}</ul>

<h2 id="nasil">Bu sayfa ne yapıyor?</h2>
<ul class="steps">
  <li><b>1 · Dünya piyasasını okur</b><p>Pinnacle, dünyanın en keskin bahis borsası sayılır: oranları milyonlarca dolarlık parayla saniyeler içinde düzelir. Onu "gerçek ihtimal" ölçütü olarak kullanıyoruz; orada hesabımız yok.</p></li>
  <li><b>2 · Nesine ile karşılaştırır</b><p>Her maçta Nesine'nin oranı, Pinnacle'dan çıkan adil oranla yan yana konur. Nesine daha yüksek veriyorsa fark bizim lehimize: buna "değer" diyoruz.</p></li>
  <li><b>3 · Üç görüşü yan yana koyar</b><p>Piyasa, takım geçmişinden istatistik, Claude'un haber okuması. Hepsinin geçmiş isabeti yazılır. Geçmiş 5.000 maçta: piyasa en isabetli; değer, 3.00 altı oranlarda gerçek, sürprizlerde yanıltıcı.</p></li>
  <li><b>4 · Kararı size bırakır</b><p>Bot para yatırmaz. Uyarıları, ihtimalleri ve kuponların gerçek maliyetini gösterir; sonradan her uyarıyı puanlar ki hangi görüşe güvenileceğini zamanla veri söylesin.</p></li>
</ul>

<footer>Sayfa her 20 dakikada otomatik yenilenir; yatırım tavsiyesi değildir. Gerçekçi hedef: uzun vadede yatırılan paranın %2–5'i. Fırsatsız günler normaldir.
<br>Kaynak kod: <a href="https://github.com/boradmir/iddia-bot">github.com/boradmir/iddia-bot</a></footer>
</div></body></html>"""


if __name__ == "__main__":
    import sys
    RECORD_COUPONS = "--record-coupons" in sys.argv
    os.makedirs("docs", exist_ok=True)
    page = build()
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(page)
    print(f"docs/index.html yazıldı ({len(page)} bayt)")
