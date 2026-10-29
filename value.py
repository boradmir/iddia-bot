"""Modül 6 – Value hesabı.

EV% = (Nesine oranı × adil olasılık − 1) × 100
Kelly = (oran × p − 1) / (oran − 1); yatırım = kasa × Kelly × 1/4, tavan kasanın %2'si.
Eşik: EV ≥ %3. MBS: maçın min. bahis sayısı >1 ise tek başına oynanamaz → karta not düşülür.
"""
EV_THRESHOLD = 3.0
KELLY_FRACTION = 0.25
MAX_STAKE_PCT = 0.02
# Geriye dönük test (5.201 maç, 2023-26): "value" oran ≥3.0 sürprizlerde yanıltıcı (ROI ≈ 0 veya eksi),
# oran <3.0 favorilerde gerçek (+%14 ± 12). Yüksek oranlı seçimler karta alınmaz.
MAX_ODDS = 3.0
# Nesine'de kupon başına alt sınır (maç sayısından bağımsız). Kelly'nin önerdiği küçük tutarlar bunun altında kalır;
# bu yüzden "bu bahis için en az ne kadar kasa gerekir" = MIN_COUPON_TL / (önerilen yüzde / 100) gösterilir.
MIN_COUPON_TL = 50


def min_bankroll_for(stake_pct):
    """Önerilen yatırım kasanın %stake_pct'i ise, 50 TL alt sınırını %stake_pct olarak oynayabilmek için gereken kasa (TL)."""
    return None if not stake_pct or stake_pct <= 0 else round(MIN_COUPON_TL * 100 / stake_pct)


def ev_pct(odds, p):
    return (odds * p - 1) * 100


def kelly(odds, p):
    return max(0.0, (odds * p - 1) / (odds - 1))


def stake(odds, p, bankroll):
    s = bankroll * kelly(odds, p) * KELLY_FRACTION
    return round(min(s, bankroll * MAX_STAKE_PCT), 2)


def evaluate(nesine_match, probs, pinnacle_odds=None, bankroll=250.0, threshold=EV_THRESHOLD):
    """Bir maçın 3 marketini tarar; eşik üstü fırsatları liste olarak döner.
    threshold=None verilirse tüm bahisleri EV'siyle döner (teşhis için)."""
    pinnacle_odds = pinnacle_odds or {}
    out = []
    for market, mk in nesine_match["markets"].items():
        if market not in probs:
            continue
        for pick, o in mk["odds"].items():
            p = probs[market].get(pick)
            if p is None:
                continue
            ev = ev_pct(o, p)
            if threshold is not None and o >= MAX_ODDS:
                continue
            if threshold is None or ev >= threshold:
                out.append({
                    "code": nesine_match["code"], "home": nesine_match["home"], "away": nesine_match["away"],
                    "start": nesine_match["start"], "league": nesine_match["league"], "sport_key": nesine_match.get("sport_key"),
                    "market": market, "pick": pick, "nesine_odds": o, "fair_prob": p, "fair_odds": round(1 / p, 2),
                    "pinnacle_odds": pinnacle_odds.get(pick) if market == "MS" else None,
                    "ev_pct": round(ev, 2), "stake": stake(o, p, bankroll),
                    "mbs": max(nesine_match.get("mbs") or 1, mk.get("mbs") or 1),
                })
    return sorted(out, key=lambda x: -x["ev_pct"])
