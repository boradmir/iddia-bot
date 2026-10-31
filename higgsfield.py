"""Higgsfield API istemcisi: text-to-video gönder, bekle, indir. Arka plan kütüphanesi (assets/bg/) üretir.
Ortam: HIGGSFIELD_API_KEY (key id), HIGGSFIELD_SECRET. Kullanım: python higgsfield.py --test | --library [--model slug]
Fiyat (indirimli, sn başı): wan-3.0 ~0.02 $, kling-2.5 ~0.02 $, seedance-2.5 ~0.14 $.
"""
import json, os, sys, time, uuid, urllib.request
import config

API = "https://api.higgsfield.ai"
KEY = os.environ.get("HIGGSFIELD_API_KEY", ""); SECRET = os.environ.get("HIGGSFIELD_SECRET", "")
BG_DIR = "assets/bg"
DEFAULT_MODEL = "alibaba/wan-3.0/text-to-video"

# Her prompt: sinematik, insansız, logosuz, döngüye uygun yavaş hareket; dikey 9:16 kadraj düşünülerek yazıldı.
STYLE = ("Documentary realism, real footage look, shot handheld on a vintage full-frame cinema camera with a 50mm lens, slight natural handheld sway, "
         "shallow depth of field with soft imperfect focus, real physical materials with wear: scratches, smudges, dust, fingerprints, uneven chalk, "
         "available light from a single warm desk lamp or window, deep shadows, natural film grain and subtle halation, slightly desaturated dark green, "
         "chalk-white and warm amber palette, nothing glossy or CGI-like, no people, no faces, hands only where stated, no readable text, no numbers, "
         "absolutely no letters, no words, no writing of any kind on paper, cards or boards, no logos, no club crests, no watermarks, vertical 9:16 composition with calm empty space in the upper third, slow loopable motion")
# ANALİZ dünyası: taktik tahtası, maket saha, kalem ve kâğıt, mıknatıslı pano, analist masası, veri ekranı — "bir şeyler biliyoruz" hissi
LIBRARY = {
    "chalk_arrow":     "Dark green chalkboard, a hand holding white chalk draws a long curved tactical arrow from one side of a drawn pitch to the other, "
                       "chalk dust drifting in the side light, extreme close-up, slow motion",
    "chalk_pitch":     "Dark green chalkboard with a hand-drawn football pitch in white chalk, small chalk circles and crosses as players, "
                       "camera slowly drifts across the board, chalk dust particles in the light",
    "chalk_erase":     "Close-up of a chalkboard duster wiping white chalk tactical lines off a dark green board in slow motion, dust cloud catching the light",
    "magnet_board":    "Dark tactical magnet board with a printed pitch, round red and yellow player magnets, a hand slides one magnet forward, "
                       "overhead view, soft studio light",
    "table_pitch":     "Miniature tabletop football pitch model on a dark wooden desk, small wooden player pieces, a hand moves one piece, "
                       "shallow depth of field, warm desk lamp light, slow push-in",
    "pen_paper":       "Fountain pen drawing a tactical arrow and a circle on plain cream paper with a printed pitch diagram only (no words), extreme close-up, "
                       "ink glistening, slow motion, warm desk lamp",
    "analyst_desk":    "Dark analyst desk at night: an open notebook with only hand-drawn pitch diagrams and arrows (no writing), a pen, a cup of coffee, a pair of glasses, "
                       "warm lamp light, slow lateral dolly, shallow focus",
    "string_board":    "Cork board in low light with pinned blank index cards connected by red string, like an investigation board, "
                       "camera slowly pans across, shallow focus, no readable writing",
    "whistle_desk":    "Referee whistle and a worn leather notebook on a dark wooden desk, rain on a window behind, warm lamp light, slow dolly",
    "chalk_dust":      "Macro of chalk dust particles floating slowly in a beam of warm light against a dark green board, abstract, loopable",
    "tactics_sheet":   "Printed match tactics sheet with blank pitch diagrams on a dark desk, a pencil rolls slowly into frame, "
                       "overhead view, soft light, no readable text",
    "rain_window":     "Rain running down a dark window at night with blurred warm stadium lights far behind, slow drift, moody, abstract",
}


def _req(method, path, body=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"Authorization": f"Key {KEY}:{SECRET}", "Content-Type": "application/json", "Idempotency-Key": str(uuid.uuid4())})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


RATE = {"seedance": {"480p": 0.2056, "720p": 0.4622, "1080p": 1.1372}, "wan": {"480p": 0.05, "720p": 0.10, "1080p": 0.20}}   # $/sn, liste fiyatı (estimate, 31.10.2026)


def estimate_cost(model, duration, resolution):
    """Klip başına tahmini $ (panel bakiye defteri için). Bakiye uç noktası yok; liste fiyatı × saniye."""
    fam = "seedance" if "seedance" in (model or "").lower() else "wan"
    return round(RATE[fam].get(str(resolution), RATE[fam]["1080p"]) * float(duration), 2)


def submit(prompt, model=DEFAULT_MODEL, duration=5, resolution="1080p", aspect="9:16", seed=None):
    body = {"prompt": prompt, "aspect_ratio": aspect, "duration": duration, "resolution": resolution}
    if seed is not None:
        body["seed"] = seed
    return _req("POST", "/" + model, body)


def wait(request_id, every=6, timeout=900):
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = _req("GET", f"/requests/{request_id}/status")
        if s.get("status") in ("completed", "failed", "nsfw", "canceled"):
            return s
        time.sleep(every)
    return {"status": "timeout"}


def video_url(status):
    v = status.get("video") or {}
    if isinstance(v, dict) and v.get("url"):
        return v["url"]
    for k in ("videos", "output", "result"):
        x = status.get(k)
        if isinstance(x, list) and x and isinstance(x[0], dict) and x[0].get("url"):
            return x[0]["url"]
        if isinstance(x, dict) and x.get("url"):
            return x["url"]
    return None


def download(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": "iddia-bot"})
    with urllib.request.urlopen(req, timeout=300) as r, open(path, "wb") as f:
        f.write(r.read())
    return os.path.getsize(path)


def generate(name, prompt, model=DEFAULT_MODEL, duration=5, resolution="1080p", out_dir=BG_DIR):
    os.makedirs(out_dir, exist_ok=True)
    full = f"{prompt}. {STYLE}"
    sub = submit(full, model, duration, resolution)
    rid = sub.get("request_id") or sub.get("id")
    print(f"[{name}] gönderildi: {rid} ({model}, {duration} sn, {resolution})")
    st = wait(rid)
    url = video_url(st)
    if st.get("status") != "completed" or not url:
        print(f"[{name}] BAŞARISIZ: {json.dumps(st)[:300]}"); return None
    path = f"{out_dir}/{name}.mp4"
    size = download(url, path)
    meta = {"name": name, "model": model, "duration": duration, "resolution": resolution, "prompt": full, "request_id": rid,
            "credits": st.get("credits") or st.get("cost") or st.get("billing"), "credits_usd": estimate_cost(model, duration, resolution),
            "size": size, "t": time.strftime("%Y-%m-%dT%H:%M:%S")}
    with open(f"{out_dir}/library.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(meta, ensure_ascii=False) + "\n")
    print(f"[{name}] indirildi: {size // 1024} KB; durum alanları: {sorted(st.keys())}")
    return path


if __name__ == "__main__":
    model = sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv else DEFAULT_MODEL
    res = sys.argv[sys.argv.index("--res") + 1] if "--res" in sys.argv else "1080p"
    if "--test" in sys.argv:
        generate("test_stadium_lights", LIBRARY["stadium_lights"], model, 5, res, out_dir="data/demo/bg")
    elif "--library" in sys.argv:
        names = sys.argv[sys.argv.index("--only") + 1].split(",") if "--only" in sys.argv else list(LIBRARY)
        for n in names:
            generate(n, LIBRARY[n], model, 5, res)
