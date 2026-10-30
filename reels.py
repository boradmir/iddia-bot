"""Reels üretici (maç önü, ~12 sn, 1080×1920, 25 fps, seslendirmeli).
Girdi: m (Nesine maçı), ai (records/claude kaydı), pm (piyasa ihtimalleri), er (ESPN kaydı, opsiyonel).
Çıktı: mp4 + kapak jpg. Ses: edge-tts (tr-TR-AhmetNeural), kelime zamanlarıyla senkron altyazı; tık efektleri; loudnorm.
Kullanım (deneme): python reels.py --demo
"""
import asyncio, json, math, os, re, shutil, subprocess, sys, tempfile
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import config  # .env (ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID)
import social, logo, icons
from social import font, wrap, tr_upper, team_style, GREEN, GREEN2, GREEN3, YELLOW, CREAM, WHITE, PALE, INK, HANDLE, DISCLAIMER, TR

W, H, FPS = 1080, 1920, 25
VOICE, RATE, PITCH = "tr-TR-AhmetNeural", "+30%", "-2Hz"
M_L, M_R = 72, 72            # kenar boşlukları
SUB_Y = 1400                 # altyazı bandı
COVER_LABEL = "Skordan öncesi"   # reels kapağındaki küçük etiket
BANNED = ("banko", "kesin", "garanti", "çivi", "yatar", "kupon", "bahis")


# ----------------------------------------------------------------- yardımcılar
def ease_out_cubic(t): return 1 - (1 - t) ** 3
def ease_out_back(t, s=1.4): t -= 1; return 1 + t * t * ((s + 1) * t + s)
def clamp(x, a=0.0, b=1.0): return max(a, min(b, x))


def short_words(text, n):
    """Kısa biçim: 'Beni en çok düşündüren,' gibi girişleri at, en fazla n kelime, virgül/noktada bitir."""
    t = (text or "").strip().rstrip(".")
    t = re.sub(r"^(beni en çok düşündüren|en büyük belirsizlik|en büyük soru işareti|sonucu en çok belirsizleştiren)[,:\s]+", "", t, flags=re.I)
    w = t.split()
    if len(w) <= n:
        return " ".join(w)
    cut = " ".join(w[:n])
    for sep in (",", ";", " ve ", " ama "):
        i = cut.rfind(sep)
        if i > len(cut) * 0.5:
            cut = cut[:i]; break
    return cut.strip(" ,;")


def tr_gen(name):
    """Türkçe ilgi eki: Fenerbahçe'nin, Göztepe'nin, Galatasaray'ın, Konyaspor'un, Beşiktaş'ın, PSG'nin."""
    base = name.strip()
    last_vowel = next((ch for ch in reversed(base.lower()) if ch in "aeıioöuü"), "e")
    suffix = {"a": "ın", "ı": "ın", "e": "in", "i": "in", "o": "un", "u": "un", "ö": "ün", "ü": "ün"}[last_vowel]
    ends_vowel = base[-1].lower() in "aeıioöuü"
    if base.isupper() and len(base) <= 4:   # kısaltma (PSG) harf okunuşuna göre: PSG → PSG'nin
        suffix = "nin"
    elif ends_vowel:
        suffix = "n" + suffix
    return f"{base}'{suffix}"


def build_script(m, bl, pm, absences):
    """Seslendirme metni (28-36 kelime) ve sahne çapaları (kelime indeksleri)."""
    ms = pm["MS"] if pm and "MS" in pm else None
    fav_side = max(ms, key=ms.get) if ms else None
    # yapay zekânın yazdığı seslendirme metni varsa ve ölçüye uyuyorsa onu kullan
    rs = (bl.get("reels_script") or "").strip()
    if rs and ms:
        market = f"Piyasaya göre {tr_gen(m['home'])} kazanma ihtimali yüzde {ms['1']*100:.0f}, {tr_gen(m['away'])} yüzde {ms['2']*100:.0f}."
        rs = re.sub(r"P[İI]YASA\.?", market, rs, count=1) if "PİYASA" in rs or "PIYASA" in rs else re.sub(r"Piyasaya göre[^.]*\.", market, rs, count=1)
    if rs and 18 <= len(rs.split()) <= 64 and not re.search(r"\b(ben|bana|bence|beni)\b", rs, re.I):
        sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", rs) if s.strip()]
        return rs, sents
    hook = (bl.get("hook") or "").strip().rstrip(".")
    if not hook or len(hook.split()) > 8:
        if ms and ms[fav_side] >= 0.6:
            fav = m["home"] if fav_side == "1" else (m["away"] if fav_side == "2" else "beraberlik")
            hook = f"Piyasa {fav} için yüzde {ms[fav_side]*100:.0f} diyor. Biz o kadar emin değiliz"
        elif absences:
            hook = f"{absences[0]['player'].split()[-1]} yok. Bu maçı değiştirir mi"
        else:
            hook = short_words(bl.get("hook") or bl.get("comment"), 8)
    parts = [hook + "."]
    if ms:
        if hook.startswith("Piyasa "):   # kanca zaten favorinin yüzdesini söyledi → yalnız diğer tarafı ver
            other = ("1", m["home"]) if fav_side == "2" else ("2", m["away"])
            parts.append(f"{other[1]} için yüzde {ms[other[0]]*100:.0f}.")
        else:
            parts.append(f"Piyasaya göre {tr_gen(m['home'])} kazanma ihtimali yüzde {ms['1']*100:.0f}, {tr_gen(m['away'])} yüzde {ms['2']*100:.0f}.")
    if absences:
        parts.append(", ".join(f"{a['player'].split()[-1]} {a['status']}" for a in absences[:2]) + ".")
    risk_short = (bl.get("risk_short") or short_words(bl.get("risk"), 12)).rstrip(".")
    if risk_short:
        parts.append(f"Bizi düşündüren: {risk_short}.")
    q = (bl.get("question") or "Siz ne diyorsunuz?").strip()
    parts.append(q if q.endswith("?") else q + "?")
    parts.append("Yoruma yazın.")
    # süre bütçesi: ~13 sn için en fazla 28 kelime; sırayla eksikler cümlesi, sonra piyasa cümlesi düşer
    def n_words(ps): return sum(len(p.split()) for p in ps)
    if n_words(parts) > 28 and absences:
        parts = [p for p in parts if not p.startswith(absences[0]['player'].split()[-1])]
    if n_words(parts) > 28 and ms:
        parts = [p for i, p in enumerate(parts) if i != 1]
    text = " ".join(parts)
    for b in BANNED:
        text = re.sub(rf"\b{b}\w*", "", text, flags=re.I)
    return text, parts


async def _tts(text, out_mp3):
    import edge_tts
    try:
        com = edge_tts.Communicate(text, VOICE, rate=RATE, pitch=PITCH, boundary="WordBoundary")
    except TypeError:
        com = edge_tts.Communicate(text, VOICE, rate=RATE, pitch=PITCH)
    words = []
    with open(out_mp3, "wb") as f:
        async for ch in com.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                words.append({"t": ch["offset"] / 1e7, "d": ch["duration"] / 1e7, "w": ch["text"]})
    return words


ELEVEN_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVEN_VOICE = os.environ.get("ELEVENLABS_VOICE_ID", "")
ELEVEN_MODEL = os.environ.get("ELEVENLABS_MODEL", "eleven_multilingual_v2")


def tts_eleven(text, out_mp3, voice_id=None, model=None):
    """ElevenLabs: ses + karakter zaman damgaları → kelime zamanları (altyazı senkronu için)."""
    import base64, urllib.request
    voice_id = voice_id or ELEVEN_VOICE
    body = json.dumps({"text": text, "model_id": model or ELEVEN_MODEL,
                       "voice_settings": {"stability": 0.40, "similarity_boost": 0.85, "style": 0.38, "use_speaker_boost": True}}).encode()   # Ahu "orta" ayar
    req = urllib.request.Request(f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps?output_format=mp3_44100_128",
                                 data=body, headers={"xi-api-key": ELEVEN_KEY, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        res = json.loads(r.read())
    with open(out_mp3, "wb") as f:
        f.write(base64.b64decode(res["audio_base64"]))
    al = res.get("alignment") or res.get("normalized_alignment") or {}
    chars, starts, ends = al.get("characters", []), al.get("character_start_times_seconds", []), al.get("character_end_times_seconds", [])
    words, cur, t0 = [], "", None
    for ch, st, en in zip(chars, starts, ends):
        if ch.isspace():
            if cur:
                words.append({"t": t0, "d": max(0.05, en_prev - t0), "w": cur}); cur, t0 = "", None
            continue
        if t0 is None:
            t0 = st
        cur += ch; en_prev = en
    if cur:
        words.append({"t": t0, "d": max(0.05, en_prev - t0), "w": cur})
    return words


# Okunuş sözlüğü: yalnız seslendirme girdisine uygulanır; altyazıda özgün yazım görünür. Kelime sayısı korunur (çok kelimeli ad → aynı sayıda kelime).
PRONOUNCE = {
    "Kuyt": "Kayt", "Oosterwolde": "Osterwolde", "Brown": "Braun", "Skriniar": "Şkriniar", "Juan": "Huan", "Henrique": "Enrike",
    "Ake": "Ake", "Szymański": "Şimanski", "Szymanski": "Şimanski", "En-Nesyri": "En-Nesiri", "Mourinho": "Morinyo", "Tedesco": "Tedesko",
    "Semedo": "Semedu", "Djiku": "Ciku", "Icardi": "İkardi", "Osimhen": "Osimen", "Sané": "Zane", "Sane": "Zane", "Torreira": "Toreyra",
    "Jakobs": "Yakobs", "Sallai": "Şallai", "Ndidi": "Indidi", "Cerny": "Çerni", "Durán": "Duran", "Jhon": "Con", "Abraham": "Eybrıhem",
    "Rashford": "Raşford", "Lewandowski": "Levandovski", "Mbappé": "Embape", "Mbappe": "Embape", "Vinicius": "Vinisyus", "Bellingham": "Belingım",
    "Haaland": "Haland", "Foden": "Fodın", "Kane": "Keyn", "Musiala": "Musiyala", "Dembélé": "Dembele", "Doué": "Due", "Kvaratskhelia": "Kvaratshelya",
    "Wirtz": "Virts", "Gyökeres": "Yökeres", "Ødegaard": "Ödegor", "Guardiola": "Guardiyola", "Enrique": "Enrike", "Hjulmand": "Yulmand",
    "Solskjær": "Solşer", "Salah": "Salah", "Szoboszlai": "Soboslai", "Gravenberch": "Gravenberh", "Mac Allister": "Mek Alister",
    "Rüdiger": "Rüdiger", "Courtois": "Kurtua", "Tchouaméni": "Çuameni", "Camavinga": "Kamavinga", "Vitinha": "Vitinya", "Hakimi": "Hakimi",
    "Olise": "Olise", "Kimmich": "Kimmih", "Neuer": "Noyer", "Lookman": "Lukman", "Yıldız": "Yıldız", "Çalhanoğlu": "Çalhanoğlu",
    "Lautaro": "Lautaro", "Thuram": "Türam", "Onana": "Onana", "Lemina": "Lemina", "Sara": "Sara", "Barış": "Barış", "Rafa": "Rafa",
    "Paulista": "Paulista", "Ndidi": "Indidi", "Jota": "Jota", "Talisca": "Talişka", "Fred": "Fred", "Nelson": "Nelsın", "Oppong": "Oppong",
    "Levent": "Levent", "Jurásek": "Yurasek", "Jurasek": "Yurasek", "Okay": "Okay", "Kadıoğlu": "Kadıoğlu", "Ederson": "Ederson",
    "Bruno": "Bruno", "Mane": "Mane", "Xavi": "Çavi", "Hazard": "Azar", "Dzeko": "Ceko", "Džeko": "Ceko", "Kerem": "Kerem",
}


def spoken_text(text, extra=None):
    """Seslendirme için okunuş sözlüğünü uygular; token sayısı aynı kalır. extra: yapay zekânın pakete yazdığı okunuşlar (öncelikli)."""
    out = text
    table = dict(PRONOUNCE); table.update({k: v for k, v in (extra or {}).items() if k and v and len(k.split()) == len(v.split())})
    for k, v in table.items():
        if k == v or k not in out:
            continue
        out = re.sub(rf"(?<![\wğüşöçİĞÜŞÖÇ]){re.escape(k)}(?![\wğüşöçĞÜŞÖÇ])", v, out)
    # ünlü uyumu: Kuyt→Kayt gibi değişimlerde ek de uyar (Kayt'ün → Kayt'ın)
    for a, b in (("Kayt'ü", "Kayt'ı"), ("Kayt'e", "Kayt'a"), ("Kayt'te", "Kayt'ta"), ("Kayt'le", "Kayt'la")):
        out = out.replace(a, b)
    return out


def tts(text, out_mp3, pronounce=None):
    spoken = spoken_text(text, pronounce)
    words = tts_eleven(spoken, out_mp3) if (ELEVEN_KEY and ELEVEN_VOICE) else asyncio.run(_tts(spoken, out_mp3))
    # altyazıda özgün yazım: kelime sayıları eşitse metni geri koy
    orig = text.split()
    if len(orig) == len(words):
        for w, o in zip(words, orig):
            w["w"] = o
    return words


# ----------------------------------------------------------------- zemin
_GRAIN = None
def grain_layers():
    global _GRAIN
    if _GRAIN is None:
        import random
        _GRAIN = []
        for k in range(4):
            g = Image.effect_noise((W // 4, H // 4), 40).resize((W, H), Image.BILINEAR).convert("L")
            _GRAIN.append(g)
    return _GRAIN


_VIG = None
def vignette():
    global _VIG
    if _VIG is None:
        v = Image.new("L", (W, H), 0); d = ImageDraw.Draw(v)
        for i in range(30):
            k = i / 30
            d.ellipse((W * (-0.4 + 0.4 * k), H * (-0.3 + 0.3 * k), W * (1.4 - 0.4 * k), H * (1.3 - 0.3 * k)), fill=int(90 * (1 - k)))
        _VIG = v.filter(ImageFilter.GaussianBlur(60))
    return _VIG


BG_DIR = os.environ.get("REELS_BG_DIR", "assets/bg_lib")   # repo içindeki sıkıştırılmış kütüphane (ham klipler: assets/bg_v2, gitignore)
VIDEO_BG = os.environ.get("REELS_VIDEO_BG", "1") == "1"
# analiz dünyası klipleri (Seedance 2.5): sahne → tercih sırası
SCENE_CLIPS = {"hook": ["chalk_arrow", "spotlight_board", "chalk_pitch"], "teams": ["table_pitch", "magnet_board"],
               "market": ["magnet_board", "chalk_pitch", "tactics_sheet"], "absences": ["pen_paper", "string_board", "analyst_desk"],
               "risk": ["chalk_erase", "whistle_desk", "rain_window"], "question": ["chalk_dust", "analyst_desk", "chalk_arrow"],
               "form": ["table_pitch", "string_board", "magnet_board"]}
_TINT = None


def clip_for(scene, used):
    """Sahne için kütüphaneden klip (varsa), aynı videoda tekrar etmemeye çalışır."""
    cands = [n for n in SCENE_CLIPS.get(scene, []) if os.path.exists(f"{BG_DIR}/{n}.mp4")]
    allc = [f[:-4] for f in os.listdir(BG_DIR) if f.endswith(".mp4")] if os.path.isdir(BG_DIR) else []
    for n in cands + [c for c in allc if c not in used]:
        if n not in used:
            return n
    return (cands or allc or [None])[0]


def tint_layer(th):
    """Video zemin üstüne marka tonlu karartma: üstte hafif, ortada güçlü (yazı okunsun), altta orta."""
    global _TINT
    if _TINT is None:
        base = th["bg"]
        lay = Image.new("RGBA", (W, H), base + (0,))
        d = ImageDraw.Draw(lay)
        for y in range(0, H, 2):
            t = y / H
            a = 90 if t < 0.12 else (125 + int(45 * min(1, (t - 0.12) / 0.3)) if t < 0.85 else 150)   # biraz daha açık: görüntü görünsün
            d.rectangle((0, y, W, y + 1), fill=base + (a,))
        _TINT = lay
    return _TINT


def background_video(frame_i, th):
    """Video zemin modu: şeffaf kare + tonlama + üst şerit (asıl görüntü ffmpeg'de alta bindirilir)."""
    img = tint_layer(th).copy()
    ImageDraw.Draw(img).rectangle((0, 0, W, 12), fill=YELLOW)
    return img


def background(frame_i, th):
    img = Image.new("RGB", (W, H), th["bg"]); d = ImageDraw.Draw(img)
    c1, c2 = th["bg"], th["bg2"]
    for y in range(0, H, 2):
        t = y / H; col = tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))
        d.rectangle((0, y, W, y + 1), fill=col)
    # saha çizgileri: %6-9 opaklık salınır, dikeyde yavaş kayar
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0)); od = ImageDraw.Draw(ov)
    a = int(255 * (0.075 + 0.015 * math.sin(frame_i / 25 * 2 * math.pi / 1.2)))
    dy = int((frame_i * 0.4) % 40)
    line = (243, 239, 228, a)
    cy = 1000 + dy
    od.ellipse((W / 2 - 420, cy - 420, W / 2 + 420, cy + 420), outline=line, width=3)
    od.line((0, cy, W, cy), fill=line, width=3)
    img = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
    # vinyet
    img = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), img, vignette())
    # grain
    g = grain_layers()[(frame_i // 2) % 4]
    img = Image.composite(Image.new("RGB", (W, H), (255, 255, 255)), img, g.point(lambda p: int(p * 0.03)))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 12), fill=YELLOW)   # üst şerit
    return img


# ----------------------------------------------------------------- metin katmanları
_WCACHE = {}
def word_img(word, f, fill):
    key = (word, f.path, f.size, fill)
    if key not in _WCACHE:
        bb = f.getbbox(word); w = bb[2] + 4; h = f.size + 20
        im = Image.new("RGBA", (max(1, w), h), (0, 0, 0, 0)); ImageDraw.Draw(im).text((0, 0), word, font=f, fill=fill)
        _WCACHE[key] = im
    return _WCACHE[key]


ISSUES = []   # render sırasında yakalanan taşmalar (yayın öncesi denetim okur)


def note_issue(msg):
    if msg not in ISSUES:
        ISSUES.append(msg)


def fit_font(text, kind, sizes, max_w, max_lines):
    """Metni en çok max_lines satıra sığdıran en büyük yazı boyu; sığmazsa en küçüğü (ve taşma notu)."""
    for size in sizes:
        f = font(kind, size)
        if len(wrap(text, f, max_w)) <= max_lines:
            return f, size
    note_issue(f"yazı sığmadı ({kind}): {text[:40]}…")
    return font(kind, sizes[-1]), sizes[-1]


def fit_width(text, kind, sizes, max_w):
    """Tek satırı genişliğe sığdıran en büyük yazı boyu."""
    for size in sizes:
        f = font(kind, size)
        if f.getlength(text) <= max_w:
            return f
    note_issue(f"tek satır sığmadı ({kind}): {text[:40]}")
    return font(kind, sizes[-1])


def draw_words(img, text, f, x0, y0, max_w, t_since, fill=WHITE, accent_words=(), stagger=0.06, dur=0.24, line_h=None):
    """Kelime kelime giriş: her kelime 24 px yukarı kayarak ve belirerek gelir."""
    line_h = line_h or int(f.size * 1.12)
    lines = wrap(text, f, max_w)
    idx = 0; y = y0
    for ln in lines:
        x = x0
        for w in ln.split():
            k = ease_out_cubic(clamp((t_since - idx * stagger) / dur))
            col = YELLOW if w.strip(".,:;?!").lower() in accent_words else fill
            im = word_img(w, f, col)
            if k > 0:
                layer = im.copy()
                if k < 1:
                    a = layer.split()[3].point(lambda p: int(p * k)); layer.putalpha(a)
                img.paste(layer, (int(x), int(y + 24 * (1 - k))), layer)
            x += f.getlength(w + " ")
            idx += 1
        y += line_h
    return y


def subtitle(img, d, words, t, f):
    """Altyazı: 3-5 kelimelik parçalar, söylenen kelime sarı, söylenmiş kemik, gelecek %40."""
    if not words:
        return
    # parçalara böl
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= 4 or w["w"].endswith((".", "?", ":")):
            chunks.append(cur); cur = []
    if cur: chunks.append(cur)
    active = None
    for ch in chunks:
        if ch[0]["t"] - 0.05 <= t <= ch[-1]["t"] + ch[-1]["d"] + 0.35:
            active = ch; break
    if not active:
        return
    text = " ".join(w["w"] for w in active)
    lines = wrap(text, f, W - M_L - M_R)
    y = SUB_Y; i = 0
    for ln in lines:
        x = (W - f.getlength(ln)) / 2
        for wd in ln.split():
            ww = active[i] if i < len(active) else None
            if ww and ww["t"] <= t <= ww["t"] + ww["d"] + 0.08:
                col = YELLOW
            elif ww and t > ww["t"]:
                col = (243, 239, 228)
            else:
                col = (243, 239, 228, 100)
            im = word_img(wd, f, col[:3])
            if len(col) == 4:
                a = im.split()[3].point(lambda p: int(p * col[3] / 255)); im = im.copy(); im.putalpha(a)
            img.paste(im, (int(x), int(y)), im); x += f.getlength(wd + " "); i += 1
        y += int(f.size * 1.15)


# ----------------------------------------------------------------- sahneler
def cover_image(img, m, th):
    """Kapak: kanca sahnesinin tam hâli + üstte etiket, altta göz işareti ve marka. Profil ızgarası ortadan kırpar (1:1 → y 420-1500);
    bütün öğeler bu kuşakta."""
    d = ImageDraw.Draw(img)
    d.text((M_L, 340), tr_upper(COVER_LABEL), font=font("displaysemi", 34), fill=YELLOW)
    lk = logo.kit_lockup(250)
    img.paste(lk, ((W - lk.width) // 2, 1190), lk)
    d.text((W / 2, 1462), HANDLE, font=font("semi", 30), fill=PALE, anchor="ma")
    return img


def scene_hook(img, d, t, hook, th):
    f, size = fit_font(tr_upper(hook), "display", (96, 86, 76, 68, 60), W - M_L - M_R, 4)
    acc = set(w.strip(".,").lower() for w in hook.split()[-3:])   # son üç kelime vurgu
    y_end = draw_words(img, tr_upper(hook), f, M_L, 420, W - M_L - M_R, 9, fill=WHITE, accent_words=set(tr_upper(w) .lower() for w in acc), stagger=0, dur=0.01, line_h=int(size * 1.12))
    if y_end + 190 > SUB_Y - 30:
        note_issue("kanca sahnesi altyazı bandına taşıyor")
    if t > 0.8 and th is not None:
        k = ease_out_cubic(clamp((t - 0.8) / 0.3))
        m_ = scene_hook.m; start = m_["start"].astimezone(TR)
        d.rectangle((M_L, y_end + 30, M_L + int(140 * k), y_end + 36), fill=YELLOW)
        d.text((M_L, y_end + 60), tr_upper(f"{m_['home']} – {m_['away']}"), font=font("display", 64), fill=tuple(int(c * k) for c in WHITE))
        d.text((M_L, y_end + 140), tr_upper(f"{social.DAYS_TR[start.weekday()]} {start:%H:%M} · {m_.get('league','')}"), font=font("displaysemi", 34), fill=tuple(int(c * k) for c in PALE))


def scene_teams(img, d, t, m, th):
    f = fit_width(tr_upper(max((m["home"], m["away"]), key=len)), "display", (150, 130, 112, 96, 84), W - M_L - M_R)
    k1 = ease_out_cubic(clamp(t / 0.26)); k2 = ease_out_cubic(clamp((t - 0.08) / 0.26))
    d.text((M_L - 80 * (1 - k1), 520), tr_upper(m["home"]), font=f, fill=tuple(int(c * k1) for c in WHITE))
    d.text((M_L - 80 * (1 - k2), 690), tr_upper(m["away"]), font=f, fill=tuple(int(c * k2) for c in YELLOW))
    start = m["start"].astimezone(TR)
    d.text((M_L, 880), tr_upper(f"{social.DAYS_TR[start.weekday()]} {start:%H:%M} · {m.get('league','')}"), font=font("displaysemi", 36), fill=PALE)


def scene_market(img, d, t, m, pm, er):
    ms = pm["MS"]; hc, _, _ = team_style(m["home"], er); ac, _, _ = team_style(m["away"], er)
    d.text((M_L, 400), tr_upper("Dünya bu maça ne diyor? · kazanma ihtimali"), font=font("displaysemi", 34), fill=YELLOW)
    best = max(ms, key=ms.get)
    rows = (("1", m["home"], hc), ("X", "Beraberlik", GREEN3), ("2", m["away"], ac))
    y = 480
    for i, (key, lab, col) in enumerate(rows):
        kc = ease_out_cubic(clamp((t - i * 0.12) / 0.6)); kb = ease_out_back(clamp((t - i * 0.12) / 0.5)) if t > i * 0.12 else 0
        val = ms[key] * 100 * kc
        fnum = font("display", 140)
        d.text((W - M_R, y - 10), f"%{val:.0f}", font=fnum, fill=WHITE, anchor="ra")
        d.text((M_L, y + 60), tr_upper(lab), font=fit_width(tr_upper(lab), "displaysemi", (40, 36, 32, 28), W - M_L - M_R - 300), fill=PALE)
        bw = (W - M_L - M_R) * ms[key] * kb
        d.rounded_rectangle((M_L, y + 160, W - M_R, y + 184), radius=12, fill=GREEN3)
        if bw > 0:
            d.rounded_rectangle((M_L, y + 160, M_L + max(24, bw), y + 184), radius=12, fill=col)
        if key == best and t > 1.1:
            kf = clamp((t - 1.1) / 0.2)
            d.rounded_rectangle((M_L - 16, y - 24, W - M_R + 16, y + 204), radius=20, outline=YELLOW, width=int(6 * kf) or 1)
        y += 250
    if "AU25" in pm and "KG" in pm and t > 1.8:
        ks = 0.8 + 0.2 * ease_out_cubic(clamp((t - 1.8) / 0.18))
        f = font("displaysemi", int(34 * ks))
        d.text((M_L, y + 10), f"3+ GOL %{pm['AU25']['Üst']*100:.0f}   ·   KARŞILIKLI GOL %{pm['KG']['Var']*100:.0f}", font=f, fill=PALE)


def scene_absences(img, d, t, absences, th):
    d.text((M_L, 400), tr_upper("Eksikler · haberlere göre"), font=font("displaysemi", 36), fill=YELLOW)
    y = 480
    for i, a in enumerate(absences[:4]):
        k = ease_out_cubic(clamp((t - i * 0.09) / 0.26))
        x = M_L + 40 * (1 - k)
        name = a['player'] if len(f"{a['player']} · {a['status']}") <= 30 else a['player'].split()[-1]
        s = f"{name} · {a['status']}"
        w = social.status_pill(d, x, y, s, a.get("status"))
        y += 70
    if not absences:
        d.text((M_L, 480), "Bilinen eksik yok.", font=font("body", 48), fill=WHITE)


def scene_form(img, d, t, m, er, th):
    """Rakip/form: iki takımın son 5 maçı (G/B/M kareleri) ve en golcü oyuncu; soldan sağa belirir."""
    last5 = (er or {}).get("last5") or {}; leaders = (er or {}).get("leaders") or {}
    d.text((M_L, 400), tr_upper("Son 5 maç"), font=font("displaysemi", 36), fill=YELLOW)
    y = 470
    for i, team in enumerate((m["home"], m["away"])):
        k = ease_out_cubic(clamp((t - i * 0.25) / 0.35))
        if k <= 0:
            continue
        d.text((M_L, y), tr_upper(team), font=font("display", 56), fill=tuple(int(c * k) for c in WHITE))
        games = None
        for tn, g in last5.items():
            if social.match.similarity(team, tn) >= 0.6:
                games = g; break
        if games:
            x = M_L
            for j, g in enumerate(games[:5]):
                kk = ease_out_cubic(clamp((t - i * 0.25 - 0.1 - j * 0.07) / 0.25))
                if kk <= 0: break
                sym = {"W": "G", "D": "B", "L": "M"}.get(g.get("result"), "?")
                col = {"W": (62, 227, 140), "D": (154, 167, 160), "L": (240, 138, 75)}.get(g.get("result"), (154, 167, 160))
                s = int(72 * kk)
                d.rounded_rectangle((x + 36 - s / 2, y + 110 - s / 2, x + 36 + s / 2, y + 110 + s / 2), radius=14, fill=col)
                if kk > 0.6:
                    d.text((x + 36, y + 110), sym, font=font("display", 44), fill=th["bg"], anchor="mm")
                x += 86
        top = None
        for tn, ls in leaders.items():
            if social.match.similarity(team, tn) >= 0.6 and ls:
                top = sorted(ls, key=lambda r_: (-r_.get("goals", 0), -r_.get("shots", 0)))[0]; break
        if top and top.get("goals"):
            d.text((M_L + 470, y + 92), f"{top['player']}", font=font("semi", 32), fill=tuple(int(c * k) for c in WHITE))
            d.text((M_L + 470, y + 130), f"{top['goals']} gol · sezon", font=font("body", 26), fill=tuple(int(c * k) for c in PALE))
        y += 300


def scene_risk(img, d, t, risk, th):
    k = ease_out_cubic(clamp(t / 0.16))
    y0 = 420 + 140 * (1 - k)
    d.rounded_rectangle((M_L, y0, W - M_R, y0 + 560), radius=28, fill=CREAM)
    d.text((M_L + 32, y0 + 28), "EN BÜYÜK BELİRSİZLİK", font=font("displaysemi", 34), fill=(107, 77, 0))
    f, size = fit_font(risk, "body", (56, 50, 44, 40), W - M_L - M_R - 64, 6)
    draw_words(img, risk, f, M_L + 32, y0 + 96, W - M_L - M_R - 64, max(0, t - 0.16), fill=th["bg"], stagger=0.05, dur=0.22, line_h=int(size * 1.18))


def scene_question(img, d, t, question, th):
    # uzun soruda yazı küçülür (en çok 4 satır); alt satırlar sorunun bittiği yere göre yerleşir, üst üste binme olmaz
    text, max_w = tr_upper(question), W - M_L - M_R
    for size in (110, 96, 84, 74, 66):
        f = font("display", size); lines = wrap(text, f, max_w)
        if len(lines) <= (3 if size >= 96 else 4):
            break
    y_end = draw_words(img, text, f, M_L, 400, max_w, t, fill=YELLOW, stagger=0.07, dur=0.24, line_h=int(size * 1.07))
    cta_y = max(820, y_end + 40)
    d.text((M_L, cta_y), "Yoruma yazın · Maçtan sonra karşılaştırırız", font=font("semi", 36), fill=PALE)
    logo_y = cta_y + 180
    if logo_y + 290 > 1540:
        note_issue("soru sahnesi alt blok dipnota taşıyor")
    # marka: kit dikey logosu (göz + ANALİZ VE ÖTESİ), belirerek gelir, hafif nefes
    k_in = ease_out_cubic(clamp(t / 0.35))
    hgt = int(290 * (1 + 0.02 * math.sin(t * 2 * math.pi / 1.6)))
    lk = logo.kit_lockup(hgt)
    if k_in < 1:
        lk = lk.copy(); lk.putalpha(lk.split()[3].point(lambda p: int(p * k_in)))
    img.paste(lk, ((W - lk.width) // 2, logo_y + (290 - lk.height) // 2), lk)
    d.text((W / 2, logo_y + 318), HANDLE, font=font("semi", 32), fill=tuple(int(c * k_in) for c in PALE), anchor="ma")
    d.text((M_L, 1580), DISCLAIMER, font=font("body", 26), fill=(170, 190, 180))


# ----------------------------------------------------------------- zaman çizelgesi
def timeline(words, parts, total):
    """Sahne başlangıçları: kelime zamanlarından. parts: [hook, piyasa, eksikler?, belirsizlik?, soru, cta]"""
    def find(prefix_words, start_idx=0):
        for i in range(start_idx, len(words)):
            if words[i]["w"].lower().startswith(prefix_words):
                return i
        return None
    t = {"hook": 0.0}
    n_hook = len(parts[0].split())
    t["teams"] = None
    first = [i for i, w in enumerate(words[:n_hook]) if w["w"].endswith(".")]
    if first and first[0] + 1 < n_hook and words[min(n_hook, len(words) - 1)]["t"] - words[first[0] + 1]["t"] >= 1.0:
        t["teams"] = words[first[0] + 1]["t"] - 0.1
    i = find("piyasaya")
    if i is None:   # kanca piyasa kalıbıysa: ikinci cümlenin ilk kelimesi
        i = min(n_hook, len(words) - 1)
    t["market"] = words[i]["t"] - 0.15 if i is not None else t["teams"] + 1.6
    # eksikler: piyasa cümlesinden sonraki cümle (varsa) → ilk kelimesi
    pi = i
    if pi is not None:
        j = pi
        while j < len(words) and not words[j]["w"].endswith("."): j += 1
        t["absences"] = words[j + 1]["t"] - 0.1 if j + 1 < len(words) and not words[j + 1]["w"].lower().startswith(("beni", "bizi")) else None
    else:
        t["absences"] = None
    i = find("bizi") or find("beni"); t["risk"] = words[i]["t"] - 0.16 if i is not None else None
    # soru: "düşündüren" cümlesi bittikten sonraki kelime
    if i is not None:
        j = i
        while j < len(words) and not words[j]["w"].endswith("."): j += 1
        t["question"] = words[j + 1]["t"] - 0.1 if j + 1 < len(words) else total - 2.0
    else:
        t["question"] = total - 2.5
    return t


def sentence_times(words, parts):
    """Her cümlenin (parts) başlangıç zamanı: kelime sayılarına göre kelime zamanlarından."""
    times = []; idx = 0
    for p in parts:
        n = len(p.split())
        times.append(words[min(idx, len(words) - 1)]["t"] if words else 0.0)
        idx += n
    return times


def timeline_sentences(words, parts, total, has_absences, has_form):
    """Yapay zekâ metni cümle sırasıyla gelir: açılış, PİYASA, eksikler(opsiyonel), rakip/form(opsiyonel), bizi düşündüren, soru, kapanış.
    Sahneler cümle başlangıçlarına kilitlenir; eksik cümle yoksa sahne atlanır."""
    st = sentence_times(words, parts)
    order = [("hook", 0.0)]
    k = 1
    def nxt(name, cond=True):
        nonlocal k
        if cond and k < len(parts):
            order.append((name, max(0.0, st[k] - 0.12))); k += 1
    nxt("market")
    nxt("absences", has_absences)
    nxt("form", has_form)
    nxt("risk")
    # kalan cümleler (soru + kapanış) tek sahne: soru
    if k < len(parts):
        order.append(("question", max(0.0, st[k] - 0.12)))
    return order


def render(m, bl, pm, er, out_mp4, absences=None):
    th = social.theme(m.get("sport_key"))
    absences = absences if absences is not None else [a for a in (bl.get("absences") or []) if a.get("player")][:4]
    text, parts = build_script(m, bl, pm, absences)
    tmp = tempfile.mkdtemp(prefix="reels_")
    voice = os.path.join(tmp, "voice.mp3")
    ISSUES.clear()
    words = tts(text, voice, bl.get("pronounce"))
    if len(words) != len(text.split()):
        note_issue(f"altyazı eşleşmesi: ses {len(words)} kelime, metin {len(text.split())} kelime")
    vdur = (words[-1]["t"] + words[-1]["d"]) if words else 11.0
    total = max(11.0, vdur + 0.9)
    ai_script = bool((bl.get("reels_script") or "").strip())
    last5 = (er or {}).get("last5") or {}
    has_form = bool(last5) and any(last5.get(t) for t in last5)
    # metinde eksik cümlesi var mı? (3. cümle piyasa cümlesinden sonra ve 'düşündür' içermiyorsa)
    has_abs_sentence = len(parts) >= 6 and "düşündür" not in parts[2].lower() and "?" not in parts[2]
    has_form_sentence = len(parts) >= 7 and "düşündür" not in parts[3].lower() and "?" not in parts[3]
    if ai_script:
        tl = None
        order = timeline_sentences(words, parts, total, has_abs_sentence, has_form_sentence and has_form)
    else:
        tl = timeline(words, parts, total)
    hook = parts[0].rstrip(".")
    risk_short = (bl.get("risk_short") or short_words(bl.get("risk"), 12))
    question = (bl.get("question") or "Siz ne diyorsunuz?")
    if ai_script:
        # metindeki 'bizi düşündür' cümlesi varsa ekranda o görünsün (sesle aynı)
        for p in parts:
            if "düşündür" in p.lower() and len(p.split()) <= 22:
                risk_short = p.rstrip(".") ; break
    fsub = font("semi", 56)
    # sahne sırası
    scene_hook.m = m
    if tl is not None:
        order = [("hook", tl["hook"]), ("market", tl["market"])] + ([("teams", tl["teams"])] if tl.get("teams") else [])
        if tl.get("absences"): order.append(("absences", tl["absences"]))
        if tl.get("risk"): order.append(("risk", tl["risk"]))
        order.append(("question", tl["question"]))
    order = sorted(order, key=lambda x: x[1])
    n = int(total * FPS)
    frames_dir = os.path.join(tmp, "f"); os.makedirs(frames_dir)
    PUSH = 0.16
    use_video = VIDEO_BG and os.path.isdir(BG_DIR) and any(f.endswith(".mp4") for f in os.listdir(BG_DIR))
    def draw_scene(name, t_s):
        img = background_video(fi, th) if use_video else background(fi, th)
        d = ImageDraw.Draw(img)
        if name == "hook": scene_hook(img, d, t_s, hook, th)
        elif name == "teams": scene_teams(img, d, t_s, m, th)
        elif name == "market": scene_market(img, d, t_s, m, pm, er)
        elif name == "absences": scene_absences(img, d, t_s, absences, th)
        elif name == "form": scene_form(img, d, t_s, m, er, th)
        elif name == "risk": scene_risk(img, d, t_s, risk_short, th)
        elif name == "question": scene_question(img, d, t_s, question, th)
        return img
    cover = None
    for fi in range(n):
        t = fi / FPS
        # aktif sahne
        cur = 0
        for k, (nm, ts) in enumerate(order):
            if t >= ts: cur = k
        name, ts = order[cur]
        img = draw_scene(name, t - ts)
        # itme geçişi (önceki sahne yukarı kayar)
        if cur > 0 and t - ts < PUSH and name in ("absences", "risk"):
            k = ease_out_cubic((t - ts) / PUSH)
            prev = draw_scene(order[cur - 1][0], ts - order[cur - 1][1])
            comp = Image.new(img.mode, (W, H), (th["bg"] + (0,)) if img.mode == "RGBA" else th["bg"])
            comp.paste(prev, (0, int(-140 * k))); comp.paste(img.crop((0, 0, W, H)), (0, int(H * (1 - k) * 0.08)))
            img = comp
        d = ImageDraw.Draw(img)
        # ilerleme çubuğu
        d.rectangle((0, H - 320, int(W * t / total), H - 314), fill=YELLOW)
        if name != "question":
            subtitle(img, d, words, t, fsub)
        if fi == 0:
            cover = cover_image(draw_scene("hook", 9.0), m, th)
        if use_video:
            img.save(os.path.join(frames_dir, f"f{fi:04d}.png"))
        else:
            img.save(os.path.join(frames_dir, f"f{fi:04d}.jpg"), quality=92)
    # ses: ses 48k + pembe gürültü yatağı + sahne kesmelerinde tık; loudnorm
    ticks = []   # tık efekti kaldırıldı (ucuz duruyordu); yalnız ses
    tick_inputs = []; tick_filters = []
    for i, ts in enumerate(ticks):
        tick_inputs += ["-f", "lavfi", "-t", "0.015", "-i", "sine=frequency=1800:sample_rate=48000"]
        tick_filters.append(f"[{2 + i}:a]adelay={int(ts*1000)}|{int(ts*1000)},volume=0.08[t{i}]")
    mix_in = "[v][n]" + "".join(f"[t{i}]" for i in range(len(ticks)))
    # ses: sesli anlatım + tıklar; zemin gürültüsü YOK (kullanıcı karıncalanma duydu); sessiz yatak = anullsrc
    fc = (f"[0:a]aresample=48000,highpass=f=80,acompressor=ratio=3,volume=1.0[v];"
          f"[1:a]volume=0.0[n];" + ";".join(tick_filters) + (";" if tick_filters else "") +
          f"{mix_in}amix=inputs={2 + len(ticks)}:duration=longest:normalize=0,loudnorm=I=-14:TP=-1:LRA=7[a]")
    bg_mp4 = None
    if use_video:
        # sahne süreleri → klip parçaları (döngüyle uzatılır) → birleştir
        segs = []; used = []
        for k, (nm, ts) in enumerate(order):
            te = order[k + 1][1] if k + 1 < len(order) else total
            clip = clip_for(nm, used); used.append(clip)
            segs.append((clip, max(0.2, te - ts)))
        seg_files = []
        for k, (clip, dur) in enumerate(segs):
            sf = os.path.join(tmp, f"seg{k}.mp4")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "6", "-i", f"{BG_DIR}/{clip}.mp4", "-t", f"{dur:.2f}",
                            "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={FPS},"
                                   f"eq=contrast=1.04:saturation=0.9,vignette=PI/4.5,noise=alls=6:allf=t",
                            "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", sf], check=True)
            seg_files.append(sf)
        lst = os.path.join(tmp, "segs.txt")
        with open(lst, "w", encoding="utf-8") as f:
            for sf in seg_files:
                f.write("file '" + sf.replace(chr(92), "/") + "'" + chr(10))
        bg_mp4 = os.path.join(tmp, "bg.mp4")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", bg_mp4], check=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", os.path.join(frames_dir, "f%04d.png" if use_video else "f%04d.jpg"),
           "-i", voice, "-f", "lavfi", "-t", f"{total:.2f}", "-i", "anullsrc=r=48000:cl=stereo"] + tick_inputs + [
           "-filter_complex", fc.replace("[0:a]", "[1:a]").replace("[1:a]volume=0.008", "[2:a]volume=0.008") if False else fc,
           "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
           "-shortest", "-movflags", "+faststart", out_mp4]
    # ffmpeg giriş indeksleri: 0 = kareler, 1 = ses, 2 = pembe gürültü, 3.. = tıklar → filtrede buna göre yeniden adlandır
    fc2 = fc.replace("[0:a]", "[1:a]", 1)
    fc2 = fc2.replace("[1:a]volume=0.008[n]", "[2:a]volume=0.008[n]")
    for i in range(len(ticks)):
        fc2 = fc2.replace(f"[{2 + i}:a]adelay", f"[{3 + i}:a]adelay")
    cmd[cmd.index("-filter_complex") + 1] = fc2
    if use_video:
        # arka plan videosu en sona giriş olarak eklenir; kareler (şeffaf PNG) üstüne bindirilir
        n_in = sum(1 for a in cmd if a == "-i")
        i_fc = cmd.index("-filter_complex")
        cmd[i_fc:i_fc] = ["-i", bg_mp4]
        i_fc = cmd.index("-filter_complex")
        cmd[i_fc + 1] = f"[{n_in}:v]scale={W}:{H},setsar=1[bgv];[bgv][0:v]overlay=0:0:format=auto,format=yuv420p[vout];" + cmd[i_fc + 1]
        cmd[cmd.index("-map") + 1] = "[vout]"
    subprocess.run(cmd, check=True)
    cover_path = out_mp4[:-4] + "_kapak.jpg"
    if cover is not None:
        if cover.mode == "RGBA":   # video zemin modunda kapak: ilk kareyi arka plan videosunun ilk karesiyle birleştir
            try:
                bgf = os.path.join(tmp, "bg0.png")
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", bg_mp4, "-frames:v", "1", bgf], check=True)
                base = Image.open(bgf).convert("RGBA").resize((W, H))
            except Exception:
                base = Image.new("RGBA", (W, H), th["bg"] + (255,))
            cover = Image.alpha_composite(base, cover).convert("RGB")
        cover.save(cover_path, quality=92)
    shutil.rmtree(tmp, ignore_errors=True)
    return {"mp4": out_mp4, "cover": cover_path, "script": text, "seconds": round(total, 1), "words": len(words), "issues": list(ISSUES),
            "voice_mp3": voice}


def check_output(res, parts=None):
    """Yayın öncesi denetim: metin, ses, görüntü. Sorun listesi döner (boşsa yayınlanabilir)."""
    probs = list(res.get("issues") or [])
    text = res.get("script") or ""
    n = len(text.split())
    if re.search(r"P[İI]YASA", text): probs.append("metin: PİYASA yer tutucusu kaldı")
    if not (18 <= n <= 70): probs.append(f"metin: kelime sayısı {n}")
    if re.search(r"\b(ben|bana|bence|beni|benim)\b", text, re.I): probs.append("metin: birinci tekil şahıs")
    for b in BANNED:
        if re.search(rf"\b{b}", text, re.I): probs.append(f"metin: yasak kelime '{b}'")
    if "yüzde" not in text.lower(): probs.append("metin: piyasa cümlesi yok")
    if "?" not in text: probs.append("metin: soru yok")
    if re.search(r"\d+[.,]\d+", text): probs.append("metin: oran benzeri sayı")
    if "!" in text: probs.append("metin: ünlem")
    # video
    try:
        info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", res["mp4"]],
                                         capture_output=True, text=True).stdout)
        v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
        a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
        dur = float(info["format"]["duration"])
        if not v or int(v["width"]) != W or int(v["height"]) != H: probs.append("video: çözünürlük 1080x1920 değil")
        if not a: probs.append("video: ses izi yok")
        if not (12 <= dur <= 90): probs.append(f"video: süre {dur:.1f} sn")
        if abs(dur - res.get("seconds", dur)) > 1.5: probs.append("video: süre beklenenden farklı")
        if os.path.getsize(res["mp4"]) > 95 * 1024 * 1024: probs.append("video: dosya 95 MB'ı aşıyor")
    except Exception as e:
        probs.append(f"video: ffprobe okunamadı ({e})")
    # ses: seviye ve uzun sessizlik
    try:
        out = subprocess.run(["ffmpeg", "-i", res["mp4"], "-af", "volumedetect,silencedetect=n=-35dB:d=2.5", "-f", "null", "-"],
                             capture_output=True, text=True).stderr
        mv = re.search(r"mean_volume:\s*(-?[\d.]+)", out)
        if not mv or not (-28 <= float(mv.group(1)) <= -8): probs.append(f"ses: ortalama seviye {mv and mv.group(1)} dB")
        sil = [float(x) for x in re.findall(r"silence_duration:\s*([\d.]+)", out)]
        inner = [s for s in sil[:-1]] if sil else []   # sondaki sessizlik normal (kapanış)
        if any(s > 3.0 for s in inner): probs.append(f"ses: içeride {max(inner):.1f} sn sessizlik")
    except Exception as e:
        probs.append(f"ses: ölçülemedi ({e})")
    return probs


if __name__ == "__main__":
    if "--demo" in sys.argv:
        import build_site, espn
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc); cut = (now - timedelta(hours=12)).isoformat()
        rows = [r for r in build_site.read_jsonl("records/nesine/*.jsonl") if r.get("t", "") >= cut]
        m = next(x for x in build_site.nesine_matches(rows) if x["home"] == "Konyaspor"); m["league"] = "Türkiye Süper Ligi"
        ai = [json.loads(l) for l in open("records/claude/2026-10-30.jsonl", encoding="utf-8")][0]
        pm = {"MS": {"1": 0.18, "X": 0.20, "2": 0.62}, "AU25": {"Alt": 0.39, "Üst": 0.61}, "KG": {"Var": 0.57, "Yok": 0.43}}
        er = None
        os.makedirs("data/demo", exist_ok=True)
        r = render(m, ai["blind"], pm, er, "data/demo/reels_v2.mp4")
        print(json.dumps(r, ensure_ascii=False, indent=1))
