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


def team_tier(name):
    n = (name or "").strip().lower().replace("i\u0307", "i")   # Python 'İ'.lower() → 'i̇' (noktalı); sade i'ye çevir
    return 0 if n in TIER0 else 1 if n in TIER1 else 2 if n in TIER2 else 9


def tier(m):
    """Maçın öncelik kademesi (küçük = önce): iki takımın en iyisi.
    İki listeli kulüp karşı karşıyaysa (derbi/büyük maç) yarım kademe daha öne — ama Türk üçlüsünün önüne geçmez."""
    a, b = team_tier(m["home"]), team_tier(m["away"])
    best = min(a, b)
    return best - 0.5 if (a <= 2 and b <= 2) else best
