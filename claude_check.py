"""Görüş 3 – Claude: haber + kadro okur, oranı GÖRMEDEN kendi ihtimalini verir; sonra piyasa ihtimaline itiraz var mı söyler.

İki aşama, tek sohbet (ikinci aşama önbellekten ucuz):
  1. KÖR TAHMİN: web araması (en çok 8 çağrı, talimatta 4-5) ile sakatlık/kadro/motivasyon/hava; 1-X-2, Alt/Üst 2.5, KG Var/Yok ihtimalleri;
     kısa Türkçe yorum; risk notu. Oran veya piyasa ihtimali verilmez (kalibrasyon ölçümü için şart).
  2. İTİRAZ: piyasa ihtimalleri gösterilir; "bunları yanlış çıkaracak somut bir bilgi var mı?" → ok / warn + gerekçe.
Claude rakam değiştirmez; sayfada 3. görüş olarak durur, isabeti zamanla ölçülür.

Maliyet (Opus 5.5, kaba): maç başına ~0.20–0.30 $ (≤8 arama + ~30k giriş + ~2k çıkış). CLAUDE_MAX_PER_DAY ile sınırlanır.
Ortam: ANTHROPIC_API_KEY, CLAUDE_MODEL (varsayılan claude-opus-5-5), CLAUDE_MAX_PER_DAY (varsayılan 3).

Kullanım (test): python claude_check.py "Galatasaray" "Fenerbahçe" "Türkiye Süper Ligi" 2026-11-01T17:00:00+00:00
"""
import json, os, sys
from datetime import datetime, timezone, timedelta
import config

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")
MAX_PER_DAY = int(os.environ.get("CLAUDE_MAX_PER_DAY", "3"))
MAX_FORCE_PER_DAY = int(os.environ.get("CLAUDE_MAX_FORCE_PER_DAY", "6"))   # fırsat uyarılı maçlar için ayrı tavan
OUT_DIR = "records/claude"

SYSTEM = """Sen yılların futbol analistisin; maç önü yazıların ölçülü, somut ve okunaklıdır — bir köşe yazısı gibi, sohbet gibi değil. Kulüplerin iç dinamiğini,
teknik direktörlerin huylarını, hangi eksiğin gerçekten acıttığını bilirsin.

Görev: Verilen maç için GÜNCEL haberleri araştır (sakatlık, ceza, açıklanan kadro, teknik direktör değişikliği, motivasyon, hava),
sonra bahis oranı GÖRMEDEN kendi olasılık tahminini ver.
Arama disiplini: en fazla 4-5 arama; her aramanın sonucunu okuyup değerlendirmeden yeni arama başlatma. Haberin tarihine dikkat et;
bir haftadan eskiyse güvenini düşür.

Yorum (comment) nasıl olmalı:
- Ses: ölçülü, deneyimli bir analist. Köşe yazısı ciddiyeti; sohbet havası değil. "Ben", "bana kalırsa", "açıkçası", "işin tuhafı"
  gibi samimi kalıpları yazı başına en fazla BİR kez kullan; gerekmiyorsa hiç kullanma. "Biz" ya da kişisiz anlatım tercih et
  ("Beklenti şu:", "Asıl soru şu:"). Ünlem yok, abartı yok, argo yok.
- Kalıp açılış kullanma ("Maçın anahtarı…", "Bu maçta…" ile başlama); her yazı farklı bir yerden girsin — bir oyuncudan, bir sayıdan,
  son maçtaki bir andan, bir çelişkiden.
- Somut ol: isimler, sayılar, son maçlardan anlar. Klişe yok ("iki takım da kazanmak isteyecek" yazma), boş genelleme yok.
- Bir görüşün olsun ve onu söyle; ama neye dayandığını da söyle. Emin olmadığın yerde bunu belirt.
- Türkçe kusursuz olsun: yazım ve dil bilgisi hatasız; özel adlara gelen ekler kesme işaretiyle (Osimhen'in, Buruk'un);
  yabancı adlar orijinal yazımıyla; her cümle tek fikir ve en fazla 25 kelime; üç nokta ve uzun noktalı virgül zincirleri yok;
  devrik cümle nadiren. Yazdıktan sonra metni bir kez daha Türkçe açısından oku ve düzelt.
- 4-6 cümle. Oran, Pinnacle, Nesine, "value", bahis tavsiyesi yazma; sadece maç.
risk: tek cümle, ölçülü ("En büyük soru işareti…", "Sonucu en çok şu belirsizleştiriyor:…"). absences: haberlerde geçen her eksik/şüpheli/dönen oyuncu için
takımdaki yeri (as/rotasyon/yedek), son maçlardaki durumu ve bu maça somut etkisi (yerine kim oynar, hangi bölge zayıflar);
emin olmadığın yere 'bilinmiyor' yaz, uydurma. lineup_note: muhtemel 11 / diziliş, 1-2 cümle; bilgi yoksa boş.
Olasılıklar toplamı her market için 1.0 olmalı; somut bilgi yoksa mütevazı, lig ortalamasına yakın kal. comment asla boş olmasın."""

BLIND_SCHEMA = {
    "type": "object",
    "properties": {
        "p_home": {"type": "number"}, "p_draw": {"type": "number"}, "p_away": {"type": "number"},
        "p_over25": {"type": "number"}, "p_btts": {"type": "number"},
        "facts": {"type": "array", "items": {"type": "string"}, "description": "Bulunan somut haberler, en fazla 5, her biri tek cümle, kaynak adıyla"},
        "comment": {"type": "string", "description": "ZORUNLU, asla boş bırakma: 4-6 cümle, ölçülü bir analist sesiyle kusursuz Türkçe maç önü yazısı; samimi kalıp en fazla bir kez; kalıp açılış yok; somut isim/sayı/an; görüş + dayanağı. Haber bulunamadıysa da yaz."},
        "risk": {"type": "string", "description": "Tek cümle, ölçülü: bu maçta sonucu en çok belirsizleştiren şey"},
        "confidence": {"type": "string", "enum": ["düşük", "orta", "yüksek"]},
        "absences": {"type": "array", "description": "Haberlerde geçen eksik/şüpheli oyuncular (en fazla 10). Bilgi yoksa boş liste.",
                     "items": {"type": "object", "properties": {
                         "team": {"type": "string"}, "player": {"type": "string"},
                         "status": {"type": "string", "enum": ["sakat", "cezalı", "şüpheli", "döndü"]},
                         "role": {"type": "string", "enum": ["as", "rotasyon", "yedek", "bilinmiyor"], "description": "Takımdaki yeri"},
                         "recent": {"type": "string", "description": "Son maçlarda durumu, kısa (örn. 'son 5 maçın 4'ünde ilk 11', 'Eylül'den beri yok')"},
                         "impact": {"type": "string", "description": "Bu maça etkisi tek cümle (yerine kim oynar, hangi bölge zayıflar)"}},
                         "required": ["team", "player", "status", "role", "recent", "impact"], "additionalProperties": False}},
        "lineup_note": {"type": "string", "description": "Muhtemel 11 / diziliş / kadro notu, 1-2 cümle; bilgi yoksa boş"},
    },
    "required": ["p_home", "p_draw", "p_away", "p_over25", "p_btts", "facts", "comment", "risk", "confidence", "absences", "lineup_note"],
    "additionalProperties": False,
}
OBJECT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["ok", "warn"], "description": "warn = piyasa ihtimalini yanlış çıkaracak SOMUT bilgi var"},
        "reason": {"type": "string", "description": "Tek-iki cümle gerekçe, düz Türkçe"},
    },
    "required": ["verdict", "reason"],
    "additionalProperties": False,
}


def _client():
    import anthropic
    # Web aramalı istekler uzun sürebilir ama sonsuza dek takılmasın: 5 dk zaman aşımı, 1 tekrar.
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY or None, timeout=300.0, max_retries=1)


class Usage:
    """Tüm çağrıların (pause_turn devamları dahil) kullanım toplamı."""
    def __init__(self):
        self.inp = self.out = self.cache_read = self.cache_write = self.searches = 0

    def add(self, u):
        if not u:
            return
        self.inp += u.input_tokens or 0
        self.out += u.output_tokens or 0
        self.cache_read += getattr(u, "cache_read_input_tokens", 0) or 0
        self.cache_write += getattr(u, "cache_creation_input_tokens", 0) or 0
        stu = getattr(u, "server_tool_use", None)
        self.searches += (getattr(stu, "web_search_requests", 0) or 0) if stu else 0

    def dict(self):
        return {"in": self.inp, "out": self.out, "cache_read": self.cache_read, "cache_write": self.cache_write, "searches": self.searches}

    def cost(self):
        # Opus 5.5: giriş 4$/M, önbellek yazma 5$/M, okuma 0.2$/M, çıkış 20$/M; web araması 10$/1000
        return round(self.inp * 4e-6 + self.cache_write * 5e-6 + self.cache_read * 0.2e-6 + self.out * 20e-6 + self.searches * 0.01, 3)


def _run(client, messages, schema, usage):
    """Web araması pause_turn verebilir; en fazla 3 kez devam eder. Metin bloğundaki JSON'u döner; kullanım usage'a eklenir."""
    for _ in range(3):
        resp = client.beta.messages.create(
            model=MODEL, max_tokens=4000,
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            # Önbellek: pause_turn devamları ve 2. aşama, önceki çağrının tam ön ekini paylaşır → okuma ucuz.
            # (2. aşama ilk kez görülen 1. aşama sonuçlarını önce yazar; kazanç devam turlarında.)
            cache_control={"type": "ephemeral"},
            system=SYSTEM, messages=messages,
            tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 8}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        usage.add(resp.usage)
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason == "pause_turn":
            continue
        if resp.stop_reason == "refusal":
            raise RuntimeError("Claude yanıt vermedi (refusal)")
        text = next((b.text for b in resp.content if b.type == "text"), None)
        return json.loads(text) if text else None
    return None


def analyze(home, away, league, start_iso, market_probs=None):
    """Tek maç analizi. market_probs = {'MS': {'1','X','2'}, 'AU25': {...}, 'KG': {...}} (yalnızca 2. aşamada gösterilir)."""
    client = _client()
    tr = timezone(timedelta(hours=3))
    start = datetime.fromisoformat(start_iso).astimezone(tr)
    q = (f"Maç: {home} - {away} ({league}), başlama: {start:%d.%m.%Y %H:%M} Türkiye saati. Bugün: {datetime.now(tr):%d.%m.%Y}. "
         "Güncel haberleri araştır ve tahminini ver.")
    messages = [{"role": "user", "content": q}]
    usage = Usage()
    blind = _run(client, messages, BLIND_SCHEMA, usage)
    out = {"model": MODEL, "blind": blind, "objection": None}
    if blind and market_probs and "MS" in market_probs:
        mp = market_probs
        q2 = ("Şimdi dünya piyasasının (Pinnacle) adil ihtimalleri: "
              f"ev %{mp['MS']['1']*100:.0f}, beraberlik %{mp['MS']['X']*100:.0f}, deplasman %{mp['MS']['2']*100:.0f}"
              + (f"; 3+ gol %{mp['AU25']['Üst']*100:.0f}; karşılıklı gol %{mp['KG']['Var']*100:.0f}" if "AU25" in mp and "KG" in mp else "")
              + ". Soru: Bulduğun haberlerde bu ihtimalleri YANLIŞ çıkaracak somut bir bilgi var mı (örn. piyasanın henüz fiyatlamadığı "
                "bir kadro haberi)? Yoksa 'ok' de. Kendi tahminin farklı diye 'warn' deme; sadece somut, yeni bilgi varsa.")
        messages.append({"role": "user", "content": q2})
        out["objection"] = _run(client, messages, OBJECT_SCHEMA, usage)
    out["usage"] = usage.dict()
    out["cost_usd"] = usage.cost()
    return out


def load_today(day=None):
    day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = f"{OUT_DIR}/{day}.jsonl"
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def analyzed_before(code):
    """Bu maç herhangi bir gün analiz edilmiş mi? (records/claude/*.jsonl)"""
    import glob
    for p in glob.glob(f"{OUT_DIR}/*.jsonl"):
        with open(p, encoding="utf-8") as f:
            for line in f:
                if line.strip() and json.loads(line).get("code") == code:
                    return True
    return False


def analyze_and_store(m, market_probs, force=False):
    """watch.py için: günlük sınır ve tekrar kontrolü ile analiz eder, records/claude/GÜN.jsonl'a yazar.
    force=True (fırsat uyarısı çıkan maç): günlük sınırı aşsa da analiz edilir."""
    if not config.ANTHROPIC_API_KEY:
        return None
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today = load_today(day)
    if any(r["code"] == m["code"] for r in today) or analyzed_before(m["code"]):
        return None   # bir maç bir kez analiz edilir (gün fark etmez)
    if not force:
        import clubs
        if clubs.tier(m) > clubs.ANALYZE_MAX_TIER:
            return None   # fırsat uyarısı yoksa yalnız büyük kulüp maçları
    if force:
        if sum(1 for r in today if r.get("forced")) >= MAX_FORCE_PER_DAY:
            return None
    elif len(today) >= MAX_PER_DAY:
        return None
    res = analyze(m["home"], m["away"], m["league"], m["start"].isoformat(), market_probs)
    if not res.get("blind"):
        print(f"Claude analizi boş döndü ({m['home']}-{m['away']}), kaydedilmedi; maliyet ${res.get('cost_usd', 0)}")
        return None
    row = {"t": datetime.now(timezone.utc).isoformat(timespec="seconds"), "code": m["code"], "home": m["home"], "away": m["away"],
           "league": m["league"], "sport": m.get("sport_key"), "start": m["start"].isoformat(),
           "market": {k: {kk: round(vv, 4) for kk, vv in v.items()} for k, v in (market_probs or {}).items() if not k.startswith("_")},
           "result": None, "forced": bool(force), **res}
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(f"{OUT_DIR}/{day}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


# ---------- Kadro notu: kadrolar açıklanınca sabahki yorumu hatırlayarak 2-3 cümlelik güncelleme (web araması yok, ucuz)
KADRO_DIR = "records/kadro"
NOTE_SYSTEM = """Sen yılların futbol analistisin. Sabah bu maç için bir maç önü yazısı yazdın; şimdi kulüpler ilk 11'leri açıkladı.
Görev: sabahki yazını hatırlayarak 2-3 cümlelik bir KADRO NOTU yaz: sürpriz var mı, beklediğin eksikler doğrulandı mı,
sabahki beklenti duruyor mu yoksa değişti mi. Sabahki yazıya atıf yap ("Sabah ... demiştik"), tekrar anlatma.
Ses: ölçülü, köşe yazısı ciddiyeti; "biz" ya da kişisiz anlatım; samimi kalıp ("bana kalırsa", "açıkçası") en fazla bir kez; ünlem yok.
Türkçe kusursuz: kesme işareti (Osimhen'in), her cümle tek fikir ve en fazla 25 kelime, üç nokta yok. Yazdıktan sonra bir kez daha oku.
Oran, bahis, piyasa, tavsiye yazma; sadece maç. Olasılıklar: kadroyu gördükten sonraki güncel tahminin; toplam 1.0."""
NOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "note": {"type": "string", "description": "ZORUNLU: 2-3 cümle kadro notu, kusursuz Türkçe, sabahki yazıya atıfla"},
        "changed": {"type": "boolean", "description": "Kadro sabahki beklentiyi anlamlı biçimde değiştirdi mi"},
        "p_home": {"type": "number"}, "p_draw": {"type": "number"}, "p_away": {"type": "number"},
    },
    "required": ["note", "changed", "p_home", "p_draw", "p_away"],
    "additionalProperties": False,
}


def _lineup_text(rosters):
    import html as _h
    out = []
    for team, r in (rosters or {}).items():
        xi = ", ".join(f"{_h.unescape(p.get('player') or '')} ({p.get('pos') or '?'})" for p in (r.get("starters") or [])[:11])
        out.append(f"{team} ({r.get('formation') or 'diziliş ?'}): {xi}")
    return "\n".join(out)


def find_prev(code):
    """Bu maç için daha önce yazılmış (kör) analiz kaydı; yoksa None."""
    import glob
    best = None
    for p in sorted(glob.glob(f"{OUT_DIR}/*.jsonl")):
        with open(p, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    if r.get("code") == code and r.get("blind"):
                        best = r
    return best


def load_kadro(day=None):
    day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = f"{KADRO_DIR}/{day}.jsonl"
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def kadro_before(code):
    import glob
    for p in glob.glob(f"{KADRO_DIR}/*.jsonl"):
        with open(p, encoding="utf-8") as f:
            if any(l.strip() and json.loads(l).get("code") == code for l in f):
                return True
    return False


def lineup_note(m, prev, rosters, market_probs=None):
    client = _client()
    bl = prev.get("blind") or {}
    tr = timezone(timedelta(hours=3))
    start = datetime.fromisoformat(prev["start"]).astimezone(tr) if prev.get("start") else m["start"].astimezone(tr)
    absences = "; ".join(f"{a.get('player')} ({a.get('team')}, {a.get('status')})" for a in bl.get("absences", [])[:10]) or "yok"
    q = (f"Maç: {m['home']} - {m['away']} ({m.get('league', '')}), {start:%d.%m.%Y %H:%M}.\n\n"
         f"SABAHKİ YAZIN:\n{bl.get('comment', '')}\n\nSabahki risk notun: {bl.get('risk', '')}\n"
         f"Sabah beklediğin eksikler: {absences}\nSabahki kadro notun: {bl.get('lineup_note', '') or 'yok'}\n"
         f"Sabahki tahminin: ev %{bl.get('p_home', 0) * 100:.0f}, beraberlik %{bl.get('p_draw', 0) * 100:.0f}, deplasman %{bl.get('p_away', 0) * 100:.0f}\n\n"
         f"AÇIKLANAN İLK 11'LER:\n{_lineup_text(rosters)}\n\nKadro notunu yaz.")
    usage = Usage()
    resp = client.beta.messages.create(
        model=MODEL, max_tokens=4000, betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        system=NOTE_SYSTEM, messages=[{"role": "user", "content": q}],
        output_config={"format": {"type": "json_schema", "schema": NOTE_SCHEMA}},
    )
    usage.add(resp.usage)
    text = next((b.text for b in resp.content if b.type == "text"), None)
    if not text:
        print(f"Kadro notu: metin yok (stop={resp.stop_reason}, bloklar={[b.type for b in resp.content]})")
    res = json.loads(text) if text else None
    return {"model": MODEL, "kadro": res, "usage": usage.dict(), "cost_usd": usage.cost()}


def lineup_note_and_store(m, rosters, market_probs=None):
    """Kadro notu: günlük sınır (MAX_PER_DAY), tekrar kontrolü, sabah analizi şartı. records/kadro/GÜN.jsonl'a yazar."""
    if not config.ANTHROPIC_API_KEY:
        return None
    prev = find_prev(m["code"])
    if not prev or kadro_before(m["code"]):
        return None
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if len(load_kadro(day)) >= MAX_PER_DAY:
        return None
    res = lineup_note(m, prev, rosters, market_probs)
    if not (res.get("kadro") or {}).get("note"):
        print(f"Kadro notu boş döndü ({m['home']}-{m['away']}); maliyet ${res.get('cost_usd', 0)}")
        return None
    row = {"t": datetime.now(timezone.utc).isoformat(timespec="seconds"), "code": m["code"], "home": m["home"], "away": m["away"],
           "league": m.get("league"), "sport": m.get("sport_key"), "start": m["start"].isoformat(),
           "market": {k: {kk: round(vv, 4) for kk, vv in v.items()} for k, v in (market_probs or {}).items() if not k.startswith("_")},
           "rosters": rosters, **res}
    os.makedirs(KADRO_DIR, exist_ok=True)
    with open(f"{KADRO_DIR}/{day}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


if __name__ == "__main__":
    home, away, league, start = sys.argv[1:5]
    probs = {"MS": {"1": 0.45, "X": 0.27, "2": 0.28}, "AU25": {"Alt": 0.48, "Üst": 0.52}, "KG": {"Var": 0.55, "Yok": 0.45}}
    r = analyze(home, away, league, start, probs)
    print(json.dumps(r, ensure_ascii=False, indent=1))
