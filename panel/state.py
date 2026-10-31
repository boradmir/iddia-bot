"""Panel durumu: dosyalardan okunur. Dış çağrılar (gh, Graph API, ElevenLabs) önbellekli ve 10-20 sn zaman aşımlı;
hata ekrana 'errors' olarak düşer, panel çökmez. Erişim belirteci hiçbir çıktıya yazılmaz."""
import glob, json, os, subprocess, time, urllib.error, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta
import build_site, clubs, control, instagram

TR = timezone(timedelta(hours=3))
REPO = "boradmir/iddia-bot"
_cache = {}


def cached(key, ttl, fn):
    now = time.time()
    v = _cache.get(key)
    if v and now - v[0] < ttl:
        return v[1]
    r = fn()
    _cache[key] = (now, r)
    return r


def _img(rel):
    return f"/img/{rel}" if os.path.exists(rel) else None


def permalink(pid):
    """Gönderi bağlantısı (Graph API permalink); 1 saat önbellek, hata → None."""
    if not pid or not instagram.TOKEN:
        return None

    def fn():
        try:
            return instagram._get(pid, {"fields": "permalink"}).get("permalink")
        except Exception:
            return None
    return cached(f"permalink:{pid}", 3600, fn)


# ---------------- Bugün ----------------

def sync():
    """Uzak kayıtları çek (bekçi 20 dk'da bir yazıyor). Önbellek yükleyicisi olarak dakikada bir çalışır."""
    from panel import actions
    with actions.GIT_LOCK:
        ok, err = actions.pull()
    return {"ok": ok, "error": err, "t": datetime.now(TR).strftime("%H:%M:%S")}


def today():
    errors = []
    day = datetime.now(TR).date(); ds = str(day)
    ctrl = control.load()
    try:
        plan = instagram.plan_today(day, ctrl)
    except Exception as e:
        errors.append(f"plan: {e}"); plan = {"paused_until": None, "sent_today": [], "picked": [], "skipped": [], "waiting": []}
    try:
        rows = build_site.recent_nesine_rows(); _, last = build_site.recent_snapshot(rows)
        ms = [m for m in build_site.nesine_matches(last) if m["start"].astimezone(TR).date() == day]
    except Exception as e:
        errors.append(f"bülten: {e}"); ms = []
    ai = {}
    for p in glob.glob(f"records/claude/{ds}.jsonl"):
        for l in open(p, encoding="utf-8"):
            try:
                r = json.loads(l)
            except ValueError:
                continue
            if r.get("blind"):
                ai[r["code"]] = r
    log = instagram.load_log()
    posted = {(x.get("type") or "carousel", x["code"]): x for x in log if x.get("day") == ds}
    slot_by = {p["m"]["code"]: p for p in plan["picked"]}
    skipped = {s["m"]["code"]: s["reason"] for s in plan["skipped"]}
    waiting = {w["m"]["code"] for w in plan["waiting"]}
    now = datetime.now(TR)
    rc = control.reels(ctrl, ds)
    out = []
    for m in ms:
        code = m["code"]; d = f"docs/social/{ds}"
        cards = {k: _img(f"{d}/{k}_{code}.jpg") for k in ("match", "yorum", "story", "devre", "ft")}
        posted_any = any(k[1] == code for k in posted)
        if clubs.tier(m) > 2 and code not in ai and not posted_any and not any(cards[k] for k in ("yorum", "story", "devre", "ft")):
            continue   # her maçın 'match' kartı var; küçük kulüp maçı yalnız analiz/yorum/story/yayın varsa listelenir
        ov = control.post(ctrl, ds, code)
        if ("carousel", code) in posted:
            st, at = "yayında", datetime.fromisoformat(posted[("carousel", code)]["t"]).astimezone(TR).strftime("%H:%M")
        elif plan["paused_until"]:
            st, at = "durduruldu", None
        elif ov.get("skip") or skipped.get(code) == "panel":
            st, at = "atlandı", None
        elif code in slot_by:
            s = slot_by[code]["slot"]
            st, at = ("planlı", s.strftime("%H:%M")) if s and now < s else ("sırada", s.strftime("%H:%M") if s else None)
        elif code in waiting:
            st, at = "bekliyor", None
        elif not cards["match"]:
            st, at = "kart yok", None
        elif m["start"] <= datetime.now(timezone.utc) + timedelta(hours=1):
            st, at = "süre geçti", None
        else:
            st, at = "sırada", None
        pid = posted.get(("carousel", code), {}).get("post_id")
        stories = {}
        for k, t in (("kadro", "story"), ("devre", "story_ht"), ("ft", "story_ft")):
            if (t, code) in posted:
                stories[k] = "yayında"
            elif control.story_skip(ctrl, ds, code) or plan["paused_until"]:
                stories[k] = "atlandı"
            elif clubs.tier(m) > 0:
                stories[k] = "yok"
            else:
                stories[k] = "bekliyor"
        stories["skip"] = control.story_skip(ctrl, ds, code)
        reels_pid = posted.get(("reels", code), {}).get("post_id")
        out.append({"code": code, "home": m["home"], "away": m["away"], "league": m.get("league", ""),
                    "kickoff": m["start"].astimezone(TR).strftime("%H:%M"), "tier": clubs.tier(m), "analysis": code in ai, "cards": cards,
                    "post": {"state": st, "at": at, "url": permalink(pid), "post_id": pid, "override_at": ov.get("at"), "skip": bool(ov.get("skip"))},
                    "stories": stories,
                    "reels": ({**rc, "url": permalink(rc.get("post_id") or reels_pid)} if rc.get("code") == code else
                              ({"status": "posted", "url": permalink(reels_pid)} if reels_pid else None))})
    out.sort(key=lambda r: (r["tier"], r["kickoff"]))
    try:
        watch = json.load(open("records/watch_status.json", encoding="utf-8"))
    except Exception:
        watch = {}
    return {"day": ds, "paused_until": plan["paused_until"], "max_per_day": instagram.MAX_PER_DAY, "sent_count": len(plan["sent_today"]),
            "matches": out, "watch": watch, "errors": errors, "standings": standings_state(ctrl, log)}


def standings_state(ctrl, log):
    """Haftalık puan durumu karuseli: bu haftanın kartları (varsa), yayın durumu, panel kararı."""
    import standings
    week = standings.week_key()
    cards = sorted(glob.glob(f"docs/social/puan/{week}/*.jpg"))
    posted = next((x for x in log if x.get("type") == "standings" and x.get("week") == week), None)
    skip = bool(((ctrl.get("standings") or {}).get(week) or {}).get("skip"))
    nxt = datetime.now(TR)
    days = (0 - nxt.weekday()) % 7
    nxt = (nxt + timedelta(days=days)).replace(hour=12, minute=0, second=0, microsecond=0)
    if nxt < datetime.now(TR):
        nxt += timedelta(days=7)
    return {"week": week, "cards": [f"/img/{p.replace(os.sep, '/')}" for p in cards], "posted": posted and posted.get("post_id"),
            "url": permalink(posted.get("post_id")) if posted else None, "skip": skip, "next": nxt.strftime("%d.%m %H:%M")}


# ---------------- Sistem ----------------

def _run(args, timeout):
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


def _gh_runs():
    r = _run(["gh", "run", "list", "-R", REPO, "--limit", "30", "--json", "databaseId,workflowName,status,conclusion,displayTitle,createdAt,updatedAt,url"], 25)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:200] or "gh run list başarısız")
    out = []
    for x in json.loads(r.stdout or "[]"):
        if x["workflowName"] == "pages-build-deployment":
            continue
        c = datetime.fromisoformat(x["createdAt"].replace("Z", "+00:00")); u = datetime.fromisoformat(x["updatedAt"].replace("Z", "+00:00"))
        out.append({"id": x["databaseId"], "name": x["workflowName"], "status": x["status"], "conclusion": x.get("conclusion") or "",
                    "title": x.get("displayTitle", ""), "started": c.astimezone(TR).strftime("%d.%m %H:%M"), "url": x["url"],
                    "minutes": int((u - c).total_seconds() // 60)})
    # uzun süren bekçi/gözcü çalışması 30'luk pencerenin dışında kalabilir (Pages derlemeleri listeyi doldurur): çalışanları ayrıca sor
    r2 = _run(["gh", "run", "list", "-R", REPO, "--status", "in_progress", "--limit", "10", "--json", "databaseId,workflowName,status,conclusion,displayTitle,createdAt,updatedAt,url"], 25)
    if r2.returncode == 0:
        have = {x["id"] for x in out}
        for x in json.loads(r2.stdout or "[]"):
            if x["databaseId"] in have or x["workflowName"] == "pages-build-deployment":
                continue
            c = datetime.fromisoformat(x["createdAt"].replace("Z", "+00:00")); u = datetime.fromisoformat(x["updatedAt"].replace("Z", "+00:00"))
            out.insert(0, {"id": x["databaseId"], "name": x["workflowName"], "status": x["status"], "conclusion": "", "title": x.get("displayTitle", ""),
                           "started": c.astimezone(TR).strftime("%d.%m %H:%M"), "url": x["url"], "minutes": int((u - c).total_seconds() // 60)})
    return out[:14]


def _ai_spend():
    today = datetime.now(TR).strftime("%Y-%m-%d"); month = today[:7]
    t = m = 0.0
    for p in glob.glob("records/claude/*.jsonl") + glob.glob("records/kadro/*.jsonl"):
        day = os.path.basename(p)[:10]
        if not day.startswith(month):
            continue
        for l in open(p, encoding="utf-8"):
            try:
                r = json.loads(l)
            except ValueError:
                continue
            c = float(r.get("cost_usd") or 0) + float((r.get("blind") or {}).get("qa_cost_usd") or 0)
            m += c
            if day == today:
                t += c
    return round(t, 2), round(m, 2)


def _eleven():
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        return {}
    req = urllib.request.Request("https://api.elevenlabs.io/v1/user/subscription", headers={"xi-api-key": key})
    with urllib.request.urlopen(req, timeout=10) as r:
        d = json.loads(r.read())
    return {"eleven_used": d.get("character_count"), "eleven_limit": d.get("character_limit"),
            "eleven_reset": datetime.fromtimestamp(d.get("next_character_count_reset_unix", 0), TR).strftime("%d.%m")}


def _ig_token():
    """Belirteç sağlığı: hesap bilgisi çekilebiliyorsa geçerli. Sistem kullanıcısı belirteci süresizdir; debug_token uygulama belirteci ister, kullanılmaz."""
    tok = os.environ.get("IG_TOKEN"); uid = os.environ.get("IG_USER_ID")
    if not tok or not uid:
        return {"valid": None}
    base = "https://graph.instagram.com/v21.0" if tok.startswith("IG") else "https://graph.facebook.com/v21.0"
    q = urllib.parse.urlencode({"fields": "username", "access_token": tok})
    try:
        with urllib.request.urlopen(f"{base}/{uid}?{q}", timeout=10) as r:
            d = json.loads(r.read())
        return {"valid": bool(d.get("username")), "expires": "süresiz (sistem kullanıcısı)", "days_left": None, "username": d.get("username")}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        if e.code in (400, 401, 403):
            return {"valid": False, "expires": None, "days_left": None, "error": body[:120].replace(tok, "***")}
        raise


BALANCES = "data/panel/balances.json"
# Higgsfield liste fiyatı (estimate uç noktası, 31.10.2026): Seedance 2.5 saniye başına 480p 0.21 / 720p 0.46 / 1080p 1.14 $;
# Wan 3.0 saniye başına 480p 0.05 / 720p 0.10 / 1080p 0.20 $. Bakiye uç noktası yok → yerel defter.
HF_RATE = {"seedance": {"480p": 0.2056, "720p": 0.4622, "1080p": 1.1372}, "wan": {"480p": 0.05, "720p": 0.10, "1080p": 0.20}}


def hf_cost(model, duration, resolution):
    m = (model or "").lower(); fam = "seedance" if "seedance" in m else "wan" if "wan" in m else "wan"
    return round(HF_RATE[fam].get(str(resolution or "1080p"), HF_RATE[fam]["1080p"]) * float(duration or 5), 2)


def higgsfield():
    """Yerel defter: kullanıcının girdiği bakiye − o tarihten sonra üretilen kliplerin (assets/*/library.jsonl) tahmini maliyeti."""
    try:
        bal = json.load(open(BALANCES, encoding="utf-8")).get("higgsfield") or {}
    except Exception:
        bal = {}
    since = bal.get("t", "")
    clips, spent, month_clips, month_spent = 0, 0.0, 0, 0.0
    month = datetime.now(TR).strftime("%Y-%m")
    for p in glob.glob("assets/*/library.jsonl"):
        for l in open(p, encoding="utf-8"):
            try:
                r = json.loads(l)
            except ValueError:
                continue
            c = r.get("credits_usd") or hf_cost(r.get("model"), r.get("duration"), r.get("resolution"))
            if (r.get("t") or "") >= since:
                clips += 1; spent += c
            if (r.get("t") or "").startswith(month):
                month_clips += 1; month_spent += c
    return {"balance_entered": bal.get("amount"), "entered_at": since[:16].replace("T", " ") if since else None,
            "clips_since": clips, "spent_since": round(spent, 1), "remaining": round(float(bal["amount"]) - spent, 1) if bal.get("amount") is not None else None,
            "month_clips": month_clips, "month_spent": round(month_spent, 1)}


def system():
    errors = []

    def safe(key, ttl, fn, default):
        try:
            return cached(key, ttl, fn)
        except Exception as e:
            errors.append(f"{key}: {str(e)[:120]}"); return default

    runs = safe("runs", 60, _gh_runs, [])
    try:
        st = json.load(open("records/status.json", encoding="utf-8"))
    except Exception:
        st = {}
    try:
        q = json.load(open("records/quota.json", encoding="utf-8"))
    except Exception:
        q = {}
    last = st.get("keeper_last")
    age = int((datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() // 60) if last else None
    ai_t, ai_m = _ai_spend()
    spend = {"ai_today_usd": ai_t, "ai_month_usd": ai_m, **safe("eleven", 300, _eleven, {}), "higgsfield": safe("higgsfield", 60, higgsfield, {})}
    return {"runs": runs,
            "keeper": {"last": datetime.fromisoformat(last).astimezone(TR).strftime("%H:%M") if last else None, "age_min": age,
                       "running": any(r["name"] == "Bekçi" and r["status"] == "in_progress" for r in runs),
                       "claude_morning": st.get("claude_morning"), "insights_day": st.get("insights_day")},
            "quota": {"remaining": int(q.get("quota") or 0), "spent_today": q.get("spent_today", 0), "day": q.get("spent_day")},
            "spend": spend, "ig_token": safe("ig_token", 3600, _ig_token, {"valid": None}), "errors": errors}


def run_log(run_id):
    if not str(run_id).isdigit():
        return {"ok": False, "lines": [], "error": "geçersiz kimlik"}
    r = _run(["gh", "run", "view", str(run_id), "-R", REPO, "--log"], 90)
    if r.returncode != 0:
        return {"ok": False, "lines": [], "error": r.stderr.strip()[:200] or "log alınamadı"}
    lines = [l.split("\t", 2)[-1] if "\t" in l else l for l in r.stdout.splitlines()]
    return {"ok": True, "lines": lines[-200:]}
