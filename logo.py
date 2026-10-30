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
        # vinyet: kenarlara doğru hafif koyulaşma
        vig = Image.new("L", (W, H), 0); vd = ImageDraw.Draw(vig)
        steps = 24
        for i in range(steps):
            k = i / steps
            vd.ellipse((W * (-0.35 + 0.35 * k), H * (-0.35 + 0.35 * k), W * (1.35 - 0.35 * k), H * (1.35 - 0.35 * k)), fill=int(70 * (1 - k)))
        img = Image.composite(Image.new("RGB", (W, H), (4, 18, 12)), img, vig)
    return img


def finish(img, w, h):
    return img.resize((w, h), Image.LANCZOS)


def pitch_lines(d, W, H, color):
    """Hafif saha dokusu: orta yuvarlak + orta çizgi."""
    r = int(min(W, H) * 0.40)
    d.ellipse((W / 2 - r, H / 2 - r, W / 2 + r, H / 2 + r), outline=color, width=max(2, W // 400))
    d.line((W * 0.06, H / 2, W * 0.94, H / 2), fill=color, width=max(2, W // 400))
    r2 = int(min(W, H) * 0.47)
    d.ellipse((W / 2 - r2, H / 2 - r2, W / 2 + r2, H / 2 + r2), outline=(36, 84, 62), width=max(2, W // 600))


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
    beyond_pt = (xr + (xr - xl) * 0.55, yb)
    r = s * 0.068
    lw = max(2, int(s * 0.02))
    # pas çizgileri
    for pts in legs:
        prev = apex
        for p in pts:
            d.line((prev, p), fill=line, width=lw); prev = p
    d.line(((xl, yb), beyond_pt), fill=line, width=lw)
    # ötesi için yumuşak hale (katmanlı yarı saydam daireler)
    base_img = d._image
    halo = Image.new("RGBA", base_img.size, (0, 0, 0, 0)); hd = ImageDraw.Draw(halo)
    for i, k in enumerate((3.2, 2.6, 2.0)):
        rr = r * k
        hd.ellipse((beyond_pt[0] - rr, beyond_pt[1] - rr, beyond_pt[0] + rr, beyond_pt[1] + rr), fill=beyond + (22 + i * 18,))
    if base_img.mode == "RGBA":
        base_img.paste(Image.alpha_composite(base_img, halo))
    else:
        base_img.paste(Image.alpha_composite(base_img.convert("RGBA"), halo).convert("RGB"))
    d = ImageDraw.Draw(base_img)
    # pullar: ince koyu kenar + minik parlama
    edge = (8, 30, 22) if dark_bg else (200, 205, 200)
    for p in [apex] + legs[0] + legs[1] + bar:
        d.ellipse((p[0] - r - lw * 0.6, p[1] - r - lw * 0.6, p[0] + r + lw * 0.6, p[1] + r + lw * 0.6), fill=edge)
        d.ellipse((p[0] - r, p[1] - r, p[0] + r, p[1] + r), fill=dot)
        d.ellipse((p[0] - r * 0.45, p[1] - r * 0.62, p[0] - r * 0.05, p[1] - r * 0.22), fill=(255, 255, 255) if dark_bg else (90, 110, 100))
    # ötesi noktası: sarı pul, ince halka
    rb = r * 1.15
    d.ellipse((beyond_pt[0] - rb - lw * 0.6, beyond_pt[1] - rb - lw * 0.6, beyond_pt[0] + rb + lw * 0.6, beyond_pt[1] + rb + lw * 0.6), fill=edge)
    d.ellipse((beyond_pt[0] - rb, beyond_pt[1] - rb, beyond_pt[0] + rb, beyond_pt[1] + rb), fill=beyond)
    d.ellipse((beyond_pt[0] - rb * 1.6, beyond_pt[1] - rb * 1.6, beyond_pt[0] + rb * 1.6, beyond_pt[1] + rb * 1.6), outline=beyond, width=max(2, lw // 2))


def eye_mark(h_px, fg=(243, 239, 228), acc=(255, 207, 77)):
    """v3 logo işareti (göz: üst kapak + spiral iris + sarı göz bebeği), şeffaf RGBA. h_px = yükseklik. 4x çizilip küçültülür.
    Geometri assets/brand/v3/symbol-color.svg ile aynı (G2: kapak 16→240, kontrol y=34; spiral 4 yay, merkez (128,132))."""
    S = 4
    # 256'lık tasarım kutusunda işaret y=25..221 arasında (kapak kalınlığı dahil) → 196 yüksek, 236 geniş
    scale = h_px * S / 196.0
    W, H = int(236 * scale) + 2 * S, int(196 * scale) + 2 * S
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    ox, oy = S - 10 * scale, S - 25 * scale   # tasarım koordinatı → tuval
    P = lambda x, y: (x * scale + ox, y * scale + oy)
    lw = max(2, int(18 * scale))
    # üst kapak: kübik Bézier (16,132) (60,34) (196,34) (240,132) örneklenir
    pts = []
    for i in range(0, 61):
        t = i / 60
        x = (1-t)**3*16 + 3*(1-t)**2*t*60 + 3*(1-t)*t**2*196 + t**3*240
        y = (1-t)**3*132 + 3*(1-t)**2*t*34 + 3*(1-t)*t**2*34 + t**3*132
        pts.append(P(x, y))
    d.line(pts, fill=fg, width=lw, joint="curve")
    for p in (pts[0], pts[-1]):
        d.ellipse((p[0] - lw / 2, p[1] - lw / 2, p[0] + lw / 2, p[1] + lw / 2), fill=fg)
    # spiral: yarım daire yaylar (merkez x, yarıçap, başlangıç açısı, bitiş açısı) — PIL açıları: 0 sağ, saat yönü
    # (cx, cy, r, başlangıç, bitiş) — SVG'deki yaylarla birebir; son yay (48,132)→(228,100) r=100, merkez (145.1,155.9)
    arcs = [(148, 132, 20, 180, 360), (128, 132, 40, 0, 180), (148, 132, 60, 180, 360), (128, 132, 80, 0, 180)]   # G2: dört yay, (48,132)'de biter
    for cx, cy, r, a0, a1 in arcs:
        x0, y0 = P(cx - r, cy - r); x1, y1 = P(cx + r, cy + r)
        d.arc((x0, y0, x1, y1), start=a0, end=a1, fill=fg, width=lw)
    # yay uçlarını yuvarlat (başlangıç: spiral merkezi; bitiş: (228,100))
    for ex, ey in (P(128, 132), P(48, 132)):
        d.ellipse((ex - lw / 2, ey - lw / 2, ex + lw / 2, ey + lw / 2), fill=fg)
    # göz bebeği
    px, py = P(128, 132); pr = 12 * scale
    d.ellipse((px - pr, py - pr, px + pr, py + pr), fill=acc)
    return img.resize((W // S, H // S), Image.LANCZOS)


def mark_image(h_px, line=(120, 160, 140)):
    """Kart imzası için işaret: v3 göz logosu (eski taktik-A yerine). line parametresi geriye uyumluluk için."""
    return eye_mark(h_px)


def hex_mark(d, cx, cy, s, fg=WHITE, accent=YELLOW):
    """Alternatif: top paneli altıgen + içinde radar/veri çizgisi (ötesine taşan)."""
    pts = [(cx + s * 0.5 * math.cos(math.radians(60 * i - 30)), cy + s * 0.5 * math.sin(math.radians(60 * i - 30))) for i in range(6)]
    lw = max(3, int(s * 0.07))
    inner = [(cx + (p[0] - cx) * 0.995, cy + (p[1] - cy) * 0.995) for p in pts]
    d.polygon(inner, fill=(20, 58, 44))
    d.line(pts + [pts[0]], fill=fg, width=lw, joint="curve")
    for p in pts:
        d.ellipse((p[0] - lw / 2, p[1] - lw / 2, p[0] + lw / 2, p[1] + lw / 2), fill=fg)
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
    yy = y + 118 * scale
    d.text((cx, yy), spaced, font=f2, fill=fill2, anchor=anchor)
    if center:
        tw = f2.getlength(spaced); gap = 28 * scale; ln = 90 * scale
        d.line((cx - tw / 2 - gap - ln, yy, cx - tw / 2 - gap, yy), fill=fill2, width=max(2, int(3 * scale)))
        d.line((cx + tw / 2 + gap, yy, cx + tw / 2 + gap + ln, yy), fill=fill2, width=max(2, int(3 * scale)))


def render_all():
    os.makedirs(OUT, exist_ok=True)
    soft = (120, 160, 140)
    # v2 profil
    img = canvas(1080, 1080); d = ImageDraw.Draw(img); W = H = 1080 * SS
    pitch_lines(d, W, H, (28, 70, 52))
    a_mark(d, W / 2, H / 2 + 40 * SS, 620 * SS, line=soft)
    finish(img, 1080, 1080).save(f"{OUT}/v2_profile.png")
    # v2 avatar: profil fotoğrafı için (Instagram 150 px daireye küçültür) — daha büyük işaret, saha çizgisi yok, A ekseni ortada
    img = canvas(1080, 1080); d = ImageDraw.Draw(img)
    a_mark(d, W / 2 - 30 * SS, H / 2 + 20 * SS, 720 * SS, line=(150, 190, 170))
    av = finish(img, 1080, 1080); av.save(f"{OUT}/v2_avatar.png")
    # daire önizlemesi (telefonda görüneceği boyut)
    small = av.resize((320, 320), Image.LANCZOS); mask = Image.new("L", (320, 320), 0); ImageDraw.Draw(mask).ellipse((0, 0, 319, 319), fill=255)
    prev = Image.new("RGB", (320, 320), (18, 18, 18)); prev.paste(small, (0, 0), mask); prev.save(f"{OUT}/v2_avatar_preview.png")
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
    a_mark(d, W / 2, H / 2 - 150 * SS, 440 * SS, dot=INK, line=(170, 180, 172), beyond=(232, 168, 0), dark_bg=False)
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
