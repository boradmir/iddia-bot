"""Panel eylemleri: kontrol dosyasını yazar ve repoya iter; gh ile iş akışı tetikler; ağır yerel işleri kuyruğa verir.
Sır yok. Her eylem data/panel/actions.log'a yazılır."""
import os, subprocess, sys, threading, time
from datetime import datetime, timezone, timedelta
import control
from panel import jobs

TR = timezone(timedelta(hours=3))
REPO = "boradmir/iddia-bot"
LOG = "data/panel/actions.log"
GIT_LOCK = threading.RLock()
TRAILER = "\n\nCo-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01F7HBZh7xgBsU7aY3kX8Gem"
CONTROL_ACTIONS = {"set_time", "skip", "story_skip", "pause"}
WORKFLOWS = {"keeper.yml": "Bekçi", "watch.yml": "Gözcü", "results.yml": "Skorlar"}


def alog(action, result):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now(TR):%Y-%m-%d %H:%M:%S}\t{action}\t{result}\n")


def sh(args, timeout=120):
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


def pull():
    r = sh(["git", "pull", "--rebase", "-X", "theirs", "--autostash", "-q", "origin", "master"])
    if r.returncode != 0:
        sh(["git", "rebase", "--abort"])
        return False, r.stderr.strip()[:300]
    return True, ""


def commit_push(paths, msg):
    """Yalnız verilen dosyaları commit edip iter. Hata metni döner ('' = tamam)."""
    with GIT_LOCK:
        if paths:
            sh(["git", "add", "--"] + list(paths))
        if sh(["git", "diff", "--cached", "--quiet"]).returncode != 0:
            r = sh(["git", "commit", "-q", "-m", msg + TRAILER])
            if r.returncode != 0:
                return "commit başarısız: " + r.stderr.strip()[:200]
        for _ in range(3):
            ok, err = pull()
            if not ok:
                time.sleep(3); continue
            if sh(["git", "push", "-q", "origin", "master"]).returncode == 0:
                return ""
            time.sleep(3)
        return "push başarısız (yerelde commit duruyor; 'Yeniden it' deneyin)"


def apply(ctrl, body, day):
    """Saf: kontrol sözlüğünü eyleme göre değiştirir. Döner (ctrl, mesaj). Geçersiz girdi → ValueError."""
    a = body.get("action"); code = body.get("code")
    if a == "set_time":
        at = (body.get("at") or "").strip()
        if at and not control.parse_hm(at):
            raise ValueError(f"geçersiz saat: {at}")
        row = control.set_post(ctrl, day, code, note="panelden")
        if at:
            row["at"] = at
        else:
            row.pop("at", None)
        return ctrl, f"Saat {'yazıldı: ' + at if at else 'kaldırıldı'}"
    if a == "skip":
        control.set_post(ctrl, day, code, skip=bool(body.get("skip")), note="panelden")
        return ctrl, "Atlandı" if body.get("skip") else "Atlama geri alındı"
    if a == "story_skip":
        control.set_story_skip(ctrl, day, code, bool(body.get("skip")))
        return ctrl, "Story'ler kapatıldı" if body.get("skip") else "Story'ler açıldı"
    if a == "pause":
        u = body.get("until")
        if u is None:
            control.set_pause(ctrl, None); return ctrl, "Durdurma kaldırıldı"
        if u == "today":
            until = datetime.fromisoformat(day).replace(hour=23, minute=59, tzinfo=TR)
        else:
            until = datetime.fromisoformat(u)
            if until.tzinfo is None:
                until = until.replace(tzinfo=TR)
        control.set_pause(ctrl, until); return ctrl, f"Durduruldu, {until:%d.%m %H:%M} kadar"
    raise ValueError(f"bilinmeyen eylem: {a}")


def _job(name, fn, after_paths=None, after_msg=None):
    """Python işini kuyruğa al; bitince (başarılıysa) verilen dosyaları commit+push et."""
    jid = jobs.submit(name, fn)
    if after_paths:
        threading.Thread(target=_after_job, args=(jid, after_paths, after_msg or name), daemon=True).start()
    alog(name, f"iş {jid}")
    return {"ok": True, "msg": f"{name}: kuyruğa alındı (sağdaki İşler kutusu)", "job": jid}


def run(body):
    a = body.get("action", "")
    day = datetime.now(TR).strftime("%Y-%m-%d")
    code = body.get("code")
    try:
        if a in CONTROL_ACTIONS:
            with GIT_LOCK:
                pull()
            ctrl = control.load()
            ctrl, msg = apply(ctrl, body, day)
            control.save(ctrl)
            err = commit_push(["records/control.json"], f"panel: {msg}")
            alog(a, msg + (" | " + err if err else ""))
            return {"ok": False, "msg": msg, "error": err} if err else {"ok": True, "msg": msg}
        if a == "workflow":
            name = body.get("name")
            if name not in WORKFLOWS:
                raise ValueError("bilinmeyen iş akışı")
            r = sh(["gh", "workflow", "run", name, "-R", REPO])
            alog(a, f"{name}: {'ok' if r.returncode == 0 else r.stderr.strip()[:200]}")
            if r.returncode != 0:
                return {"ok": False, "error": r.stderr.strip()[:200] or "tetiklenemedi"}
            return {"ok": True, "msg": f"{WORKFLOWS[name]} tetiklendi"}
        if a == "cancel_run":
            r = sh(["gh", "run", "cancel", str(int(body.get("run_id"))), "-R", REPO])
            alog(a, f"{body.get('run_id')}: {'ok' if r.returncode == 0 else r.stderr.strip()[:200]}")
            return {"ok": r.returncode == 0, "msg": "Çalışma iptal edildi", "error": r.stderr.strip()[:200]}
        if a == "instagram_now":
            jid = jobs.submit("Instagram gönderimi", [sys.executable, "instagram.py"])
            threading.Thread(target=_after_job, args=(jid, ["records/instagram.jsonl"], "panel: instagram elle çalıştırıldı"), daemon=True).start()
            alog(a, f"iş {jid}"); return {"ok": True, "msg": "Instagram işi kuyruğa alındı"}
        if a == "insights_now":
            jid = jobs.submit("Insights çekimi", [sys.executable, "insights.py"])
            threading.Thread(target=_after_job, args=(jid, ["records/insights"], "panel: insights elle çekildi"), daemon=True).start()
            alog(a, f"iş {jid}"); return {"ok": True, "msg": "Insights işi kuyruğa alındı"}
        if a == "retry_push":
            err = commit_push([], "panel: yeniden it")
            alog(a, err or "ok")
            return {"ok": False, "error": err} if err else {"ok": True, "msg": "İtildi"}

        # ---- İçerik
        from panel import content, reels_flow, stats
        if a == "content_save":
            changed = content.save(int(code), body.get("fields") or {}, body.get("caption_override"))
            alog(a, f"{code}: {changed}")
            return {"ok": True, "msg": ("Kaydedildi: " + ", ".join(changed)) if changed else "Değişiklik yok", "changed": changed}
        if a == "content_regen":
            c = int(code)
            return _job("Kart yenileme", lambda log: content.regen_cards(c, log))
        if a == "content_publish":
            c = int(code)
            paths = content.publish_paths(c)
            err = commit_push(paths, f"panel: içerik düzenlendi ({c})")
            alog(a, f"{c}: {err or 'ok'}")
            return {"ok": False, "error": err} if err else {"ok": True, "msg": "Yayına yazıldı (repoya itildi)"}
        if a == "content_rerun":
            c = int(code); note = (body.get("note") or "").strip()
            paths = content.publish_paths(c)
            return _job("Analizi yeniden çalıştır", lambda log: content.rerun(c, note, log), after_paths=lambda: content.publish_paths(c), after_msg=f"panel: analiz yeniden ({c})")

        # ---- Reels
        if a == "reels_choose":
            s = reels_flow.choose(int(code), body.get("voice"))
            err = commit_push(["records/control.json"], f"panel: reels maçı seçildi {code}")
            alog(a, f"{code} {s.get('voice')} {err or 'ok'}")
            if body.get("produce"):
                v = body.get("voice")
                return _job("Reels üretimi (metin + ses + video)", lambda log: reels_flow.run_all(log, v))
            return {"ok": True, "msg": "Maç seçildi"}
        if a == "reels_script":
            return _job("Reels metni", lambda log: reels_flow.step_script(log))
        if a == "reels_voice":
            v = body.get("voice"); seed = body.get("seed")
            return _job("Reels sesi", lambda log: reels_flow.step_voice(log, v, int(seed) if seed else None))
        if a == "reels_render":
            return _job("Reels videosu", lambda log: reels_flow.step_render(log))
        if a == "reels_all":
            v = body.get("voice")
            return _job("Reels üretimi (metin + ses + video)", lambda log: reels_flow.run_all(log, v))
        if a == "reels_publish":
            at = (body.get("at") or "").strip()
            return _job("Reels yayına al", lambda log: reels_flow.publish(at, log))
        if a == "reels_cancel":
            return _job("Reels iptal", lambda log: reels_flow.cancel(log))
        if a == "voice_candidates":
            return {"ok": True, "voices": reels_flow.voice_candidates()}
        if a == "voice_adopt":
            v = reels_flow.adopt_voice(body.get("owner"), body.get("voice_id"), body.get("name") or "Erkek")
            alog(a, str(v)); return {"ok": True, "msg": f"Erkek ses seçildi: {v['name']}"}

        # ---- İstatistik
        if a == "add_ad":
            rec = stats.add_ad(body.get("post_id"), body.get("budget_tl"), body.get("days"), body.get("note") or "")
            err = commit_push(["records/insights/ads.jsonl"], f"panel: reklam kaydı {rec['home']}-{rec['away']} {rec['budget_tl']:.0f} TL")
            alog(a, f"{rec} {err or 'ok'}")
            return {"ok": False, "error": err} if err else {"ok": True, "msg": "Reklam kaydedildi"}
        raise ValueError(f"bilinmeyen eylem: {a}")
    except Exception as e:
        alog(a, f"HATA {e}")
        return {"ok": False, "error": str(e)}


def _after_job(jid, paths, msg):
    """İş bitince ilgili dosyaları commit edip iter (yerel üretimin günlüğü GitHub'a gitsin). paths çağrılabilir olabilir."""
    while True:
        j = jobs.get(jid)
        if j and j["status"] in ("bitti", "hata"):
            break
        time.sleep(2)
    if j["status"] == "bitti" and paths:
        p = paths() if callable(paths) else paths
        err = commit_push(p, msg)
        alog("after_job", f"{msg}: {err or 'ok'}")
