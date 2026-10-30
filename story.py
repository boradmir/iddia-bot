"""Story kartı (1080×1920): kadrolar açıklandığında — iki takımın 11'i + dizilişi, kadro notu ("Biz ne düşünüyoruz"),
uluslararası piyasanın o anki ihtimali. Kartta yapay zekâ, oran, bahis geçmez.
Kullanım: story.story_card(m, rosters, note, pm, out_path)
  rosters: espn.fetch_match(...)["rosters"] → {takım: {"formation": "4-2-3-1", "starters": [{"no","player","pos"}], ...}}
"""
import html
from PIL import Image, ImageDraw
import logo, match, social
from social import (font, wrap, text, tr_upper, tr_date, save, team_style, GREEN, GREEN2, GREEN3, YELLOW, CREAM, INK,
                    WHITE, PALE, HANDLE, DISCLAIMER, TR)

SW, SH = 1080, 1920
SAFE_TOP, SAFE_BOTTOM = 200, 200   # Instagram'ın üst/alt arayüzü için boş pay


def clean_name(s):
    """ESPN adlarındaki HTML varlıklarını ve bozuk büyük/küçük harfi düzelt: 'Bahad&#305;R Han' → 'Bahadır Han'."""
    s = html.unescape(s or "").strip()
    def fix(w):
        if len(w) <= 3 and w.isupper():
            return w
        return w[0].upper() + w[1:].lower() if any(ch.isupper() for ch in w[1:]) or w.islower() else w
    return " ".join("-".join(fix(p) for p in w.split("-")) for w in s.split())


def short_name(s, f, max_w):
    """Sığmıyorsa ilk adı baş harfe indir: 'Victor Osimhen' → 'V. Osimhen'."""
    s = clean_name(s)
    if f.getlength(s) <= max_w:
        return s
    parts = s.split()
    if len(parts) >= 2:
        s2 = f"{parts[0][0]}. {' '.join(parts[1:])}"
        if f.getlength(s2) <= max_w:
            return s2
        s = " ".join(parts[1:])
    while f.getlength(s + "…") > max_w and len(s) > 3:
        s = s[:-1]
    return s + "…" if f.getlength(s) > max_w else s


def background(th):
    img = social.gradient(SW, SH, th)
    return Image.alpha_composite(img.convert("RGBA"), social.motif_overlay(SW, SH, th)).convert("RGB")


def find_roster(rosters, team_name):
    best, score = None, 0.0
    for k, v in (rosters or {}).items():
        sc = match.similarity(team_name, k)
        if sc > score:
            best, score = v, sc
    return best if score >= 0.5 else None


def _fg(c1, c2):
    return c2 if sum(c2) > sum(c1) else WHITE


def lineup_column(d, x, y, w, team, roster, er, box=GREEN3):
    c1, c2, _ = team_style(team, er)
    d.rounded_rectangle((x, y, x + w, y + 64), radius=16, fill=c1)
    f = font("display", 34)
    while f.getlength(team) > w - 120 and f.size > 22:
        f = font("display", f.size - 2)
    d.text((x + 18, y + 32), team, font=f, fill=_fg(c1, c2), anchor="lm")
    form = (roster or {}).get("formation") or "—"
    d.text((x + w - 18, y + 32), form, font=font("displaysemi", 30), fill=_fg(c1, c2), anchor="rm")
    y += 80
    fn, fp = font("semi", 27), font("display", 24)
    starters = (roster or {}).get("starters") or []
    for p in starters[:11]:
        d.rounded_rectangle((x, y, x + 52, y + 40), radius=10, fill=box)
        d.text((x + 26, y + 20), str(p.get("no") or "·"), font=fp, fill=YELLOW, anchor="mm")
        d.text((x + 66, y + 20), short_name(p.get("player"), fn, w - 66), font=fn, fill=WHITE, anchor="lm")
        y += 46
    if not starters:
        d.text((x, y + 10), "Kadro henüz açıklanmadı", font=font("body", 26), fill=PALE)
        y += 60
    return y


def story_card(m, rosters, note, pm, out_path, er=None):
    th = social.theme(m.get("sport_key")); img = background(th); d = ImageDraw.Draw(img)
    start = m["start"].astimezone(TR)
    y = SAFE_TOP
    # üst etiket + logo/handle
    text(d, (60, y), tr_upper("Kadrolar açıklandı"), font("displaysemi", 30), YELLOW)
    mk = logo.mark_image(54); hx = int(SW - 60 - font("semi", 26).getlength(HANDLE))
    text(d, (SW - 60, y), HANDLE, font("semi", 26), WHITE, anchor="ra")
    img.paste(mk, (hx - 14 - mk.width, y + 12 - mk.height // 2), mk)
    y += 56
    fh = font("display", 72); title = f"{m['home']} – {m['away']}"
    while fh.getlength(title) > SW - 120:
        fh = font("display", fh.size - 4)
    text(d, (60, y), title, fh, WHITE); y += fh.size + 14
    text(d, (60, y), f"{tr_date(m['start'])} · {start:%H:%M} · {m.get('league', '')}", font("body", 28), PALE); y += 70
    # iki sütun kadro
    cw = (SW - 120 - 30) / 2
    y1 = lineup_column(d, 60, y, cw, m["home"], find_roster(rosters, m["home"]), er, th["box"])
    y2 = lineup_column(d, 60 + cw + 30, y, cw, m["away"], find_roster(rosters, m["away"]), er, th["box"])
    y = max(y1, y2) + 20
    text(d, (60, y), "Kaynak: ESPN · kulüplerin açıkladığı ilk 11", font("body", 22), (150, 175, 160)); y += 50
    # piyasa satırı
    if pm and pm.get("MS"):
        ms = pm["MS"]; hc1, _, _ = team_style(m["home"], er); ac1, _, _ = team_style(m["away"], er)
        text(d, (60, y), tr_upper("Uluslararası piyasa şu an"), font("displaysemi", 24), YELLOW); y += 38
        bw = (SW - 120 - 24) / 3
        best = max(ms.values())
        for i, (lab, p, c) in enumerate([(m["home"], ms["1"], hc1), ("Beraberlik", ms["X"], th["box"]), (m["away"], ms["2"], ac1)]):
            x = 60 + i * (bw + 12); top = p == best
            d.rounded_rectangle((x, y, x + bw, y + 104), radius=16, fill=c, outline=YELLOW if top else None, width=4 if top else 0)
            fg = WHITE if (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) < 150 else INK
            d.text((x + 18, y + 8), f"%{p * 100:.0f}", font=font("display", 56), fill=fg)
            fl = font("semi", 21); lab2 = lab
            while fl.getlength(lab2) > bw - 36 and len(lab2) > 4:
                lab2 = lab2[:-1]
            d.text((x + 18, y + 72), lab2, font=fl, fill=fg)
        y += 118
        # 2.5 alt/üst ve karşılıklı gol: dört küçük kutu
        small = []
        if pm.get("AU25"):
            small += [("3+ gol", pm["AU25"].get("Üst")), ("2 veya az gol", pm["AU25"].get("Alt"))]
        if pm.get("KG"):
            small += [("Karşılıklı gol", pm["KG"].get("Var"))]
        small = [(l, p) for l, p in small if p is not None]
        if small:
            sw = (SW - 120 - 12 * (len(small) - 1)) / len(small)
            for i, (lab, p) in enumerate(small):
                x = 60 + i * (sw + 12)
                d.rounded_rectangle((x, y, x + sw, y + 84), radius=14, fill=th["box"])
                d.text((x + 16, y + 6), f"%{p * 100:.0f}", font=font("display", 42), fill=WHITE)
                fl = font("semi", 19); lab2 = lab
                while fl.getlength(lab2) > sw - 30 and len(lab2) > 4:
                    lab2 = lab2[:-1]
                d.text((x + 16, y + 56), lab2, font=fl, fill=PALE)
            y += 108
    # dipnot yeri (güvenli alanın üstünde) → kadro notu için kalan yükseklik
    f2 = font("body", 22); dl = wrap(DISCLAIMER, f2, SW - 120)
    yb = SH - SAFE_BOTTOM - 30 * len(dl)
    avail = yb - 40 - y
    # kadro notu: sığana kadar yazıyı küçült
    maxw = SW - 160
    for size in range(29, 20, -1):
        f = font("body", size); lh = int(size * 1.38)
        lines = wrap(note, f, maxw)
        box_h = 66 + lh * len(lines) + 26
        if box_h <= avail:
            break
    d.rounded_rectangle((60, y, SW - 60, y + box_h), radius=22, fill=CREAM)
    d.text((80, y + 12), "BİZ NE DÜŞÜNÜYORUZ", font=font("displaysemi", 26), fill=GREEN)
    yy = y + 58
    for ln in lines:
        d.text((80, yy), ln, font=f, fill=INK); yy += lh
    d.line((60, yb - 16, SW - 60, yb - 16), fill=(60, 95, 78), width=2)
    for ln in dl:
        d.text((60, yb), ln, font=f2, fill=(170, 190, 180)); yb += 30
    save(img, out_path)
    return out_path
