"""Kupon önerileri: yaklaşan maçlardan 3-5 maçlık kombineler.

Her kupon için: toplam oran, gelme ihtimali (piyasa olasılıklarının çarpımı; maçlar bağımsız sayılır),
adil oran (1/ihtimal), beklenen değer. Dürüst not: en yüksek ihtimalli kupon genelde en eksi değerli kupondur,
çünkü İddaa marjı her maçta katlanır. Karar kullanıcıda; sayfa rakamı saklamaz.

bets: value.evaluate(..., threshold=None) çıktısı (tüm bahisler, ev_pct, fair_prob, nesine_odds, mbs, code, start...).
"""
import itertools

MIN_LEGS, MAX_LEGS = 3, 5


def _per_match(bets, key):
    """Her maçtan tek bacak: key'e göre en iyi."""
    best = {}
    for b in bets:
        if b["code"] not in best or key(b) > key(best[b["code"]]):
            best[b["code"]] = b
    return list(best.values())


def _coupon(legs):
    p = 1.0; o = 1.0
    for b in legs:
        p *= b["fair_prob"]; o *= b["nesine_odds"]
    return {"legs": sorted(legs, key=lambda b: b["start"]), "odds": o, "prob": p, "fair_odds": 1 / p if p else None,
            "ev_pct": (o * p - 1) * 100, "n": len(legs)}


def _mbs_ok(legs):
    return all(b["mbs"] <= len(legs) for b in legs)


def safest(bets, n):
    """n maçlık, gelme ihtimali en yüksek kupon."""
    legs = sorted(_per_match(bets, key=lambda b: b["fair_prob"]), key=lambda b: -b["fair_prob"])
    # MBS kısıtı: en yüksek ihtimalli ilk n uygun kombinasyon (küçük havuzda tam arama)
    pool = legs[: n + 4]
    best = None
    for combo in itertools.combinations(pool, n):
        if not _mbs_ok(combo):
            continue
        c = _coupon(list(combo))
        if best is None or c["prob"] > best["prob"]:
            best = c
    return best


def least_loss(bets, n):
    """n maçlık, beklenen değeri en iyi (en az eksi) kupon: her maçtan oran×ihtimal en yüksek bacak."""
    legs = sorted(_per_match(bets, key=lambda b: b["nesine_odds"] * b["fair_prob"]), key=lambda b: -(b["nesine_odds"] * b["fair_prob"]))
    pool = legs[: n + 4]
    best = None
    for combo in itertools.combinations(pool, n):
        if not _mbs_ok(combo):
            continue
        c = _coupon(list(combo))
        if best is None or c["ev_pct"] > best["ev_pct"]:
            best = c
    return best


def value_coupon(bets, threshold=3.0, max_odds=3.0, max_legs=3):
    """Sadece eşik üstü (value) bacaklardan kupon; yoksa None."""
    legs = [b for b in _per_match(bets, key=lambda b: b["ev_pct"]) if b["ev_pct"] >= threshold and b["nesine_odds"] < max_odds]
    legs.sort(key=lambda b: -b["ev_pct"])
    legs = legs[:max_legs]
    if len(legs) < 2:
        return None
    return _coupon(legs)


def build_all(bets):
    out = {"safest": [], "least_loss": []}
    if len({b["code"] for b in bets}) < MIN_LEGS:
        return out
    for n in range(MIN_LEGS, MAX_LEGS + 1):
        c = safest(bets, n)
        if c:
            out["safest"].append(c)
        c = least_loss(bets, n)
        if c:
            out["least_loss"].append(c)
    out["value"] = value_coupon(bets)
    return out
