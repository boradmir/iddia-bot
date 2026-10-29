"""Instagram kartları (1080×1350), yasal şeritte: analiz içeriği, oran/kupon/yatırım YOK, 18+ bilgi notu VAR.

Kartlar:
  - match_<kod>.png  : "Günün maçı" — piyasa ihtimali çubukları, son 5 maç, golcüler (ESPN verisi),
                       eksikler (haberlere göre), kısa analiz (yapay zekâ), bilgi notu
  - injuries.png     : "Sakatlık bülteni" — günün maçlarındaki eksikler (haberlere göre)
Çıktı: docs/social/GÜN/ ; 3 günden eski klasörler silinir. Claude çağrısı yok (kayıtlı analizler kullanılır).

Kullanım: python social.py [--date 2026-10-30]
"""
import glob, json, os, shutil, sys, textwrap
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageDraw, ImageFont
import build_site, espn, prob, odds, match

W, H = 1080, 1350
C = {"bg": (244, 241, 234), "board": (15, 51, 38), "board2": (22, 75, 56), "ink": (20, 38, 31), "ink2": (74, 90, 82), "muted": (125, 138, 131),
     "sodium": (232, 168, 0), "signal": (29, 154, 91), "ember": (209, 97, 42), "line": (227, 222, 210), "card": (255, 255, 255), "chalk": (242, 245, 240), "chalkdim": (185, 199, 191)}
FONT_DIR = "assets/fonts"
TR = timezone(timedelta(hours=3))
OUT = "docs/social"
HANDLE = "@analizveotesi"
DISCLAIMER = "18+ · Bilgi amaçlıdır; bahis veya yatırım tavsiyesi değildir. Veri: dünya bahis borsası (Pinnacle), ESPN; haberler yapay zekâ özetidir."


def font(kind, size):
    if kind == "display":
        return ImageFont.truetype(f"{FONT_DIR}/BarlowCondensed-Bold.ttf", size)
    f = ImageFont.truetype(f"{FONT_DIR}/SourceSans3.ttf", size)
    f.set_variation_by_axes([{"body": 420, "semi": 600, "bold": 700}[kind]])
    return f


def text(d, xy, s, f, fill, anchor="la", max_w=None):
    if max_w:
        while f.getlength(s) > max_w and len(s) > 3:
            s = s[:-2].rstrip() + "…"
    d.text(xy, s, font=f, fill=fill, anchor=anchor)


def wrap(s, f, max_w):
    lines, cur = [], ""
    for word in s.split():
        t = (cur + " " + word).strip()
        if f.getlength(t) <= max_w:
            cur = t
        else:
            if cur: lines.append(cur)
            cur = word
    if cur: lines.append(cur)
    return lines


def rounded(d, box, r, fill, outline=None):
    d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=2 if outline else 0)


def header(d, title, sub, h=250):
    d.rectangle((0, 0, W, h), fill=C["board"])
    text(d, (60, 44), "MAÇ ANALİZİ", font("semi", 24), C["chalkdim"])
    text(d, (W - 60, 44), HANDLE, font("semi", 24), C["sodium"], anchor="ra")
    f = font("display", 76)
    lines = wrap(title, f, W - 120)[:2]
    y = 86
    for ln in lines:
        text(d, (60, y), ln, f, (255, 255, 255)); y += 78
    text(d, (60, h - 48), sub, font("body", 26), C["chalkdim"])


def footer(d):
    f = font("body", 20)
    lines = wrap(DISCLAIMER, f, W - 120)
    y = H - 36 - 26 * len(lines)
    d.line((60, y - 18, W - 60, y - 18), fill=C["line"], width=2)
    for ln in lines:
        text(d, (60, y), ln, f, C["muted"]); y += 26
    text(d, (W - 60, H - 36 - 26 * len(lines) - 44), HANDLE, font("semi", 22), C["board"], anchor="ra")


def section(d, y, label):
    text(d, (60, y), label.upper(), font("semi", 22), C["muted"])
    return y + 34


def bar_row(d, y, label, p, color):
    text(d, (60, y + 6), label, font("semi", 28), C["ink"])
    x0, x1 = 360, W - 60 - 110
    rounded(d, (x0, y + 8, x1, y + 36), 14, (230, 225, 213))
    rounded(d, (x0, y + 8, x0 + max(28, int((x1 - x0) * p)), y + 36), 14, color)
    text(d, (W - 60, y + 4), f"%{p*100:.0f}", font("display", 40), C["ink"], anchor="ra")
    return y + 56


def form_strip(d, x, y, games):
    sym = {"W": "G", "D": "B", "L": "M"}
    col = {"W": C["signal"], "D": (154, 167, 160), "L": C["ember"]}
    for g in games:
        rounded(d, (x, y, x + 40, y + 40), 8, col.get(g["result"], (169, 181, 174)))
        text(d, (x + 20, y + 20), sym.get(g["result"], "?"), font("display", 30), (255, 255, 255), anchor="mm")
        x += 48
    return x


def match_card(m, pm, ai, er, out_path):
    img = Image.new("RGB", (W, H), C["bg"]); d = ImageDraw.Draw(img)
    start = m["start"].astimezone(TR)
    header(d, f"{m['home']} – {m['away']}", f"{start:%d.%m.%Y %H:%M} · {m['league']}")
    y = 290
    # piyasa ihtimali
    if pm and "MS" in pm:
        y = section(d, y, "Dünya bahis borsasının ihtimali")
        y = bar_row(d, y, f"{m['home'][:18]} kazanır", pm["MS"]["1"], C["board2"])
        y = bar_row(d, y, "Beraberlik", pm["MS"]["X"], (154, 167, 160))
        y = bar_row(d, y, f"{m['away'][:18]} kazanır", pm["MS"]["2"], C["sodium"])
        if "AU25" in pm and "KG" in pm:
            text(d, (60, y + 4), f"3+ gol %{pm['AU25']['Üst']*100:.0f}  ·  karşılıklı gol %{pm['KG']['Var']*100:.0f}", font("body", 26), C["ink2"])
            y += 44
        y += 10
    # son 5 + golcüler (iki sütun)
    l5 = (er or {}).get("last5") or {}
    leaders = (er or {}).get("leaders") or {}
    if l5 or leaders:
        y = section(d, y, "Son 5 maç · gol atması en olası (sezon verisi)")
        col_x = [60, 560]
        teams = list(l5.keys())[:2] or list(leaders.keys())[:2]
        maxy = y
        for i, t in enumerate(teams):
            x = col_x[i]; yy = y
            text(d, (x, yy), t, font("semi", 28), C["ink"], max_w=440); yy += 38
            if l5.get(t):
                form_strip(d, x, yy, l5[t]); yy += 52
            for l in sorted(leaders.get(t, []), key=lambda r: (-r["goals"], -r["shots"]))[:2]:
                if not l["goals"] and not l["shots"]:
                    continue
                d.ellipse((x, yy + 7, x + 18, yy + 25), fill=C["board"]); d.ellipse((x + 5, yy + 12, x + 13, yy + 20), fill=(255, 255, 255))
                text(d, (x + 28, yy), l['player'], font("semi", 26), C["ink"], max_w=270)
                text(d, (x + 300, yy + 2), f"{l['goals']} gol · {l['shots']} şut", font("body", 24), C["muted"])
                yy += 34
            maxy = max(maxy, yy)
        y = maxy + 14
    # eksikler
    absences = ((ai or {}).get("blind") or {}).get("absences") or []
    if absences:
        y = section(d, y, "Eksikler · haberlere göre")
        col = {"sakat": C["ember"], "cezalı": (180, 30, 30), "şüpheli": C["sodium"], "döndü": C["signal"]}
        for a in absences[:5]:
            d.ellipse((60, y + 8, 76, y + 24), fill=col.get(a.get("status"), C["muted"]))
            text(d, (90, y), f"{a.get('player', '')}", font("semi", 26), C["ink"], max_w=330)
            text(d, (430, y + 1), f"{a.get('team', '')[:14]} · {a.get('status', '')} · {a.get('role', '')}", font("body", 24), C["ink2"], max_w=590)
            y += 34
        y += 10
    # analiz
    comment = ((ai or {}).get("blind") or {}).get("comment") or ""
    if comment:
        y = section(d, y, "Analiz")
        f = font("body", 26)
        room = max(2, (H - 110 - y) // 34)
        # cümle cümle ekle; sığmayan ilk cümlede dur
        import re
        sents = re.split(r"(?<=[.!?])\s+", comment.strip())
        acc = ""
        for st in sents:
            cand = (acc + " " + st).strip()
            if len(wrap(cand, f, W - 120)) > room:
                break
            acc = cand
        for ln in wrap(acc or sents[0], f, W - 120)[:room]:
            text(d, (60, y), ln, f, C["ink2"]); y += 34
    footer(d)
    img.save(out_path, "PNG", optimize=True)


def injuries_card(items, day, out_path):
    img = Image.new("RGB", (W, H), C["bg"]); d = ImageDraw.Draw(img)
    header(d, "Sakatlık bülteni", f"{day:%d.%m.%Y} · günün maçları · haberlere göre", h=230)
    y = 270
    col = {"sakat": C["ember"], "cezalı": (180, 30, 30), "şüpheli": C["sodium"], "döndü": C["signal"]}
    cur = None
    for it in items[:16]:
        if it["match"] != cur:
            cur = it["match"]; y += 8
            text(d, (60, y), cur, font("display", 34), C["board"], max_w=W - 120); y += 44
        d.ellipse((60, y + 8, 76, y + 24), fill=col.get(it["status"], C["muted"]))
        text(d, (90, y), it["player"], font("semi", 27), C["ink"], max_w=360)
        text(d, (460, y + 2), f"{it['team'][:16]} · {it['status']} · {it['role']}", font("body", 24), C["ink2"], max_w=560)
        y += 36
        if y > H - 200:
            break
    if not items:
        text(d, (60, 300), "Bugünkü maçlarda haberlere yansıyan önemli eksik yok.", font("body", 28), C["ink2"])
    footer(d)
    img.save(out_path, "PNG", optimize=True)


def main():
    day = datetime.strptime(sys.argv[sys.argv.index("--date") + 1], "%Y-%m-%d").date() if "--date" in sys.argv else datetime.now(TR).date()
    rows = build_site.read_jsonl("records/nesine/*.jsonl"); t, last = build_site.latest_snapshot(rows)
    nm = [m for m in build_site.nesine_matches(last) if m["start"].astimezone(TR).date() == day]
    ai = {r["code"]: r for r in build_site.read_jsonl("records/claude/*.jsonl") if r.get("blind")}
    es = espn.load_all()
    pin = build_site.pinnacle_events(build_site.read_jsonl("records/pinnacle/*.jsonl"))
    aliases = json.load(open("aliases.json", encoding="utf-8")) if os.path.exists("aliases.json") else {}
    out_dir = f"{OUT}/{day}"; os.makedirs(out_dir, exist_ok=True)
    made, inj = [], []
    for m, ev, score in match.match_all(nm, pin, aliases):
        pm = None
        if ev and odds.pinnacle_h2h(ev):
            pm = prob.market_probs(odds.pinnacle_h2h(ev), odds.pinnacle_totals(ev))
        a = ai.get(m["code"]); er = es.get(m["code"])
        for x in ((a or {}).get("blind") or {}).get("absences") or []:
            inj.append({"match": f"{m['home']} – {m['away']}", **{k: x.get(k, "") for k in ("team", "player", "status", "role")}})
        if a or er:  # içerik yoksa kart üretme
            p = f"{out_dir}/match_{m['code']}.png"; match_card(m, pm, a, er, p); made.append(p)
    injuries_card(inj, day, f"{out_dir}/injuries.png"); made.append(f"{out_dir}/injuries.png")
    # eski klasörleri sil
    for p in glob.glob(f"{OUT}/*"):
        try:
            if (day - datetime.strptime(os.path.basename(p), "%Y-%m-%d").date()).days > 3:
                shutil.rmtree(p)
        except ValueError:
            pass
    print(f"{len(made)} kart: {out_dir}")


if __name__ == "__main__":
    main()
