"""Reels stili: TAKTİK TAHTASI. reels.py'nin akışını (ses, altyazı, zaman çizelgesi, kodlama) kullanır; zemin ve sahneleri değiştirir.
Tebeşir dokulu yazı ve çizgiler; saha, oyuncu noktaları ve pas okları "çizilerek" belirir.
Kullanım (deneme): python reels_board.py --demo
"""
import math, random, sys, json, os
from PIL import Image, ImageDraw, ImageFilter
import reels, social, logo
from reels import W, H, M_L, M_R, SUB_Y, ease_out_cubic, clamp
from social import font, wrap, tr_upper, team_style, YELLOW, TR, HANDLE, DISCLAIMER

BOARD = (16, 46, 34)          # tahta yeşili
BOARD2 = (10, 32, 24)
CHALK = (238, 234, 222)
CHALK_DIM = (190, 196, 184)
RED_CHALK = (235, 110, 96)
YEL_CHALK = (248, 214, 110)

_NOISE = None
def noise():
    global _NOISE
    if _NOISE is None:
        _NOISE = [Image.effect_noise((W, H), 70).convert("L") for _ in range(3)]
    return _NOISE


def chalk_layer():
    return Image.new("RGBA", (W, H), (0, 0, 0, 0))


_MASKS = {}
def _mask(strength, seed):
    key = (round(strength, 2), seed % 3)
    if key not in _MASKS:
        n = noise()[seed % 3].point(lambda p: 255 - int((255 - p) * strength))
        _MASKS[key] = n.point(lambda p: 255 if p > 60 else int(p * 2))
    return _MASKS[key]


def chalkify(layer, strength=0.55, seed=0):
    """Katmandaki alfa kanalını tebeşir dokusuyla parçalar (gren), hafif yumuşatır. Yalnız dolu bölgede çalışır (hız)."""
    a = layer.split()[3]; bb = a.getbbox()
    if not bb:
        return layer
    bb = (max(0, bb[0] - 2), max(0, bb[1] - 2), min(W, bb[2] + 2), min(H, bb[3] + 2))
    sub = a.crop(bb); m = _mask(strength, seed).crop(bb)
    sub = Image.composite(sub, Image.new("L", sub.size, 0), m).filter(ImageFilter.GaussianBlur(0.6))
    a.paste(sub, bb); layer.putalpha(a)
    return layer


def chalk_text(img, text, f, xy, fill=CHALK, anchor="la", alpha=1.0, seed=0):
    layer = chalk_layer(); d = ImageDraw.Draw(layer)
    d.text(xy, text, font=f, fill=fill + (int(255 * alpha),), anchor=anchor)
    img.alpha_composite(chalkify(layer, 0.5, seed))


def chalk_words(img, text, f, x0, y0, max_w, t_since, fill=CHALK, stagger=0.07, dur=0.22, line_h=None):
    """Kelime kelime tebeşirle yazılır (kelime 'belirir')."""
    line_h = line_h or int(f.size * 1.15)
    lines = wrap(text, f, max_w); idx = 0; y = y0
    for ln in lines:
        x = x0
        for w in ln.split():
            k = ease_out_cubic(clamp((t_since - idx * stagger) / dur))
            if k > 0:
                chalk_text(img, w, f, (x, y), fill=fill, alpha=k, seed=idx)
            x += f.getlength(w + " "); idx += 1
        y += line_h
    return y


def jitter(p, amt=1.6, seed=0):
    r = random.Random(int(p[0] * 7 + p[1] * 13 + seed))
    return (p[0] + r.uniform(-amt, amt), p[1] + r.uniform(-amt, amt))


def chalk_line(layer_draw, pts, width=6, fill=CHALK, progress=1.0, seed=0):
    """Çoklu çizgi; progress 0→1 ile çizilerek belirir."""
    if len(pts) < 2:
        return
    total = sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
    budget = total * clamp(progress)
    drawn = []
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]; seg = math.dist(a, b)
        if budget <= 0:
            break
        if seg <= budget:
            drawn.append((jitter(a, seed=seed), jitter(b, seed=seed + 1))); budget -= seg
        else:
            k = budget / seg; drawn.append((jitter(a, seed=seed), (a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k))); budget = 0
    for a, b in drawn:
        layer_draw.line((a, b), fill=fill + (255,), width=width)
        for p in (a, b):
            layer_draw.ellipse((p[0] - width / 2, p[1] - width / 2, p[0] + width / 2, p[1] + width / 2), fill=fill + (255,))


def chalk_circle(layer_draw, c, r, width=6, fill=CHALK, progress=1.0, seed=0):
    pts = [(c[0] + r * math.cos(math.radians(a)), c[1] + r * math.sin(math.radians(a))) for a in range(-90, 271, 6)]
    chalk_line(layer_draw, pts, width, fill, progress, seed)


def pitch(img, t, progress=1.0, seed=0):
    """Saha: dış çizgi, orta çizgi, orta yuvarlak, iki ceza sahası; çizilerek belirir."""
    layer = chalk_layer(); d = ImageDraw.Draw(layer)
    L, R, T, B = 96, W - 96, 300, 1340
    p = clamp(progress)
    chalk_line(d, [(L, T), (R, T), (R, B), (L, B), (L, T)], 6, CHALK, min(1, p * 1.6), seed)
    chalk_line(d, [(L, (T + B) / 2), (R, (T + B) / 2)], 5, CHALK, clamp((p - 0.3) / 0.4), seed + 1)
    chalk_circle(d, (W / 2, (T + B) / 2), 150, 5, CHALK, clamp((p - 0.45) / 0.4), seed + 2)
    chalk_line(d, [(300, T), (300, T + 210), (W - 300, T + 210), (W - 300, T)], 5, CHALK, clamp((p - 0.6) / 0.4), seed + 3)
    chalk_line(d, [(300, B), (300, B - 210), (W - 300, B - 210), (W - 300, B)], 5, CHALK, clamp((p - 0.6) / 0.4), seed + 4)
    img.alpha_composite(chalkify(layer, 0.45, seed))


def dot(img, c, color, r=24, t=1.0, label=None, f=None):
    k = ease_out_cubic(clamp(t))
    if k <= 0:
        return
    layer = chalk_layer(); d = ImageDraw.Draw(layer)
    rr = r * (0.6 + 0.4 * k)
    d.ellipse((c[0] - rr, c[1] - rr, c[0] + rr, c[1] + rr), fill=color + (int(255 * k),), outline=CHALK + (int(255 * k),), width=4)
    img.alpha_composite(chalkify(layer, 0.25))
    if label and f:
        chalk_text(img, label, f, (c[0], c[1] + rr + 10), fill=CHALK, anchor="ma", alpha=k)


def background(frame_i, th=None):
    """Tahta: koyu yeşil, tebeşir tozu, vinyet, üstte ince sarı şerit."""
    img = Image.new("RGB", (W, H), BOARD); d = ImageDraw.Draw(img)
    for y in range(0, H, 2):
        t = y / H; d.rectangle((0, y, W, y + 1), fill=tuple(int(BOARD[i] + (BOARD2[i] - BOARD[i]) * t) for i in range(3)))
    dust = noise()[frame_i % 3].point(lambda p: int(p * 0.06))
    img = Image.composite(Image.new("RGB", (W, H), (200, 210, 195)), img, dust)
    img = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), img, reels.vignette())
    img = img.convert("RGBA")
    ImageDraw.Draw(img).rectangle((0, 0, W, 12), fill=YELLOW)
    return img


# ----------------------------------------------------------------- sahneler
def scene_hook(img, d, t, hook, th):
    m = reels.scene_hook.m
    pitch(img, t, progress=clamp(t / 1.2) * 0.35 + 0.65 * 0 if False else clamp(t / 1.0))
    f = font("display", 96)
    y = chalk_words(img, tr_upper(hook), f, M_L, 380, W - M_L - M_R, t, stagger=0.06, dur=0.2, line_h=104)
    layer = chalk_layer(); dd = ImageDraw.Draw(layer)
    chalk_line(dd, [(M_L, y + 16), (M_L + 220, y + 16)], 8, YEL_CHALK, clamp((t - 0.6) / 0.3)); img.alpha_composite(chalkify(layer, 0.4))
    if t > 0.9:
        k = ease_out_cubic(clamp((t - 0.9) / 0.3)); start = m["start"].astimezone(TR)
        chalk_text(img, tr_upper(f"{m['home']} – {m['away']}"), font("display", 60), (M_L, y + 50), fill=CHALK, alpha=k)
        chalk_text(img, tr_upper(f"{social.DAYS_TR[start.weekday()]} {start:%H:%M} · {m.get('league','')}"), font("displaysemi", 32), (M_L, y + 125), fill=CHALK_DIM, alpha=k)


def scene_market(img, d, t, m, pm, er):
    pitch(img, t, 1.0)
    ms = pm["MS"]; hc, _, _ = team_style(m["home"], er); ac, _, _ = team_style(m["away"], er)
    chalk_text(img, tr_upper("Dünya bu maça ne diyor?"), font("displaysemi", 38), (M_L, 330), fill=YEL_CHALK)
    # üç tebeşir dairesi: boyut ihtimale göre; içinde yüzde (sayaç)
    cols = [("1", m["home"], hc, 300), ("X", "Beraberlik", (70, 90, 80), 540), ("2", m["away"], ac, 780)]
    for i, (key, lab, col, cx) in enumerate(cols):
        k = ease_out_cubic(clamp((t - i * 0.15) / 0.6))
        r = 70 + 160 * ms[key] * k
        cy = 820
        layer = chalk_layer(); dd = ImageDraw.Draw(layer)
        dd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=col + (int(120 * k),))
        chalk_circle(dd, (cx, cy), r, 6, CHALK, k, seed=i)
        img.alpha_composite(chalkify(layer, 0.35, i))
        if k > 0.2:
            chalk_text(img, f"%{ms[key]*100*k:.0f}", font("display", int(60 + 70 * ms[key])), (cx, cy), fill=CHALK, anchor="mm", alpha=k)
            chalk_text(img, tr_upper(lab), font("displaysemi", 30), (cx, cy + r + 16), fill=CHALK_DIM, anchor="ma", alpha=k)
    if "AU25" in pm and "KG" in pm and t > 1.4:
        k = ease_out_cubic(clamp((t - 1.4) / 0.25))
        chalk_text(img, f"3+ GOL %{pm['AU25']['Üst']*100:.0f}   ·   KARŞILIKLI GOL %{pm['KG']['Var']*100:.0f}", font("displaysemi", 34), (W / 2, 1160), fill=CHALK_DIM, anchor="ma", alpha=k)


def scene_absences(img, d, t, absences, th):
    pitch(img, t, 1.0)
    chalk_text(img, tr_upper("Eksikler · haberlere göre"), font("displaysemi", 38), (M_L, 330), fill=YEL_CHALK)
    f = font("display", 64); y = 420
    for i, a in enumerate(absences[:4]):
        k = ease_out_cubic(clamp((t - i * 0.18) / 0.3))
        if k <= 0:
            break
        nm = a["player"]
        chalk_text(img, nm, f, (M_L + 20, y), fill=CHALK, alpha=k)
        # üstünü çiz: cezalı kırmızı, diğerleri beyaz
        wlen = f.getlength(nm)
        kx = ease_out_cubic(clamp((t - i * 0.18 - 0.25) / 0.25))
        layer = chalk_layer(); dd = ImageDraw.Draw(layer)
        col = RED_CHALK if a.get("status") == "cezalı" else CHALK
        chalk_line(dd, [(M_L + 10, y + 42), (M_L + 30 + wlen, y + 30)], 8, col, kx, seed=i)
        img.alpha_composite(chalkify(layer, 0.4, i))
        chalk_text(img, tr_upper(a.get("status", "")), font("displaysemi", 30), (M_L + 40 + wlen, y + 22), fill=col, alpha=k)
        y += 110
    if not absences:
        chalk_text(img, "Bilinen eksik yok", f, (M_L + 20, 420))


def scene_risk(img, d, t, risk, th):
    pitch(img, t, 1.0)
    m = reels.scene_hook.m; hc, _, _ = team_style(m["home"]); ac, _, _ = team_style(m["away"])
    # sol kanattan pas-koşu oku + savunma noktaları
    pts = [(250, 1000), (330, 840), (440, 700), (560, 560)]
    layer = chalk_layer(); dd = ImageDraw.Draw(layer)
    chalk_line(dd, pts, 9, YEL_CHALK, clamp((t - 0.2) / 0.8), seed=3)
    img.alpha_composite(chalkify(layer, 0.35, 3))
    if t > 1.0:
        k = ease_out_cubic(clamp((t - 1.0) / 0.2)); x, y = pts[-1]
        layer = chalk_layer(); dd = ImageDraw.Draw(layer)
        dd.polygon([(x - 26 * k, y + 30), (x + 26 * k, y + 30), (x, y - 26 * k)], fill=YEL_CHALK + (255,)); img.alpha_composite(chalkify(layer, 0.3))
    for i, p in enumerate(pts[:3]):
        dot(img, p, hc, 22, (t - 0.2 - i * 0.2) / 0.3)
    for i, p in enumerate(((520, 420), (700, 380), (640, 520))):
        dot(img, p, ac, 22, (t - 0.1 - i * 0.15) / 0.3)
    chalk_text(img, tr_upper("Bizi düşündüren"), font("displaysemi", 38), (M_L, 1060), fill=YEL_CHALK)
    f = font("display", 64)
    while len(wrap(tr_upper(risk), f, W - M_L - M_R)) > 3 and f.size > 44:
        f = font("display", f.size - 4)
    chalk_words(img, tr_upper(risk), f, M_L, 1110, W - M_L - M_R, max(0, t - 0.3), stagger=0.06, dur=0.22, line_h=int(f.size * 1.12))


def scene_question(img, d, t, question, th):
    pitch(img, t, 1.0)
    chalk_words(img, tr_upper(question), font("display", 104), M_L, 420, W - M_L - M_R, t, fill=YEL_CHALK, stagger=0.07, dur=0.24, line_h=112)
    chalk_text(img, "Yoruma yazın · Maçtan sonra karşılaştırırız", font("semi", 36), (M_L, 820), fill=CHALK_DIM)
    mk = logo.eye_mark(150, fg=CHALK, acc=YEL_CHALK)
    img.paste(mk, ((W - mk.width) // 2, 980), mk)
    chalk_text(img, "ANALİZ VE ÖTESİ", font("display", 56), (W / 2, 1170), fill=CHALK, anchor="ma")
    chalk_text(img, HANDLE, font("semi", 32), (W / 2, 1240), fill=CHALK_DIM, anchor="ma")
    chalk_text(img, DISCLAIMER, font("body", 26), (M_L, 1580), fill=CHALK_DIM)


def subtitle(img, d, words, t, f):
    """Altyazı tebeşirle (reels.subtitle ile aynı mantık, tebeşir doku)."""
    if not words:
        return
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= 4 or w["w"].endswith((".", "?", ":")):
            chunks.append(cur); cur = []
    if cur: chunks.append(cur)
    active = next((ch for ch in chunks if ch[0]["t"] - 0.05 <= t <= ch[-1]["t"] + ch[-1]["d"] + 0.35), None)
    if not active:
        return
    text = " ".join(w["w"] for w in active); lines = wrap(text, f, W - M_L - M_R); y = SUB_Y; i = 0
    for ln in lines:
        x = (W - f.getlength(ln)) / 2
        for wd in ln.split():
            ww = active[i] if i < len(active) else None
            if ww and ww["t"] <= t <= ww["t"] + ww["d"] + 0.08: col, a = YEL_CHALK, 1.0
            elif ww and t > ww["t"]: col, a = CHALK, 1.0
            else: col, a = CHALK, 0.45
            chalk_text(img, wd, f, (x, y), fill=col, alpha=a); x += f.getlength(wd + " "); i += 1
        y += int(f.size * 1.15)


def install():
    """reels.py'nin zemin/sahne/altyazı fonksiyonlarını tahta stiliyle değiştirir."""
    reels.background = background
    reels.scene_hook = scene_hook; reels.scene_market = scene_market; reels.scene_absences = scene_absences
    reels.scene_risk = scene_risk; reels.scene_question = scene_question; reels.subtitle = subtitle
    # RGBA karelerle çalış: render içinde ImageDraw.Draw(img) RGBA'da sorunsuz; kaydederken RGB'ye çevir
    _save = Image.Image.save
    def save_rgb(self, fp, *a, **k):
        if self.mode == "RGBA" and str(fp).lower().endswith(".jpg"):
            return _save(self.convert("RGB"), fp, *a, **k)
        return _save(self, fp, *a, **k)
    Image.Image.save = save_rgb


if __name__ == "__main__" and "--demo" in sys.argv:
    from datetime import datetime
    install()
    d = json.load(open("data/demo/fb_test.json", encoding="utf-8"))
    m = d["m"]; m["start"] = datetime.fromisoformat(m["start"]); bl = d["res"]["blind"]
    pm = {"MS": {"1": 0.72, "X": 0.17, "2": 0.11}, "AU25": {"Alt": 0.35, "Üst": 0.65}, "KG": {"Var": 0.45, "Yok": 0.55}}
    r = reels.render(m, bl, pm, None, "data/demo/reels_board.mp4")
    print(json.dumps(r, ensure_ascii=False, indent=1))
