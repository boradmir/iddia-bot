"""Instagram'a otomatik gönderim (Instagram Graph API, içerik yayınlama).

Gereksinimler (bir kez, kullanıcı yapar):
  1. Instagram hesabı "Profesyonel → İçerik üreticisi" olmalı.
  2. developers.facebook.com → uygulama (tür: Business) → "Instagram" ürünü → "Instagram API with Instagram Login".
  3. Uygulama panelinde hesabı test kullanıcısı olarak ekle, "Generate token" ile erişim belirteci al
     (izinler: instagram_business_basic, instagram_business_content_publish). Belirteç 60 gün geçerli; yenilenir.
  4. GitHub secret: IG_TOKEN (belirteç), IG_USER_ID (Instagram kullanıcı kimliği, panelde görünür).

Nasıl çalışır: kart görselleri GitHub Pages'te herkese açık URL'de durur (API bunu ister); her maç için
carousel (maç kartı + yorum kartı) oluşturulur ve yayınlanır. Günlük en fazla IG_MAX_PER_DAY gönderi.
Gönderilenler records/instagram.jsonl'da tutulur (tekrar gönderilmez). Secret yoksa kuru çalışma (sadece yazar).

Kullanım: python instagram.py [--dry]
"""
import json, os, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta
import config, clubs, control  # .env yükler (yerelde); Actions'ta secrets zaten ortamda

TOKEN_ENV = os.environ.get("IG_TOKEN", "")
# Belirteç türüne göre uç nokta: "IGAA…" = Instagram login (graph.instagram.com), "EAA…" = Unified/Facebook login (graph.facebook.com)
API = "https://graph.instagram.com/v21.0" if TOKEN_ENV.startswith("IG") else "https://graph.facebook.com/v21.0"
PAGES = "https://boradmir.github.io/iddia-bot"
RAW = "https://raw.githubusercontent.com/boradmir/iddia-bot/master/docs"   # story'ler için: push ile anında erişilir, Pages derlemesi beklenmez
LOG = "records/instagram.jsonl"
TR = timezone(timedelta(hours=3))
TOKEN = os.environ.get("IG_TOKEN", "")
USER_ID = os.environ.get("IG_USER_ID", "")
MAX_PER_DAY = int(os.environ.get("IG_MAX_PER_DAY", "2"))
HASHTAGS = "#maçanalizi"
NOTE = "18+ · Burada kupon yok, okuma var. Karar sizin."
LEAGUE_TAGS = {"soccer_turkey_super_league": "#SüperLig", "soccer_epl": "#PremierLeague", "soccer_spain_la_liga": "#LaLiga",
               "soccer_italy_serie_a": "#SerieA", "soccer_germany_bundesliga": "#Bundesliga", "soccer_france_ligue_one": "#Ligue1",
               "soccer_uefa_champs_league": "#ŞampiyonlarLigi", "soccer_uefa_europa_league": "#AvrupaLigi",
               "soccer_uefa_europa_conference_league": "#KonferansLigi", "soccer_uefa_nations_league": "#UluslarLigi"}
BIG = {"Galatasaray", "Fenerbahçe", "Fenerbahce", "Beşiktaş", "Besiktas", "Trabzonspor", "Real Madrid", "Barcelona", "Man. City", "Man. Utd", "Liverpool",
       "Arsenal", "Chelsea", "Bayern Münih", "B. Dortmund", "Juventus", "Inter", "AC Milan", "PSG", "Atl Madrid", "Napoli", "Tottenham"}


def tag_name(name):
    """Takım adından hashtag: boşluk/nokta/çizgi atılır (#Konyaspor, #ManUtd)."""
    import re
    t = re.sub(r"[^0-9A-Za-zÇĞİÖŞÜçğıöşü]", "", name.replace(".", ""))
    return "#" + t if t else ""


def hashtags_for(m):
    """En fazla 5 etiket (Instagram sınırı), etkileşim sırasına göre:
    büyük kulüp → diğer takım → maç eşleşmesi (#KONvGS) → lig → #maçanalizi."""
    import social
    _, _, ha = social.team_style(m["home"]); _, _, aa = social.team_style(m["away"])
    tr = str.maketrans("İÇÖŞÜĞ", "ICOSUG")
    teams = [m["home"], m["away"]]
    teams.sort(key=lambda t: 0 if t in BIG else 1)      # büyük kulüp önce
    pair = tag_name(teams[0]) + tag_name(teams[1]).lstrip("#")   # #GalatasarayKonyaspor (aranan biçim)
    tags = [tag_name(teams[0]), tag_name(teams[1]), pair, LEAGUE_TAGS.get(m.get("sport_key"), ""), "#maçanalizi"]
    out, seen = [], set()
    for t in tags:
        if t and t.lower() not in seen:
            out.append(t); seen.add(t.lower())
    return " ".join(out[:5])


def _post(path, params):
    data = urllib.parse.urlencode({**params, "access_token": TOKEN}).encode()
    req = urllib.request.Request(f"{API}/{path}", data=data, headers={"User-Agent": "iddia-bot"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"API {e.code} {path}: {body}") from None


def _get(path, params):
    q = urllib.parse.urlencode({**params, "access_token": TOKEN})
    with urllib.request.urlopen(f"{API}/{path}?{q}", timeout=60) as r:
        return json.loads(r.read())


def wait_ready(container_id, tries=20):
    for _ in range(tries):
        st = _get(container_id, {"fields": "status_code"}).get("status_code")
        if st == "FINISHED":
            return True
        if st in ("ERROR", "EXPIRED"):
            return False
        time.sleep(5)
    return False


def publish_carousel(image_urls, caption):
    children = []
    for u in image_urls:
        c = _post(f"{USER_ID}/media", {"image_url": u, "is_carousel_item": "true"})
        if not wait_ready(c["id"]):
            raise RuntimeError(f"görsel hazırlanamadı: {u}")
        children.append(c["id"])
    if len(children) == 1:
        c = _post(f"{USER_ID}/media", {"image_url": image_urls[0], "caption": caption})
    else:
        c = _post(f"{USER_ID}/media", {"media_type": "CAROUSEL", "children": ",".join(children), "caption": caption})
    if not wait_ready(c["id"]):
        raise RuntimeError("carousel hazırlanamadı")
    return _post(f"{USER_ID}/media_publish", {"creation_id": c["id"]})["id"]


MAX_STORY_PER_DAY = int(os.environ.get("IG_STORY_MAX_PER_DAY", "3"))   # tür başına (kadro / devre arası / maç sonu)


def publish_story(image_url):
    """Tek görselli story (1080×1920). Yazı/altyazı almaz; 24 saat kalır."""
    c = _post(f"{USER_ID}/media", {"media_type": "STORIES", "image_url": image_url})
    if not wait_ready(c["id"]):
        raise RuntimeError("story hazırlanamadı")
    return _post(f"{USER_ID}/media_publish", {"creation_id": c["id"]})["id"]


def publish_reels_file(path, caption, thumb_offset_ms=0, share_to_feed=True, publish=True, cover_url=None):
    """Reels: videoyu doğrudan yükler (resumable upload; barındırma gerekmez), işlenmesini bekler, yayınlar.
    publish=False: yalnız kapsayıcı + yükleme + hazır olma testi (yayınlamaz)."""
    size = os.path.getsize(path)
    params = {"media_type": "REELS", "upload_type": "resumable", "caption": caption, "share_to_feed": "true" if share_to_feed else "false"}
    if cover_url:
        params["cover_url"] = cover_url
    else:
        params["thumb_offset"] = str(thumb_offset_ms)
    c = _post(f"{USER_ID}/media", params)
    cid = c["id"]
    up_url = c.get("uri") or f"https://rupload.facebook.com/ig-api-upload/v21.0/{cid}"
    with open(path, "rb") as f:
        data = f.read()
    req = urllib.request.Request(up_url, data=data, method="POST",
                                 headers={"Authorization": f"OAuth {TOKEN}", "offset": "0", "file_size": str(size),
                                          "Content-Type": "application/octet-stream", "User-Agent": "iddia-bot"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            up = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"video yüklenemedi {e.code}: {e.read().decode('utf-8', 'replace')[:300]}") from None
    if not up.get("success", True):
        raise RuntimeError(f"video yüklenemedi: {up}")
    if not wait_ready(cid, tries=90):   # video işleme 1-5 dk sürebilir
        st = _get(cid, {"fields": "status_code,status"})
        raise RuntimeError(f"reels hazırlanamadı: {st}")
    if not publish:
        return cid
    return _post(f"{USER_ID}/media_publish", {"creation_id": cid})["id"]


def reels_caption(m, bl, pm=None):
    """Reels açıklaması: kısa. İlk satır arama için; soru; dipnot; hashtag."""
    hook = (bl.get("hook") or "").strip()
    q = (bl.get("question") or "").strip() or "Siz ne düşünüyorsunuz?"
    parts = [f"{m['home']} – {m['away']} maç öncesi analiz" + (f": {hook}" if hook else ""),
             f"{q} Yoruma yazın. Maç sonu karşılaştırmak için kaydedin.", NOTE, hashtags_for(m)]
    return "\n\n".join(parts)[:2190]


def log_post(m, kind, pid):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"day": str(datetime.now(TR).date()), "type": kind, "code": m["code"], "home": m["home"], "away": m["away"],
                            "post_id": pid, "t": datetime.now(timezone.utc).isoformat(timespec="seconds")}, ensure_ascii=False) + "\n")


def wait_public(url, timeout=480, size=None):
    """GitHub Pages görseli yayınlayana kadar bekle (en fazla timeout sn). size verilirse dosya boyutu eşleşene kadar
    (aynı adreste eski bir sürüm varsa yenisi gelsin diye)."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "iddia-bot", "Cache-Control": "no-cache"})
            with urllib.request.urlopen(req, timeout=20) as r:
                if r.status == 200 and (size is None or int(r.headers.get("Content-Length", 0)) == size):
                    return True
        except Exception:
            pass
        time.sleep(10)
    return False


def post_story_for(m, image_url, kind="story", size=None):
    """Maç story'si (kind: story=kadro, story_ht=devre arası, story_ft=maç sonu): tür başına günde en fazla
    MAX_STORY_PER_DAY, maç+tür başına bir kez. Günlüğe type=kind yazar."""
    if not (TOKEN and USER_ID):
        return None
    today = str(datetime.now(TR).date())
    log = load_log()
    if any(s.get("type") == kind and s.get("code") == m["code"] for s in log):
        return None
    if sum(1 for s in log if s.get("type") == kind and s.get("day") == today) >= MAX_STORY_PER_DAY:
        return None
    if not wait_public(image_url, size=size):
        raise RuntimeError(f"görsel yayına girmedi: {image_url}")
    pid = publish_story(image_url)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"day": today, "type": kind, "code": m["code"], "home": m["home"], "away": m["away"], "post_id": pid,
                            "t": datetime.now(timezone.utc).isoformat(timespec="seconds")}, ensure_ascii=False) + "\n")
    return pid


def existing_captions():
    """Hesaptaki son gönderilerin açıklamaları (elle paylaşılanlar dahil) — aynı maç bir daha gitmesin."""
    caps = []
    try:
        d = _get(f"{USER_ID}/media", {"fields": "caption,timestamp", "limit": "50"})
        caps = [(x.get("caption") or "") for x in d.get("data", [])]
    except Exception as e:
        print(f"mevcut gönderiler okunamadı: {e}")
    return caps


def already_posted(m, caps):
    keys = (f"{m['home']} – {m['away']} |", f"{m['home']} – {m['away']} maç analizi")
    return any(k in c for c in caps for k in keys)


def load_log():
    if not os.path.exists(LOG):
        return []
    with open(LOG, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def caption_for(m, ai, pm):
    ov = ((ai or {}).get("caption_override") or "").strip()   # panelden düzenlenmiş açıklama: olduğu gibi kullanılır
    if ov:
        return ov[:2190]
    bl = (ai or {}).get("blind") or {}
    start = m["start"].astimezone(TR)
    import social, re
    parts = []
    # kanca: yapay zekânın yazdığı tam cümle (hook); eski kayıtlarda yoksa yazının ilk cümlesi — asla ortadan kesilmez
    hook = (bl.get("hook") or "").strip()
    if not hook:
        comment = (bl.get("comment") or "").strip()
        if comment:
            first = re.split(r"(?<=[.!?])\s+", comment)[0]
            if len(first) > 200:
                # en fazla 200 karakter: son virgül/noktalı virgülde kes, nokta ile bitir
                cut = max(first.rfind(", ", 0, 190), first.rfind("; ", 0, 190))
                first = (first[:cut].rstrip() + ".") if cut > 60 else first[:190].rsplit(" ", 1)[0].rstrip(",;") + "."
            hook = first
    # ilk satır: arama için anahtar kelime + kanca
    parts.append(f"{m['home']} – {m['away']} maç analizi: {hook}" if hook else f"{m['home']} – {m['away']} maç analizi")
    parts.append(f"{social.tr_date(m['start'])}, {start:%H:%M} | {m['league']}")
    # tam yazı açıklamada (kartta kısa sürüm var)
    comment_full = (bl.get("comment") or "").strip()
    if comment_full and comment_full != hook:
        parts.append(comment_full)
    abs_ = [f"{a['player']} ({a['status']})" for a in (bl.get("absences") or [])[:4]]
    if abs_:
        parts.append("Eksikler: " + ", ".join(abs_))
    if pm and "MS" in pm:
        parts.append(f"Uluslararası piyasanın ihtimali: {m['home']} %{pm['MS']['1']*100:.0f} · beraberlik %{pm['MS']['X']*100:.0f} · {m['away']} %{pm['MS']['2']*100:.0f}")
    if bl.get("risk"):
        parts.append("En büyük belirsizlik: " + bl["risk"])
    q = (bl.get("question") or "").strip() or "Siz ne düşünüyorsunuz?"
    parts.append(f"{q} Yoruma yazın. Maç sonu karşılaştırmak için kaydedin.")
    parts.append(NOTE); parts.append(hashtags_for(m))
    cap = "\n\n".join(parts)
    if len(cap) > 2150:   # Instagram sınırı 2200: önce tam yazıyı kısalt
        short = comment_full[:comment_full.rfind(". ", 0, 700) + 1] if comment_full else ""
        cap = "\n\n".join(p if p != comment_full else short for p in parts)
    return cap[:2190]


PLAN = "records/plan.json"


def day_plan(day):
    """Günün planı (reels saati vb.); dosya yoksa boş."""
    try:
        return json.load(open(PLAN, encoding="utf-8")).get(str(day), {})
    except Exception:
        return {}


def post_slots(cands, today, ctrl=None):
    """Her aday için yayın saati (TR). İlk: 12:00; maç 15:00'ten erkense 10:00; o gün reels 2 saat içindeyse 2 saat öne (en erken 09:00).
    Sonrakiler (31.10.2026 kuralı): maçtan 3,5 saat önce (hafta sonu 4 saat; gündüz kullanım daha yaygın), 15:30'dan erken ve
    18:00'den geç olmasın; önceki karusel ve günün reels'inden en az 3 saat sonra (birbirlerinin erişimini düşürmesinler);
    her durumda maçtan en geç 1 saat önce. Gerekçe: küçük hesapta erişim ilk 60-90 dk'daki kaydet/paylaş sinyaliyle açılıyor,
    Türkiye'de akşam yoğunluğu 17:00'de başlıyor; 20:00-22:00 zirvesi maçın içinde kaldığı için ön analiz o saate bırakılmaz.
    Panel kararları (control.json): posts[gün:kod].at hesaplanan saatin yerine geçer (maçtan ≥1 sa önce kuralı yine uygulanır);
    reels saati control.reels[gün].at'tan (status planned/ready) okunur, yoksa plan.json reels_at (geriye uyum)."""
    if ctrl is None:
        ctrl = control.load()
    plan = day_plan(today)
    rc = control.reels(ctrl, today)
    ra = rc.get("at") if rc.get("status") in ("planned", "ready") else plan.get("reels_at")
    slots = []
    prev = None
    for i, (_, m, pm, has_comment) in enumerate(cands):
        ko = m["start"].astimezone(TR)
        if i == 0:
            t = ko.replace(hour=12, minute=0, second=0, microsecond=0)
            if ko < ko.replace(hour=15, minute=0):
                t = t.replace(hour=10)
            if ra:
                rh, rm = map(int, ra.split(":")); r_at = ko.replace(hour=rh, minute=rm, second=0, microsecond=0)
                if abs((r_at - t).total_seconds()) < 2 * 3600:
                    t = max(r_at - timedelta(hours=2), ko.replace(hour=9, minute=0, second=0, microsecond=0))
        else:
            lead = timedelta(hours=4) if ko.weekday() >= 5 else timedelta(hours=3, minutes=30)
            t = min(max(ko - lead, ko.replace(hour=15, minute=30, second=0, microsecond=0)), ko.replace(hour=18, minute=0, second=0, microsecond=0))
            t = max(t, prev + timedelta(hours=3))
            if ra:
                rh, rm = map(int, ra.split(":")); t = max(t, ko.replace(hour=rh, minute=rm, second=0, microsecond=0) + timedelta(hours=3))
        ov = control.post(ctrl, today, m.get("code")) if m.get("code") is not None else {}
        hm = control.parse_hm(ov.get("at")) if ov.get("at") else None
        if hm:
            t = ko.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
        if t > ko - timedelta(hours=1):
            if hm:
                print(f"uyarı: panel saati {ov['at']} maça 1 saatten yakın, {ko - timedelta(hours=1):%H:%M} alındı")
            t = ko - timedelta(hours=1)
        slots.append(t); prev = t
    return slots


def plan_today(today, ctrl=None, only=None, caps=None):
    """Günün karusel planı: aday maçlar, sıraları, saatleri, atlananlar. instagram.main ve panel aynı listeyi kullanır.
    only: ev sahibi adı parçaları (elle yeniden yükleme; sınır ve günlük yok sayılır). caps: hesaptaki açıklamalar (None = bakılmaz)."""
    import build_site, prob, odds, match
    if ctrl is None:
        ctrl = control.load()
    sent = load_log()
    sent_today = [s for s in sent if s["day"] == str(today) and not str(s.get("type", "")).startswith(("story", "reels"))]
    out = {"paused_until": ctrl.get("paused_until") if control.is_paused(ctrl) else None,
           "sent_today": sent_today, "picked": [], "skipped": [], "waiting": []}
    day_dir = f"docs/social/{today}"
    if not os.path.isdir(day_dir):
        return out
    rows = build_site.read_jsonl("records/nesine/*.jsonl"); t, last = build_site.recent_snapshot(rows)
    now = datetime.now(timezone.utc)
    nm = [m for m in build_site.nesine_matches(last) if m["start"].astimezone(TR).date() == today and m["start"] > now + timedelta(hours=1)]
    pin = build_site.pinnacle_events(build_site.read_jsonl("records/pinnacle/*.jsonl"))
    aliases = json.load(open("aliases.json", encoding="utf-8")) if os.path.exists("aliases.json") else {}
    done = {s["code"] for s in sent if not str(s.get("type", "")).startswith(("story", "reels"))}
    cands = []
    for m, ev, score in match.match_all(nm, pin, aliases):
        if not os.path.exists(f"{day_dir}/match_{m['code']}.jpg"):
            continue
        if only is not None:
            if not any(k in m["home"].lower() for k in only):
                continue
        elif m["code"] in done:
            continue
        if control.post(ctrl, today, m["code"]).get("skip"):
            out["skipped"].append({"m": m, "reason": "panel"}); continue
        if caps is not None and already_posted(m, caps):
            out["skipped"].append({"m": m, "reason": "hesapta var"}); continue
        pm = prob.market_probs(odds.pinnacle_h2h(ev), odds.pinnacle_totals(ev)) if ev and odds.pinnacle_h2h(ev) else None
        has_comment = os.path.exists(f"{day_dir}/yorum_{m['code']}.jpg")
        cands.append(((0 if has_comment else 1, clubs.tier(m), m["start"]), m, pm, has_comment))
    cands.sort(key=lambda x: x[0])  # yorumu olan → büyük kulüp → erken başlayan
    budget = len(cands) if only is not None else max(0, MAX_PER_DAY - len(sent_today))
    picked = cands[:budget]
    out["waiting"] = [{"m": c[1]} for c in cands[budget:]]
    prev = [(None, {"start": datetime.fromisoformat(x["t"]).astimezone(TR), "code": x.get("code")}, None, None) for x in sent_today]
    slots = post_slots(prev + picked, today, ctrl)[len(sent_today):] if only is None else [None] * len(picked)
    for (_, m, pm, has_comment), slot in zip(picked, slots):
        urls = [f"{PAGES}/social/{today}/match_{m['code']}.jpg"] + ([f"{PAGES}/social/{today}/yorum_{m['code']}.jpg"] if has_comment else [])
        out["picked"].append({"m": m, "pm": pm, "has_comment": has_comment, "slot": slot, "urls": urls})
    return out


def main():
    import build_site
    dry = "--dry" in sys.argv or not (TOKEN and USER_ID)
    today = datetime.now(TR).date()
    ctrl = control.load()
    if control.is_paused(ctrl):
        pu = datetime.fromisoformat(ctrl["paused_until"])
        print(f"Duraklatıldı (panel), {pu:%d.%m %H:%M} kadar")
        if pu.astimezone(TR).date() == today:
            print(f"NEXT_SLOT_UTC={pu.astimezone(timezone.utc):%H:%M}")
        return
    # --only Konyaspor,Nice : sadece bu ev sahiplerini gönder (günlük sınır ve günlük yok sayılır; elle yeniden yükleme için)
    only = [s.strip().lower() for s in sys.argv[sys.argv.index("--only") + 1].split(",")] if "--only" in sys.argv else None
    caps = existing_captions() if (TOKEN and USER_ID) else []  # kuru modda da hesaptaki gönderilere bak
    plan = plan_today(today, ctrl, only, caps)
    if only is None and len(plan["sent_today"]) >= MAX_PER_DAY:
        print(f"Bugünkü sınır dolu ({MAX_PER_DAY})"); return
    if not os.path.isdir(f"docs/social/{today}"):
        print("Bugün için kart yok"); return
    for s in plan["skipped"]:
        print(f"atlandı ({s['reason']}): {s['m']['home']}-{s['m']['away']}")
    ai = {r["code"]: r for r in build_site.read_jsonl("records/claude/*.jsonl") if r.get("blind")}
    now_tr = datetime.now(TR)
    pending = []
    for p in plan["picked"]:
        m, slot = p["m"], p["slot"]
        if slot is not None and now_tr < slot:
            pending.append(slot); print(f"planlı {slot:%H:%M}: {m['home']}-{m['away']}"); continue
        cap = caption_for(m, ai.get(m["code"]), p["pm"])
        if dry:
            print(f"[kuru] {m['home']}-{m['away']} ({slot and f'{slot:%H:%M}'}): {len(p['urls'])} görsel\n{cap[:300]}...\n"); continue
        try:
            pid = publish_carousel(p["urls"], cap)
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps({"day": str(today), "code": m["code"], "home": m["home"], "away": m["away"], "post_id": pid,
                                    "t": datetime.now(timezone.utc).isoformat(timespec="seconds")}, ensure_ascii=False) + "\n")
            print(f"Gönderildi: {m['home']}-{m['away']} ({pid})")
        except Exception as e:
            print(f"Gönderim hatası {m['home']}-{m['away']}: {e}")
    if pending:
        print(f"NEXT_SLOT_UTC={min(pending).astimezone(timezone.utc):%H:%M}")


INTRO_CAPTION = """Skordan öncesini okuruz.

Her maçtan önce: kim yok, kim formda, uluslararası piyasa ne diyor. Kadro, sakatlık, son 5 maç, golcüler ve bir yazar sesiyle maç önü yazısı.

Kupon yok, oran yok, tavsiye yok. Tutanı da tutmayanı da yazarız; zamanla kimin daha isabetli olduğu sayıyla çıkar.

Kartlar nasıl okunur, bu gönderide. Hoş geldiniz.

""" + NOTE + "\n\n#futbol #maçanalizi #SüperLig #PremierLeague #analizveotesi"


def post_intro():
    urls = [f"{PAGES}/social/intro/intro_{k}.jpg" for k in (1, 2, 3, 4)]
    pid = publish_carousel(urls, INTRO_CAPTION)
    print(f"Tanıtım gönderildi: {pid}")


if __name__ == "__main__":
    if "--intro" in sys.argv:
        post_intro()
    else:
        main()
