"""Modül 3 – Nesine maçı ↔ Odds API maçı eşleştirme (saat ±20 dk + takım adı benzerliği).

Kullanım: python match.py --show-matches [--cache]
  --cache : Nesine bültenini data/bulten.json'dan okur (yeniden indirmez).
Odds API'ye yalnızca bültende maçı olan ligler için istek atılır (kota koruması).
aliases tablosu (db) elle düzeltme içindir: nesine_name → api_name.
"""
import re, sys, unicodedata, json
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
import nesine, odds

NOISE = {"fc", "sk", "afc", "cf", "sc", "ac", "fk", "as", "ss", "cd", "club", "de", "the", "jk", "spor", "1907", "calcio"}
REPLACE = {"utd": "united", "st": "saint", "bb": "basaksehir"}


# Millî takımlar: Nesine Türkçe ad → ESPN/Pinnacle İngilizce ad (kelime bazlı; normalize sonrası, aksansız)
NATION_EN = {"turkiye": "turkey", "almanya": "germany", "fransa": "france", "ispanya": "spain", "ingiltere": "england", "italya": "italy",
             "portekiz": "portugal", "hollanda": "netherlands", "belcika": "belgium", "hirvatistan": "croatia", "isvicre": "switzerland",
             "avusturya": "austria", "polonya": "poland", "danimarka": "denmark", "isvec": "sweden", "norvec": "norway", "yunanistan": "greece",
             "iskocya": "scotland", "galler": "wales", "irlanda": "ireland", "cekya": "czechia", "macaristan": "hungary", "romanya": "romania",
             "sirbistan": "serbia", "ukrayna": "ukraine", "gurcistan": "georgia", "bosna": "bosnia", "hersek": "herzegovina", "karadag": "montenegro",
             "slovenya": "slovenia", "slovakya": "slovakia", "bulgaristan": "bulgaria", "kuzey": "north", "makedonya": "macedonia",
             "finlandiya": "finland", "izlanda": "iceland", "israil": "israel", "ermenistan": "armenia", "azerbaycan": "azerbaijan",
             "kazakistan": "kazakhstan", "letonya": "latvia", "litvanya": "lithuania", "estonya": "estonia", "luksemburg": "luxembourg",
             "arnavutluk": "albania", "kosova": "kosovo", "rusya": "russia", "brezilya": "brazil", "arjantin": "argentina", "meksika": "mexico",
             "japonya": "japan", "guney": "south", "kore": "korea", "misir": "egypt", "fas": "morocco", "cezayir": "algeria", "nijerya": "nigeria",
             "kamerun": "cameroon", "gana": "ghana", "kibris": "cyprus", "malta": "malta", "faroe": "faroe", "adalari": "islands"}


def normalize(name):
    s = name.lower().replace("ı", "i").replace("İ", "i")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    words = [NATION_EN.get(REPLACE.get(w, w), REPLACE.get(w, w)) for w in s.split() if w not in NOISE]
    return " ".join(words)


def similarity(a, b):
    a, b = normalize(a), normalize(b)
    if not a or not b:
        return 0.0
    seq = SequenceMatcher(None, a, b).ratio()
    # önek eşleşmesi: "D. Zagreb" ~ "Dinamo Zagreb" gibi kısaltmalar için kelime bazlı
    wa, wb = a.split(), b.split()
    hits = sum(1 for x in wa if any(y.startswith(x.rstrip(".")) or x.startswith(y) for y in wb))
    prefix = hits / max(len(wa), len(wb))
    return max(seq, prefix)


def match_all(nesine_matches, api_events, aliases=None, window_min=20):
    """Her Nesine maçı için en iyi Odds API maçını bulur. [(nesine, event|None, score)] döner."""
    aliases = aliases or {}
    now = datetime.now(timezone.utc)
    out = []
    for nm in nesine_matches:
        if nm["start"] < now:
            continue  # başlamış/bitmiş maç: oynanamaz, Odds API'de de yok
        best, best_score = None, 0.0
        home = aliases.get(nm["home"], nm["home"]); away = aliases.get(nm["away"], nm["away"])
        for ev in api_events:
            if ev.get("sport_key") != nm["sport_key"]:
                continue
            t = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00"))
            if abs((t - nm["start"]).total_seconds()) > window_min * 60:
                continue
            sh, sa = similarity(home, ev["home_team"]), similarity(away, ev["away_team"])
            if sh >= 0.4 and sa >= 0.4:
                score = (sh + sa) / 2
                if score >= 0.6 and score > best_score:
                    best, best_score = ev, score
        out.append((nm, best, best_score))
    return out


def save_matches(con, pairs):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for nm, ev, score in pairs:
        con.execute("INSERT OR REPLACE INTO matches (nesine_code,event_id,sport_key,nesine_home,nesine_away,api_home,api_away,start,score,method,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (nm["code"], ev["id"] if ev else None, nm["sport_key"], nm["home"], nm["away"],
                     ev["home_team"] if ev else None, ev["away_team"] if ev else None,
                     nm["start"].isoformat(), score if ev else None, "fuzzy" if ev else None, now))
    con.commit()


if __name__ == "__main__":
    use_cache = "--cache" in sys.argv
    data = json.load(open("data/bulten.json", encoding="utf-8")) if use_cache else nesine.fetch()
    nm = nesine.parse(data)
    sports = sorted({m["sport_key"] for m in nm if m["sport_key"]})
    print(f"Nesine hedef liglerde {len(nm)} maç, {len(sports)} lig için Odds API sorgulanıyor...")
    import db
    con = db.connect()
    aliases = dict(con.execute("SELECT nesine_name, api_name FROM aliases").fetchall())
    events = []
    remaining = None
    for s in sports:
        evs, remaining = odds.fetch(s)
        odds.save_snapshots(con, s, evs)
        events += evs
    pairs = match_all(nm, events, aliases)
    save_matches(con, pairs)
    matched = sum(1 for _, ev, _ in pairs if ev)
    print(f"\nEşleşme: {matched}/{len(pairs)} gelecek maç = %{100*matched/max(1,len(pairs)):.0f}   (kalan kota: {remaining})\n")
    if "--show-matches" in sys.argv:
        for m, ev, sc in sorted(pairs, key=lambda p: p[0]["start"]):
            t = m["start"].astimezone().strftime("%d.%m %H:%M")
            if ev:
                flag = "" if sc >= 0.8 else "  ⚠ isim eşleşmesini kontrol et"
                pin = odds.pinnacle_h2h(ev)
                print(f"✅ {t} {m['home']} - {m['away']}  →  {ev['home_team']} - {ev['away_team']}  (skor {sc:.2f}) Pinnacle={pin}{flag}")
            else:
                print(f"❌ {t} {m['home']} - {m['away']}  [{m['league']}]  eşleşmedi")
