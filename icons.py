"""Kart simgeleri: 4 kat büyük çizilip küçültülür (pürüzsüz kenar). Hepsi RGBA döner; img.paste(ic, (x, y), ic) ile yapıştırılır.
  ball(size)        futbol topu (gol)
  red_card(size)    eğik kırmızı kart, hafif gölge (cezalı / kırmızı kart)
  medical(size)     beyaz daire içinde kırmızı artı (sakat)
  question(size)    sarı daire içinde soru işareti (şüpheli)
  check(size)       yeşil daire içinde tik (döndü)
  sub(size)         değişiklik: yeşil yukarı ok (giren) + kırmızı aşağı ok (çıkan)
"""
import math
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFont

S = 4
WHITE = (255, 255, 255)
DARK = (20, 30, 26)
RED = (222, 36, 40)
GREEN = (11, 42, 31)
YELLOW = (255, 207, 77)
SIGNAL = (62, 227, 140)
FONT = "assets/fonts/BarlowCondensed-Bold.ttf"


def _canvas(w, h):
    img = Image.new("RGBA", (int(w * S), int(h * S)), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def _down(img, w, h):
    return img.resize((int(w), int(h)), Image.LANCZOS)


@lru_cache(maxsize=None)
def ball(size, dark=DARK):
    img, d = _canvas(size, size)
    R = size * S / 2; cx = cy = R
    d.ellipse((S, S, size * S - S, size * S - S), fill=WHITE, outline=dark, width=S)
    pt = lambda r, a: (cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
    d.polygon([pt(R * 0.36, -90 + i * 72) for i in range(5)], fill=dark)
    for i in range(5):
        a = -90 + i * 72
        d.line((pt(R * 0.36, a), pt(R * 0.78, a)), fill=dark, width=int(S * 1.6))
        d.polygon([pt(R * 0.78, a), pt(R * 0.98, a - 20), pt(R * 0.98, a + 20)], fill=dark)
    return _down(img, size, size)


@lru_cache(maxsize=None)
def red_card(size):
    """Yükseklik = size; genişlik ~0.8*size (eğim payı). Hafif sağa yatık, altında yumuşak gölge."""
    w = int(size * 0.8); h = size
    img, d = _canvas(w, h)
    cw, ch = size * S * 0.56, size * S * 0.78
    card = Image.new("RGBA", (int(cw) + 8, int(ch) + 8), (0, 0, 0, 0)); cd = ImageDraw.Draw(card)
    cd.rounded_rectangle((4, 4, cw + 4, ch + 4), radius=int(size * S * 0.08), fill=RED, outline=(255, 235, 235), width=max(2, S // 2))
    card = card.rotate(-12, resample=Image.BICUBIC, expand=True)
    # gölge
    sh = Image.new("RGBA", card.size, (0, 0, 0, 0)); sd = ImageDraw.Draw(sh)
    sd.rounded_rectangle((6, 10, card.width - 2, card.height - 2), radius=int(size * S * 0.1), fill=(0, 0, 0, 70))
    img.alpha_composite(sh, (int((w * S - card.width) / 2) + 2, int((h * S - card.height) / 2) + 4))
    img.alpha_composite(card, (int((w * S - card.width) / 2), int((h * S - card.height) / 2)))
    return _down(img, w, h)


def _disc(size, fill):
    img, d = _canvas(size, size)
    d.ellipse((S, S, size * S - S, size * S - S), fill=fill)
    return img, d


@lru_cache(maxsize=None)
def medical(size):
    img, d = _disc(size, WHITE)
    R = size * S; t = R * 0.2; c = R / 2
    d.rounded_rectangle((c - t / 2, R * 0.2, c + t / 2, R * 0.8), radius=int(t * 0.25), fill=RED)
    d.rounded_rectangle((R * 0.2, c - t / 2, R * 0.8, c + t / 2), radius=int(t * 0.25), fill=RED)
    return _down(img, size, size)


@lru_cache(maxsize=None)
def question(size):
    img, d = _disc(size, YELLOW)
    R = size * S
    f = ImageFont.truetype(FONT, int(R * 0.8))
    d.text((R / 2, R / 2 + R * 0.03), "?", font=f, fill=GREEN, anchor="mm")
    return _down(img, size, size)


@lru_cache(maxsize=None)
def check(size):
    img, d = _disc(size, SIGNAL)
    R = size * S
    d.line((R * 0.24, R * 0.53, R * 0.42, R * 0.72, R * 0.78, R * 0.3), fill=GREEN, width=int(R * 0.12), joint="curve")
    return _down(img, size, size)


def _arrow(d, x, y0, y1, w, color, up=True):
    """Düz saplı, üçgen başlı ok; x merkez, y0 üst, y1 alt."""
    hh = w * 1.1   # baş yüksekliği
    if up:
        d.polygon([(x, y0), (x - w, y0 + hh), (x + w, y0 + hh)], fill=color)
        d.rectangle((x - w * 0.36, y0 + hh * 0.9, x + w * 0.36, y1), fill=color)
    else:
        d.polygon([(x, y1), (x - w, y1 - hh), (x + w, y1 - hh)], fill=color)
        d.rectangle((x - w * 0.36, y0, x + w * 0.36, y1 - hh * 0.9), fill=color)


@lru_cache(maxsize=None)
def sub(size):
    """Değişiklik: solda yeşil yukarı ok (giren), sağda kırmızı aşağı ok (çıkan)."""
    w = size; h = size
    img, d = _canvas(w, h)
    R = size * S
    _arrow(d, R * 0.3, R * 0.08, R * 0.92, R * 0.19, SIGNAL, up=True)
    _arrow(d, R * 0.7, R * 0.08, R * 0.92, R * 0.19, (235, 80, 70), up=False)
    return _down(img, w, h)


def paste(img, icon, x, y):
    img.paste(icon, (int(x), int(y)), icon)
    return icon.width
