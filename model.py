"""Görüş 2 – İstatistik modeli: takımların maç geçmişinden Poisson gol beklentisi.

Her takım için hücum (att) ve savunma (def) gücü, geçmiş maçlardan zaman ağırlıklı
(yakın maçlar daha önemli, yarı ömür HALF_LIFE gün) hesaplanır (Maher/Dixon-Coles'un sade hali):
  λ_ev  = ev_sahibi_ortalaması × att[ev] × def[dep]
  λ_dep = deplasman_ortalaması × att[dep] × def[ev]
Skor tablosundan 1/X/2, Alt/Üst 2.5, KG Var/Yok olasılıkları çıkar (prob.py ile aynı tablo).

Kullanım:
  m = Model(); m.fit(matches)   # matches: [{"date": datetime, "home": str, "away": str, "hg": int, "ag": int}]
  m.predict("Galatasaray", "Fenerbahce", as_of=datetime)  → {"MS": {...}, "AU25": {...}, "KG": {...}, "_lambda": {...}}
  m.form("Galatasaray", n=10)  → son n maç özeti (kartın "neden" bölümü için)
"""
import math, collections
from datetime import datetime
import prob

HALF_LIFE = 240      # gün; 240 ≈ 1 sezon sonra ağırlık yarıya iner
MIN_MATCHES = 6      # bir takım için en az maç; azsa lig ortalaması kullanılır
ITER = 12


class Model:
    def __init__(self):
        self.matches = []
        self.att, self.dfn = {}, {}
        self.base_home = self.base_away = 1.3
        self.fitted_at = None

    def fit(self, matches, as_of=None):
        """Yalnızca as_of'tan önceki maçlar kullanılır (geleceğe bakma yok)."""
        as_of = as_of or max(m["date"] for m in matches)
        ms = [m for m in matches if m["date"] < as_of]
        self.matches = ms
        self.fitted_at = as_of
        if not ms:
            return self
        w = [0.5 ** ((as_of - m["date"]).days / HALF_LIFE) for m in ms]
        sw = sum(w)
        self.base_home = sum(wi * m["hg"] for wi, m in zip(w, ms)) / sw
        self.base_away = sum(wi * m["ag"] for wi, m in zip(w, ms)) / sw
        teams = {m["home"] for m in ms} | {m["away"] for m in ms}
        att = {t: 1.0 for t in teams}; dfn = {t: 1.0 for t in teams}
        count = collections.Counter()
        for m in ms:
            count[m["home"]] += 1; count[m["away"]] += 1
        for _ in range(ITER):
            num_a = collections.defaultdict(float); den_a = collections.defaultdict(float)
            num_d = collections.defaultdict(float); den_d = collections.defaultdict(float)
            for wi, m in zip(w, ms):
                h, a = m["home"], m["away"]
                num_a[h] += wi * m["hg"]; den_a[h] += wi * self.base_home * dfn[a]
                num_a[a] += wi * m["ag"]; den_a[a] += wi * self.base_away * dfn[h]
                num_d[h] += wi * m["ag"]; den_d[h] += wi * self.base_away * att[a]
                num_d[a] += wi * m["hg"]; den_d[a] += wi * self.base_home * att[h]
            for t in teams:
                # az maçlı takımı 1.0'a (lig ortalaması) doğru çek
                shrink = min(1.0, count[t] / (MIN_MATCHES * 2))
                att[t] = (1 - shrink) + shrink * (num_a[t] / den_a[t] if den_a[t] else 1.0)
                dfn[t] = (1 - shrink) + shrink * (num_d[t] / den_d[t] if den_d[t] else 1.0)
            # ölçek: ortalama güç 1.0 kalsın
            ma = sum(att.values()) / len(att); md = sum(dfn.values()) / len(dfn)
            for t in teams:
                att[t] /= ma; dfn[t] /= md
        self.att, self.dfn = att, dfn
        return self

    def known(self, team):
        return team in self.att

    def predict(self, home, away):
        if not self.known(home) or not self.known(away):
            return None
        lh = self.base_home * self.att[home] * self.dfn[away]
        la = self.base_away * self.att[away] * self.dfn[home]
        m = prob.score_matrix(lh, la)
        ph, pd, pa = prob.outcome_probs(m)
        n = prob.MAX_GOALS
        under = sum(m[h][a] for h in range(n) for a in range(n) if h + a <= 2)
        btts = sum(m[h][a] for h in range(1, n) for a in range(1, n))
        return {"MS": {"1": ph, "X": pd, "2": pa}, "AU25": {"Alt": under, "Üst": 1 - under},
                "KG": {"Var": btts, "Yok": 1 - btts}, "_lambda": {"home": lh, "away": la}}

    def form(self, team, n=10):
        """Son n maç: gol attı/yedi ortalaması, KG %, Üst 2.5 %, galibiyet sayısı."""
        ms = [m for m in self.matches if team in (m["home"], m["away"])]
        ms.sort(key=lambda m: m["date"], reverse=True)
        ms = ms[:n]
        if not ms:
            return None
        gf = ga = w = btts = over = 0
        for m in ms:
            mine, theirs = (m["hg"], m["ag"]) if m["home"] == team else (m["ag"], m["hg"])
            gf += mine; ga += theirs; w += mine > theirs
            btts += (m["hg"] > 0 and m["ag"] > 0); over += (m["hg"] + m["ag"] > 2)
        k = len(ms)
        return {"n": k, "gf": gf / k, "ga": ga / k, "wins": w, "btts_pct": 100 * btts / k, "over25_pct": 100 * over / k,
                "att": self.att.get(team), "def": self.dfn.get(team)}
