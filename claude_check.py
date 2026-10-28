"""Görüş 3 – Claude: haber + kadro okur, oranı GÖRMEDEN kendi ihtimalini verir; sonra piyasa ihtimaline itiraz var mı söyler.

İki aşama, tek sohbet (ikinci aşama önbellekten ucuz):
  1. KÖR TAHMİN: web araması (en çok 4) ile sakatlık/kadro/motivasyon/hava; 1-X-2, Alt/Üst 2.5, KG Var/Yok ihtimalleri;
     kısa Türkçe yorum; risk notu. Oran veya piyasa ihtimali verilmez (kalibrasyon ölçümü için şart).
  2. İTİRAZ: piyasa ihtimalleri gösterilir; "bunları yanlış çıkaracak somut bir bilgi var mı?" → ok / warn + gerekçe.
Claude rakam değiştirmez; sayfada 3. görüş olarak durur, isabeti zamanla ölçülür.

Maliyet (Opus 5.5, kaba): maç başına ~0.15–0.20 $ (arama + ~20k giriş + ~2k çıkış). CLAUDE_MAX_PER_DAY ile sınırlanır.
Ortam: ANTHROPIC_API_KEY, CLAUDE_MODEL (varsayılan claude-opus-5-5), CLAUDE_MAX_PER_DAY (varsayılan 3).

Kullanım (test): python claude_check.py "Galatasaray" "Fenerbahçe" "Türkiye Süper Ligi" 2026-11-01T17:00:00+00:00
"""
import json, os, sys
from datetime import datetime, timezone
import config

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")
MAX_PER_DAY = int(os.environ.get("CLAUDE_MAX_PER_DAY", "3"))
OUT_DIR = "records/claude"

SYSTEM = """Sen 20 yıllık profesyonel bir futbol analistisin: kulüplere ve yayıncılara maç önü raporu yazan türden.
Üslubun: kendinden emin ama kanıta bağlı; genelleme yok, klişe yok ("iki takım da kazanmak isteyecek" gibi boş cümle yazma).
Her iddianın arkasında bir gerçek olsun: kadro/sakatlık/ceza, son maçlardaki form ve gol üretimi, taktik eşleşme (pres, geçiş,
kanat/orta, duran top), fikstür yoğunluğu ve motivasyon (küme hattı, tur durumu, derbi), saha/hava/seyahat.
Görev: Verilen maç için GÜNCEL haberleri araştır (sakatlık, ceza, açıklanan kadro, teknik direktör değişikliği, motivasyon, hava),
sonra bahis oranı GÖRMEDEN kendi olasılık tahminini ver.
Yorum biçimi: önce maçın anahtarı (tek cümle), sonra iki takımın durumu, sonra beklenen senaryo. 3-5 cümle, Türkçe, net; bir
spor gazetesinin analiz köşesi gibi okunmalı ama teknik olmayan biri de anlamalı.
Olasılıklar toplamı her market için 1.0 olmalı. Somut bilgi bulamadığın yerde bunu söyle ve mütevazı, lig ortalamasına yakın kal;
bulduğun bilginin tarihi eskiyse (bir haftadan öncesi) güvenini düşür.
Oran, Pinnacle, Nesine, "value" veya bahis tavsiyesi hakkında yazma; sadece maç analizi ve ihtimaller."""

BLIND_SCHEMA = {
    "type": "object",
    "properties": {
        "p_home": {"type": "number"}, "p_draw": {"type": "number"}, "p_away": {"type": "number"},
        "p_over25": {"type": "number"}, "p_btts": {"type": "number"},
        "facts": {"type": "array", "items": {"type": "string"}, "description": "Bulunan somut haberler, en fazla 5, her biri tek cümle, kaynak adıyla"},
        "comment": {"type": "string", "description": "3-5 cümle, profesyonel analist üslubunda Türkçe maç önü yorumu: anahtar faktör, iki takımın durumu, beklenen senaryo"},
        "risk": {"type": "string", "description": "Tek cümle: bu maçta bahis açısından en büyük belirsizlik"},
        "confidence": {"type": "string", "enum": ["düşük", "orta", "yüksek"]},
    },
    "required": ["p_home", "p_draw", "p_away", "p_over25", "p_btts", "facts", "comment", "risk", "confidence"],
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
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY or None)


def _run(client, messages, schema):
    """Web araması pause_turn verebilir; en fazla 3 kez devam eder. Metin bloğundaki JSON'u döner."""
    for _ in range(3):
        resp = client.beta.messages.create(
            model=MODEL, max_tokens=4000,
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            system=SYSTEM, messages=messages,
            tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 4}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason == "pause_turn":
            continue
        if resp.stop_reason == "refusal":
            raise RuntimeError("Claude yanıt vermedi (refusal)")
        text = next((b.text for b in resp.content if b.type == "text"), None)
        return json.loads(text) if text else None, resp.usage
    return None, None


def analyze(home, away, league, start_iso, market_probs=None):
    """Tek maç analizi. market_probs = {'MS': {'1','X','2'}, 'AU25': {...}, 'KG': {...}} (yalnızca 2. aşamada gösterilir)."""
    client = _client()
    tr = timezone(timedelta(hours=3))
    start = datetime.fromisoformat(start_iso).astimezone(tr)
    q = (f"Maç: {home} - {away} ({league}), başlama: {start:%d.%m.%Y %H:%M} Türkiye saati. Bugün: {datetime.now(tr):%d.%m.%Y}. "
         "Güncel haberleri araştır ve tahminini ver.")
    messages = [{"role": "user", "content": q}]
    blind, u1 = _run(client, messages, BLIND_SCHEMA)
    out = {"model": MODEL, "blind": blind, "objection": None, "usage": {}}
    if u1:
        out["usage"] = {"in": u1.input_tokens, "out": u1.output_tokens}
    if blind and market_probs and "MS" in market_probs:
        mp = market_probs
        q2 = ("Şimdi dünya piyasasının (Pinnacle) adil ihtimalleri: "
              f"ev %{mp['MS']['1']*100:.0f}, beraberlik %{mp['MS']['X']*100:.0f}, deplasman %{mp['MS']['2']*100:.0f}"
              + (f"; 3+ gol %{mp['AU25']['Üst']*100:.0f}; karşılıklı gol %{mp['KG']['Var']*100:.0f}" if "AU25" in mp and "KG" in mp else "")
              + ". Soru: Bulduğun haberlerde bu ihtimalleri YANLIŞ çıkaracak somut bir bilgi var mı (örn. piyasanın henüz fiyatlamadığı "
                "bir kadro haberi)? Yoksa 'ok' de. Kendi tahminin farklı diye 'warn' deme; sadece somut, yeni bilgi varsa.")
        messages.append({"role": "user", "content": q2})
        obj, u2 = _run(client, messages, OBJECT_SCHEMA)
        out["objection"] = obj
        if u2:
            out["usage"]["in"] = out["usage"].get("in", 0) + u2.input_tokens
            out["usage"]["out"] = out["usage"].get("out", 0) + u2.output_tokens
    return out


def load_today(day=None):
    day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = f"{OUT_DIR}/{day}.jsonl"
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def analyze_and_store(m, market_probs):
    """watch.py için: günlük sınır ve tekrar kontrolü ile analiz eder, records/claude/GÜN.jsonl'a yazar."""
    if not config.ANTHROPIC_API_KEY:
        return None
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today = load_today(day)
    if any(r["code"] == m["code"] for r in today):
        return None
    if len(today) >= MAX_PER_DAY:
        return None
    res = analyze(m["home"], m["away"], m["league"], m["start"].isoformat(), market_probs)
    row = {"t": datetime.now(timezone.utc).isoformat(timespec="seconds"), "code": m["code"], "home": m["home"], "away": m["away"],
           "league": m["league"], "sport": m.get("sport_key"), "start": m["start"].isoformat(),
           "market": {k: {kk: round(vv, 4) for kk, vv in v.items()} for k, v in market_probs.items() if not k.startswith("_")},
           "result": None, **res}
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(f"{OUT_DIR}/{day}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


if __name__ == "__main__":
    home, away, league, start = sys.argv[1:5]
    probs = {"MS": {"1": 0.45, "X": 0.27, "2": 0.28}, "AU25": {"Alt": 0.48, "Üst": 0.52}, "KG": {"Var": 0.55, "Yok": 0.45}}
    r = analyze(home, away, league, start, probs)
    print(json.dumps(r, ensure_ascii=False, indent=1))
