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
import glob, json, math, os, random, shutil, sys
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageDraw, ImageFont


def save(img, path):
    """Instagram için JPEG: kalite 95, renk alt örnekleme kapalı (kırmızı/sarı yazılar bulanmasın)."""
    img.convert("RGB").save(path, "JPEG", quality=95, subsampling=0, optimize=True)
import build_site, espn, prob, odds, match
import logo, icons

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
DISCLAIMER = "18+ · Burada kupon yok, okuma var. Karar sizin."


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


# Tema: Avrupa kupalarında farklı zemin (lig maçları yeşil saha). bg/bg2 degrade, box koyu kutu rengi, motif arka plan deseni.
THEMES = {
    "default": {"bg": GREEN, "bg2": GREEN2, "box": GREEN3, "label": None, "motif": "pitch"},
    "soccer_uefa_champs_league": {"bg": (8, 20, 54), "bg2": (16, 36, 92), "box": (30, 56, 118), "label": "Şampiyonlar Ligi", "motif": "stars"},
    "soccer_uefa_europa_league": {"bg": (34, 16, 6), "bg2": (72, 32, 10), "box": (118, 58, 18), "label": "Avrupa Ligi", "motif": "rings"},
    "soccer_uefa_europa_conference_league": {"bg": (6, 32, 36), "bg2": (10, 58, 64), "box": (18, 92, 100), "label": "Konferans Ligi", "motif": "hex"},
    # millî maçlar: koyu kızıl zemin; Türkiye oynuyorsa hilal-yıldız deseni, diğer millî maçlarda yıldızlar
    "soccer_uefa_nations_league": {"bg": (70, 10, 18), "bg2": (124, 20, 32), "box": (156, 36, 48), "label": "Millî maç · Uluslar Ligi", "motif": "stars"},
    "soccer_international_friendlies": {"bg": (70, 10, 18), "bg2": (124, 20, 32), "box": (156, 36, 48), "label": "Millî maç · Hazırlık", "motif": "stars"},
    "soccer_fifa_world_cup_qualifiers_europe": {"bg": (70, 10, 18), "bg2": (124, 20, 32), "box": (156, 36, 48), "label": "Millî maç · Dünya Kupası elemeleri", "motif": "stars"},
    "soccer_euro_qualifiers": {"bg": (70, 10, 18), "bg2": (124, 20, 32), "box": (156, 36, 48), "label": "Millî maç · Avrupa Şampiyonası elemeleri", "motif": "stars"},
}
NATIONAL = {"soccer_uefa_nations_league", "soccer_international_friendlies", "soccer_fifa_world_cup_qualifiers_europe", "soccer_euro_qualifiers"}


def theme(sport_key, m=None):
    th = THEMES.get(sport_key or "", THEMES["default"])
    if sport_key in NATIONAL and m and any("türkiye" in (m.get(k) or "").lower().replace("i\u0307", "i") for k in ("home", "away")):
        th = {**th, "motif": "crescent"}
    return th


def _star(od, cx, cy, r, fill):
    pts = []
    for i in range(10):
        a = math.radians(-90 + i * 36); rr = r if i % 2 == 0 else r * 0.42
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    od.polygon(pts, fill=fill)


def motif_overlay(w, h, th):
    """Yarı saydam desen katmanı: saha çizgileri (lig), yıldızlar (ŞL), halkalar (AL), altıgenler (KL)."""
    ov = Image.new("RGBA", (w, h), (0, 0, 0, 0)); od = ImageDraw.Draw(ov)
    line = (255, 255, 255, 26)
    mid = int(h * 0.533)
    kind = th.get("motif", "pitch")
    if kind == "pitch":
        od.ellipse((w / 2 - 300, mid - 300, w / 2 + 300, mid + 300), outline=line, width=4)
        od.line((0, mid, w, mid), fill=line, width=4)
        od.arc((w / 2 - 520, h - 120, w / 2 + 520, h + 700), start=200, end=340, fill=line, width=4)
    elif kind == "stars":
        rnd = random.Random(7)
        for _ in range(26):
            x, y, r = rnd.uniform(40, w - 40), rnd.uniform(40, h - 40), rnd.uniform(6, 22)
            _star(od, x, y, r, (255, 255, 255, rnd.randint(14, 34)))
        od.ellipse((w / 2 - 320, mid - 320, w / 2 + 320, mid + 320), outline=(255, 255, 255, 18), width=4)
    elif kind == "rings":
        cx, cy = w * 0.82, h * 0.62
        for i in range(6):
            r = 120 + i * 110
            od.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(255, 190, 120, 22), width=5)
    elif kind == "crescent":
        # büyük, soluk hilal (iki daire farkı) sağ üstte + beş köşeli yıldız; bayrak kopyası değil, ima
        cx, cy, r = w * 0.74, h * 0.40, 300
        hil = Image.new("L", (w, h), 0); hd = ImageDraw.Draw(hil)
        hd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=40)
        hd.ellipse((cx - r + 95, cy - r + 10, cx + r + 75, cy + r - 10), fill=0)
        ov.paste(Image.new("RGBA", (w, h), (255, 255, 255, 255)), (0, 0), hil)
        _star(od, cx + 150, cy, 70, (255, 255, 255, 44))
        od.line((0, mid, w, mid), fill=line, width=4)
    elif kind == "hex":
        R = 150
        for row in range(-1, int(h / (R * 1.5)) + 2):
            for col in range(-1, int(w / (R * 1.732)) + 2):
                cx = col * R * 1.732 + (R * 0.866 if row % 2 else 0); cy = row * R * 1.5
                pts = [(cx + R * 0.95 * math.cos(math.radians(60 * k + 30)), cy + R * 0.95 * math.sin(math.radians(60 * k + 30))) for k in range(6)]
                od.polygon(pts, outline=(180, 255, 240, 16))
    return ov


def gradient(w, h, th):
    img = Image.new("RGB", (w, h), th["bg"]); d = ImageDraw.Draw(img)
    c1, c2 = th["bg"], th["bg2"]
    for y in range(h):
        t = y / h
        d.line((0, y, w, y), fill=tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3)))
    return img


def pitch_background(th=None):
    """Dikey degrade + temanın yarı saydam deseni (lig: saha çizgileri; Avrupa kupaları: kendi deseni)."""
    th = th or THEMES["default"]
    img = gradient(W, H, th)
    return Image.alpha_composite(img.convert("RGBA"), motif_overlay(W, H, th)).convert("RGB")


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
    f = font("body", 23)
    lines = wrap(DISCLAIMER, f, W - 120)
    y = H - 34 - 30 * len(lines)
    d.line((60, y - 16, W - 60, y - 16), fill=(60, 95, 78) if dark else (227, 222, 210), width=2)
    for ln in lines:
        d.text((60, y), ln, font=f, fill=(170, 190, 180) if dark else MUTED); y += 30


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


def status_icon(d, x, y, status, h=28):
    """Durum simgesi (icons.py, pürüzsüz): cezalı = eğik kırmızı kart, sakat = ilk yardım, şüpheli = soru, döndü = tik."""
    img = d._image
    if status == "cezalı":
        ic = icons.red_card(h + 8); img.paste(ic, (int(x), int(y) - 4), ic); return ic.width + 4
    if status == "sakat":
        ic = icons.medical(h + 2); img.paste(ic, (int(x), int(y) - 1), ic); return h + 6
    if status == "şüpheli":
        ic = icons.question(h + 2); img.paste(ic, (int(x), int(y) - 1), ic); return h + 6
    if status == "döndü":
        ic = icons.check(h + 2); img.paste(ic, (int(x), int(y) - 1), ic); return h + 6
    return 0


def status_pill(d, x, y, s, status):
    """Etiket: simge + metin; metin 'Oyuncu · durum'."""
    col = {"sakat": (120, 30, 30), "cezalı": (90, 20, 20), "şüpheli": (110, 85, 0), "döndü": (20, 90, 50)}
    f = font("semi", 23)
    icon_w = {"cezalı": icons.red_card(36).width + 4, "sakat": 34, "şüpheli": 34, "döndü": 34}.get(status, 0)
    w = f.getlength(s) + 28 + icon_w
    d.rounded_rectangle((x, y, x + w, y + 44), radius=22, fill=col.get(status, GREY))
    status_icon(d, x + 12, y + 8, status, 28)
    d.text((x + 14 + icon_w, y + 22), s, font=f, fill=WHITE, anchor="lm")
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
    th = theme(m.get("sport_key"), m); img = pitch_background(th); d = ImageDraw.Draw(img)
    start = m["start"].astimezone(TR)
    d.rectangle((0, 0, W, 10), fill=YELLOW)
    topbar(d, f"Maç analizi · {start:%d.%m} · {m['league']}")
    fh = font("display", 118)
    home, away = tr_upper(m["home"]), tr_upper(m["away"])
    while fh.getlength(home) > W - 120 or fh.getlength(away) > W - 120:
        fh = font("display", fh.size - 6)
    y1 = 104; y2 = 104 + fh.size - 6
    text(d, (60, y1), home, fh, WHITE)
    text(d, (60, y2), away, fh, YELLOW)
    if m.get("sport_key") in NATIONAL:   # millî maç: armalar her yerde serbest (kullanıcı kararı 31.10.2026)
        import story
        cs = min(104, fh.size - 8)
        for nm_, yy in ((m["home"], y1), (m["away"], y2)):
            c = story.crest_for(nm_, er, cs)
            if c:
                img.paste(c, (W - 60 - cs, yy + (fh.size - cs) // 2), c)
    y = 104 + 2 * fh.size + 4
    ft = font("display", 46)
    text(d, (60, y), f"{start:%H:%M}", ft, WHITE)
    text(d, (60 + ft.getlength(f"{start:%H:%M}") + 16, y + 10), f"{tr_date(m['start'])} · TSİ", font("semi", 26), PALE)
    y += 80
    if pm and "MS" in pm:
        text(d, (60, y), "ULUSLARARASI PİYASANIN İHTİMALİ", font("displaysemi", 26), YELLOW); y += 40
        hc1, hc2, _ = team_style(m["home"], er); ac1, ac2, _ = team_style(m["away"], er)
        def lum(c): return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]
        cols = [(f"{m['home']} kazanır", pm["MS"]["1"], hc1), ("Beraberlik", pm["MS"]["X"], th["box"]), (f"{m['away']} kazanır", pm["MS"]["2"], ac1)]
        best = max(p for _, p, _ in cols)
        bw = (W - 120 - 24) / 3
        for i, (lab, p, c1) in enumerate(cols):
            x = 60 + i * (bw + 12); top = p == best
            fg = (20, 20, 20) if lum(c1) > 150 else WHITE
            d.rounded_rectangle((x, y, x + bw, y + 140), radius=18, fill=c1, outline=YELLOW if top else None, width=5 if top else 0)
            d.text((x + 22, y + 12), f"%{p*100:.0f}", font=font("display", 84), fill=fg)
            d.text((x + 22, y + 100), fit(lab, font("semi", 22), bw - 44), font=font("semi", 22), fill=fg)
        y += 152
        # oranlı şerit: ev | beraberlik | deplasman (takım renkleri)
        x0, x1 = 60, W - 60; tot = x1 - x0
        segs = [(pm["MS"]["1"], hc1), (pm["MS"]["X"], (120, 140, 130)), (pm["MS"]["2"], ac1)]
        xx = x0
        for i, (p, c) in enumerate(segs):
            w = tot * p
            d.rounded_rectangle((xx, y, xx + w - (4 if i < 2 else 0), y + 16), radius=6, fill=c, outline=(255, 255, 255) if lum(c) < 40 else None, width=1)
            xx += w
        y += 30
        if "AU25" in pm and "KG" in pm:
            x = pill(d, 60, y, f"3+ gol  %{pm['AU25']['Üst']*100:.0f}", font("semi", 24), th["box"], WHITE)
            pill(d, x, y, f"Karşılıklı gol  %{pm['KG']['Var']*100:.0f}", font("semi", 24), th["box"], WHITE)
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
                text(d, (x + 66, yy + 24), f"{l['goals']} gol · {l['shots']} şut · sezon", font("body", 21), MUTED)
                yy += 54
        y += ph + 22
    absences = ((ai or {}).get("blind") or {}).get("absences") or []
    if absences:
        text(d, (60, y), "EKSİKLER · HABERLERE GÖRE", font("displaysemi", 26), YELLOW); y += 40
        x = 60
        for a in absences[:6]:
            s = f"{a.get('player', '')} · {a.get('status', '')}"
            w = font("semi", 23).getlength(s) + 28 + 34
            if x + w > W - 60:
                x = 60; y += 54
            if y > H - 170:
                break
            w = status_pill(d, x, y, s, a.get("status")); x += w + 10
        y += 60
    footer(d, dark=True)
    save(img, out_path)


def first_sentence(text_):
    import re
    s = re.split(r"(?<=[.!?])\s+", (text_ or "").strip())
    return s[0] if s else ""


def short_text(text_, max_words):
    """Yazının ilk cümleleri, en fazla max_words kelime; cümle ortasında kesmez."""
    import re
    out, n = [], 0
    for s in re.split(r"(?<=[.!?])\s+", (text_ or "").strip()):
        w = len(s.split())
        if out and n + w > max_words:
            break
        out.append(s); n += w
    return " ".join(out)


def comment_card(m, ai, out_path, er=None):
    comment_card.er = er
    bl = (ai or {}).get("blind") or {}
    if not bl.get("comment"):
        return False
    img = Image.new("RGB", (W, H), CREAM); d = ImageDraw.Draw(img)
    th = theme(m.get("sport_key"), m); d.rectangle((0, 0, W, 230), fill=th["bg"])
    start = m["start"].astimezone(TR)
    mk = logo.mark_image(54); mk_x = int(W - 60 - font("semi", 26).getlength(HANDLE) - 14 - mk.width)
    label = tr_upper(f"Maç önü · Biz ne düşünüyoruz? · {tr_date(m['start'])} · {start:%H:%M}")
    fl = font("displaysemi", 28)
    while fl.getlength(label) > mk_x - 60 - 30 and fl.size > 20:
        fl = font("displaysemi", fl.size - 1)
    text(d, (60, 50 + (28 - fl.size) // 2), label, fl, YELLOW)
    text(d, (W - 60, 50), HANDLE, font("semi", 26), WHITE, anchor="ra")
    d._image.paste(mk, (mk_x, 62 - mk.height // 2), mk)
    fh = font("display", 70); title = f"{m['home']} – {m['away']}"
    while fh.getlength(title) > W - 120:
        fh = font("display", fh.size - 4)
    text(d, (60, 110), title, fh, WHITE)
    if m.get("sport_key") in NATIONAL:
        import story
        x = W - 60
        for nm_ in (m["away"], m["home"]):
            c = story.crest_for(nm_, comment_card.er, 62)
            if c:
                x -= 62; img.paste(c, (x, 110 + (fh.size - 62) // 2), c); x -= 12
    # tez: kalın tek cümle (yapay zekânın "hook" alanı; eski kayıtlarda yazının ilk cümlesi)
    tez = (bl.get("hook") or "").strip() or first_sentence(bl["comment"])
    y = 270; ft = font("display", 46)
    for ln in wrap(tez, ft, W - 120)[:3]:
        d.text((60, y), ln, font=ft, fill=th["bg"]); y += 54
    d.rectangle((60, y + 10, 180, y + 16), fill=YELLOW); y += 44
    # gövde: kart metni (en fazla ~80 kelime); eski kayıtlarda yazının ilk cümleleri
    body = (bl.get("card_text") or "").strip()
    if not body:   # eski kayıt: tez ilk cümleyse gövde ondan sonrasıyla başlasın
        rest = bl["comment"].strip()
        if rest.startswith(tez):
            rest = rest[len(tez):].strip()
        body = short_text(rest or bl["comment"], 80)
    f = font("body", 34)
    for ln in wrap(body, f, W - 120):
        if y > H - 380:
            break
        d.text((60, y), ln, font=f, fill=INK); y += 46
    y += 18
    if bl.get("risk"):
        # kutu metne göre büyür (en çok 5 satır; daha uzunsa son satır üç noktayla biter), metin kesilmez
        rl = wrap(bl["risk"], font("body", 24), W - 170)
        if len(rl) > 5:
            rl = rl[:5]; rl[-1] = rl[-1].rstrip(".,; ") + "…"
        box_h = 50 + 30 * len(rl) + 10
        d.rounded_rectangle((60, y, W - 60, y + box_h), radius=18, fill=(255, 243, 204))
        text(d, (84, y + 16), "EN BÜYÜK BELİRSİZLİK", font("displaysemi", 24), (107, 77, 0))
        yy = y + 50
        for ln in rl:
            d.text((84, yy), ln, font=font("body", 24), fill=INK2); yy += 30
        y += box_h + 16
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
    save(img, out_path)
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
        w = font("semi", 23).getlength(s) + 28 + 34
        if x + w > W - 60:
            x = 60; y += 54
        if y > H - 160:
            break
        w = status_pill(d, x, y, s, it["status"]); x += w + 10
    if not items:
        text(d, (60, 440), "Bugünkü maçlarda haberlere yansıyan önemli eksik yok.", font("body", 28), WHITE)
    footer(d, dark=True)
    save(img, out_path)


# ----------------------------------------------------------------- ana akış
def main():
    day = datetime.strptime(sys.argv[sys.argv.index("--date") + 1], "%Y-%m-%d").date() if "--date" in sys.argv else datetime.now(TR).date()
    rows = build_site.read_jsonl("records/nesine/*.jsonl"); t, last = build_site.recent_snapshot(rows)
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
            p = f"{out_dir}/match_{m['code']}.jpg"; match_card(m, pm, a, er, p); made.append(p)
            p2 = f"{out_dir}/yorum_{m['code']}.jpg"
            if comment_card(m, a, p2, er=er):
                made.append(p2)
    for old in glob.glob(f"{out_dir}/*.png"):
        os.remove(old)   # png → jpg geçişi; bülten kartı da kaldırıldı
    for p in glob.glob(f"{OUT}/*"):
        try:
            if (day - datetime.strptime(os.path.basename(p), "%Y-%m-%d").date()).days > 3:
                shutil.rmtree(p)
        except ValueError:
            pass
    print(f"{len(made)} kart: {out_dir}")


if __name__ == "__main__":
    main()
