"""Analiz ve Ötesi logosu v2 — taktik tahtası "A": 11 oyuncu noktası pas çizgileriyle bir A oluşturur;
çapraz çubuk sağ bacağın ötesine taşan SARI nokta ile biter ("ötesi"). Yüksek çözünürlükte çizilip küçültülür (yumuşak kenar).

Çıktı (assets/brand ve docs/brand):
  v2_profile.png   1080×1080  yalnız işaret, yeşil degrade zemin
  v2_wordmark.png  1080×1080  işaret + ANALİZ / VE ÖTESİ
  v2_wide.png      1600×600   yatay
  v2_light.png     1080×1080  açık zemin sürümü (krem)
  v3_*.png         alternatif yön: altıgen top paneli + radar çizgisi
Kullanım: python logo.py
"""
import math, os, shutil
from PIL import Image, ImageDraw, ImageFont

GREEN, GREEN2, YELLOW, WHITE, CREAM, INK = (11, 42, 31), (16, 66, 48), (255, 207, 77), (255, 255, 255), (247, 243, 233), (14, 38, 30)
FONT = "assets/fonts/BarlowCondensed-Bold.ttf"
FONT_SEMI = "assets/fonts/BarlowCondensed-SemiBold.ttf"
OUT = "assets/brand"
SS = 4  # süper örnekleme


def canvas(w, h, light=False):
    W, H = w * SS, h * SS
    img = Image.new("RGB", (W, H), CREAM if light else GREEN); d = ImageDraw.Draw(img)
    if not light:
        for y in range(H):
            t = y / H; d.line((0, y, W, y), fill=tuple(int(GREEN[i] + (GREEN2[i] - GREEN[i]) * t) for i in range(3)))
    return img


def finish(img, w, h):
    return img.resize((w, h), Image.LANCZOS)


def pitch_lines(d, W, H, color):
    """Hafif saha dokusu: orta yuvarlak + orta çizgi."""
    r = int(min(W, H) * 0.40)
    d.ellipse((W / 2 - r, H / 2 - r, W / 2 + r, H / 2 + r), outline=color, width=max(2, W // 400))
    d.line((W * 0.06, H / 2, W * 0.94, H / 2), fill=color, width=max(2, W // 400))


def a_mark(d, cx, cy, s, dot=WHITE, line=(255, 255, 255), beyond=YELLOW, dark_bg=True):
    """Taktik tahtası A. s = A yüksekliği. 11 nokta + 1 'ötesi' noktası."""
    apex = (cx, cy - s * 0.50)
    lf = (cx - s * 0.40, cy + s * 0.50)
    rf = (cx + s * 0.40, cy + s * 0.50)
    legs = []
    for foot in (lf, rf):
        pts = [(apex[0] + (foot[0] - apex[0]) * k / 4, apex[1] + (foot[1] - apex[1]) * k / 4) for k in range(1, 5)]
        legs.append(pts)
    # çapraz çubuk: bacakların %60 seviyesinde, iki nokta; sağa 'ötesi' noktası
    yb = apex[1] + (lf[1] - apex[1]) * 0.62
    xl = apex[0] + (lf[0] - apex[0]) * 0.62
    xr = apex[0] + (rf[0] - apex[0]) * 0.62
    bar = [(xl + (xr - xl) * 1 / 3, yb), (xl + (xr - xl) * 2 / 3, yb)]
    beyond_pt = (xr + (xr - xl) * 0.42, yb)
    r = s * 0.072
    lw = max(2, int(s * 0.018))
    # pas çizgileri
    for pts in legs:
        prev = apex
        for p in pts:
            d.line((prev, p), fill=line, width=lw); prev = p
    d.line(((xl, yb), beyond_pt), fill=line, width=lw)
    # çizgi alfa etkisi yerine: çizgi rengi zaten yumuşak verilir
    # noktalar
    for p in [apex] + legs[0] + legs[1] + bar:
        d.ellipse((p[0] - r, p[1] - r, p[0] + r, p[1] + r), fill=dot)
    # ötesi noktası: sarı, biraz büyük, ince halka
    rb = r * 1.18
    d.ellipse((beyond_pt[0] - rb * 1.45, beyond_pt[1] - rb * 1.45, beyond_pt[0] + rb * 1.45, beyond_pt[1] + rb * 1.45), outline=beyond, width=lw)
    d.ellipse((beyond_pt[0] - rb, beyond_pt[1] - rb, beyond_pt[0] + rb, beyond_pt[1] + rb), fill=beyond)


def hex_mark(d, cx, cy, s, fg=WHITE, accent=YELLOW):
    """Alternatif: top paneli altıgen + içinde radar/veri çizgisi (ötesine taşan)."""
    pts = [(cx + s * 0.5 * math.cos(math.radians(60 * i - 30)), cy + s * 0.5 * math.sin(math.radians(60 * i - 30))) for i in range(6)]
    lw = max(3, int(s * 0.07))
    d.polygon(pts, outline=fg, width=lw)
    # veri çizgisi: altıgenin içinden girip sağ üstten dışarı çıkar
    path = [(cx - s * 0.32, cy + s * 0.22), (cx - s * 0.12, cy + 0.02 * s), (cx + s * 0.02, cy + s * 0.16), (cx + s * 0.18, cy - s * 0.12), (cx + s * 0.62, cy - s * 0.52)]
    d.line(path, fill=accent, width=lw, joint="curve")
    for p in path[:-1]:
        d.ellipse((p[0] - lw * 0.9, p[1] - lw * 0.9, p[0] + lw * 0.9, p[1] + lw * 0.9), fill=accent)
    e = path[-1]
    d.ellipse((e[0] - lw * 1.3, e[1] - lw * 1.3, e[0] + lw * 1.3, e[1] + lw * 1.3), fill=accent)


def wordmark_text(d, cx, y, scale, fill1, fill2, center=True):
    f1 = ImageFont.truetype(FONT, int(150 * scale)); f2 = ImageFont.truetype(FONT_SEMI, int(78 * scale))
    anchor = "mm" if center else "lm"
    d.text((cx, y), "ANALİZ", font=f1, fill=fill1, anchor=anchor)
    # harf aralıklı alt satır
    sub = "VE ÖTESİ"
    spaced = " ".join(sub)  # geniş aralık
    d.text((cx, y + 118 * scale), spaced, font=f2, fill=fill2, anchor=anchor)


def render_all():
    os.makedirs(OUT, exist_ok=True)
    soft = (120, 160, 140)
    # v2 profil
    img = canvas(1080, 1080); d = ImageDraw.Draw(img); W = H = 1080 * SS
    pitch_lines(d, W, H, (28, 70, 52))
    a_mark(d, W / 2, H / 2 + 40 * SS, 620 * SS, line=soft)
    finish(img, 1080, 1080).save(f"{OUT}/v2_profile.png")
    # v2 yazılı
    img = canvas(1080, 1080); d = ImageDraw.Draw(img)
    pitch_lines(d, W, H, (28, 70, 52))
    a_mark(d, W / 2, H / 2 - 150 * SS, 440 * SS, line=soft)
    wordmark_text(d, W / 2, 790 * SS, SS, WHITE, YELLOW)
    finish(img, 1080, 1080).save(f"{OUT}/v2_wordmark.png")
    # v2 yatay
    img = canvas(1600, 600); d = ImageDraw.Draw(img); W2, H2 = 1600 * SS, 600 * SS
    a_mark(d, 300 * SS, 300 * SS, 400 * SS, line=soft)
    wordmark_text(d, 560 * SS, 265 * SS, SS * 1.15, WHITE, YELLOW, center=False)
    finish(img, 1600, 600).save(f"{OUT}/v2_wide.png")
    # v2 açık zemin
    img = canvas(1080, 1080, light=True); d = ImageDraw.Draw(img)
    a_mark(d, W / 2, H / 2 - 150 * SS, 440 * SS, dot=INK, line=(170, 180, 172), beyond=(232, 168, 0))
    wordmark_text(d, W / 2, 790 * SS, SS, INK, (232, 168, 0))
    finish(img, 1080, 1080).save(f"{OUT}/v2_light.png")
    # v3 alternatif
    img = canvas(1080, 1080); d = ImageDraw.Draw(img)
    pitch_lines(d, W, H, (28, 70, 52))
    hex_mark(d, W / 2, H / 2 + 20 * SS, 620 * SS)
    finish(img, 1080, 1080).save(f"{OUT}/v3_profile.png")
    img = canvas(1080, 1080); d = ImageDraw.Draw(img)
    pitch_lines(d, W, H, (28, 70, 52))
    hex_mark(d, W / 2, H / 2 - 150 * SS, 440 * SS)
    wordmark_text(d, W / 2, 790 * SS, SS, WHITE, YELLOW)
    finish(img, 1080, 1080).save(f"{OUT}/v3_wordmark.png")
    os.makedirs("docs/brand", exist_ok=True)
    for f in os.listdir(OUT):
        if f.startswith(("v2_", "v3_")):
            shutil.copy(f"{OUT}/{f}", f"docs/brand/{f}")
    print("logo:", sorted(f for f in os.listdir(OUT) if f.startswith(("v2_", "v3_"))))


if __name__ == "__main__":
    render_all()
