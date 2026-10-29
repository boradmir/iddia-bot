"""Instagram kartları (1080×1350), yasal şeritte: analiz içeriği, oran/kupon/yatırım YOK, 18+ bilgi notu VAR.
Kartlarda "yapay zekâ" ifadesi geçmez (kullanıcı kararı); yorum "maç önü değerlendirme" olarak sunulur.

Görsel sistem: koyu çim yeşili zemin (saha çizgileri), sarı vurgu, dev kondanse tipografi, renk blokları.
Kartlar:
  - match_<kod>.png : hero (takımlar) · dev ihtimal rakamları · son 5 · golcüler · eksik etiketleri
  - yorum_<kod>.png : tam maç önü değerlendirmesi (alıntı kartı) · risk · kaynaklı haberler
  - injuries.png    : günün eksikleri (maça göre gruplu etiketler)
Çıktı: docs/social/GÜN/ ; 3 günden eski klasörler silinir. Claude çağrısı yok.

Kullanım: python social.py [--date 2026-10-30]
"""
import glob, json, os, shutil, sys
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageDraw, ImageFont
import build_site, espn, prob, odds, match
import logo

W, H = 1080, 1350
GREEN, GREEN2, GREEN3 = (11, 42, 31), (16, 66, 48), (24, 92, 66)
YELLOW, CREAM, INK, INK2, MUTED = (255, 207, 77), (247, 243, 233), (20, 38, 31), (74, 90, 82), (125, 138, 131)
RED, ORANGE, SIGNAL, GREY = (226, 72, 60), (240, 138, 75), (62, 227, 140), (154, 167, 160)
WHITE, PALE = (255, 255, 255), (200, 210, 204)
FONT_DIR = "assets/fonts"
TR = timezone(timedelta(hours=3))
OUT = "docs/social"
HANDLE = "@analizveotesi"
DAYS_TR = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
MONTHS_TR = ["", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


def tr_date(dt):
    """'Cuma, 30 Ekim' biçimi (TSİ)."""
    dt = dt.astimezone(TR)
    return f"{DAYS_TR[dt.weekday()]}, {dt.day} {MONTHS_TR[dt.month]}"
DISCLAIMER = "18+ · Bilgi amaçlıdır; bahis veya yatırım tavsiyesi değildir. Veri: uluslararası piyasa oranları, ESPN. Haber özetleri basından derlenmiştir."


# ----------------------------------------------------------------- araçlar
def font(kind, size):
    if kind in ("display", "displaysemi"):
        return ImageFont.truetype(f"{FONT_DIR}/BarlowCondensed-{'Bold' if kind == 'display' else 'SemiBold'}.ttf", size)
    f = ImageFont.truetype(f"{FONT_DIR}/SourceSans3.ttf", size)
    f.set_variation_by_axes([{"body": 420, "semi": 600, "bold": 700}[kind]])
    return f


def fit(s, f, max_w):
    while f.getlength(s) > max_w and len(s) > 3:
        s = s[:-2].rstrip() + "…"
    return s


def wrap(s, f, max_w):
    lines, cur = [], ""
    for word in s.split():
        t = (cur + " " + word).strip()
        if f.getlength(t) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def text(d, xy, s, f, fill, anchor="la", max_w=None):
    d.text(xy, fit(s, f, max_w) if max_w else s, font=f, fill=fill, anchor=anchor)


def pitch_background():
    """Dikey yeşil degrade + yarı saydam saha çizgileri (orta yuvarlak, orta çizgi, ceza sahası yayı)."""
    img = Image.new("RGB", (W, H), GREEN)
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line((0, y, W, y), fill=tuple(int(GREEN[i] + (GREEN2[i] - GREEN[i]) * t) for i in range(3)))
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0)); od = ImageDraw.Draw(ov)
    line = (255, 255, 255, 26)
    od.ellipse((W / 2 - 300, 720 - 300, W / 2 + 300, 720 + 300), outline=line, width=4)
    od.line((0, 720, W, 720), fill=line, width=4)
    od.arc((W / 2 - 520, H - 120, W / 2 + 520, H + 700), start=200, end=340, fill=line, width=4)
    return Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")


def tr_upper(s):
    """Türkçe büyük harf: i → İ, ı → I (Python upper() i'yi I yapar)."""
    return s.replace("i", "İ").replace("ı", "I").upper()


def topbar(d, label):
    text(d, (60, 50), tr_upper(label), font("displaysemi", 30), YELLOW)
    text(d, (W - 60, 50), HANDLE, font("semi", 26), WHITE, anchor="ra")
    hw = font("semi", 26).getlength(HANDLE)
    mk = logo.mark_image(54)
    d._image.paste(mk, (int(W - 60 - hw - 14 - mk.width), 62 - mk.height // 2), mk)   # küçük marka işareti


def footer(d, dark=True):
    f = font("body", 20)
    lines = wrap(DISCLAIMER, f, W - 120)
    y = H - 34 - 26 * len(lines)
    d.line((60, y - 16, W - 60, y - 16), fill=(60, 95, 78) if dark else (227, 222, 210), width=2)
    for ln in lines:
        d.text((60, y), ln, font=f, fill=(150, 170, 160) if dark else MUTED); y += 26


def pill(d, x, y, s, f, bg, fg, pad=14):
    w = f.getlength(s) + pad * 2
    d.rounded_rectangle((x, y, x + w, y + 44), radius=22, fill=bg)
    d.text((x + pad, y + 22), s, font=f, fill=fg, anchor="lm")
    return x + w + 10


def form_strip(d, x, y, games, size=44):
    sym = {"W": "G", "D": "B", "L": "M"}
    col = {"W": SIGNAL, "D": GREY, "L": ORANGE}
    for g in games:
        d.rounded_rectangle((x, y, x + size, y + size), radius=10, fill=col.get(g["result"], GREY))
        d.text((x + size / 2, y + size / 2), sym.get(g["result"], "?"), font=font("display", int(size * 0.72)), fill=GREEN, anchor="mm")
        x += size + 8
    return x


def status_pill(d, x, y, s, status):
    col = {"sakat": RED, "cezalı": (160, 30, 30), "şüpheli": YELLOW, "döndü": SIGNAL}
    fg = {"sakat": WHITE, "cezalı": WHITE, "şüpheli": GREEN, "döndü": GREEN}
    f = font("semi", 23); w = f.getlength(s) + 28
    d.rounded_rectangle((x, y, x + w, y + 44), radius=22, fill=col.get(status, GREY))
    d.text((x + 14, y + 22), s, font=f, fill=fg.get(status, WHITE), anchor="lm")
    return w


# ----------------------------------------------------------------- takım rozetleri
_COLORS = None


def team_style(name, er=None):
    """(ana renk, ikincil renk, kısaltma): önce kendi tablomuz, sonra ESPN, sonra nötr."""
    global _COLORS
    if _COLORS is None:
        try:
            _COLORS = {k: v for k, v in json.load(open("assets/team_colors.json", encoding="utf-8")).items() if not k.startswith("_")}
        except Exception:
            _COLORS = {}
    def hx(h):
        h = (h or "").lstrip("#")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) if len(h) == 6 else None
    if name in _COLORS:
        c1, c2, ab = _COLORS[name]; return hx(c1), hx(c2), ab
    best, score = None, 0.0
    for k in _COLORS:
        sc = match.similarity(name, k)
        if sc > score:
            best, score = k, sc
    if best and score >= 0.75:
        c1, c2, ab = _COLORS[best]; return hx(c1), hx(c2), ab
    for tname, t in ((er or {}).get("teams") or {}).items():
        if match.similarity(name, tname) >= 0.6:
            c1, c2 = hx(t.get("color")), hx(t.get("alt"))
            if c1 and c1 != (0, 0, 0):
                return c1, (c2 if c2 and c2 != c1 else WHITE), (t.get("abbr") or name[:3]).upper()[:4]
    return GREEN3, YELLOW, name.replace(" ", "")[:3].upper()


def badge(img, d, cx, cy, r, name, er=None):
    """Monogram rozeti: ana renk daire, ikincil renk halka, kısaltma."""
    c1, c2, ab = team_style(name, er)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=c2)
    d.ellipse((cx - r + 6, cy - r + 6, cx + r - 6, cy + r - 6), fill=c1)
    lum = 0.299 * c1[0] + 0.587 * c1[1] + 0.114 * c1[2]
    fg = (20, 20, 20) if lum > 150 else WHITE
    f = font("display", int(r * (0.95 if len(ab) <= 3 else 0.75)))
    d.text((cx, cy + 2), ab, font=f, fill=fg, anchor="mm")


# ----------------------------------------------------------------- kartlar
def match_card(m, pm, ai, er, out_path):
    img = pitch_background(); d = ImageDraw.Draw(img)
    start = m["start"].astimezone(TR)
    hc1, hc2, _ = team_style(m["home"], er); ac1, ac2, _ = team_style(m["away"], er)
    d.rectangle((0, 0, W // 2, 14), fill=hc1); d.rectangle((W // 2, 0, W, 14), fill=ac1)
    d.rectangle((0, 14, W // 2, 20), fill=hc2); d.rectangle((W // 2, 14, W, 20), fill=ac2)
    topbar(d, f"Maç analizi · {start:%d.%m} · {m['league']}")
    fh = font("display", 110)
    home, away = tr_upper(m["home"]), tr_upper(m["away"])
    bx = 60 + 58  # rozet yarıçapı 50 + boşluk
    while fh.getlength(home) > W - bx - 60 - 70 or fh.getlength(away) > W - bx - 60 - 70:
        fh = font("display", fh.size - 6)
    y1 = 104; y2 = 104 + fh.size - 6
    badge(img, d, 60 + 50, y1 + fh.size * 0.55, 50, m["home"], er)
    badge(img, d, 60 + 50, y2 + fh.size * 0.55, 50, m["away"], er)
    text(d, (bx + 70, y1), home, fh, WHITE)
    text(d, (bx + 70, y2), away, fh, YELLOW)
    y = 104 + 2 * fh.size + 4
    ft = font("display", 46)
    text(d, (60, y), f"{start:%H:%M}", ft, WHITE)
    text(d, (60 + ft.getlength(f"{start:%H:%M}") + 16, y + 10), f"{tr_date(m['start'])} · TSİ", font("semi", 26), PALE)
    y += 80
    if pm and "MS" in pm:
        text(d, (60, y), "ULUSLARARASI PİYASANIN İHTİMALİ", font("displaysemi", 26), YELLOW); y += 40
        hc1, hc2, _ = team_style(m["home"], er); ac1, ac2, _ = team_style(m["away"], er)
        def lum(c): return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]
        cols = [(f"{m['home']} kazanır", pm["MS"]["1"], hc1, hc2), ("Beraberlik", pm["MS"]["X"], GREEN3, PALE), (f"{m['away']} kazanır", pm["MS"]["2"], ac1, ac2)]
        best = max(p for _, p, _, _ in cols)
        bw = (W - 120 - 24) / 3
        for i, (lab, p, c1, c2) in enumerate(cols):
            x = 60 + i * (bw + 12); top = p == best
            fill = c1
            fg = (20, 20, 20) if lum(fill) > 150 else WHITE
            d.rounded_rectangle((x, y, x + bw, y + 150), radius=18, fill=fill, outline=YELLOW if top else None, width=5 if top else 0)
            d.rectangle((x + 18, y + 128, x + 18 + int((bw - 36) * p), y + 136), fill=c2 if lum(c2) != lum(fill) else fg)
            d.text((x + 22, y + 14), f"%{p*100:.0f}", font=font("display", 84), fill=fg)
            d.text((x + 22, y + 100), fit(lab, font("semi", 22), bw - 44), font=font("semi", 22), fill=fg)
        y += 168
        if "AU25" in pm and "KG" in pm:
            x = pill(d, 60, y, f"3+ gol  %{pm['AU25']['Üst']*100:.0f}", font("semi", 24), GREEN3, WHITE)
            pill(d, x, y, f"Karşılıklı gol  %{pm['KG']['Var']*100:.0f}", font("semi", 24), GREEN3, WHITE)
            y += 64
    l5 = (er or {}).get("last5") or {}
    leaders = (er or {}).get("leaders") or {}
    if l5 or leaders:
        ph = 240
        d.rounded_rectangle((60, y, W - 60, y + ph), radius=22, fill=CREAM)
        teams = (list(l5.keys()) or list(leaders.keys()))[:2]
        for i, t in enumerate(teams):
            x = 90 + i * ((W - 180) / 2); yy = y + 20
            text(d, (x, yy), t, font("display", 36), INK, max_w=430); yy += 46
            if l5.get(t):
                text(d, (x, yy + 10), "Son 5", font("semi", 20), MUTED)
                form_strip(d, x + 68, yy, l5[t], size=40); yy += 56
            top = [l for l in sorted(leaders.get(t, []), key=lambda r: (-r["goals"], -r["shots"])) if l["goals"] or l["shots"]][:2]
            for l in top:
                d.rounded_rectangle((x, yy, x + 54, yy + 44), radius=10, fill=GREEN)
                d.text((x + 27, yy + 22), str(l["goals"]), font=font("display", 32), fill=YELLOW, anchor="mm")
                text(d, (x + 66, yy - 2), l["player"], font("semi", 26), INK, max_w=330)
                text(d, (x + 66, yy + 24), f"{l['goals']} gol · {l['shots']} şut · sezon", font("body", 19), MUTED)
                yy += 54
        y += ph + 22
    absences = ((ai or {}).get("blind") or {}).get("absences") or []
    if absences:
        text(d, (60, y), "EKSİKLER · HABERLERE GÖRE", font("displaysemi", 26), YELLOW); y += 40
        x = 60
        for a in absences[:6]:
            s = f"{a.get('player', '')} · {a.get('status', '')}"
            w = font("semi", 23).getlength(s) + 28
            if x + w > W - 60:
                x = 60; y += 54
            if y > H - 170:
                break
            status_pill(d, x, y, s, a.get("status")); x += w + 10
        y += 60
    footer(d, dark=True)
    img.save(out_path, "PNG", optimize=True)


def comment_card(m, ai, out_path):
    bl = (ai or {}).get("blind") or {}
    if not bl.get("comment"):
        return False
    img = Image.new("RGB", (W, H), CREAM); d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 230), fill=GREEN)
    start = m["start"].astimezone(TR)
    text(d, (60, 50), tr_upper(f"Maç önü değerlendirme · {tr_date(m['start'])} · {start:%H:%M}"), font("displaysemi", 28), YELLOW)
    text(d, (W - 60, 50), HANDLE, font("semi", 26), WHITE, anchor="ra")
    mk = logo.mark_image(54); d._image.paste(mk, (int(W - 60 - font("semi", 26).getlength(HANDLE) - 14 - mk.width), 62 - mk.height // 2), mk)
    fh = font("display", 70); title = f"{m['home']} – {m['away']}"
    while fh.getlength(title) > W - 120:
        fh = font("display", fh.size - 4)
    text(d, (60, 110), title, fh, WHITE)
    d.text((54, 226), "“", font=font("display", 160), fill=YELLOW)
    y = 352; f = font("body", 30)
    for ln in wrap(bl["comment"], f, W - 120):
        if y > H - 360:
            break
        d.text((60, y), ln, font=f, fill=INK); y += 42
    y += 14
    if bl.get("risk"):
        d.rounded_rectangle((60, y, W - 60, y + 118), radius=18, fill=(255, 243, 204))
        text(d, (84, y + 16), "EN BÜYÜK BELİRSİZLİK", font("displaysemi", 24), (107, 77, 0))
        yy = y + 50
        for ln in wrap(bl["risk"], font("body", 24), W - 170)[:2]:
            d.text((84, yy), ln, font=font("body", 24), fill=INK2); yy += 30
        y += 134
    facts = bl.get("facts") or []
    if facts and y < H - 200:
        text(d, (60, y), "KAYNAKLI HABERLER", font("displaysemi", 24), MUTED); y += 34
        for fct in facts[:3]:
            lines = wrap("• " + fct, font("body", 22), W - 120)[:2]
            if y + 29 * len(lines) > H - 125:  # sığmayan haberi hiç başlatma (yarım satır olmasın)
                break
            for ln in lines:
                d.text((60, y), ln, font=font("body", 22), fill=INK2); y += 29
            y += 4
    footer(d, dark=False)
    img.save(out_path, "PNG", optimize=True)
    return True


def injuries_card(items, day, out_path):
    img = pitch_background(); d = ImageDraw.Draw(img)
    topbar(d, f"Sakatlık bülteni · {day:%d.%m}")
    text(d, (60, 104), "GÜNÜN", font("display", 118), WHITE)
    text(d, (60, 216), "EKSİKLERİ", font("display", 118), YELLOW)
    text(d, (60, 350), "Haberlere göre · sakat, cezalı, şüpheli", font("body", 26), PALE)
    y = 410; cur = None; x = 60
    for it in items[:18]:
        if it["match"] != cur:
            cur = it["match"]; y += 12
            if y > H - 200:
                break
            text(d, (60, y), cur, font("display", 40), WHITE, max_w=W - 120); y += 50; x = 60
        s = f"{it['player']} · {it['status']}"
        w = font("semi", 23).getlength(s) + 28
        if x + w > W - 60:
            x = 60; y += 54
        if y > H - 160:
            break
        status_pill(d, x, y, s, it["status"]); x += w + 10
    if not items:
        text(d, (60, 440), "Bugünkü maçlarda haberlere yansıyan önemli eksik yok.", font("body", 28), WHITE)
    footer(d, dark=True)
    img.save(out_path, "PNG", optimize=True)


# ----------------------------------------------------------------- ana akış
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
        if a or er:
            p = f"{out_dir}/match_{m['code']}.png"; match_card(m, pm, a, er, p); made.append(p)
            p2 = f"{out_dir}/yorum_{m['code']}.png"
            if comment_card(m, a, p2):
                made.append(p2)
    injuries_card(inj, day, f"{out_dir}/injuries.png"); made.append(f"{out_dir}/injuries.png")
    for p in glob.glob(f"{OUT}/*"):
        try:
            if (day - datetime.strptime(os.path.basename(p), "%Y-%m-%d").date()).days > 3:
                shutil.rmtree(p)
        except ValueError:
            pass
    print(f"{len(made)} kart: {out_dir}")


if __name__ == "__main__":
    main()
