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
import json, os, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta

API = "https://graph.instagram.com/v21.0"
PAGES = "https://boradmir.github.io/iddia-bot"
LOG = "records/instagram.jsonl"
TR = timezone(timedelta(hours=3))
TOKEN = os.environ.get("IG_TOKEN", "")
USER_ID = os.environ.get("IG_USER_ID", "")
MAX_PER_DAY = int(os.environ.get("IG_MAX_PER_DAY", "2"))
HASHTAGS = "#futbol #maçanalizi #sakatlık #kadro"
NOTE = "18+ · Bilgi amaçlıdır; bahis veya yatırım tavsiyesi değildir."


def _post(path, params):
    data = urllib.parse.urlencode({**params, "access_token": TOKEN}).encode()
    req = urllib.request.Request(f"{API}/{path}", data=data, headers={"User-Agent": "iddia-bot"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


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


def load_log():
    if not os.path.exists(LOG):
        return []
    with open(LOG, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def caption_for(m, ai, pm):
    bl = (ai or {}).get("blind") or {}
    start = m["start"].astimezone(TR)
    parts = [f"{m['home']} – {m['away']} | {start:%d.%m %H:%M} | {m['league']}"]
    abs_ = [f"{a['player']} ({a['status']})" for a in (bl.get("absences") or [])[:4]]
    if abs_:
        parts.append("Eksikler: " + ", ".join(abs_))
    if pm and "MS" in pm:
        parts.append(f"Dünya bahis borsası: {m['home']} %{pm['MS']['1']*100:.0f} · beraberlik %{pm['MS']['X']*100:.0f} · {m['away']} %{pm['MS']['2']*100:.0f}")
    if bl.get("risk"):
        parts.append("En büyük belirsizlik: " + bl["risk"])
    parts.append(NOTE); parts.append(HASHTAGS)
    return "\n\n".join(parts)[:2100]


def main():
    import build_site, prob, odds, match
    dry = "--dry" in sys.argv or not (TOKEN and USER_ID)
    today = datetime.now(TR).date()
    sent = load_log()
    sent_today = [s for s in sent if s["day"] == str(today)]
    if len(sent_today) >= MAX_PER_DAY:
        print(f"Bugünkü sınır dolu ({MAX_PER_DAY})"); return
    day_dir = f"docs/social/{today}"
    if not os.path.isdir(day_dir):
        print("Bugün için kart yok"); return
    rows = build_site.read_jsonl("records/nesine/*.jsonl"); t, last = build_site.latest_snapshot(rows)
    now = datetime.now(timezone.utc)
    nm = [m for m in build_site.nesine_matches(last) if m["start"].astimezone(TR).date() == today and m["start"] > now + timedelta(hours=1)]
    ai = {r["code"]: r for r in build_site.read_jsonl("records/claude/*.jsonl") if r.get("blind")}
    pin = build_site.pinnacle_events(build_site.read_jsonl("records/pinnacle/*.jsonl"))
    aliases = json.load(open("aliases.json", encoding="utf-8")) if os.path.exists("aliases.json") else {}
    done = {s["code"] for s in sent}
    # öncelik: yorumu olan (iki kartlı) maçlar, sonra en yakın başlangıç
    cands = []
    for m, ev, score in match.match_all(nm, pin, aliases):
        if m["code"] in done or not os.path.exists(f"{day_dir}/match_{m['code']}.png"):
            continue
        pm = prob.market_probs(odds.pinnacle_h2h(ev), odds.pinnacle_totals(ev)) if ev and odds.pinnacle_h2h(ev) else None
        has_comment = os.path.exists(f"{day_dir}/yorum_{m['code']}.png")
        cands.append((0 if has_comment else 1, m["start"], m, pm, has_comment))
    cands.sort(key=lambda x: (x[0], x[1]))
    budget = MAX_PER_DAY - len(sent_today)
    for _, _, m, pm, has_comment in cands[:budget]:
        urls = [f"{PAGES}/social/{today}/match_{m['code']}.png"] + ([f"{PAGES}/social/{today}/yorum_{m['code']}.png"] if has_comment else [])
        cap = caption_for(m, ai.get(m["code"]), pm)
        if dry:
            print(f"[kuru] {m['home']}-{m['away']}: {len(urls)} görsel\n{cap[:300]}...\n"); continue
        try:
            pid = publish_carousel(urls, cap)
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps({"day": str(today), "code": m["code"], "home": m["home"], "away": m["away"], "post_id": pid,
                                    "t": datetime.now(timezone.utc).isoformat(timespec="seconds")}, ensure_ascii=False) + "\n")
            print(f"Gönderildi: {m['home']}-{m['away']} ({pid})")
        except Exception as e:
            print(f"Gönderim hatası {m['home']}-{m['away']}: {e}")


if __name__ == "__main__":
    main()
