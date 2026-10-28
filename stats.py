"""Görüş 2 için veri köprüsü: football-data.co.uk CSV'leri → model.Model (lig başına) + Nesine takım adı eşlemesi.

Lig eşlemesi Odds API spor anahtarı → football-data Div (T1, E0, SP1, I1, D1, F1). Avrupa kupaları için veri yok → istatistik görüşü boş.

Kullanım:
  s = Stats(); s.load()
  s.view(nesine_match) → {"probs": {...}, "home_form": {...}, "away_form": {...}, "names": (fd_home, fd_away)} | None
"""
import csv, glob, json, os
from datetime import datetime
import match, model

LEAGUE_DIV = {"soccer_turkey_super_league": "T1", "soccer_epl": "E0", "soccer_spain_la_liga": "SP1",
              "soccer_italy_serie_a": "I1", "soccer_germany_bundesliga": "D1", "soccer_france_ligue_one": "F1"}
ALIAS_FILE = "fd_aliases.json"


def load_fd(div):
    rows = []
    for path in sorted(glob.glob(f"records/fd/{div}_*.csv")):
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    rows.append({"date": datetime.strptime(r["Date"], "%d/%m/%Y"), "home": r["HomeTeam"], "away": r["AwayTeam"],
                                 "hg": int(r["FTHG"]), "ag": int(r["FTAG"])})
                except (ValueError, KeyError):
                    continue
    return rows


class Stats:
    def __init__(self):
        self.models = {}
        self.teams = {}
        self.aliases = json.load(open(ALIAS_FILE, encoding="utf-8")) if os.path.exists(ALIAS_FILE) else {}

    def load(self, as_of=None):
        as_of = as_of or datetime.now()
        for div in set(LEAGUE_DIV.values()):
            rows = load_fd(div)
            if not rows:
                continue
            m = model.Model().fit(rows, as_of=as_of)
            self.models[div] = m
            self.teams[div] = sorted(m.att)
        return self

    def fd_name(self, div, nesine_name):
        """Nesine takım adını football-data adına çevirir (alias → benzerlik ≥0.6)."""
        if nesine_name in self.aliases:
            return self.aliases[nesine_name]
        best, score = None, 0.0
        for t in self.teams.get(div, []):
            s = match.similarity(nesine_name, t)
            if s > score:
                best, score = t, s
        return best if score >= 0.6 else None

    def view(self, nm):
        div = LEAGUE_DIV.get(nm.get("sport_key"))
        if not div or div not in self.models:
            return None
        h, a = self.fd_name(div, nm["home"]), self.fd_name(div, nm["away"])
        if not h or not a:
            return None
        m = self.models[div]
        probs = m.predict(h, a)
        if not probs:
            return None
        return {"probs": probs, "home_form": m.form(h), "away_form": m.form(a), "names": (h, a)}


if __name__ == "__main__":
    s = Stats().load()
    for div, m in s.models.items():
        print(f"{div}: {len(m.matches)} maç, {len(m.att)} takım, ev gol ort {m.base_home:.2f}, dep {m.base_away:.2f}")
