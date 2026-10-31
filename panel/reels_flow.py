"""Reels akışı (panel içi): maç seç → metin → ses (Ahu / erkek) → video → denetim → önizleme → saat → yayına al.
'Yayına al': mp4 + açıklama GitHub Release'e yüklenir, kapak docs/social'a; control.reels[gün] 'ready' olur; bekçi saatinde yayınlar
(bilgisayar kapalı olsa da). Çalışma dosyaları data/panel/reels/<gün>/ (yerel)."""
import json, os, shutil, subprocess, sys
from datetime import datetime, timezone, timedelta
import build_site, clubs, control, espn, instagram, reels
from panel import content

TR = timezone(timedelta(hours=3))
REPO = "boradmir/iddia-bot"
DIR = "data/panel/reels"
STATE = "data/panel/reels_state.json"
VOICES = "data/panel/voices.json"


# ---------------- sesler ----------------

def voices():
    try:
        v = json.load(open(VOICES, encoding="utf-8"))
    except Exception:
        v = {}
    if "ahu" not in v and os.environ.get("ELEVENLABS_VOICE_ID"):
        v["ahu"] = {"id": os.environ["ELEVENLABS_VOICE_ID"], "name": "Ahu"}
    return v


def save_voices(v):
    os.makedirs(os.path.dirname(VOICES), exist_ok=True)
    json.dump(v, open(VOICES, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def default_voice(day):
    """Gün sırasına göre dönüşümlü: çift gün Ahu, tek gün erkek (erkek ses seçilmişse)."""
    v = voices()
    if "erkek" in v and int(day[-2:]) % 2 == 1:
        return "erkek"
    return "ahu"


def _eleven(path, data=None):
    import urllib.request
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise RuntimeError("ELEVENLABS_API_KEY yok")
    req = urllib.request.Request(f"https://api.elevenlabs.io/v1/{path}", data=json.dumps(data).encode() if data is not None else None,
                                 headers={"xi-api-key": key, "Content-Type": "application/json"}, method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def voice_candidates():
    """ElevenLabs paylaşılan kütüphanesinden Türkçe erkek sesler (dinleme bağlantılarıyla); kullanıcı seçer."""
    import urllib.parse
    q = urllib.parse.urlencode({"language": "tr", "gender": "male", "page_size": 12, "sort": "usage_character_count_1y"})
    d = _eleven(f"shared-voices?{q}")
    return [{"name": x["name"], "voice_id": x["voice_id"], "owner": x.get("public_owner_id"), "preview_url": x.get("preview_url"),
             "accent": x.get("accent"), "age": x.get("age"), "use_case": x.get("use_case"), "desc": (x.get("description") or "")[:160]}
            for x in d.get("voices", [])]


def adopt_voice(owner, voice_id, name):
    """Seçilen paylaşılan sesi hesabın kütüphanesine ekler ve 'erkek' olarak kaydeder."""
    d = _eleven(f"voices/add/{owner}/{voice_id}", {"new_name": name})
    vid = d.get("voice_id") or voice_id
    v = voices(); v["erkek"] = {"id": vid, "name": name}; save_voices(v)
    return v["erkek"]


def set_voice(key, voice_id, name):
    v = voices(); v[key] = {"id": voice_id, "name": name}; save_voices(v); return v


# ---------------- durum ----------------

def _load():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return {}


def _save(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(st, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def today_key():
    return datetime.now(TR).strftime("%Y-%m-%d")


def candidates(day=None):
    """Bugün analizli (yorumu olan) maçlar, büyük kulüp önce; reels için seçilebilirler."""
    day = day or today_key()
    rows = build_site.read_jsonl("records/nesine/*.jsonl"); _, last = build_site.recent_snapshot(rows)
    ai = {r["code"]: r for r in build_site.read_jsonl(f"records/claude/{day}.jsonl") if r.get("blind") and (r["blind"].get("comment"))}
    out = []
    for m in build_site.nesine_matches(last):
        if m["start"].astimezone(TR).strftime("%Y-%m-%d") != day or m["code"] not in ai:
            continue
        out.append({"code": m["code"], "home": m["home"], "away": m["away"], "kickoff": m["start"].astimezone(TR).strftime("%H:%M"), "tier": clubs.tier(m),
                    "league": m.get("league", "")})
    out.sort(key=lambda x: (x["tier"], x["kickoff"]))
    return out


def status():
    day = today_key()
    st = _load().get(day) or {}
    rc = control.reels(control.load(), day)
    v = voices()
    posted = {x["code"]: x for x in instagram.load_log() if x.get("type") == "reels" and x.get("day") == day}
    for k in ("mp3", "mp4", "cover"):
        if st.get(k) and not os.path.exists(st[k]):
            st[k] = None
    return {"day": day, "state": st, "control": rc, "voices": v, "default_voice": default_voice(day), "candidates": candidates(day),
            "posted": {str(c): x.get("post_id") for c, x in posted.items()},
            "urls": {"mp3": f"/img/{st['mp3']}" if st.get("mp3") else None, "mp4": f"/img/{st['mp4']}" if st.get("mp4") else None,
                     "cover": f"/img/{st['cover']}" if st.get("cover") else None}}


def _ctx(code):
    _, _, row = content.current_record(code)
    if not row:
        raise RuntimeError("analiz kaydı yok")
    m = content.match_for(code, row)
    bl = row["blind"]
    pm = content.market_probs(m)
    er = espn.load_all().get(code)
    return m, bl, pm, er


def choose(code, voice=None):
    day = today_key()
    st = _load()
    st[day] = {"code": int(code), "voice": voice or default_voice(day), "step": "seçildi", "t": datetime.now(TR).isoformat(timespec="seconds")}
    _save(st)
    ctrl = control.load()
    rc = control.reels(ctrl, day)
    if rc.get("status") not in ("ready", "posted") or rc.get("code") != int(code):
        control.set_reels(ctrl, day, code=int(code), status="planned", voice=st[day]["voice"]); control.save(ctrl)
    return st[day]


def step_script(log):
    day = today_key(); st = _load(); s = st[day]
    m, bl, pm, er = _ctx(s["code"])
    absences = [a for a in (bl.get("absences") or []) if a.get("player")][:4]
    text, parts = reels.build_script(m, bl, pm, absences)
    s.update({"text": text, "parts": parts, "step": "metin", "spoken": reels.spoken_text(text, bl.get("pronounce"))})
    _save(st); log(f"Metin ({len(text.split())} kelime): {text}")
    return text


def step_voice(log, voice=None, seed=None):
    day = today_key(); st = _load(); s = st[day]
    if not s.get("text"):
        step_script(log)
    v = voices(); key = voice or s.get("voice") or "ahu"
    if key not in v:
        raise RuntimeError(f"ses tanımlı değil: {key}")
    out_dir = f"{DIR}/{day}"; os.makedirs(out_dir, exist_ok=True)
    n = int(s.get("voice_n") or 0) + 1
    mp3 = f"{out_dir}/ses_{s['code']}_{key}_{n}.mp3"
    log(f"Ses üretiliyor: {v[key]['name']}" + (f" (tohum {seed})" if seed is not None else ""))
    words = reels.tts_eleven(s["spoken"], mp3, voice_id=v[key]["id"], seed=seed)
    json.dump(words, open(mp3[:-4] + ".json", "w", encoding="utf-8"), ensure_ascii=False)
    s.update({"voice": key, "voice_n": n, "mp3": mp3, "step": "ses", "mp4": None, "cover": None, "issues": None})
    _save(st); log(f"Ses hazır: {mp3} ({len(words)} kelime)")
    return mp3


def step_render(log):
    day = today_key(); st = _load(); s = st[day]
    if not s.get("mp3"):
        step_voice(log)
    m, bl, pm, er = _ctx(s["code"])
    out_dir = f"{DIR}/{day}"; os.makedirs(out_dir, exist_ok=True)
    out = f"{out_dir}/reels_{s['code']}.mp4"
    os.environ["REELS_VOICE_FILE"] = s["mp3"]
    try:
        log("Video üretiliyor (ffmpeg)…")
        r = reels.render(m, bl, pm, er, out)
    finally:
        os.environ.pop("REELS_VOICE_FILE", None)
    cap = instagram.reels_caption(m, bl, pm)
    problems = reels.check_output(r)
    if "PİYASA" in cap or "PIYASA" in cap:
        problems.append("açıklama: PİYASA yer tutucusu")
    open(f"{out_dir}/caption_{s['code']}.txt", "w", encoding="utf-8").write(cap)
    s.update({"mp4": out, "cover": r.get("cover"), "seconds": r.get("seconds"), "issues": problems, "caption": cap, "step": "video"})
    _save(st)
    log(f"Video hazır: {out} ({r.get('seconds')} sn) · denetim: " + (" | ".join(problems) if problems else "TEMİZ"))
    return out


def run_all(log, voice=None):
    step_script(log); step_voice(log, voice); step_render(log)
    return "tamam"


def publish(at, log):
    """Yayına al: Release'e yükle, kapağı repoya koy, control.reels ready. Yayını bekçi yapar."""
    day = today_key(); st = _load(); s = st[day]
    if not s.get("mp4") or not os.path.exists(s["mp4"]):
        raise RuntimeError("önce video üretilmeli")
    if s.get("issues"):
        raise RuntimeError("denetim sorunları var: " + " | ".join(s["issues"]))
    if at and not control.parse_hm(at):
        raise RuntimeError(f"geçersiz saat: {at}")
    m, bl, pm, er = _ctx(s["code"])
    tag = f"reels-{day}"
    name = os.path.basename(s["mp4"]); cap_name = f"caption_{s['code']}.txt"
    cap_path = f"{DIR}/{day}/{cap_name}"
    if subprocess.run(["gh", "release", "view", tag, "-R", REPO], capture_output=True).returncode != 0:
        r = subprocess.run(["gh", "release", "create", tag, "-R", REPO, "--title", f"Reels {day}", "--notes", "Panelden hazırlanan reels dosyaları (bekçi yayınlar)."],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            raise RuntimeError("release oluşturulamadı: " + r.stderr.strip()[:200])
        log(f"Release açıldı: {tag}")
    log("Yükleniyor (mp4 + açıklama)…")
    r = subprocess.run(["gh", "release", "upload", tag, s["mp4"], cap_path, "-R", REPO, "--clobber"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError("yükleme başarısız: " + r.stderr.strip()[:200])
    cover_rel = None
    if s.get("cover") and os.path.exists(s["cover"]):
        cover_rel = f"social/{day}/reels_{s['code']}_kapak.jpg"
        os.makedirs(f"docs/social/{day}", exist_ok=True); shutil.copyfile(s["cover"], f"docs/{cover_rel}")
    ctrl = control.load()
    control.set_reels(ctrl, day, code=s["code"], home=m["home"], away=m["away"], at=at or None, voice=s.get("voice"), status="ready",
                      asset=f"{tag}/{name}", caption_asset=f"{tag}/{cap_name}", cover=cover_rel, prepared_at=datetime.now(TR).isoformat(timespec="seconds"))
    ctrl["reels"][day].pop("error", None)
    control.save(ctrl)
    s["step"] = "hazır"; s["at"] = at; _save(st)
    from panel import actions
    err = actions.commit_push(["records/control.json"] + ([f"docs/{cover_rel}"] if cover_rel else []), f"panel: reels hazır {m['home']}-{m['away']} {at or 'hemen'}")
    if err:
        raise RuntimeError(err)
    log(f"Hazır. Bekçi {at or 'ilk turda'} yayınlayacak.")
    return "hazır"


def cancel(log):
    day = today_key()
    ctrl = control.load()
    rc = control.reels(ctrl, day)
    if not rc:
        return "kayıt yok"
    if rc.get("status") == "posted":
        raise RuntimeError("zaten yayınlanmış")
    control.set_reels(ctrl, day, status="cancelled"); control.save(ctrl)
    st = _load()
    if day in st:
        st[day]["step"] = "iptal"; _save(st)
    from panel import actions
    err = actions.commit_push(["records/control.json"], "panel: reels iptal")
    if err:
        raise RuntimeError(err)
    log("İptal edildi; bekçi yayınlamayacak.")
    return "iptal"
