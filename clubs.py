"""Büyük kulüp önceliği: yapay zekâ analizi ve Instagram paylaşımı sırasında, lig sırasından önce bakılır.
Adlar Nesine bülteninde geçtiği gibi (küçük harf karşılaştırma). tier(m): 0 = Türk üç büyük, 1 = dünya devleri, 2 = büyük, 9 = diğer."""

ANALYZE_MAX_TIER = 2   # sabah yapay zekâ analizi yalnız listeli kulüplerin (kademe 0-2) maçlarına; yoksa o gün analiz yok

TIER0 = {"galatasaray", "fenerbahçe", "beşiktaş", "trabzonspor", "türkiye"}   # Türkiye'nin dört büyüğü + A millî takım: her zaman en önde
TIER1 = {"real madrid", "barcelona", "man. city", "manchester city", "liverpool", "arsenal", "bayern münih", "bayern munih", "psg",
         # büyük millî takımlar (Nesine adları)
         "almanya", "fransa", "ispanya", "ingiltere", "italya", "portekiz", "hollanda", "brezilya", "arjantin", "belçika", "hırvatistan"}
# not: Nesine'de "Paris" = Paris FC (PSG değil); PSG ayrı geçer
TIER2 = {"atl madrid", "atletico madrid", "chelsea", "tottenham", "man. utd", "manchester utd", "man. united",
         "b. dortmund", "dortmund", "juventus", "inter", "ac milan", "milan", "napoli", "as roma", "roma", "b. leverkusen", "leverkusen"}


FILE = "records/clubs.json"   # panelden yönetilen kademeler (public, zararsız): {"tiers": {"0": [...], "1": [...], "2": [...]}, "analyze_max_tier": 2}


def _load_file():
    """records/clubs.json varsa koddaki listeleri onunla değiştirir (panel Kademeler sayfası yazar)."""
    global TIER0, TIER1, TIER2, ANALYZE_MAX_TIER
    try:
        import json, os
        if not os.path.exists(FILE):
            return
        d = json.load(open(FILE, encoding="utf-8"))
        t = d.get("tiers") or {}
        norm = lambda xs: {x.strip().lower().replace("i\u0307", "i") for x in xs if x and x.strip()}
        if t.get("0") is not None: TIER0 = norm(t["0"])
        if t.get("1") is not None: TIER1 = norm(t["1"])
        if t.get("2") is not None: TIER2 = norm(t["2"])
        if d.get("analyze_max_tier") is not None: ANALYZE_MAX_TIER = int(d["analyze_max_tier"])
    except Exception as e:
        print(f"clubs.json okunamadı, varsayılanlar kullanılıyor: {e}")


_load_file()


def team_tier(name):
    n = (name or "").strip().lower().replace("i\u0307", "i")   # Python 'İ'.lower() → 'i̇' (noktalı); sade i'ye çevir
    return 0 if n in TIER0 else 1 if n in TIER1 else 2 if n in TIER2 else 9


def tier(m):
    """Maçın öncelik kademesi (küçük = önce): iki takımın en iyisi.
    İki listeli kulüp karşı karşıyaysa (derbi/büyük maç) yarım kademe daha öne — ama Türk üçlüsünün önüne geçmez."""
    a, b = team_tier(m["home"]), team_tier(m["away"])
    best = min(a, b)
    return best - 0.5 if (a <= 2 and b <= 2) else best
