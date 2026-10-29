"""Tanıtım carousel'i (sabitlenecek gönderi): 4 kart, 1080×1350.
  1 · logo + slogan   2 · ne yapıyoruz   3 · kart nasıl okunur   4 · ne yapmıyoruz / 18+
Çıktı: docs/social/intro/intro_1..4.png
Kullanım: python intro.py
"""
import os
from PIL import Image, ImageDraw, ImageFont
import logo, social
from social import save, W, H, GREEN, GREEN3, YELLOW, CREAM, INK, INK2, MUTED, WHITE, PALE, RED, SIGNAL, font, wrap, text, pitch_background, footer, HANDLE

OUT = "docs/social/intro"


def card1():
    img = pitch_background(); d = ImageDraw.Draw(img)
    mk = logo.mark_image(360)
    img.paste(mk, ((W - mk.width) // 2, 120), mk)
    d.text((W / 2, 720), "ANALİZ", font=font("display", 150), fill=WHITE, anchor="mm")
    d.text((W / 2, 830), "V E   Ö T E S İ", font=ImageFont.truetype("assets/fonts/BarlowCondensed-SemiBold.ttf", 78), fill=YELLOW, anchor="mm")
    d.text((W / 2, 960), "Skordan öncesini okuruz.", font=font("semi", 40), fill=WHITE, anchor="mm")
    d.text((W / 2, 1020), "Kadro · form · sakatlık · ihtimaller", font=font("body", 30), fill=PALE, anchor="mm")
    d.text((W / 2, 1140), HANDLE, font=font("semi", 30), fill=YELLOW, anchor="mm")
    footer(d, dark=True)
    save(img, f"{OUT}/intro_1.jpg")


def bullets(d, y, items, fg=WHITE, dim=PALE, maxw=W - 160):
    for n, (title, body) in enumerate(items, 1):
        d.rounded_rectangle((60, y, 120, y + 60), radius=14, fill=YELLOW)
        d.text((90, y + 31), str(n), font=font("display", 44), fill=GREEN, anchor="mm")
        text(d, (144, y - 4), title, font("display", 56), fg)
        y += 66
        for ln in wrap(body, font("body", 30), maxw - 84):
            text(d, (144, y), ln, font("body", 30), dim); y += 40
        y += 44
    return y


def card2():
    img = pitch_background(); d = ImageDraw.Draw(img)
    social.topbar(d, "Ne yapıyoruz")
    text(d, (60, 110), "HER MAÇTAN ÖNCE", font("display", 96), WHITE)
    text(d, (60, 200), "NE BİLİYORUZ?", font("display", 96), YELLOW)
    y = bullets(d, 340, [
        ("Kadro ve eksikler", "Sakat, cezalı ve şüpheli oyuncular; kulüp açıklayınca ilk 11 ve diziliş."),
        ("Form ve golcüler", "Son 5 maç, sezon golleri ve şutlar — ESPN verisi, yorum değil."),
        ("Uluslararası piyasanın ihtimali", "Dünyanın en keskin fiyatlayıcısı bu maça yüzde kaç veriyor? Üç kutu, bir şerit."),
        ("Maç önü yazısı", "Basından derlenmiş haberlerle, bir yazar sesiyle: ne bekliyoruz, neden."),
    ])
    footer(d, dark=True)
    save(img, f"{OUT}/intro_2.jpg")


def card3():
    img = Image.new("RGB", (W, H), CREAM); d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 230), fill=GREEN)
    text(d, (60, 50), "KART NASIL OKUNUR", font("displaysemi", 28), YELLOW)
    text(d, (W - 60, 50), HANDLE, font("semi", 26), WHITE, anchor="ra")
    text(d, (60, 110), "Bir bakışta", font("display", 70), WHITE)
    # örnek ihtimal kutuları
    y = 280
    text(d, (60, y), "ULUSLARARASI PİYASANIN İHTİMALİ", font("displaysemi", 24), MUTED); y += 40
    bw = (W - 120 - 24) / 3
    for i, (lab, p, top) in enumerate([("Ev sahibi", 19, False), ("Beraberlik", 22, False), ("Deplasman", 59, True)]):
        x = 60 + i * (bw + 12)
        d.rounded_rectangle((x, y, x + bw, y + 130), radius=18, fill=YELLOW if top else GREEN3)
        d.text((x + 22, y + 10), f"%{p}", font=font("display", 78), fill=GREEN if top else WHITE)
        d.text((x + 22, y + 92), lab, font=font("semi", 22), fill=GREEN if top else PALE)
    y += 150
    text(d, (60, y), "Sarı kutu en olası sonuç. Toplam %100; bu, tahmin değil, piyasanın ortak aklı.", font("body", 26), INK2); y += 70
    # son 5 + golcü
    text(d, (60, y), "SON 5 MAÇ · GOLCÜLER", font("displaysemi", 24), MUTED); y += 40
    social.form_strip(d, 60, y, [{"result": "W"}, {"result": "D"}, {"result": "L"}, {"result": "W"}, {"result": "W"}], size=44)
    text(d, (340, y + 6), "G galibiyet · B beraberlik · M mağlubiyet", font("body", 26), INK2); y += 70
    d.rounded_rectangle((60, y, 114, y + 44), radius=10, fill=GREEN); d.text((87, y + 22), "8", font=font("display", 32), fill=YELLOW, anchor="mm")
    text(d, (126, y - 2), "Oyuncu adı", font("semi", 26), INK); text(d, (126, y + 24), "8 gol · 52 şut · sezon", font("body", 19), MUTED); y += 80
    # eksikler
    text(d, (60, y), "EKSİKLER · HABERLERE GÖRE", font("displaysemi", 24), MUTED); y += 40
    x = 60
    for s, st in (("Oyuncu · cezalı", "cezalı"), ("Oyuncu · sakat", "sakat"), ("Oyuncu · şüpheli", "şüpheli")):
        w = social.status_pill(d, x, y, s, st); x += w + 10
    y += 70
    text(d, (60, y), "Kırmızı kart = cezalı, artı = sakat, soru = belirsiz. Kadro açıklanınca kesinleşir.", font("body", 26), INK2); y += 80
    text(d, (60, y), "MAÇ ÖNÜ YAZISI", font("displaysemi", 24), MUTED); y += 40
    d.rounded_rectangle((60, y, W - 60, y + 150), radius=16, fill=(255, 255, 255))
    d.text((80, y - 6), "“", font=font("display", 110), fill=YELLOW)
    for ln in wrap("İkinci görselde, maçı bilen birinin sesiyle 4-6 cümle: eksikler ne demek, kim nasıl oynar, ne bekliyoruz. Kaynaklı haberlerle.", font("body", 26), W - 220):
        d.text((150, y + 26), ln, font=font("body", 26), fill=INK2); y += 36
    footer(d, dark=False)
    save(img, f"{OUT}/intro_3.jpg")


def card4():
    img = pitch_background(); d = ImageDraw.Draw(img)
    social.topbar(d, "Ne yapmıyoruz")
    text(d, (60, 110), "TAVSİYE", font("display", 110), WHITE)
    text(d, (60, 215), "VERMİYORUZ.", font("display", 110), YELLOW)
    y = bullets(d, 380, [
        ("Kupon yok, oran yok", "Ne oynayacağınızı söylemiyoruz. Veriyi ve bağlamı koyuyoruz; karar sizin."),
        ("Tutanı da tutmayanı da yazarız", "Yazılar maç sonrası silinmez. Piyasa mı, yazı mı daha isabetliydi — zamanla sayısı çıkar."),
        ("18+", "İçerik bilgi amaçlıdır, tavsiye niteliği taşımaz. Yaşınız 18'den küçükse bu sayfa size göre değil."),
    ])
    d.text((W / 2, 1150), "Skordan öncesini okuruz.", font=font("semi", 36), fill=YELLOW, anchor="mm")
    footer(d, dark=True)
    save(img, f"{OUT}/intro_4.jpg")


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    card1(); card2(); card3(); card4()
    print("tanıtım kartları:", sorted(os.listdir(OUT)))
