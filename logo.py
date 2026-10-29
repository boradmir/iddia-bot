"""Analiz ve Ötesi logosu: 'A' + ötesine fırlayan sarı ok. Çıktı: assets/brand/*.png
  profile.png   1080×1080  yalnız işaret (profil fotoğrafı)
  wordmark.png  1080×1080  işaret + ANALİZ / VE ÖTESİ
  wide.png      1600×600   yatay (kapak / imza)
Kullanım: python logo.py
"""
import os
from PIL import Image, ImageDraw, ImageFont

GREEN, GREEN2, YELLOW, WHITE = (11, 42, 31), (16, 66, 48), (255, 207, 77), (255, 255, 255)
FONT = "assets/fonts/BarlowCondensed-Bold.ttf"
OUT = "assets/brand"


def bg(w, h, radius=None):
    img = Image.new("RGB", (w, h), GREEN); d = ImageDraw.Draw(img)
    for y in range(h):  # degrade
        t = y / h; d.line((0, y, w, y), fill=tuple(int(GREEN[i] + (GREEN2[i] - GREEN[i]) * t) for i in range(3)))
    ov = Image.new("RGBA", (w, h), (0, 0, 0, 0)); od = ImageDraw.Draw(ov)
    r = int(min(w, h) * 0.42)
    od.ellipse((w / 2 - r, h / 2 - r, w / 2 + r, h / 2 + r), outline=(255, 255, 255, 22), width=max(3, w // 300))
    img = Image.alpha_composite(img.convert("RGBA"), ov)
    if radius:
        mask = Image.new("L", (w, h), 0); ImageDraw.Draw(mask).rounded_rectangle((0, 0, w, h), radius=radius, fill=255)
        img.putalpha(mask)
    return img


def mark(d, cx, cy, s):
    """İşaret: 'A' (beyaz) ve A'nın gövdesinden sağ üste çıkan sarı ok. s = ölçek (A yüksekliği)."""
    t = s * 0.16                       # çizgi kalınlığı
    ax, ay = cx - s * 0.36, cy + s * 0.5   # A sol ayak
    bx, by = cx + s * 0.36, cy + s * 0.5   # A sağ ayak
    tx, ty = cx, cy - s * 0.5              # tepe
    # A'nın bacakları
    d.line((ax, ay, tx, ty), fill=WHITE, width=int(t), joint="curve")
    d.line((bx, by, tx, ty), fill=WHITE, width=int(t), joint="curve")
    # köşe yuvarlama
    for (x, y) in ((ax, ay), (bx, by), (tx, ty)):
        d.ellipse((x - t / 2, y - t / 2, x + t / 2, y + t / 2), fill=WHITE)
    # çapraz çubuk = okun başlangıcı: soldan girip sağ üste fırlar
    import math
    cx1, cy1 = cx - s * 0.20, cy + s * 0.12
    ex, ey = cx + s * 0.64, cy - s * 0.44          # ok ucu (tepe noktası)
    ux, uy = ex - cx1, ey - cy1; n = math.hypot(ux, uy); ux, uy = ux / n, uy / n
    px, py = -uy, ux                                # dik yön
    head = s * 0.26                                 # ok başı uzunluğu
    base = (ex - ux * head, ey - uy * head)         # ok başı tabanının merkezi
    # gövde: taban merkezine kadar
    d.line((cx1, cy1, base[0] + ux * t * 0.3, base[1] + uy * t * 0.3), fill=YELLOW, width=int(t * 0.95))
    d.ellipse((cx1 - t * 0.47, cy1 - t * 0.47, cx1 + t * 0.47, cy1 + t * 0.47), fill=YELLOW)
    # ok başı: simetrik üçgen (taban genişliği ≈ gövdenin 2.2 katı)
    hw = t * 1.1
    d.polygon([(ex, ey), (base[0] + px * hw, base[1] + py * hw), (base[0] - px * hw, base[1] - py * hw)], fill=YELLOW)


def profile():
    img = bg(1080, 1080); d = ImageDraw.Draw(img)
    mark(d, 540, 560, 560)
    img.convert("RGB").save(f"{OUT}/profile.png", "PNG")


def wordmark():
    img = bg(1080, 1080); d = ImageDraw.Draw(img)
    mark(d, 540, 400, 420)
    f1 = ImageFont.truetype(FONT, 150); f2 = ImageFont.truetype(FONT, 96)
    d.text((540, 760), "ANALİZ", font=f1, fill=WHITE, anchor="mm")
    d.text((540, 880), "VE ÖTESİ", font=f2, fill=YELLOW, anchor="mm")
    img.convert("RGB").save(f"{OUT}/wordmark.png", "PNG")


def wide():
    img = bg(1600, 600); d = ImageDraw.Draw(img)
    mark(d, 300, 300, 380)
    f1 = ImageFont.truetype(FONT, 190); f2 = ImageFont.truetype(FONT, 110)
    d.text((560, 250), "ANALİZ", font=f1, fill=WHITE, anchor="lm")
    d.text((560, 400), "VE ÖTESİ", font=f2, fill=YELLOW, anchor="lm")
    img.convert("RGB").save(f"{OUT}/wide.png", "PNG")


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    profile(); wordmark(); wide()
    print("logo:", os.listdir(OUT))
