"""Modül 4 – Adil olasılık.

- MS: Pinnacle 1/X/2 oranlarından kesinti (marj) çıkarılır: p_i = (1/o_i) / Σ(1/o_j).
- Alt/Üst 2.5 ve KG: Pinnacle'ın toplam gol çizgisinden toplam gol beklentisi (λ),
  MS olasılıklarından ev/deplasman bölüşümü bulunur; Poisson skor tablosundan
  P(Alt/Üst 2.5) ve P(KG Var/Yok) hesaplanır.
Claude bu rakamlara dokunmaz.
"""
import math

MAX_GOALS = 10


def fair_probs(odds, method="power"):
    """{'1': 1.8, 'X': 3.5, '2': 4.5} → marjsız olasılıklar (toplamı 1).
    method='basic': oransal (1/o)/Σ(1/o). Favori-sürpriz yanlılığını düzeltmez.
    method='power': (1/o)^k, Σ=1 olacak k bulunur; marjı sürprizlere daha çok yükler
                    (geçmiş veride kalibrasyonu çok daha iyi — bkz. backtest.py)."""
    inv = {k: 1 / v for k, v in odds.items()}
    if method == "basic" or len(inv) < 2:
        s = sum(inv.values())
        return {k: v / s for k, v in inv.items()}
    lo, hi = 1.0, 3.0
    for _ in range(60):
        k = (lo + hi) / 2
        s = sum(v ** k for v in inv.values())
        if s > 1:
            lo = k
        else:
            hi = k
    k = (lo + hi) / 2
    p = {n: v ** k for n, v in inv.items()}
    s = sum(p.values())
    return {n: v / s for n, v in p.items()}


def _pois(k, lam):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def _cdf(k, lam):
    return sum(_pois(i, lam) for i in range(k + 1))


def under_prob(lam, line):
    """Poisson(λ) altında 'Alt line' bahsinin kazanma olasılığı (iade hariç, kazanç/kayıp oranı).
    X.5: P(gol ≤ X). X.0: iade (gol = X) dışlanır. X.25 / X.75: iki komşu çizginin ortalaması (Asya çizgisi)."""
    frac = round(line % 1, 2)
    if frac == 0.5:
        return _cdf(int(line), lam)
    if frac == 0.0:
        k = int(line)
        push = _pois(k, lam)
        return _cdf(k - 1, lam) / (1 - push)
    if frac == 0.25:
        return 0.5 * under_prob(lam, line - 0.25) + 0.5 * under_prob(lam, line + 0.25)
    if frac == 0.75:
        return 0.5 * under_prob(lam, line - 0.25) + 0.5 * under_prob(lam, line + 0.25)
    raise ValueError(f"desteklenmeyen çizgi {line}")


def total_lambda(p_under, line):
    """under_prob(λ, line) = p_under olacak λ'yı ikiye bölme ile bulur. Her çizgi tipiyle çalışır."""
    lo, hi = 0.05, 8.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if under_prob(mid, line) > p_under:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def score_matrix(lh, la):
    return [[_pois(h, lh) * _pois(a, la) for a in range(MAX_GOALS)] for h in range(MAX_GOALS)]


def outcome_probs(matrix):
    home = sum(matrix[h][a] for h in range(MAX_GOALS) for a in range(MAX_GOALS) if h > a)
    away = sum(matrix[h][a] for h in range(MAX_GOALS) for a in range(MAX_GOALS) if h < a)
    return home, 1 - home - away, away


def split_lambda(total, p_home, p_away):
    """Toplam λ'yı ev/deplasman olarak böl: Poisson 1/2 olasılıkları Pinnacle'a en yakın olsun."""
    best = None
    for i in range(1, 200):
        lh = total * i / 200
        la = total - lh
        ph, _, pa = outcome_probs(score_matrix(lh, la))
        err = (ph - p_home) ** 2 + (pa - p_away) ** 2
        if best is None or err < best[0]:
            best = (err, lh, la)
    return best[1], best[2]


def market_probs(h2h_odds, totals=None):
    """Pinnacle MS (+ toplam gol) → {'MS': {...}, 'AU25': {...}, 'KG': {...}} adil olasılıklar.
    totals = {'line': 2.5, 'Alt': o, 'Üst': o}; yoksa sadece MS döner."""
    ms = fair_probs(h2h_odds)
    out = {"MS": ms}
    if not totals:
        return out
    pu = fair_probs({"Alt": totals["Alt"], "Üst": totals["Üst"]})["Alt"]
    total = total_lambda(pu, totals["line"])
    lh, la = split_lambda(total, ms["1"], ms["2"])
    m = score_matrix(lh, la)
    under25 = sum(m[h][a] for h in range(MAX_GOALS) for a in range(MAX_GOALS) if h + a <= 2)
    btts = sum(m[h][a] for h in range(1, MAX_GOALS) for a in range(1, MAX_GOALS))
    out["AU25"] = {"Alt": under25, "Üst": 1 - under25}
    out["KG"] = {"Var": btts, "Yok": 1 - btts}
    out["_lambda"] = {"home": lh, "away": la}
    return out
