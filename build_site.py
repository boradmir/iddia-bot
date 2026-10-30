"""GitHub Pages sayfasını üretir: records/ içindeki kayıtlardan docs/index.html.

API çağrısı yapmaz, kota harcamaz. Herkese açık sayfa olduğu için kişisel hiçbir bilgi içermez;
yatırım tutarı TL değil kasa yüzdesi olarak gösterilir. Teknik olmayan okuyucu için yazılmıştır.

Bölümler: durum · uyarılar (gözcü) · fırsat kartları · kupon önerileri · yaklaşan maçlar (üç görüş + neden)
          · eşiğe en yakın bahisler · Nesine oran değişimleri · nasıl çalışır
"""
import glob, html, json, os, collections
from datetime import datetime, timezone, timedelta
import match, odds, prob, value, stats, coupons, espn

TR = timezone(timedelta(hours=3))
RECORD_COUPONS = False   # build_site.py --record-coupons ile açılır (yalnızca kayıtçı iş akışı)
CLAUDE_ACC = "henüz ölçülmedi"   # build() içinde puanlanmış Yapay zekâ tahminlerinden hesaplanır
ESPN_BY = {}    # build() içinde espn.load_all(); maç kodu → ESPN verisi
SHADOW = True   # gölge test: para oynanmaz, her şey kaydedilip puanlanır (29.10.2026 karar)
MARKET_TR = {"MS": "Maç sonucu", "AU25": "2.5 gol alt/üst", "KG": "Karşılıklı gol"}
PICK_TR = {("MS", "1"): "MS 1 · ev sahibi kazanır", ("MS", "X"): "MS X · beraberlik", ("MS", "2"): "MS 2 · deplasman kazanır",
           ("AU25", "Alt"): "2.5 Alt · 2 veya daha az gol", ("AU25", "Üst"): "2.5 Üst · 3 veya daha fazla gol",
           ("KG", "Var"): "KG Var · iki takım da gol atar", ("KG", "Yok"): "KG Yok · en az bir takım gol atamaz"}
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


def countdown(t, now):
    """'sonraki güncelleme' metni: birazdan / ~12 dk / ~2 sa 10 dk / Cum 19:20."""
    s = (t - now).total_seconds()
    if s <= 60:
        return "birazdan"
    m = int(s // 60)
    if m < 60:
        return f"~{m} dk"
    if m < 24 * 60:
        return f"~{m // 60} sa {m % 60} dk"
    return t.astimezone(TR).strftime("%d.%m %H:%M")


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
:root{--bg:#F4F1EA;--card:#FFFFFF;--line:#E3DED2;--ink:#14261F;--ink-2:#4A5A52;--muted:#7D8A83;--board:#0F3326;--board-2:#164B38;
--sodium:#E8A800;--sodium-soft:#FFF3CC;--signal:#1D9A5B;--signal-soft:#E3F5EB;--ember:#D1612A;--ember-soft:#FBE9DF;--chalk:#F2F5F0;--chalk-dim:#B9C7BF}
*{box-sizing:border-box;min-width:0}
html{background:var(--bg)}
body{margin:0;font-family:"Source Sans 3",system-ui,sans-serif;font-size:16.5px;line-height:1.5;color:var(--ink);background:var(--bg);overflow-x:hidden}
a{color:var(--board-2)}
.wrap{max-width:1040px;margin:0 auto;padding:0 20px 80px}
/* üst bar */
.topbar{display:flex;justify-content:space-between;align-items:center;padding:18px 0 14px;gap:12px;flex-wrap:wrap}
.brand{font-family:"Barlow Condensed",sans-serif;font-weight:700;font-size:24px;letter-spacing:.06em;text-transform:uppercase;color:var(--board)}
.brand small{display:block;font-family:"Source Sans 3",sans-serif;font-weight:400;font-size:13.5px;letter-spacing:0;text-transform:none;color:var(--muted)}
.clock{font-family:"JetBrains Mono",monospace;font-size:13px;color:var(--muted)}
/* skorbord */
.board{background:linear-gradient(135deg,var(--board) 0%,var(--board-2) 100%);color:var(--chalk);border-radius:18px;padding:28px 28px 24px;box-shadow:0 14px 40px rgba(15,51,38,.25);position:relative;overflow:hidden}
.board::after{content:"";position:absolute;inset:auto -60px -120px auto;width:320px;height:320px;border-radius:50%;border:2px solid rgba(255,255,255,.08)}
.verdict{font-family:"Barlow Condensed",sans-serif;font-weight:700;font-size:clamp(42px,7vw,76px);line-height:.95;letter-spacing:-.01em;margin:0;opacity:0;transform:translateY(10px);animation:rise .6s .05s cubic-bezier(.2,.7,.2,1) forwards}
.verdict em{font-style:normal;color:#FFCF4D}
@keyframes rise{to{opacity:1;transform:none}}
.pills{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0 0;padding:0;list-style:none}
.pills li{display:inline-flex;align-items:center;gap:8px;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.16);border-radius:999px;padding:5px 12px;font-size:13.5px;color:var(--chalk-dim)}
.pills b{color:var(--chalk);font-weight:600}
.pills .shadow{border-color:rgba(255,207,77,.6);color:#FFCF4D}
.pulse{display:inline-block;width:9px;height:9px;border-radius:50%;background:#3EE38C;box-shadow:0 0 0 0 rgba(62,227,140,.6);animation:pulse 2.2s infinite}
.pulse.off{background:var(--ember);box-shadow:none;animation:none}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(62,227,140,.6)}70%{box-shadow:0 0 0 10px rgba(62,227,140,0)}100%{box-shadow:0 0 0 0 rgba(62,227,140,0)}}
.facts{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:20px 0 0;padding:0;list-style:none}
.facts li{background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.12);border-radius:12px;padding:12px 14px}
.facts .n{font-family:"Barlow Condensed",sans-serif;font-size:34px;font-weight:700;line-height:1;color:#fff}
.facts .l{font-size:13px;color:var(--chalk-dim);margin-top:4px}
.facts .good{color:#3EE38C}.facts .bad{color:#FF9A6B}
/* sekmeler */
.tabs{position:sticky;top:0;z-index:5;background:rgba(244,241,234,.94);backdrop-filter:blur(6px);margin:18px -20px 0;padding:10px 20px;border-bottom:1px solid var(--line);display:flex;gap:6px;overflow-x:auto;scrollbar-width:none}
.tabs::-webkit-scrollbar{display:none}
.tabs a{flex:0 0 auto;text-decoration:none;color:var(--ink-2);font-weight:600;font-size:14.5px;padding:8px 14px;border-radius:999px;border:1px solid transparent;white-space:nowrap}
.tabs a:hover{background:#fff;border-color:var(--line)}
.tabs a.on{background:var(--board);color:#fff;border-color:var(--board)}
.tabs a .cnt{display:inline-block;margin-left:6px;background:rgba(255,255,255,.18);border-radius:999px;padding:0 7px;font-size:12px}
.tabs a:not(.on) .cnt{background:var(--sodium-soft);color:#6b4d00}
.panel{display:none;padding-top:26px;animation:fade .35s}
.panel.on{display:block}
@keyframes fade{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
h2{font-family:"Barlow Condensed",sans-serif;font-weight:700;font-size:30px;letter-spacing:.01em;margin:0 0 4px;color:var(--board)}
h2 small{font-family:"Source Sans 3",sans-serif;font-size:14px;letter-spacing:0;color:var(--muted);font-weight:400;margin-left:8px}
h3{font-family:"Barlow Condensed",sans-serif;font-weight:700;font-size:22px;margin:30px 0 8px;color:var(--board)}
.lead{margin:0 0 16px;color:var(--ink-2);font-size:15.5px;max-width:760px}
.lead b{color:var(--ink);font-weight:600}
.lead a.q{font-size:13px;margin-left:6px;color:var(--board-2);text-decoration:underline dotted}
.note{background:var(--sodium-soft);border-left:4px solid var(--sodium);padding:10px 14px;border-radius:0 10px 10px 0;color:#4a3a00;font-size:14.5px;margin:0 0 16px;max-width:900px}
.note b{color:#2f2500}
.empty{background:var(--card);border:1px dashed var(--line);border-radius:14px;padding:18px 20px;color:var(--ink-2);font-size:15px}
.empty b{color:var(--ink)}
.plain{color:var(--ink-2);font-size:15px;line-height:1.55}
.plain b{color:var(--ink)}
/* kart genel */
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 20px;box-shadow:0 2px 10px rgba(20,38,31,.05)}
/* fırsat kartı */
.coupon{position:relative;background:var(--card);color:var(--ink);border:1px solid var(--line);border-left:6px solid var(--signal);border-radius:14px;padding:18px 20px;margin:14px 0;box-shadow:0 6px 20px rgba(20,38,31,.07);opacity:0;animation:rise .5s forwards}
.coupon.combo{border-left-color:var(--board-2)}
.coupon .top{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;border-bottom:1px solid var(--line);padding-bottom:10px;margin-bottom:12px}
.coupon .teams{font-family:"Barlow Condensed",sans-serif;font-weight:700;font-size:26px;line-height:1.05;color:var(--board)}
.coupon .meta{font-family:"JetBrains Mono",monospace;font-size:12px;color:var(--muted);text-align:right}
.coupon .title{font-family:"Barlow Condensed",sans-serif;font-weight:700;font-size:22px;color:var(--board)}
.pickbadge{display:inline-block;background:var(--sodium);color:#1B1B1B;font-family:"Barlow Condensed",sans-serif;font-weight:700;font-size:22px;letter-spacing:.02em;padding:4px 12px;border-radius:8px;margin:2px 0 6px}
.pickbadge small{display:block;font-family:"Source Sans 3",sans-serif;font-weight:600;font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:#5a4a12;margin-bottom:-2px}
.coupon .pick{font-size:18px;font-weight:600;margin:0 0 10px}
.coupon .pick small{display:block;font-weight:400;font-size:13.5px;color:var(--muted)}
.coupon dl{display:grid;grid-template-columns:1fr auto;gap:6px 16px;margin:0;font-size:15px}
.coupon dt{color:var(--ink-2)}
.coupon dd{margin:0;font-family:"JetBrains Mono",monospace;font-weight:600;text-align:right;white-space:nowrap}
.coupon dd.good{color:var(--signal)}.coupon dd.bad{color:var(--ember)}
.coupon .status{margin-top:12px;padding:10px 12px;border-radius:10px;background:var(--signal-soft);font-size:14px;color:#145c3a}
.coupon .status.warn{background:var(--ember-soft);color:#8a3d12}
.coupon .why{margin-top:10px;font-size:14px;color:var(--ink-2)}
.coupon .why b{color:var(--ink)}
.coupon .legs{list-style:none;margin:0 0 12px;padding:0;font-size:15px}
.coupon .legs li{display:grid;grid-template-columns:1fr auto auto;gap:10px;padding:7px 0;border-bottom:1px solid var(--line);align-items:center}
.coupon .legs .p{font-family:"JetBrains Mono",monospace;color:var(--muted);font-size:13.5px}
.coupon .legs .o{font-family:"JetBrains Mono",monospace;font-weight:700}
.coupon .legs small{display:block;color:var(--muted);font-size:12.5px;margin-top:2px}
.pb{display:inline-block;background:var(--sodium-soft);color:#5a4a12;border:1px solid #F0D98A;font-weight:700;font-size:12px;padding:1px 7px;border-radius:5px;margin-right:5px}
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}
.grid .coupon{margin:4px 0}
.claudebox{margin:12px 0 0;padding:12px 14px;border-radius:10px;background:var(--sodium-soft);border:1px solid #F0D98A;font-size:14.5px;color:var(--ink)}
.claudebox p{margin:6px 0 0}.claudebox ul{margin:8px 0 0;padding-left:18px;color:var(--ink-2);font-size:13.5px}.claudebox .muted{color:var(--muted);font-size:13px}
/* değer sayacı */
.list{list-style:none;margin:0;padding:0}
.row{display:grid;grid-template-columns:1fr 160px 64px;gap:14px;align-items:center;padding:10px 0;border-bottom:1px solid var(--line)}
.row .t{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.row .d{font-size:13.5px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.row .d code{font-family:"JetBrains Mono",monospace;font-size:13px;color:var(--ink)}
.row .v{font-family:"JetBrains Mono",monospace;font-size:14.5px;text-align:right;color:var(--ink-2)}
.row.hit .v{color:var(--signal);font-weight:700}
.meter{position:relative;height:10px;background:#E6E1D5;border-radius:5px}
.meter .bar{height:100%;width:0;border-radius:5px;background:#A9B5AE;animation:grow 1s cubic-bezier(.2,.7,.2,1) forwards}
.meter.near .bar{background:var(--sodium)}
.meter.hit .bar{background:var(--signal)}
.meter .tick{position:absolute;top:-4px;bottom:-4px;width:2px;background:var(--board);opacity:.8;left:calc(100% * (3 - (-25)) / (8 - (-25)))}
@keyframes grow{to{width:var(--w)}}
.legend{display:flex;gap:18px;flex-wrap:wrap;font-size:13px;color:var(--muted);margin:10px 0 0}
.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}
/* maç kartları */
details.match{background:var(--card);border:1px solid var(--line);border-radius:14px;margin:10px 0;overflow:hidden;box-shadow:0 2px 10px rgba(20,38,31,.04)}
details.match summary{list-style:none;cursor:pointer;display:grid;grid-template-columns:104px 1fr auto;gap:12px;padding:13px 16px;align-items:center}
details.match summary::-webkit-details-marker{display:none}
details.match summary:hover{background:#FBFAF6}
details.match summary time{font-family:"JetBrains Mono",monospace;font-size:12.5px;color:var(--muted)}
details.match summary .tm{font-weight:700;color:var(--board)}
details.match summary .lg{font-size:12.5px;color:var(--muted)}
details.match summary .tag{font-size:12px;padding:3px 9px;border-radius:999px;background:#EFEBE0;color:var(--ink-2);white-space:nowrap}
details.match summary .tag.hit{background:var(--signal-soft);color:#145c3a}
details.match summary .tag.miss{background:var(--ember-soft);color:#8a3d12}
details.match[open] summary{border-bottom:1px solid var(--line);background:#FBFAF6}
.views{padding:14px 16px 16px;overflow-x:auto}
.views table{width:100%;border-collapse:collapse;font-size:14.5px;min-width:520px}
.views th{font-weight:600;color:var(--muted);font-size:12.5px;text-align:right;padding:6px 8px;border-bottom:1px solid var(--line)}
.views th:first-child,.views td:first-child{text-align:left}
.views td{padding:7px 8px;text-align:right;font-family:"JetBrains Mono",monospace;font-size:13.5px;border-bottom:1px solid #F0ECE2}
.views td:first-child{font-family:"Source Sans 3",sans-serif;font-size:14.5px}
.views td.good{color:var(--signal);font-weight:700}
.views td.dim{color:var(--muted)}
.views tr.rec td{background:var(--signal-soft)}
.views tr.rec td:first-child{font-weight:700;color:#145c3a}
.views tr.rec td:first-child::before{content:"▶ ";font-size:11px}
.views .why{margin:12px 0 0;font-size:14px;color:var(--ink-2)}
.views .why b{color:var(--ink)}
.views .acc{margin:10px 0 0;font-size:12.5px;color:var(--muted)}
.plainlegs{list-style:none;margin:0;padding:0}.plainlegs li{display:grid;grid-template-columns:1fr auto auto;gap:10px;padding:7px 0;border-bottom:1px solid var(--line);font-size:14.5px}.plainlegs small{display:block;color:var(--muted);font-size:12.5px}.plainlegs .o{font-family:"JetBrains Mono",monospace}
/* listeler */
.alerts,.changes{list-style:none;margin:0;padding:0}
.alerts li,.changes li{display:grid;grid-template-columns:84px 1fr auto;gap:12px;padding:10px 0;border-bottom:1px solid var(--line);font-size:15px;align-items:baseline}
.alerts time,.changes time{font-family:"JetBrains Mono",monospace;font-size:12.5px;color:var(--muted)}
.alerts .r,.changes .o{font-family:"JetBrains Mono",monospace;font-size:14px;text-align:right;white-space:nowrap}
.alerts .r.good,.changes .o.up{color:var(--signal)}.alerts .r.bad,.changes .o.down{color:var(--ember)}
.alerts small,.changes small{display:block;color:var(--muted);font-size:13px}
.changes small{display:inline}
/* claude kartları */
.cl{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}
.cl .card{opacity:0;animation:rise .5s forwards}
.cl .head{display:flex;justify-content:space-between;gap:10px;align-items:flex-start;margin-bottom:8px}
.cl .tm{font-family:"Barlow Condensed",sans-serif;font-weight:700;font-size:22px;color:var(--board);line-height:1.05}
.cl .when{font-family:"JetBrains Mono",monospace;font-size:12px;color:var(--muted)}
.cl .vd{font-size:12px;padding:3px 9px;border-radius:999px;white-space:nowrap}
.cl .vd.ok{background:var(--signal-soft);color:#145c3a}.cl .vd.warn{background:var(--ember-soft);color:#8a3d12}
.cl .probs{display:grid;grid-template-columns:repeat(5,1fr);gap:6px;margin:10px 0}
.cl .probs div{background:#F7F5EF;border-radius:8px;padding:6px 8px;text-align:center}
.cl .probs b{display:block;font-family:"JetBrains Mono",monospace;font-size:15px}
.cl .probs small{font-size:11px;color:var(--muted)}
.cl .probs .hitp{background:var(--signal-soft);outline:2px solid var(--signal)}
.cl .probs em{display:block;font-style:normal;font-size:11px;color:var(--muted);margin-top:2px}
.cl .probs i{display:block;font-style:normal;font-size:11px;font-weight:700;color:#145c3a;margin-top:2px}
.cl .plabel{font-size:13px;color:var(--muted);margin-top:6px}.cl .plabel b{color:var(--ink-2)}
.cl .abs{margin-top:12px;padding-top:10px;border-top:1px solid var(--line)}
.cl .tbl{overflow-x:auto;margin-top:6px}
.cl .tbl table{width:100%;border-collapse:collapse;font-size:13.5px;min-width:560px}
.cl .tbl th{text-align:left;font-weight:600;color:var(--muted);font-size:12px;padding:5px 8px;border-bottom:1px solid var(--line)}
.cl .tbl td{padding:6px 8px;border-bottom:1px solid #F0ECE2;vertical-align:top;color:var(--ink-2)}
.cl .tbl td b{color:var(--ink)}
.cl .st{display:inline-block;font-size:12px;padding:1px 8px;border-radius:999px;background:#EFEBE0;white-space:nowrap}
.cl .st.miss{background:var(--ember-soft);color:#8a3d12}.cl .st.warn{background:var(--sodium-soft);color:#6b4d00}.cl .st.ok{background:var(--signal-soft);color:#145c3a}
.cl .lnote,.views .lnote{margin:8px 0 0;font-size:14px;color:var(--ink-2)}
.abs{margin-top:12px;padding-top:10px;border-top:1px solid var(--line)}
.abs .plabel{font-size:13px;color:var(--muted);margin-bottom:6px}.abs .plabel b{color:var(--ink-2)}
.chips{display:flex;flex-wrap:wrap;gap:8px}
details.chip{display:inline-block;position:relative}
details.chip summary{list-style:none;cursor:pointer;display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);background:#fff;border-radius:999px;padding:4px 11px;font-size:13.5px;font-weight:600;color:var(--ink)}
details.chip summary::-webkit-details-marker{display:none}
details.chip summary small{font-weight:400;color:var(--muted);font-size:12px}
details.chip.miss summary{border-color:#F2C2A8;background:var(--ember-soft)}
details.chip.warn summary{border-color:#F0D98A;background:var(--sodium-soft)}
details.chip.ok summary{border-color:#BFE6CF;background:var(--signal-soft)}
details.chip.goal summary{border-color:#BFD9EA;background:#E8F2F9}
details.lineup{margin:6px 0}
details.lineup summary{list-style:none;cursor:pointer;font-size:14px;color:var(--ink-2);padding:6px 10px;border:1px solid var(--line);border-radius:8px;background:#fff}
details.lineup summary::-webkit-details-marker{display:none}
details.lineup .pop2{font-size:13.5px;color:var(--ink-2);padding:8px 10px;display:grid;gap:4px}
details.lineup .pop2 b{color:var(--ink)}
.l5{font-size:14px;color:var(--ink-2)}
.r5{display:inline-block;width:20px;height:20px;line-height:20px;text-align:center;border-radius:4px;font-size:12px;font-weight:700;color:#fff;background:#A9B5AE;margin-right:2px}
.r5.W{background:var(--signal)}.r5.L{background:var(--ember)}.r5.D{background:#9AA7A0}
details.chip[open] summary{box-shadow:0 0 0 2px rgba(15,51,38,.15)}
details.chip .pop{position:absolute;z-index:4;top:calc(100% + 6px);left:0;min-width:260px;max-width:360px;background:#fff;border:1px solid var(--line);border-radius:10px;padding:10px 12px;box-shadow:0 10px 28px rgba(20,38,31,.15);font-size:13.5px;color:var(--ink-2);display:grid;gap:4px}
details.chip .pop b{color:var(--ink)}
.cl{grid-template-columns:1fr}
.cl p{margin:8px 0 0;font-size:14.5px;color:var(--ink-2)}
.cl ul{margin:8px 0 0;padding-left:18px;font-size:13.5px;color:var(--ink-2)}
.cl .res{margin-top:10px;font-size:13.5px;color:var(--ink-2);border-top:1px solid var(--line);padding-top:8px}
.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px;margin:0;padding:0;list-style:none}
.steps li{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px}
.steps b{display:block;font-family:"Barlow Condensed",sans-serif;font-size:22px;font-weight:700;margin-bottom:4px;color:var(--board)}
.steps p{margin:0;color:var(--ink-2);font-size:14.5px}
.gloss{margin:16px 0 0;padding:0;list-style:none;display:grid;gap:10px}
.gloss li{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 16px}
.gloss b{display:block;color:var(--board);margin-bottom:2px}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px}
.tile{display:block;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;text-decoration:none;color:var(--ink-2);font-size:13.5px}
.tile img{width:100%;display:block;aspect-ratio:4/5;object-fit:cover}
.tile span{display:block;padding:8px 10px}
.post{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px;margin:12px 0}
.post-h{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-bottom:10px}
.post-h .when{font-family:"JetBrains Mono",monospace;font-size:12.5px;color:var(--muted)}
.tiles.small{grid-template-columns:repeat(auto-fill,minmax(150px,1fr))}
.cap{margin-top:10px;display:grid;gap:8px}
.cap textarea{width:100%;font:14px/1.45 "Source Sans 3",system-ui,sans-serif;color:var(--ink);background:#FBFAF6;border:1px solid var(--line);border-radius:10px;padding:10px;resize:vertical}
.cap .copy{justify-self:start;padding:7px 14px;border-radius:8px;border:1px solid var(--board);background:var(--board);color:#fff;cursor:pointer;font-weight:600}
.cap .copy.ok{background:var(--signal);border-color:var(--signal)}
footer{margin-top:56px;padding-top:18px;border-top:1px solid var(--line);color:var(--muted);font-size:13.5px}
@media (max-width:760px){.grid,.cl{grid-template-columns:1fr}.facts{grid-template-columns:repeat(2,1fr)}.board{padding:22px 18px 18px;border-radius:14px}}
@media (max-width:560px){.row{grid-template-columns:1fr 92px 54px}.alerts li,.changes li{grid-template-columns:64px 1fr}.alerts .r,.changes .o{grid-column:2;text-align:left}
details.match summary{grid-template-columns:1fr auto}details.match summary time{grid-column:1/-1}.coupon{padding:16px 14px}.coupon .meta{text-align:left}.cl .probs{grid-template-columns:repeat(3,1fr)}}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}.verdict,.coupon,.cl .card{opacity:1;transform:none}.meter .bar{width:var(--w)}}
"""


# ----------------------------------------------------------------- kupon defteri
COUPON_DIR = "records/coupons"
KIND_TR = {"safest": "En güvenli", "least_loss": "En az kayıplı", "balanced": "Dengeli", "value": "Değerli"}


def coupon_key(kind, c):
    legs = sorted((b["code"], b["market"], b["pick"]) for b in c["legs"])
    first_day = min(b["start"] for b in c["legs"]).astimezone(TR).strftime("%Y-%m-%d")
    return f"{kind}:{c['n']}:{first_day}"


def record_coupons(cps, now):
    """Önerilen kuponları ilk görüldükleri anda kilitler (o an oynanmış gibi). Tür+maç sayısı+gün başına bir kez."""
    past_all = read_jsonl(f"{COUPON_DIR}/*.jsonl")
    existing = {c["key"] for c in past_all}
    next_no = max((c.get("no", 0) for c in past_all), default=0) + 1
    new = []
    items = [("value", cps["value"])] if cps.get("value") else []
    items += [("safest", c) for c in cps.get("safest", [])] + [("balanced", c) for c in cps.get("balanced", [])]
    for kind, c in items:
        k = coupon_key(kind, c)
        if k in existing:
            continue
        existing.add(k)
        new.append({"key": k, "no": next_no, "t": now.isoformat(timespec="seconds"), "kind": kind, "n": c["n"], "odds": round(c["odds"], 2),
                    "prob": round(c["prob"], 4), "ev_pct": round(c["ev_pct"], 1), "result": None,
                    "legs": [{"code": b["code"], "home": b["home"], "away": b["away"], "league": b["league"], "sport": b.get("sport_key"),
                              "start": b["start"].isoformat(), "market": b["market"], "pick": b["pick"], "odds": b["nesine_odds"],
                              "prob": round(b["fair_prob"], 4)} for b in c["legs"]]})
        next_no += 1
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
    for kind in ("safest", "balanced", "least_loss", "value"):
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
        legs = "".join(f'<li><div>{esc(l["home"])} – {esc(l["away"])}<small><span class="pb">{esc(PICK_SHORT.get((l["market"], l["pick"]), l["pick"]))}</span>{tr_time(l["start"], day=True)}'
                       f'{(" · skor " + l["score"]) if l.get("score") else ""}</small></div>'
                       f'<div class="p">{"✓" if l.get("result") == "won" else "✗" if l.get("result") == "lost" else "…"}</div><div class="o">{l["odds"]:.2f}</div></li>' for l in c["legs"])
        items += f"""<details class="match"><summary><time>{tr_time(c['t'], day=True)}</time><div><div class="tm">{('#' + str(c['no']) + ' · ') if c.get('no') else ''}{KIND_TR.get(c['kind'], c['kind'])} · {c['n']} maç · oran {c['odds']:.2f}</div>
<div class="lg">gelme ihtimali %{c['prob']*100:.0f} · beklenen değer {c['ev_pct']:+.0f}%</div></div>{tag}</summary>
<div class="views"><ul class="legs plainlegs">{legs}</ul></div></details>"""
    return summ + (items or "")


# ----------------------------------------------------------------- parçalar
def coupon_card(b, i, stale, sv, cr=None):
    ok = not stale
    if ok and SHADOW:
        status = '<div class="status">✅ Şartlar sağlandı — gölge testte kaydedildi. Para oynanmıyor; sonucu ve kapanış oranı puanlanacak.</div>'
    elif ok:
        status = '<div class="status">✅ Oynanabilir: değer eşiğin üstünde, dünya piyasası verisi güncel.</div>'
    else:
        status = '<div class="status warn">⏸ Şimdilik sadece izliyoruz: dünya piyasası verisi eski, deneme aşamasındayız.</div>'
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
  <div class="pickbadge"><small>{'Önerilen bahis' if ok else 'İzlenen bahis (veri eski)'}</small>{esc(PICK_SHORT.get((b['market'], b['pick']), b['pick']))}</div>
  <p class="pick">{esc(PICK_TR.get((b['market'], b['pick']), b['pick']))}<small>{MARKET_TR[b['market']]}</small></p>
  <dl>
    <dt>Nesine'nin verdiği oran</dt><dd>{b['nesine_odds']:.2f}</dd>
    <dt>Dünya piyasasına göre gerçek ihtimal</dt><dd>{pct(b['fair_prob'])}</dd>
    <dt>Bu ihtimale denk gelen adil oran</dt><dd>{b['fair_odds']:.2f}</dd>
    <dt>Nesine'nin fazladan verdiği</dt><dd class="good">+%{b['ev_pct']:.1f}</dd>
    <dt>Önerilen kasa payı</dt><dd>%{b['stake']:.1f}</dd>
    <dt>Nesine alt sınırı 50 TL → bu oran için gereken kasa</dt><dd>{(value.min_bankroll_for(b['stake']) or 0):,} TL</dd>
  </dl>
  <div class="why">Nesine'de bir kupon en az <b>50 TL</b>. Kasanız bunun altındaysa 50 TL bu bahsin önerdiğinden çok daha büyük bir pay demektir; o zaman oynamamak doğru karardır.</div>
  {why}
  {claude_box(cr)}
  {status}
</article>"""


def combo_card(title, c, i, kind, no=None):
    if not c:
        return ""
    title = f"#{no} · {title}" if no else title
    loss = -c["ev_pct"]
    ev_cls = "good" if c["ev_pct"] >= 0 else "bad"
    legs = "".join(f'<li><div>{esc(b["home"])} – {esc(b["away"])}<small><span class="pb">{esc(PICK_SHORT.get((b["market"], b["pick"]), b["pick"]))}</span>{tr_time(b["start"], day=True)}</small></div>'
                   f'<div class="p">{pct(b["fair_prob"])}</div><div class="o">{b["nesine_odds"]:.2f}</div></li>' for b in c["legs"])
    tl = value.MIN_COUPON_TL
    verdict = (f"Nesine'nin en küçük kuponu {tl} TL. Bu kupona {tl} TL yatırılırsa tutarsa <b>{tl*c['odds']:.0f} TL</b> öder; "
               f"uzun vadede her {tl} TL'nin yaklaşık <b>{loss*tl/100:.0f} TL'si kaybedilir</b>." if c["ev_pct"] < 0 else
               f"Nesine'nin en küçük kuponu {tl} TL; tutarsa <b>{tl*c['odds']:.0f} TL</b> öder. Beklenen değer artı: {tl} TL'ye yaklaşık <b>{c['ev_pct']*tl/100:.0f} TL kazanç</b> beklenir.")
    return f"""
<article class="coupon combo" style="animation-delay:{.4 + i*.1:.2f}s">
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


def absence_chips(bl):
    """Eksik/şüpheli oyuncular: tıklanınca ayrıntı açılan çipler. bl = kör tahmin sözlüğü."""
    items = (bl or {}).get("absences") or []
    if not items and not (bl or {}).get("lineup_note"):
        return ""
    icon = {"sakat": "🩹", "cezalı": "🟥", "şüpheli": "❔", "döndü": "✅"}
    chips = ""
    for a in items[:12]:
        st = a.get("status", ""); cls = {"sakat": "miss", "cezalı": "miss", "şüpheli": "warn", "döndü": "ok"}.get(st, "")
        chips += (f'<details class="chip {cls}"><summary>{icon.get(st, "•")} {esc(a.get("player", ""))} <small>{esc(a.get("team", ""))} · {esc(a.get("role", ""))}</small></summary>'
                  f'<div class="pop"><div><b>Durum:</b> {esc(st)}</div><div><b>Takımdaki yeri:</b> {esc(a.get("role", ""))}</div>'
                  f'<div><b>Son maçlar:</b> {esc(a.get("recent", "") or "bilgi yok")}</div><div><b>Bu maça etkisi:</b> {esc(a.get("impact", "") or "—")}</div></div></details>')
    note = f'<p class="lnote">{esc(bl.get("lineup_note", ""))}</p>' if bl.get("lineup_note") else ""
    return (f'<div class="abs"><div class="plabel"><b>Sakat / cezalı / şüpheli</b> · haberlere göre · oyuncuya tıklayın</div>'
            f'<div class="chips">{chips or "<span class=\"muted\">haberlerde eksik geçmiyor</span>"}</div>{note}</div>')


def espn_block(code, home=None, away=None):
    """ESPN VERİSİ: gol atması en olası oyuncular (sezon golü/şutu), açıklanan ilk 11, son 5 maç."""
    er = ESPN_BY.get(code)
    if not er:
        return ""
    html_ = ""
    # golcüler
    chips = ""
    for team, ls in (er.get("leaders") or {}).items():
        names_in_roster = None
        ro = (er.get("rosters") or {}).get(team)
        if ro:
            names_in_roster = {p["player"] for p in ro["starters"]} | set(ro["bench"])
        for l in sorted(ls, key=lambda r: (-r["goals"], -r["shots"]))[:2]:
            if not l["goals"] and not l["shots"]:
                continue
            gpm = f'{l["goals"]/l["matches"]:.2f}' if l.get("matches") else "?"
            out_tag = ""
            if names_in_roster is not None and l["player"] not in names_in_roster:
                out_tag = ' <small style="color:#8a3d12">· kadroda değil</small>'
            chips += (f'<details class="chip goal"><summary>⚽ {esc(l["player"])} <small>{esc(team)} · {l["goals"]} gol</small>{out_tag}</summary>'
                      f'<div class="pop"><div><b>Sezon:</b> {l.get("matches") or "?"} maç, {l["goals"]} gol, {l["assists"]} asist</div><div><b>Maç başı gol:</b> {gpm}</div>'
                      f'<div><b>Toplam şut:</b> {l["shots"]}</div></div></details>')
    if chips:
        html_ += f'<div class="plabel"><b>Gol atması en olası</b> · sezon verisi (ESPN)</div><div class="chips">{chips}</div>'
    # ilk 11
    ros = er.get("rosters") or {}
    if ros:
        parts = ""
        for team, ro in ros.items():
            st = ", ".join(f'{esc(p["player"])}' for p in ro["starters"])
            bn = ", ".join(esc(x) for x in ro["bench"])
            parts += (f'<details class="lineup"><summary><b>{esc(team)}</b> · {esc(ro.get("formation") or "diziliş ?")} · ilk 11 açıklandı</summary>'
                      f'<div class="pop2"><div><b>İlk 11:</b> {st}</div><div><b>Yedek:</b> {bn or "—"}</div></div></details>')
        html_ += f'<div class="plabel" style="margin-top:10px"><b>Açıklanan kadro</b> · ESPN</div>{parts}'
    # son 5
    l5 = er.get("last5") or {}
    if l5:
        sym = {"W": "G", "D": "B", "L": "M"}
        rows = " · ".join(f'<b>{esc(t)}</b> ' + " ".join(f'<span class="r5 {g["result"]}">{sym.get(g["result"], "?")}</span>' for g in gs) for t, gs in l5.items())
        html_ += f'<div class="plabel" style="margin-top:10px"><b>Son 5 maç</b> (G galibiyet · B beraberlik · M mağlubiyet, en eski → en yeni)</div><div class="l5">{rows}</div>'
    return f'<div class="abs espn">{html_}</div>' if html_ else ""


_KADRO = None


def kadro_rows():
    """records/kadro/*.jsonl → {code: son kayıt} (bir kez okunur)."""
    global _KADRO
    if _KADRO is None:
        _KADRO = {}
        for r in read_jsonl("records/kadro/*.jsonl"):
            _KADRO[r.get("code")] = r
    return _KADRO


def claude_box(cr):
    if not cr:
        return ""
    bl = cr["blind"]; ob = cr.get("objection") or {}
    facts = "".join(f"<li>{esc(x)}</li>" for x in bl.get("facts", [])[:5])
    verdict = ('<span class="tag hit">piyasaya itiraz yok ✓</span>' if ob.get("verdict") == "ok" else
               '<span class="tag miss">⚠ itiraz var</span>' if ob.get("verdict") == "warn" else "")
    html_ = (f'<div class="claudebox"><b>Yapay zekâ ne diyor?</b> {verdict}<p>{esc(bl.get("comment", ""))}</p>'
             f'<p><b>Risk:</b> {esc(bl.get("risk", ""))} <span class="muted">(güven: {esc(bl.get("confidence", ""))})</span></p>')
    kd = kadro_rows().get(cr.get("code"))
    if kd and (kd.get("kadro") or {}).get("note"):
        k = kd["kadro"]
        html_ += (f'<p><b>Kadro açıklandıktan sonra:</b> {esc(k["note"])} <span class="muted">(güncel tahmin: ev %{k.get("p_home", 0) * 100:.0f} · '
                  f'beraberlik %{k.get("p_draw", 0) * 100:.0f} · deplasman %{k.get("p_away", 0) * 100:.0f})</span></p>')
    if ob.get("verdict") == "warn":
        html_ += f'<p><b>İtiraz gerekçesi:</b> {esc(ob.get("reason", ""))}</p>'
    html_ += (f"<ul>{facts}</ul>" if facts else '<p class="muted">Somut haber bulunamadı.</p>') + "</div>"
    return html_


def claude_section(rows):
    """Yapay zekânın tüm analizleri (maç bitince de kalır): kör ihtimaller (piyasa ile yan yana), yorum, risk, haberler, sonuç."""
    rows = sorted(rows, key=lambda r: r["t"], reverse=True)[:12]
    if not rows:
        return '<div class="empty"><b>Henüz analiz yok.</b> Yapay zekâ, gözcü açıkken maça 100 dakika kala devreye girer: haberleri okur, oranı görmeden tahmin eder.</div>'
    out = ""
    for i, r in enumerate(rows):
        bl = r["blind"]; ob = r.get("objection") or {}; res = r.get("result") if isinstance(r.get("result"), dict) else None
        mk = r.get("market") or {}
        vd = ('<span class="vd ok">piyasaya itiraz yok</span>' if ob.get("verdict") == "ok" else
              '<span class="vd warn">⚠ itiraz var</span>' if ob.get("verdict") == "warn" else "")
        def cell(label, p_ai, key, want):
            p_mk = mk.get(key, {}).get(want)
            happened = bool(res) and res.get(key) == want
            return (f'<div class="{"hitp" if happened else ""}"><b>%{p_ai*100:.0f}</b><small>{label}</small>'
                    f'<em>{("piyasa %" + f"{p_mk*100:.0f}") if p_mk is not None else "&nbsp;"}</em>'
                    f'{"<i>✓ oldu</i>" if happened else ""}</div>')
        probs = (cell("Ev kazanır", bl["p_home"], "MS", "1") + cell("Beraberlik", bl["p_draw"], "MS", "X") + cell("Deplasman kazanır", bl["p_away"], "MS", "2")
                 + cell("3+ gol", bl["p_over25"], "AU25", "Üst") + cell("KG var", bl["p_btts"], "KG", "Var"))
        facts = "".join(f"<li>{esc(x)}</li>" for x in bl.get("facts", [])[:4])
        abs_html = absence_chips(bl) + espn_block(r.get('code'))
        resline = ""
        if res:
            ms = res.get("MS"); lab = {"1": "ev galibiyetine", "X": "beraberliğe", "2": "deplasman galibiyetine"}.get(ms, "")
            p_ai = {"1": bl["p_home"], "X": bl["p_draw"], "2": bl["p_away"]}.get(ms); p_mk = mk.get("MS", {}).get(ms)
            who = ""
            if p_ai is not None and p_mk is not None:
                who = " → bu maçta <b>yapay zekâ</b> daha isabetliydi." if p_ai > p_mk else " → bu maçta <b>piyasa</b> daha isabetliydi."
            resline = (f'<div class="res">Sonuç <b>{esc(res.get("score", ""))}</b>. Gerçekleşen sonuca ({lab}) yapay zekâ <b>%{(p_ai or 0)*100:.0f}</b>, '
                       f'piyasa <b>%{(p_mk or 0)*100:.0f}</b> vermişti{who}</div>') if p_ai is not None else f'<div class="res">Sonuç <b>{esc(res.get("score", ""))}</b></div>'
        out += f"""<article class="card" style="animation-delay:{i*.06:.2f}s"><div class="head"><div><div class="tm">{esc(r['home'])} – {esc(r['away'])}</div>
<div class="when">{tr_time(r['start'], day=True)} · {esc(r.get('league', ''))} · analiz {tr_time(r['t'])}</div></div>{vd}</div>
<div class="plabel">Yapay zekânın <b>oranı görmeden</b> verdiği gerçekleşme ihtimalleri · altta piyasanın ihtimali</div>
<div class="probs">{probs}</div>
<p>{esc(bl.get('comment') or 'Bu analizde yazılı yorum üretilmedi; haberler ve ihtimaller aşağıda.')}</p>
<p><b>Risk:</b> {esc(bl.get('risk', ''))} <span class="when">(güven: {esc(bl.get('confidence', ''))})</span></p>
{f'<p><b>İtiraz gerekçesi:</b> {esc(ob.get("reason", ""))}</p>' if ob.get("verdict") == "warn" else ''}
{abs_html}
{f'<ul>{facts}</ul>' if facts else ''}
{resline}</article>"""
    return f'<div class="cl">{out}</div>'


def match_details(m, h2h_probs, sv, bets_by_code, cr=None):
    bets = bets_by_code.get(m["code"], [])
    best = max(bets, key=lambda b: b["ev_pct"]) if bets else None
    rec_set = {(x["market"], x["pick"]) for x in bets if x["ev_pct"] >= value.EV_THRESHOLD and x["nesine_odds"] < value.MAX_ODDS}
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
            rec = ' class="rec"' if (mk, pick) in rec_set else ""
            rows += (f'<tr{rec}><td>{esc(PICK_TR.get((mk, pick), pick))}</td><td>{o:.2f}</td>'
                     f'<td>{pct(pm) if pm is not None else "—"}</td><td>{pct(ps) if ps is not None else "—"}</td>'
                     f'<td class="{pc_cls}">{pct(pc) if pc is not None else "—"}{" ✓" if agree else ""}</td>'
                     f'<td class="{ev_cls}">{f"{ev:+.1f}%" if ev is not None else "—"}</td></tr>')
    why = (f'<p class="why">{form_line(m["home"], sv["home_form"])} {form_line(m["away"], sv["away_form"])}</p>' if sv else
           '<p class="why">Bu lig için takım geçmişi verisi yok (Avrupa kupaları ve milli maçlar). İstatistik görüşü boş.</p>')
    mbs = f' · <span class="tag">en az {m["mbs"]} maçla oynanır</span>' if m["mbs"] > 1 else ""
    cbox = espn_block(m["code"]) + claude_box(cr) + (absence_chips(cr["blind"]) if cr and cr.get("blind") else "")
    return f"""
<details class="match"><summary><time>{tr_time(m['start'], day=True)}</time><div><div class="tm">{esc(m['home'])} – {esc(m['away'])}</div><div class="lg">{esc(m['league'])}{mbs}</div></div>{tag}</summary>
<div class="views"><table><tr><th>Bahis</th><th>Nesine</th><th>Piyasa</th><th>İstatistik</th><th>Yapay zekâ</th><th>Değer</th></tr>{rows}</table>
{why}
{cbox}
<p class="acc">İsabet geçmişi (5.200 maç): <b>piyasa</b> ±2 puan kalibre · <b>istatistik</b> piyasadan daha az isabetli, tek başına izlenirse geçmişte −12% · <b>Yapay zekâ</b> {CLAUDE_ACC} (✓ = piyasayla 5 puan içinde uyuşuyor).</p>
</div></details>"""


# ----------------------------------------------------------------- sayfa
def build():
    nes_rows = read_jsonl("records/nesine/*.jsonl")
    pin_rows = read_jsonl("records/pinnacle/*.jsonl")
    alerts = read_jsonl("records/alerts/*.jsonl")
    all_claude = [r for r in read_jsonl("records/claude/*.jsonl") if r.get("blind")]
    claude_rows = {r["code"]: r for r in all_claude}
    global CLAUDE_ACC
    scored = [r for r in all_claude if isinstance(r.get("result"), dict) and r["result"].get("brier_market", {}).get("MS") is not None]
    if scored:
        bc = sum(r["result"]["brier_claude"]["MS"] for r in scored) / len(scored)
        bm = sum(r["result"]["brier_market"]["MS"] for r in scored) / len(scored)
        CLAUDE_ACC = (f"{len(scored)} maçta ölçüldü: isabet puanı {bc:.3f}, piyasa {bm:.3f} (küçük iyi) — "
                      + ("Yapay zekâ önde" if bc < bm else "piyasa önde") + "; 100 maçtan önce yorum yapmayın")
    else:
        CLAUDE_ACC = "henüz ölçülmedi"
    status = json.load(open("records/status.json", encoding="utf-8")) if os.path.exists("records/status.json") else {}
    if os.path.exists("records/quota.json"):  # kota ve son Pinnacle bilgisi gözcünün dosyasından
        status.update(json.load(open("records/quota.json", encoding="utf-8")))
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
    global ESPN_BY
    ESPN_BY = espn.load_all()
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
    pin_old = pin_age is not None and pin_age > 10
    # sonraki güncelleme zamanları: Nesine = bekçi 20 dk'da bir (gözcü açıkken 10 dk); piyasa = gözcünün planı, kapalıysa sıradaki maça 100 dk kala
    nes_next = (datetime.fromisoformat(t_nes) + timedelta(minutes=10 if watch.get("active") else 20)) if t_nes else None
    if watch.get("active") and watch.get("next_pinnacle"):
        pin_next = datetime.fromisoformat(watch["next_pinnacle"])
    else:
        nxt_m = min((m["start"] for m in nm if m["start"] > now), default=None)
        pin_next = (nxt_m - timedelta(minutes=100)) if nxt_m else None
    def nxt_html(t):
        if not t:
            return ""
        return f' · sonraki <b class="nxt" data-next="{t.isoformat()}">{countdown(t, now)}</b>'
    pills = (f'<li><span class="pulse{"" if live else " off"}"></span>Nesine <b class="ago" data-ts="{t_nes or ""}">{ago(nes_age)}</b> kontrol edildi{nxt_html(nes_next)}</li>'
             f'<li>Dünya piyasası <b class="ago" data-ts="{t_pin or ""}">{ago(pin_age)}</b>{nxt_html(pin_next)}</li>')
    if watch.get("active"):
        pills += f'<li>Gözcü açık · <b>{esc(watch.get("note", ""))}</b></li>'
    if SHADOW:
        pills += '<li class="shadow">Gölge test · para oynanmıyor, her fırsat puanlanıyor</li>'
    sub = f'<ul class="pills">{pills}</ul>'
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
        al_html += (f'<li><time>{tr_time(a["t"])}</time><div>{esc(a["home"])} – {esc(a["away"])}<small><span class="pb">{esc(PICK_SHORT.get((a["market"], a["pick"]), a["pick"]))}</span>{MARKET_TR.get(a["market"], a["market"])} · '
                    f'Nesine {a["nesine_odds"]:.2f} · adil {a["fair_odds"]:.2f} · +%{a["ev_pct"]:.1f} · kasanın %{a["stake"]:.1f}\'i (50 TL için ≥{(value.min_bankroll_for(a["stake"]) or 0):,} TL kasa)</small></div>'
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
    no_by_key = {c["key"]: c.get("no") for c in past}
    cp_html = ""
    if cps.get("value"):
        cp_html += combo_card("Değerli kupon", cps["value"], 0, "sadece eşik üstü maçlar", no_by_key.get(coupon_key("value", cps["value"])))
    for i, c in enumerate(cps.get("safest", [])):
        cp_html += combo_card("En güvenli", c, i + 1, "en yüksek gelme ihtimali", no_by_key.get(coupon_key("safest", c)))
    for i, c in enumerate(cps.get("balanced", [])):
        cp_html += combo_card("Dengeli", c, i + 4, "bacak oranları 1.50–2.50", no_by_key.get(coupon_key("balanced", c)))
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

    n_alerts = len(alerts); n_cards = len(cards); n_claude = len(all_claude); n_soon = len(soon)
    import hashlib
    SOCIAL_HASH = hashlib.sha256(os.environ.get("SOCIAL_PASS", "analiz2026").encode("utf-8")).hexdigest()
    social_html = ""
    # paket numaraları: kalıcı, ilk görüldüğünde atanır (records/posts.jsonl); yalnızca kayıtçı (RECORD_COUPONS) yeni numara verir
    post_log = "records/posts.jsonl"
    post_no = {}
    for r in read_jsonl(post_log):
        post_no[r["key"]] = r["no"]
    def pno(key, label):
        if key in post_no:
            return post_no[key]
        if not RECORD_COUPONS:
            return None
        n = max(post_no.values(), default=0) + 1
        post_no[key] = n
        with open(post_log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"key": key, "no": n, "label": label, "t": now.isoformat(timespec="seconds")}, ensure_ascii=False) + "\n")
        return n
    try:
        import instagram as ig
        for dd in sorted(glob.glob("docs/social/*"), reverse=True)[:2]:
            day_name = os.path.basename(dd)
            day_matches = [m for m in nesine_matches(nes_last) if m["start"].astimezone(TR).strftime("%Y-%m-%d") == day_name]
            posts = ""
            n = 0
            for m in sorted(day_matches, key=lambda x: x["start"]):
                mp = f"{dd}/match_{m['code']}.jpg"
                if not os.path.exists(mp):
                    continue
                n += 1
                imgs = [f"social/{day_name}/match_{m['code']}.jpg"]
                if os.path.exists(f"{dd}/yorum_{m['code']}.jpg"):
                    imgs.append(f"social/{day_name}/yorum_{m['code']}.jpg")
                if os.path.exists(f"{dd}/story_{m['code']}.jpg"):
                    imgs.append(f"social/{day_name}/story_{m['code']}.jpg")
                cap = ig.caption_for(m, claude_rows.get(m["code"]), probs_by_code.get(m["code"]))
                tiles = "".join(f'<a class="tile" href="{u}" download><img src="{u}" alt="" loading="lazy"><span>{"story · kadro" if "/story_" in u else ("1 · maç kartı" if i == 0 else "2 · yorum kartı")}</span></a>' for i, u in enumerate(imgs))
                num = pno(f"{day_name}:{m['code']}", f"{m['home']} – {m['away']}")
                posts += f"""<div class="post"><div class="post-h"><b>{('Paket #' + str(num)) if num else 'Paket'} · {esc(m['home'])} – {esc(m['away'])}</b><span class="when">{tr_time(m['start'], day=True)} · {esc(m['league'])}</span></div>
<div class="tiles small">{tiles}</div>
<div class="cap"><textarea readonly rows="7">{esc(cap)}</textarea><button type="button" class="copy">Açıklamayı kopyala</button></div></div>"""
            if posts:
                social_html += f'<h3>{day_name}</h3>{posts}'
    except Exception as e:
        social_html = f'<div class="empty">Paylaşım paketleri üretilemedi: {esc(type(e).__name__)}</div>'
    if not social_html:
        social_html = '<div class="empty">Henüz kart üretilmedi; Bekçi saatte bir üretir.</div>'
    cnt = lambda n: f'<span class="cnt">{n}</span>' if n else ""
    return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>İddia Bot</title>
<meta name="description" content="Nesine oranlarını dünya piyasasıyla karşılaştıran deneme sayfası.">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=Source+Sans+3:wght@400;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body><div class="wrap">
<div class="topbar"><div class="brand">İddia Bot<small>Nesine oranı dünya piyasasından yüksek mi? · gölge test</small></div><div class="clock">{tr_time(now)} TSİ</div></div>

<section class="board">
  <h1 class="verdict">{verdict}</h1>
  {sub}
  {facts}
</section>

<nav class="tabs" id="tabs">
  <a href="#bugun" data-tab="bugun" class="on">Bugün{cnt(n_cards)}</a>
  <a href="#uyarilar" data-tab="uyarilar">Uyarılar{cnt(n_alerts)}</a>
  <a href="#kuponlar" data-tab="kuponlar">Kuponlar</a>
  <a href="#gecmis" data-tab="gecmis">Geçmiş</a>
  <a href="#maclar" data-tab="maclar">Maçlar{cnt(n_soon)}</a>
  <a href="#claude" data-tab="claude">Yapay zekâ{cnt(n_claude)}</a>
  <a href="#hareket" data-tab="hareket">Oran hareketi</a>
  <a href="#nasil" data-tab="nasil">Nasıl çalışır</a>
</nav>

<section class="panel on" id="p-bugun">
<h2>Fırsatlar <small>şu anki kayıtlara göre</small></h2>
<p class="lead">Fırsat = Nesine oranı adil orandan en az <b>%3</b> yüksek, oran <b>3.00'ın altında</b>, dünya piyasası verisi <b>10 dakikadan taze</b>. <a class="q" href="#nasil" data-go="nasil">Bu ne demek?</a></p>
{cards_html}
<h3>Eşiğe en yakın bahisler</h3>
<p class="lead">Çubuk ne kadar sağdaysa Nesine o kadar cömert; koyu çizgi +%3 eşiği. Çoğunun solda kalması Nesine'nin normal hâlidir.</p>
<div class="card">{f'<ul class="list">{rows_html}</ul>' if rows_html else '<div class="empty">Henüz karşılaştırma yok.</div>'}
<div class="legend"><span><i style="background:#A9B5AE"></i>geride</span><span><i style="background:var(--sodium)"></i>yaklaşıyor (−%5 içinde)</span><span><i style="background:var(--signal)"></i>eşiği geçti</span></div></div>
</section>

<section class="panel" id="p-uyarilar">
<h2>Gözcü uyarıları <small>maç saatine yakın yakalananlar</small></h2>
<p class="lead">{al_lead} <a class="q" href="#nasil" data-go="nasil">Gözcü nedir?</a></p>
{f'<div class="card"><ul class="alerts">{al_html}</ul></div>' if al_html else '<div class="empty"><b>Henüz uyarı yok.</b> Gözcü maç saatine yakın açılır; Nesine dünya piyasasından geç kaldığında ilk satır burada belirir.</div>'}
</section>

<section class="panel" id="p-kuponlar">
<h2>Kupon önerileri <small>önümüzdeki 48 saat, 3–5 maç</small></h2>
<p class="note"><b>Açık konuşalım:</b> "En güvenli" kupon en sık tutan kupondur ama uzun vadede en çok kaybettiren de odur. Nesine'de bir kupon en az <b>50 TL</b>; her kuponun altında 50 TL yatırsanız ne ödeyeceği ve uzun vadede kaçının gideceği yazıyor. Karar sizin. <a class="q" href="#nasil" data-go="nasil">Kombine nasıl hesaplanır?</a></p>
{cp_html}
</section>

<section class="panel" id="p-gecmis">
<h2>Geçmiş kuponlar <small>önerilenler tuttu mu?</small></h2>
<p class="lead">Her önerilen kupon ilk göründüğü anda kilitlenir; maçlar bitince tuttu mu bakılır. Tahmin değil, kayıt. <a class="q" href="#nasil" data-go="nasil">Ayrıntı</a></p>
{past_coupons_html(past)}
</section>

<section class="panel" id="p-maclar">
<h2>Yaklaşan maçlar <small>üç görüş yan yana · 48 saat</small></h2>
<p class="lead">Maça tıklayın: Nesine oranı · <b>Piyasa</b> ihtimali · <b>İstatistik</b> ihtimali · <b>Yapay zekâ</b> ihtimali · Değer. Altında iki takımın son maçları. <a class="q" href="#nasil" data-go="nasil">Üç görüş nedir?</a></p>
{md_html}
</section>

<section class="panel" id="p-claude">
<h2>Yapay zekânın analizleri <small>son 12 · maç bitince de kalır</small></h2>
<p class="lead">Yapay zekâ maça 100 dk kala haberleri okur, <b>oranı görmeden</b> ihtimal verir, sonra piyasaya itirazı var mı söyler. Her kartta üç sistemden ikisi yan yana: büyük yüzde yapay zekânın, küçük yüzde piyasanın ihtimali (üçüncü sistem, takım istatistiği, Maçlar sekmesinde). Maç bitince gerçekleşen sonuç yeşil işaretlenir ve hangisinin daha isabetli olduğu yazılır. Genel isabet: <b>{CLAUDE_ACC}</b>.</p>
{claude_section(all_claude)}
</section>

<section class="panel" id="p-hareket">
<h2>İddaa oranları hareket ediyor mu?</h2>
<p class="lead">{ch_lead} Yeşil ▲ oran yükseldi, turuncu ▼ düştü; "maça kalan" değişimin maçtan ne kadar önce olduğunu gösterir.</p>
{f'<div class="card"><ul class="changes">{ch_html}</ul></div>' if ch_html else '<div class="empty">Henüz oran değişimi görülmedi; kayıtlar birikiyor.</div>'}
</section>

<section class="panel" id="p-paylasim">
<h2>Paylaşım kartları <small>Instagram için · son 3 gün</small></h2>
<div id="lock" class="empty"><b>Bu bölüm şifrelidir.</b> <input id="pw" type="password" placeholder="Şifre" style="margin:0 8px;padding:6px 10px;border:1px solid var(--line);border-radius:8px"> <button id="pwb" style="padding:6px 14px;border-radius:8px;border:1px solid var(--board);background:var(--board);color:#fff;cursor:pointer">Aç</button> <span id="pwmsg" style="color:var(--ember)"></span></div>
<template id="social-tpl">
<p class="lead">Gönderi paketleri, maç saatine göre sıralı. Her paket: görseller (kaydetmek için tıklayın) + hazır açıklama (Kopyala). Instagram'da "Gönderi" → görselleri sırayla seçin → açıklamayı yapıştırın.</p>
{social_html}
</template>
<div id="social-out"></div>
</section>

<section class="panel" id="p-nasil">
<h2>Bu sayfa ne yapıyor?</h2>
<ul class="steps">
  <li><b>1 · Dünya piyasasını okur</b><p>Pinnacle, dünyanın en keskin bahis borsası sayılır: oranları milyonlarca dolarlık parayla saniyeler içinde düzelir. Onu "gerçek ihtimal" ölçütü olarak kullanıyoruz; orada hesabımız yok.</p></li>
  <li><b>2 · Nesine ile karşılaştırır</b><p>Her maçta Nesine'nin oranı, Pinnacle'dan çıkan adil oranla yan yana konur. Nesine daha yüksek veriyorsa fark bizim lehimize: buna "değer" diyoruz.</p></li>
  <li><b>3 · Üç görüşü yan yana koyar</b><p>Piyasa, takım geçmişinden istatistik, Yapay zekânın haber okuması. Hepsinin geçmiş isabeti yazılır. Geçmiş 5.000 maçta: piyasa en isabetli; değer, 3.00 altı oranlarda gerçek, sürprizlerde yanıltıcı.</p></li>
  <li><b>4 · Kararı size bırakır</b><p>Bot para yatırmaz. Uyarıları, ihtimalleri ve kuponların gerçek maliyetini gösterir; sonradan her uyarıyı puanlar ki hangi görüşe güvenileceğini zamanla veri söylesin.</p></li>
</ul>
<h3>Sözlük</h3>
<ul class="gloss">
  <li><b>Adil oran ve fırsat</b><span class="plain">Bir maçta ev sahibinin kazanma ihtimali gerçekte %50 ise adil oran 2.00'dır (100 ÷ 50). Nesine 2.10 veriyorsa hak ettiğinizden fazla ödüyor demektir: fırsat. 1.85 veriyorsa (çoğu zaman öyle) fırsat yoktur.</span></li>
  <li><b>Gözcü</b><span class="plain">Maçtan 1-2 saat önce kadrolar açıklanır, sakatlıklar duyulur. Dünya piyasası bunu saniyeler içinde orana yansıtır; Nesine bazen geç kalır. Gözcü o anları yakalamak için maç saatine yakın sürekli bakar. Ücretsiz veri kotası yüzünden dünya piyasası verisi yalnızca bu pencerede çekilir; diğer saatlerde "X saat önce" yazar.</span></li>
  <li><b>Yatırım tutarı ve 50 TL kuralı</b><span class="plain">Kartta "kasa payı %2" gibi bir oran yazar; bu matematiğin önerdiği pay. Nesine'de bir kupon en az 50 TL olduğu için kartta ayrıca "bu oran için gereken kasa" yazar (örn. %2 için 2.500 TL). Kasanız daha küçükse 50 TL'lik tek kupon bile önerilenden çok daha büyük risktir.</span></li>
  <li><b>Kombine (kupon)</b><span class="plain">Birkaç maçı tek kupona yazmak; hepsi tutmalı. Oranlar çarpılır ama ihtimaller de çarpılır: %70 ihtimalli 3 maç bir arada %34 eder. Nesine her maçtan payını aldığı için (marj) kombinede bu pay katlanır.</span></li>
  <li><b>Geçmiş kuponlar</b><span class="plain">Önerilen her kupon ilk göründüğü anda kilitlenir (o an oynanmış sayılır). Maçlar bitince tuttu mu bakılır; bir bacağı kaybettiği an "tutmadı" olur. Böylece "en güvenli" kuponun gerçekten kazandırıp kazandırmadığı sayılarla görünür.</span></li>
  <li><b>Üç görüş</b><span class="plain"><b>Piyasa</b>: Pinnacle oranından hesaplanan ihtimal. <b>İstatistik</b>: iki takımın son 2-3 sezondaki gollerinden Poisson modeli (geçmişte piyasadan daha az isabetli; tek başına izlenirse −12%). <b>Yapay zekâ</b>: haberleri okuyan dil modeli; oranı görmeden tahmin eder, sonra piyasaya itirazı var mı söyler. "Değer" sütunu: Nesine oranı piyasa ihtimaline göre fazla mı az mı.</span></li>
  <li><b>Gölge test</b><span class="plain">Para oynanmıyor. Her fırsat kaydediliyor, maç bitince sonucu ve kapanış oranıyla puanlanıyor. 200 uyarı sonunda kapanış oranını ortalama +%2 geçiyorsa yöntem kanıtlanmış sayılır; o zaman kasa konuşulur.</span></li>
</ul>
</section>

<footer>Sayfa her 20 dakikada otomatik yenilenir; yatırım tavsiyesi değildir. Gerçekçi hedef: uzun vadede yatırılan paranın %2–5'i. Fırsatsız günler normaldir.
<br>Kaynak kod: <a href="https://github.com/boradmir/iddia-bot">github.com/boradmir/iddia-bot</a></footer>
</div>
<script>
(function(){{
  function ago(ms){{var m=Math.floor(ms/60000); if(m<1) return "az önce"; if(m<60) return m+" dk önce"; if(m<2880) return Math.floor(m/60)+" saat önce"; return Math.floor(m/1440)+" gün önce";}}
  function left(ms){{var m=Math.floor(ms/60000); if(ms<=60000) return "birazdan"; if(m<60) return "~"+m+" dk"; if(m<1440) return "~"+Math.floor(m/60)+" sa "+(m%60)+" dk"; var d=new Date(Date.now()+ms); return d.toLocaleString("tr-TR",{{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"}});}}
  function tick(){{var now=Date.now();
    document.querySelectorAll("b.ago[data-ts]").forEach(function(e){{var t=Date.parse(e.dataset.ts); if(!isNaN(t)) e.textContent=ago(now-t);}});
    document.querySelectorAll("b.nxt[data-next]").forEach(function(e){{var t=Date.parse(e.dataset.next); if(!isNaN(t)) e.textContent=left(t-now);}});}}
  tick(); setInterval(tick, 30000);
}})();
(function(){{
  var tabs=document.querySelectorAll('#tabs a[data-tab]'),panels=document.querySelectorAll('.panel');
  function show(id){{
    if(!document.getElementById('p-'+id)) id='bugun';   // menüde olmayan (gizli) paneller de açılabilir
    tabs.forEach(function(a){{ a.classList.toggle('on', a.dataset.tab===id); }});
    panels.forEach(function(p){{ p.classList.toggle('on', p.id==='p-'+id); }});
    try{{ localStorage.setItem('tab', id); }}catch(e){{}}
  }}
  document.addEventListener('click', function(ev){{
    var a=ev.target.closest('a[data-tab],a[data-go]'); if(!a) return;
    ev.preventDefault(); var id=a.dataset.tab||a.dataset.go; show(id); history.replaceState(null,'','#'+id);
    if(a.dataset.go) document.getElementById('tabs').scrollIntoView({{behavior:'smooth',block:'start'}});
  }});
  var h=location.hash.replace('#',''); var saved=null; try{{ saved=localStorage.getItem('tab'); }}catch(e){{}}
  show(h||saved||'bugun');
  // Paylaşım kapısı
  var HASH='{SOCIAL_HASH}';
  async function sha(s){{ var b=new TextEncoder().encode(s); var d=await crypto.subtle.digest('SHA-256',b); return Array.from(new Uint8Array(d)).map(function(x){{return x.toString(16).padStart(2,'0')}}).join(''); }}
  function unlock(){{ var t=document.getElementById('social-tpl'); var o=document.getElementById('social-out'); if(t&&o){{ o.innerHTML=t.innerHTML; document.getElementById('lock').style.display='none'; }} }}
  try{{ if(sessionStorage.getItem('social_ok')===HASH) unlock(); }}catch(e){{}}
  var btn=document.getElementById('pwb');
  if(btn) btn.addEventListener('click', async function(){{ var v=document.getElementById('pw').value; var hh=await sha(v);
    if(hh===HASH){{ try{{ sessionStorage.setItem('social_ok',HASH); }}catch(e){{}} unlock(); }} else {{ document.getElementById('pwmsg').textContent='Yanlış şifre'; }} }});
  var pw=document.getElementById('pw'); if(pw) pw.addEventListener('keydown', function(ev){{ if(ev.key==='Enter') btn.click(); }});
  document.addEventListener('click', function(ev){{ var c=ev.target.closest('button.copy'); if(!c) return; var ta=c.parentElement.querySelector('textarea');
    navigator.clipboard.writeText(ta.value).then(function(){{ c.textContent='Kopyalandı ✓'; c.classList.add('ok'); setTimeout(function(){{ c.textContent='Açıklamayı kopyala'; c.classList.remove('ok'); }}, 2000); }}); }});
}})();
</script>
</body></html>"""


if __name__ == "__main__":
    import sys
    RECORD_COUPONS = "--record-coupons" in sys.argv
    os.makedirs("docs", exist_ok=True)
    page = build()
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(page)
    print(f"docs/index.html yazıldı ({len(page)} bayt)")
