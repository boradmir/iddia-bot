"""Büyük kulüp önceliği: yapay zekâ analizi ve Instagram paylaşımı sırasında, lig sırasından önce bakılır.
Adlar Nesine bülteninde geçtiği gibi (küçük harf karşılaştırma). tier(m): 0 = en büyük, 1 = büyük, 9 = diğer."""

TIER1 = {"galatasaray", "fenerbahçe", "beşiktaş", "real madrid", "barcelona", "man. city", "manchester city",
         "liverpool", "arsenal", "bayern münih", "bayern munih", "psg", "paris"}
TIER2 = {"trabzonspor", "atl madrid", "atletico madrid", "chelsea", "tottenham", "man. utd", "manchester utd", "man. united",
         "b. dortmund", "dortmund", "juventus", "inter", "ac milan", "milan", "napoli", "as roma", "roma", "b. leverkusen", "leverkusen"}


def team_tier(name):
    n = (name or "").strip().lower()
    return 0 if n in TIER1 else 1 if n in TIER2 else 9


def tier(m):
    """Maçın öncelik kademesi: iki takımın en iyisi. İki büyük kulüp karşı karşıyaysa (derbi) bir kademe daha öne."""
    a, b = team_tier(m["home"]), team_tier(m["away"])
    best = min(a, b)
    return best - 1 if (a <= 1 and b <= 1) else best
