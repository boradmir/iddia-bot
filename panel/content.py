"""İçerik ekranı: bir gönderinin açıklama metni ve kart yazıları düzenlenir, kart yeniden üretilir, analiz editör notuyla yeniden çalıştırılır.
Düzenlemeler records/claude/<gün>.jsonl satırına yazılır (caption_override, blind alanları, edited_at); okuyucular (instagram, social) aynı satırı kullanır."""
import glob, json, os, subprocess, sys
from datetime import datetime, timezone, timedelta
import build_site, instagram, clubs

TR = timezone(timedelta(hours=3))
FIELDS = ("hook", "comment", "card_text", "risk", "risk_short", "question", "reels_script")
FIELD_TR = {"hook": "Kanca (ilk cümle, açıklamanın başı)", "comment": "Tam yazı (açıklamada)", "card_text": "Kart yazısı (yorum kartı)",
            "risk": "En büyük belirsizlik", "risk_short": "Belirsizlik, kısa (reels)", "question": "Soru (açıklama ve reels sonu)",
            "reels_script": "Reels seslendirme metni ('PİYASA.' yer tutucusu kalsın)"}


def _rows(path):
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def current_record(code):
    """Bu maçın geçerli kaydı: dosya sırasına göre son satır (okuyucular da böyle seçer). Döner (path, index, row) ya da (None, None, None)."""
    found = (None, None, None)
    for p in sorted(glob.glob("records/claude/*.jsonl")):
        rows = _rows(p)
        for i, r in enumerate(rows):
            if r.get("code") == code and r.get("blind"):
                found = (p, i, r)
    return found


def match_for(code, row=None):
    """Nesine son kayıtta maç; yoksa kayıt satırından türetilir."""
    try:
        rows = build_site.read_jsonl("records/nesine/*.jsonl"); _, last = build_site.recent_snapshot(rows)
        for m in build_site.nesine_matches(last):
            if m["code"] == code:
                return m
    except Exception:
        pass
    if row:
        return {"code": code, "home": row["home"], "away": row["away"], "league": row.get("league", ""), "sport_key": row.get("sport"),
                "start": datetime.fromisoformat(row["start"])}
    return None


def market_probs(m):
    import odds, prob, match
    events = build_site.pinnacle_events(build_site.read_jsonl("records/pinnacle/*.jsonl"))
    aliases = json.load(open("aliases.json", encoding="utf-8")) if os.path.exists("aliases.json") else {}
    for mm, ev, sc in match.match_all([m], events, aliases):
        if ev and odds.pinnacle_h2h(ev):
            return prob.market_probs(odds.pinnacle_h2h(ev), odds.pinnacle_totals(ev))
    return None


def estimate_cost():
    """Son 7 günün ortalama analiz maliyeti (yeniden çalıştırma düğmesinde gösterilir)."""
    costs = []
    cut = (datetime.now(TR) - timedelta(days=7)).strftime("%Y-%m-%d")
    for p in glob.glob("records/claude/*.jsonl"):
        if os.path.basename(p)[:10] < cut:
            continue
        for r in _rows(p):
            if r.get("cost_usd"):
                costs.append(float(r["cost_usd"]))
    return round(sum(costs) / len(costs), 2) if costs else 0.5


def posted(code):
    return any(s.get("code") == code and not str(s.get("type", "")).startswith(("story", "reels")) for s in instagram.load_log())


def get(code):
    path, idx, row = current_record(code)
    if not row:
        return {"ok": False, "error": "bu maç için analiz kaydı yok"}
    m = match_for(code, row)
    day = datetime.fromisoformat(row["start"]).astimezone(TR).strftime("%Y-%m-%d")
    bl = row.get("blind") or {}
    pm = market_probs(m) if m else None
    cards = {k: f"/img/docs/social/{day}/{k}_{code}.jpg" for k in ("match", "yorum") if os.path.exists(f"docs/social/{day}/{k}_{code}.jpg")}
    return {"ok": True, "code": code, "home": row["home"], "away": row["away"], "day": day, "file": path, "posted": posted(code),
            "caption": instagram.caption_for(m or {"home": row["home"], "away": row["away"], "league": row.get("league", ""), "start": datetime.fromisoformat(row["start"])}, row, pm),
            "caption_override": row.get("caption_override") or "", "fields": {k: bl.get(k) or "" for k in FIELDS}, "field_names": FIELD_TR,
            "revision": row.get("revision") or 0, "note": row.get("note") or "", "cost_usd": row.get("cost_usd"), "edited_at": row.get("edited_at"),
            "est_cost": estimate_cost(), "cards": cards, "probs": {k: bl.get(k) for k in ("p_home", "p_draw", "p_away")}}


def save(code, fields=None, caption_override=None):
    """Alanları ve/veya açıklama düzenlemesini kayda yazar (dosya yeniden yazılır). Boş caption_override = düzenlemeyi kaldır."""
    path, idx, row = current_record(code)
    if not row:
        raise ValueError("analiz kaydı yok")
    rows = _rows(path)
    r = rows[idx]
    changed = []
    for k, v in (fields or {}).items():
        if k in FIELDS and (v or "").strip() != (r["blind"].get(k) or ""):
            r["blind"][k] = (v or "").strip(); changed.append(k)
    if caption_override is not None:
        co = caption_override.strip()
        if co != (r.get("caption_override") or ""):
            if co:
                r["caption_override"] = co
            else:
                r.pop("caption_override", None)
            changed.append("caption")
    if changed:
        r["edited_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with open(path, "w", encoding="utf-8") as f:
            for x in rows:
                f.write(json.dumps(x, ensure_ascii=False) + "\n")
    return changed


def regen_cards(code, log):
    """Günün kartlarını yeniden üretir (social.py tüm günü üretir, hızlıdır)."""
    _, _, row = current_record(code)
    day = datetime.fromisoformat(row["start"]).astimezone(TR).strftime("%Y-%m-%d")
    p = subprocess.run([sys.executable, "social.py", "--date", day], capture_output=True, text=True, encoding="utf-8", errors="replace")
    for l in (p.stdout + p.stderr).splitlines():
        log(l)
    if p.returncode != 0:
        raise RuntimeError("kart üretimi başarısız")
    return day


def publish_paths(code):
    """Yayına yazılacak dosyalar: günün kart dosyaları + analiz kaydı."""
    path, _, row = current_record(code)
    day = datetime.fromisoformat(row["start"]).astimezone(TR).strftime("%Y-%m-%d")
    paths = [path] + [p for p in (f"docs/social/{day}/match_{code}.jpg", f"docs/social/{day}/yorum_{code}.jpg") if os.path.exists(p)]
    return paths


def rerun(code, note, log):
    """Analizi editör notuyla yeniden çalıştırır (ücretli), sonra kartları yeniler."""
    import claude_check
    _, _, row = current_record(code)
    m = match_for(code, row)
    if not m:
        raise RuntimeError("maç bulunamadı")
    pm = market_probs(m)
    log(f"Yeniden analiz: {m['home']} - {m['away']}" + (f" · not: {note}" if note else ""))
    new = claude_check.reanalyze_and_store(m, pm, note=note)
    log(f"Bitti. Maliyet ${new.get('cost_usd')} · sürüm {new.get('revision')}")
    regen_cards(code, log)
    return {"cost_usd": new.get("cost_usd"), "revision": new.get("revision")}
