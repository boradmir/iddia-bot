"""Story kartı (1080×1920): kadrolar açıklandığında — iki takımın 11'i + dizilişi, kadro notu ("Biz ne düşünüyoruz"),
uluslararası piyasanın o anki ihtimali. Kartta yapay zekâ, oran, bahis geçmez.
Kullanım: story.story_card(m, rosters, note, pm, out_path)
  rosters: espn.fetch_match(...)["rosters"] → {takım: {"formation": "4-2-3-1", "starters": [{"no","player","pos"}], ...}}
"""
import html
from PIL import Image, ImageDraw
import logo, match, social, icons
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


def crest_for(team, er, size):
    """ESPN takım arması (varsa). er = espn.fetch_match kaydı ("teams" içinde logo adresi)."""
    import espn
    for tname, t in ((er or {}).get("teams") or {}).items():
        if match.similarity(team, tname) >= 0.6 and t.get("logo"):
            return espn.team_logo(t["logo"], size)
    return None


def lineup_column(d, x, y, w, team, roster, er, box=GREEN3):
    c1, c2, _ = team_style(team, er)
    d.rounded_rectangle((x, y, x + w, y + 64), radius=16, fill=c1)
    crest = crest_for(team, er, 48)
    tx = x + 18
    if crest:
        d._image.paste(crest, (int(x + 12), int(y + 8)), crest); tx = x + 70
    f = font("display", 34)
    while f.getlength(team) > w - 120 - (52 if crest else 0) and f.size > 22:
        f = font("display", f.size - 2)
    d.text((tx, y + 32), team, font=f, fill=_fg(c1, c2), anchor="lm")
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


def ball_icon(size, dark=(20, 30, 26)):
    """Futbol topu simgesi (RGBA): beyaz top, ortada siyah beşgen, kenarlarda beş siyah parça. 4x çizilip küçültülür."""
    import math
    S = 4; R = size * S / 2; cx = cy = R
    img = Image.new("RGBA", (size * S, size * S), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    d.ellipse((1, 1, size * S - 2, size * S - 2), fill=WHITE, outline=dark, width=max(2, S))
    def pt(r, ang):
        return (cx + r * math.cos(math.radians(ang)), cy + r * math.sin(math.radians(ang)))
    inner = [pt(R * 0.36, -90 + i * 72) for i in range(5)]
    d.polygon(inner, fill=dark)
    for i in range(5):
        a = -90 + i * 72
        p1 = pt(R * 0.36, a); p2 = pt(R * 0.78, a)
        d.line((p1, p2), fill=dark, width=max(2, int(S * 1.5)))
        # kenar parçası: dış halkaya yakın beşgen dilimi
        poly = [pt(R * 0.78, a), pt(R * 0.98, a - 20), pt(R * 0.98, a + 20)]
        d.polygon(poly, fill=dark)
    return img.resize((size, size), Image.LANCZOS)


def _num(v):
    try:
        return float(str(v).replace("%", "").replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def score_card(m, live, kind, out_path, er=None):
    """Devre arası (kind='ht') / maç sonu (kind='ft') story'si: skor, goller, kırmızı kartlar, oranlı istatistik çubukları. Yorum yok."""
    th = social.theme(m.get("sport_key")); img = background(th); d = ImageDraw.Draw(img)
    start = m["start"].astimezone(TR)
    hc1, hc2, _ = team_style(m["home"], er); ac1, ac2, _ = team_style(m["away"], er)
    st = live.get("stats") or {}
    rows = [k for k in ("Topla oynama", "Şut", "İsabetli şut", "Korner", "Faul") if k in (st.get("home") or {}) or k in (st.get("away") or {})]
    # olaylar: goller + kırmızı kartlar her zaman; değişiklikler taraf başına en fazla 6 olay kalacak şekilde (en erken olanlar)
    def _min(g):
        return int("".join(ch for ch in (g.get("minute") or "0").split("+")[0] if ch.isdigit()) or 0)
    evs = []
    for side in ("home", "away"):
        core = [g for g in live.get("goals", []) + live.get("cards", []) if (g.get("side") or "home") == side]
        subs = sorted([g for g in live.get("subs", []) if (g.get("side") or "home") == side], key=_min)
        evs += core + subs[:max(0, 6 - len(core))]
    n_ev = max(len([g for g in evs if (g.get("side") or "home") == "home"]), len([g for g in evs if g.get("side") == "away"]))
    f2 = font("body", 22); dl = wrap(DISCLAIMER, f2, SW - 120)
    yb = SH - SAFE_BOTTOM - 30 * len(dl)
    avail = yb - 40 - SAFE_TOP
    row_h, stat_h = 50, 96
    content_h = 56 + 70 + 70 + 330 + (n_ev * row_h + 30 if n_ev else 70) + (30 + 50 + len(rows) * stat_h if rows else 0) + 50
    def _h():
        return 56 + 70 + 70 + 330 + (n_ev * row_h + 30 if n_ev else 70) + (30 + 50 + len(rows) * stat_h if rows else 0) + 50
    if content_h > avail:   # çok olay varsa satırları sıkıştır
        row_h, stat_h = 42, 84; content_h = _h()
    if content_h > avail and "Faul" in rows:   # hâlâ sığmıyorsa faul satırını düşür
        rows.remove("Faul"); content_h = _h()
    y = SAFE_TOP + max(0, int((avail - content_h) / 2))
    # başlık
    text(d, (60, y), tr_upper("Devre arası" if kind == "ht" else "Maç sonu"), font("displaysemi", 30), YELLOW)
    mk = logo.mark_image(54); hx = int(SW - 60 - font("semi", 26).getlength(HANDLE))
    text(d, (SW - 60, y), HANDLE, font("semi", 26), WHITE, anchor="ra")
    img.paste(mk, (hx - 14 - mk.width, y + 12 - mk.height // 2), mk)
    y += 56
    text(d, (60, y), f"{tr_date(m['start'])} · {start:%H:%M} · {m.get('league', '')}", font("body", 28), PALE); y += 70
    if er and (er.get("teams") or {}):
        y += 70   # armalar için yer
    # skor: takım adları renkli şeritle, büyük beyaz rakamlar, ince ayraç
    half = (SW - 120) / 2
    sh_, sa = live["score"].get("home"), live["score"].get("away")
    fn = font("display", 44)
    for cx, nm, c1, c2, x0 in ((60 + half / 2, m["home"], hc1, hc2, 60), (60 + half + half / 2, m["away"], ac1, ac2, 60 + half)):
        crest = crest_for(nm, er, 72)
        if crest:
            img.paste(crest, (int(cx - 36), int(y - 60)), crest)
        f = fn
        while f.getlength(nm) > half - 40 and f.size > 24:
            f = font("display", f.size - 2)
        d.text((cx, y + 22), nm, font=f, fill=WHITE, anchor="mm")
        d.rounded_rectangle((x0 + 30, y + 54, x0 + half - 30, y + 62), radius=4, fill=c1)
        if c2 and c2 != c1:
            d.rounded_rectangle((x0 + 30, y + 62, x0 + half - 30, y + 66), radius=2, fill=c2)
    fs = font("display", 230)
    d.text((60 + half / 2, y + 200), str(sh_ if sh_ is not None else "-"), font=fs, fill=WHITE, anchor="mm")
    d.text((60 + half + half / 2, y + 200), str(sa if sa is not None else "-"), font=fs, fill=WHITE, anchor="mm")
    d.rounded_rectangle((SW / 2 - 4, y + 130, SW / 2 + 4, y + 270), radius=4, fill=YELLOW)
    y += 330
    # goller + kırmızı kartlar: ev solda, deplasman sağda
    fg_ = font("semi", 30); fm = font("display", 28)
    cols = {"home": 60, "away": 60 + half + 20}
    ys = {"home": y, "away": y}
    events = sorted(evs, key=lambda g: int("".join(ch for ch in g.get("minute", "0") if ch.isdigit()) or 0))
    fs_ = font("semi", 24)
    _BALL = icons.ball(30); _SUB = icons.sub(30); _RED = icons.red_card(34)
    for g in events:
        side = g.get("side") or "home"
        x = cols[side]; yy = ys[side]
        if g.get("kind") == "red":
            img.paste(_RED, (int(x) - 2, int(yy) + 2), _RED)
            d.text((x + 38, yy + 19), short_name(g.get("player") or "", fg_, half - 110), font=fg_, fill=WHITE, anchor="lm")
        elif g.get("kind") == "sub":
            # değişiklik: yeşil ok giren, kırmızı ok çıkan
            img.paste(_SUB, (int(x) - 2, int(yy) + 4), _SUB)
            p_in = short_name(g.get("player") or "", fs_, (half - 130) * 0.55)
            p_out = short_name(g.get("out") or "", fs_, (half - 130) * 0.45)
            d.text((x + 38, yy + 19), p_in, font=fs_, fill=WHITE, anchor="lm")
            d.text((x + 38 + fs_.getlength(p_in) + 10, yy + 19), f"← {p_out}", font=fs_, fill=PALE, anchor="lm")
        else:
            img.paste(_BALL, (int(x) - 2, int(yy) + 4), _BALL)
            label = short_name(g.get("player") or "", fg_, half - 110) + (" (P)" if g.get("pen") else "") + (" (KK)" if g.get("own") else "")
            d.text((x + 38, yy + 19), label, font=fg_, fill=WHITE, anchor="lm")
        d.text((x + half - 30, yy + 19), g.get("minute", ""), font=fm, fill=YELLOW, anchor="rm")
        ys[side] = yy + row_h
    y = max(ys.values()) + (30 if events else 0)
    if not events:
        text(d, (SW / 2, y + 10), "Gol yok", font("body", 28), PALE, anchor="ma"); y += 70
    # istatistik: her satır takım renkli oranlı çubuk; baskın taraf daha uzun
    if rows:
        y += 30
        text(d, (SW / 2, y), tr_upper("İlk yarı" if kind == "ht" else "Maç") + " İSTATİSTİKLERİ", font("displaysemi", 26), YELLOW, anchor="ma"); y += 50
        fv, fl = font("display", 40), font("semi", 25)
        bar_x0, bar_x1, bh = 60, SW - 60, 26
        for k in rows:
            hv = (st.get("home") or {}).get(k, "-"); av = (st.get("away") or {}).get(k, "-")
            hn, an = _num(hv), _num(av)
            tot = hn + an
            share = 0.5 if tot <= 0 else hn / tot
            if k == "Topla oynama":
                hv = f"%{_num(hv):.0f}"; av = f"%{_num(av):.0f}"
            d.text((bar_x0, y + 18), str(hv), font=fv, fill=WHITE if hn >= an else PALE, anchor="lm")
            d.text((SW / 2, y + 18), k, font=fl, fill=PALE, anchor="mm")
            d.text((bar_x1, y + 18), str(av), font=fv, fill=WHITE if an >= hn else PALE, anchor="rm")
            by = y + 48
            d.rounded_rectangle((bar_x0, by, bar_x1, by + bh), radius=bh // 2, fill=th["box"])
            w = bar_x1 - bar_x0 - 6
            hw = int(w * share)
            if hw > 0:
                d.rounded_rectangle((bar_x0, by, bar_x0 + hw + 3, by + bh), radius=bh // 2, fill=hc1)
            if w - hw > 0:
                d.rounded_rectangle((bar_x0 + hw + 3, by, bar_x1, by + bh), radius=bh // 2, fill=ac1)
            y += stat_h
    if y + 40 < yb - 20:
        text(d, (60, y + 6), "Kaynak: ESPN", font("body", 22), (150, 175, 160))
    d.line((60, yb - 16, SW - 60, yb - 16), fill=(60, 95, 78), width=2)
    for ln in dl:
        d.text((60, yb), ln, font=f2, fill=(170, 190, 180)); yb += 30
    save(img, out_path)
    return out_path


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
                d.rounded_rectangle((x, y, x + sw, y + 56), radius=12, fill=th["box"])
                d.text((x + 16, y + 28), f"%{p * 100:.0f}", font=font("display", 34), fill=WHITE, anchor="lm")
                fl = font("semi", 20); lab2 = lab
                while fl.getlength(lab2) > sw - 110 and len(lab2) > 4:
                    lab2 = lab2[:-1]
                d.text((x + sw - 16, y + 28), lab2, font=fl, fill=PALE, anchor="rm")
            y += 76
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
