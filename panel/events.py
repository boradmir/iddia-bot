"""Günlük (olaylar ve hatalar): tüm serüven tek zaman çizgisinde. Kaynaklar: Instagram gönderi günlüğü, yapay zekâ analizleri ve kadro notları,
panel eylemleri, kontrol dosyası (reels hata/hazır), GitHub çalışmaları (hata/iptal) ve son çalışmaların loglarındaki hata satırları,
gözcü uyarıları, reklam kayıtları. Seviye: hata / uyarı / bilgi."""
import glob, json, os, re, subprocess, time
from datetime import datetime, timezone, timedelta

TR = timezone(timedelta(hours=3))
REPO = "boradmir/iddia-bot"
_cache = {}
ERR_PAT = re.compile(r"hata|HATA|Traceback|Error|error|başarısız|yapılmadı|gönderilmedi|çöktü|DURDURULDU|UYARI|uyarı|exit code", re.I)
NOISE = re.compile(r"Claude analizi yapılmadı \(sınır/tekrar/boş\)|instagram günlüğü okunamadı|warning: in the working copy|Puanlanan uyarı|alerts_today", re.I)


def _rows(pattern):
    out = []
    for p in sorted(glob.glob(pattern)):
        for l in open(p, encoding="utf-8"):
            try:
                out.append(json.loads(l))
            except ValueError:
                pass
    return out


def _t(iso):
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TR)
    except Exception:
        return None


def _ev(t, level, source, text, link=None):
    return {"t": t.isoformat(timespec="seconds") if t else "", "when": t.strftime("%d.%m %H:%M") if t else "", "level": level, "source": source, "text": text, "link": link}


def local_events(days):
    cut = datetime.now(TR) - timedelta(days=days)
    ev = []
    for x in _rows("records/instagram.jsonl"):
        t = _t(x.get("t", ""))
        if t and t >= cut:
            kind = {"story": "kadro story", "story_ht": "devre story", "story_ft": "maç sonu story", "reels": "reels"}.get(x.get("type"), "karusel")
            ev.append(_ev(t, "bilgi", "Instagram", f"{kind} yayınlandı: {x.get('home')} – {x.get('away')}"))
    for p in glob.glob("records/claude/*.jsonl"):
        for r in _rows(p):
            t = _t(r.get("t", ""))
            if t and t >= cut:
                ev.append(_ev(t, "bilgi", "Yapay zekâ", f"analiz: {r.get('home')} – {r.get('away')} (${r.get('cost_usd', 0)}" + (f", sürüm {r['revision']}" if r.get("revision") else "") + ")"))
    for p in glob.glob("records/kadro/*.jsonl"):
        for r in _rows(p):
            t = _t(r.get("t", ""))
            if t and t >= cut:
                ev.append(_ev(t, "bilgi", "Yapay zekâ", f"kadro notu: {r.get('home')} – {r.get('away')} (${r.get('cost_usd', 0)})"))
    for a in _rows("records/alerts/*.jsonl"):
        t = _t(a.get("t", ""))
        if t and t >= cut:
            ev.append(_ev(t, "uyarı", "Gözcü", f"fırsat uyarısı: {a.get('home')} – {a.get('away')} {a.get('market')} {a.get('pick')} (Nesine {a.get('nesine_odds')}, +%{a.get('ev_pct')})"))
    for a in _rows("records/insights/ads.jsonl"):
        t = _t(a.get("t", "")) or _t(a.get("day", "") + "T12:00:00+03:00")
        if t and t >= cut:
            ev.append(_ev(t, "bilgi", "Reklam", f"{a.get('type')} {a.get('home')} – {a.get('away')}: {a.get('budget_tl')} TL / {a.get('days')} gün"))
    if os.path.exists("data/panel/actions.log"):
        for l in open("data/panel/actions.log", encoding="utf-8"):
            try:
                ts, action, result = l.rstrip("\n").split("\t", 2)
                t = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TR)
            except ValueError:
                continue
            if t >= cut:
                ev.append(_ev(t, "hata" if result.startswith("HATA") or "başarısız" in result else "bilgi", "Panel", f"{action}: {result[:160]}"))
    try:
        ctrl = json.load(open("records/control.json", encoding="utf-8"))
        for day, rc in (ctrl.get("reels") or {}).items():
            if rc.get("status") == "error":
                ev.append(_ev(_t(rc.get("prepared_at", "")) or datetime.now(TR), "hata", "Bekçi", f"reels yayın hatası ({day}): {rc.get('error')}"))
            elif rc.get("status") == "ready":
                ev.append(_ev(_t(rc.get("prepared_at", "")), "bilgi", "Panel", f"reels hazır, bekçi {rc.get('at') or 'ilk turda'} yayınlayacak ({rc.get('home')} – {rc.get('away')})"))
        if ctrl.get("paused_until"):
            ev.append(_ev(_t(ctrl.get("updated", "")), "uyarı", "Panel", f"paylaşımlar durduruldu: {ctrl['paused_until'][:16]} kadar"))
    except Exception:
        pass
    return ev


def _run(args, timeout):
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


def github_events(days):
    """Çalışma sonuçları + son çalışmaların loglarındaki hata satırları (5 dk önbellek)."""
    now = time.time()
    v = _cache.get("gh")
    if v and now - v[0] < 300:
        return v[1]
    ev = []
    cut = datetime.now(TR) - timedelta(days=days)
    r = _run(["gh", "run", "list", "-R", REPO, "--limit", "40", "--json", "databaseId,workflowName,status,conclusion,createdAt,updatedAt,url"], 25)
    runs = json.loads(r.stdout or "[]") if r.returncode == 0 else []
    runs = [x for x in runs if x["workflowName"] != "pages-build-deployment"]
    seen_logs = 0
    for x in runs:
        t = _t(x["updatedAt"]) or _t(x["createdAt"])
        if not t or t < cut:
            continue
        name, st, con = x["workflowName"], x["status"], x.get("conclusion") or ""
        if con == "failure":
            ev.append(_ev(t, "hata", "GitHub", f"{name} çalışması HATA ile bitti", x["url"]))
        elif con == "cancelled":
            ev.append(_ev(t, "uyarı", "GitHub", f"{name} çalışması iptal edildi", x["url"]))
        elif st == "in_progress":
            ev.append(_ev(_t(x["createdAt"]), "bilgi", "GitHub", f"{name} çalışıyor (başlangıç)", x["url"]))
        # log tarama: en yeni 6 çalışma (uzun bekçi/gözcü logları dahil)
        if seen_logs < 6 and name in ("Bekçi", "Maç günü gözcüsü", "Sonuçlar ve puanlama"):
            seen_logs += 1
            lr = _run(["gh", "run", "view", str(x["databaseId"]), "-R", REPO, "--log"], 90)
            if lr.returncode != 0:
                continue
            found = 0
            for line in lr.stdout.splitlines():
                parts = line.split("\t", 2)
                if len(parts) < 3:
                    continue
                body = parts[2]
                m = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)\.\d+Z\s?(.*)", body)
                if not m:
                    continue
                lt, msg = _t(m.group(1) + "+00:00"), m.group(2)
                if not ERR_PAT.search(msg) or NOISE.search(msg) or not msg.strip():
                    continue
                if lt and lt >= cut and found < 40:
                    ev.append(_ev(lt, "hata" if re.search(r"Traceback|HATA|başarısız|exit code|Error", msg) else "uyarı", name, msg[:200], x["url"]))
                    found += 1
    _cache["gh"] = (now, ev)
    return ev


def data(days=3, level=None):
    ev = local_events(days) + github_events(days)
    # aynı metin + dakika tekrarlarını birleştir
    seen, out = set(), []
    for e in sorted(ev, key=lambda e: e["t"], reverse=True):
        k = (e["text"][:80], e["when"])
        if k in seen:
            continue
        seen.add(k); out.append(e)
    if level:
        out = [e for e in out if e["level"] == level]
    counts = {"hata": sum(1 for e in out if e["level"] == "hata"), "uyarı": sum(1 for e in out if e["level"] == "uyarı"), "bilgi": sum(1 for e in out if e["level"] == "bilgi")}
    return {"days": days, "events": out[:400], "counts": counts}
