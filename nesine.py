"""Modül 1 – Nesine bülteni: maçları ve 3 marketi (MS, Alt/Üst 2.5, KG) okur.

Gerçek veriyle doğrulanmış alanlar (28.10.2026):
  sg.EA[]  : etkinlikler. TYPE 1 = futbol, -1/-2 = uzun vadeli ("Şampiyon Kim Olur") → atlanır.
  C        : Nesine maç kodu          HN / AN : ev / deplasman takım adı
  ESD      : başlama (epoch ms)       LC      : lig kodu (sg.LA[].LID ile eşleşir, adı LA[].N)
  EMBS     : maçın min. bahis sayısı  MA[]    : marketler
  Markette : MTID tip, MBS min bahis sayısı, SOV barem, OCA [{N: sonuç no, O: oran}]
  Market isimleri bültende YOK; MTID'ler oran yapısından çıkarıldı (inspect_bulten.py):
    MTID 1  = Maç Sonucu   N1=1  N2=X  N3=2
    MTID 12 = Alt/Üst 2.5  N1=Alt N2=Üst   (SOV 2.5)
    MTID 38 = KG Var/Yok   N1=Var N2=Yok
  Oran 1.0 = kapalı/oynanmaz sayılır.
"""
import json, sys, time, urllib.request
from datetime import datetime, timezone

URL = "https://cdnbulten.nesine.com/api/bulten/getprebultenfull"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.nesine.com/", "Accept-Encoding": "identity"}

MT_MS, MT_OU25, MT_KG = 1, 12, 38
OUTCOME_NAMES = {MT_MS: {1: "1", 2: "X", 3: "2"}, MT_OU25: {1: "Alt", 2: "Üst"}, MT_KG: {1: "Var", 2: "Yok"}}
MARKET_NAMES = {MT_MS: "MS", MT_OU25: "AU25", MT_KG: "KG"}

# Hedef ligler: Nesine LID → The Odds API spor anahtarı
LEAGUES = {
    584: "soccer_turkey_super_league",
    43: "soccer_epl",
    129: "soccer_spain_la_liga",
    143: "soccer_italy_serie_a",
    45: "soccer_germany_bundesliga",
    381: "soccer_france_ligue_one",
    10014: "soccer_uefa_champs_league", 46194: "soccer_uefa_champs_league",
    10015: "soccer_uefa_europa_league", 46195: "soccer_uefa_europa_league",
    23986: "soccer_uefa_europa_conference_league",
    10004: "soccer_uefa_nations_league", 1407: "soccer_uefa_nations_league",
}


def fetch(save_path="data/bulten.json"):
    req = urllib.request.Request(URL, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
    if save_path:
        with open(save_path, "wb") as f:
            f.write(raw)
    return json.loads(raw)


def parse(data, only_target_leagues=True):
    """Bülten JSON'unu sade maç listesine çevirir."""
    sg = data["sg"]
    league_names = {l["LID"]: l["N"] for l in sg.get("LA", [])}
    matches = []
    for e in sg["EA"]:
        if e.get("TYPE") != 1 or "HN" not in e:
            continue  # futbol değil veya uzun vadeli bahis
        if only_target_leagues and e.get("LC") not in LEAGUES:
            continue
        markets = {}
        for m in e.get("MA", []):
            mt = m.get("MTID")
            if mt not in OUTCOME_NAMES:
                continue
            if mt == MT_OU25 and m.get("SOV") != 2.5:
                continue
            odds = {OUTCOME_NAMES[mt][o["N"]]: o["O"] for o in m["OCA"] if o["N"] in OUTCOME_NAMES[mt] and o["O"] > 1}
            if len(odds) == len(OUTCOME_NAMES[mt]):
                markets[MARKET_NAMES[mt]] = {"odds": odds, "mbs": m.get("MBS")}
        matches.append({
            "code": e["C"], "home": e["HN"], "away": e["AN"],
            "start": datetime.fromtimestamp(e["ESD"] / 1000, tz=timezone.utc),
            "league_id": e.get("LC"), "league": league_names.get(e.get("LC"), str(e.get("LC"))),
            "sport_key": LEAGUES.get(e.get("LC")), "mbs": e.get("EMBS"), "markets": markets,
        })
    return matches


def save_snapshots(con, matches, fetched_at):
    """Nesine oranlarını zaman damgasıyla kaydeder (kendi geçmiş veri setimiz; backtest için şart)."""
    rows = []
    for m in matches:
        for mk, d in m["markets"].items():
            for outcome, price in d["odds"].items():
                rows.append((fetched_at, m["code"], m["start"].isoformat(), m["home"], m["away"], m["league"],
                             mk, outcome, price, max(m.get("mbs") or 1, d.get("mbs") or 1)))
    con.executemany("INSERT INTO nesine_snapshots (fetched_at,nesine_code,start,home,away,league,market,outcome,price,mbs) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    return len(rows)


def margin(odds):
    """Marketin kesinti oranı: Σ(1/oran) − 1. İddaa'da %7-18 arası."""
    return sum(1 / o for o in odds.values()) - 1


if __name__ == "__main__":
    use_cache = "--cache" in sys.argv
    if use_cache:
        data = json.load(open("data/bulten.json", encoding="utf-8"))
    else:
        t = time.time(); data = fetch(); print(f"Bülten indirildi ({time.time()-t:.1f} sn)")
    all_fb = parse(data, only_target_leagues=False)
    target = parse(data)
    print(f"Toplam futbol maçı: {len(all_fb)}  |  hedef liglerde: {len(target)}")
    by_league = {}
    for m in target:
        by_league.setdefault(m["league"], []).append(m)
    for lg, ms in sorted(by_league.items(), key=lambda x: -len(x[1])):
        full = sum(1 for m in ms if len(m["markets"]) == 3)
        print(f"  {lg}: {len(ms)} maç, {full} tanesinde 3 market de açık")
    print("\nÖrnek:")
    for m in target[:5]:
        local = m["start"].astimezone()
        mk = {k: v["odds"] for k, v in m["markets"].items()}
        print(f"  {local:%d.%m %H:%M} [{m['code']}] {m['home']} - {m['away']} MBS={m['mbs']} {mk}")
