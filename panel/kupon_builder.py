"""Kupon oluşturucu (yalnız panel, kişisel kullanım): önümüzdeki 48 saatin maçları, Nesine oranları ve üç kaynaktan ihtimal
(bizim yapay zekâ analizi, istatistik modeli, piyasa/Pinnacle); oyuncu 'gol atar' oranları + golcü istatistikleri (ESPN: sezon ve son 5 maç).
Kullanıcı seçer → kupon (toplam oran, kaynaklara göre tutma ihtimali, EV) → yapay zekâ kısa yorum. Kuponlar data/panel/kuponlarim.jsonl (yerel)."""
import glob, json, os, re, unicodedata
from datetime import datetime, timezone, timedelta
import build_site, match, odds, prob, value, clubs, nesine, espn, results

TR = timezone(timedelta(hours=3))
FILE = "data/panel/kuponlarim.jsonl"
PDIR = "data/panel/espn_players"
MARKETS = {"MS": ("1", "X", "2"), "AU25": ("Alt", "Üst"), "KG": ("Var", "Yok")}
PICK_TR = {("MS", "1"): "Ev", ("MS", "X"): "Beraberlik", ("MS", "2"): "Deplasman", ("AU25", "Alt"): "2,5 alt", ("AU25", "Üst"): "2,5 üst", ("KG", "Var"): "KG var", ("KG", "Yok"): "KG yok"}
_stats = None
_raw = {"t": 0, "data": None}


def _stats_model():
    global _stats
    if _stats is None:
        import stats
        try:
            _stats = stats.Stats().load()
        except Exception:
            _stats = False
    return _stats or None


def _bulletin():
    """Taze bülten (oyuncu pazarları için ham veri); 3 dk önbellek."""
    import time
    if time.time() - _raw["t"] > 180 or _raw["data"] is None:
        try:
            _raw["data"] = nesine.fetch(save_path=None); _raw["t"] = time.time()
        except Exception:
            if _raw["data"] is None and os.path.exists("data/bulten.json"):
                _raw["data"] = json.load(open("data/bulten.json", encoding="utf-8"))
    return _raw["data"]


def ai_index():
    out = {}
    for p in sorted(glob.glob("records/claude/*.jsonl")):
        for l in open(p, encoding="utf-8"):
            try:
                r = json.loads(l)
            except ValueError:
                continue
            bl = r.get("blind") or {}
            if bl.get("p_home") is not None and not r.get("superseded"):
                out[r["code"]] = {"MS": {"1": bl["p_home"], "X": bl["p_draw"], "2": bl["p_away"]},
                                  "AU25": {"Alt": 1 - bl["p_over25"], "Üst": bl["p_over25"]} if bl.get("p_over25") is not None else None,
                                  "KG": {"Var": bl["p_btts"], "Yok": 1 - bl["p_btts"]} if bl.get("p_btts") is not None else None,
                                  "hook": bl.get("hook"), "risk_short": bl.get("risk_short")}
    return out


def board(hours=48, only_tracked=True):
    """Seçilebilir maçlar ve pazar başına oran + ihtimaller; oyuncu gol oranları (varsa)."""
    data = _bulletin()
    nm_all = nesine.parse(data) if data else []
    now = datetime.now(timezone.utc)
    nm = [m for m in nm_all if now < m["start"] <= now + timedelta(hours=hours)]
    import stats as _st
    if only_tracked:
        nm = [m for m in nm if m.get("sport_key") in _st.LEAGUE_DIV or (m.get("sport_key") or "").startswith("soccer_uefa")]
    pgo = nesine.player_goal_odds(data) if data else {}
    events = build_site.pinnacle_events(build_site.read_jsonl("records/pinnacle/*.jsonl"))
    aliases = json.load(open("aliases.json", encoding="utf-8")) if os.path.exists("aliases.json") else {}
    ai = ai_index(); sm = _stats_model(); es = espn.load_all()
    out = []
    for m, ev, score in match.match_all(nm, events, aliases):
        pin = prob.market_probs(odds.pinnacle_h2h(ev), odds.pinnacle_totals(ev)) if ev and odds.pinnacle_h2h(ev) else {}
        sv = None
        if sm:
            try:
                v = sm.view(m); sv = v["probs"] if v else None
            except Exception:
                sv = None
        a = ai.get(m["code"]) or {}
        markets = {}
        for mk, picks in MARKETS.items():
            mo = (m.get("markets") or {}).get(mk, {}).get("odds") or {}
            if not mo:
                continue
            markets[mk] = {}
            for pk in picks:
                o = mo.get(pk)
                if o is None:
                    continue
                pp = (pin.get(mk) or {}).get(pk); sp = (sv or {}).get(mk, {}).get(pk) if sv else None; ap = (a.get(mk) or {}).get(pk) if a.get(mk) else None
                markets[mk][pk] = {"odds": o, "pin": round(pp * 100) if pp else None, "stat": round(sp * 100) if sp else None, "ai": round(ap * 100) if ap else None,
                                   "ev_pin": round(value.ev_pct(o, pp), 1) if pp else None}
        out.append({"code": m["code"], "home": m["home"], "away": m["away"], "league": m["league"], "sport": m.get("sport_key"),
                    "start": m["start"].astimezone(TR).strftime("%d.%m %H:%M"), "start_iso": m["start"].isoformat(), "tier": clubs.tier(m),
                    "analysis": bool(a), "hook": a.get("hook"), "markets": markets, "players_odds": pgo.get(m["code"], []),
                    "has_espn": m["code"] in es})
    out.sort(key=lambda x: (x["start_iso"], x["tier"]))
    return {"matches": out, "n": len(out), "t": datetime.now(TR).strftime("%H:%M")}


# ---------------- golcüler ----------------

def _norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]", "", s).strip()


def _same_player(a, b):
    na, nb = _norm(a).split(), _norm(b).split()
    if not na or not nb:
        return False
    return na[-1] == nb[-1] and (na[0][0] == nb[0][0] or len(na) == 1 or len(nb) == 1)


def _last5_goals(slug, team_id, day):
    """Takımın son 5 tamamlanmış maçında gol atanlar (ESPN keyEvents). Günlük önbellek."""
    os.makedirs(PDIR, exist_ok=True)
    cp = f"{PDIR}/{slug}_{team_id}_{day}.json"
    if os.path.exists(cp):
        return json.load(open(cp, encoding="utf-8"))
    out = {"games": [], "goals": {}}
    try:
        sch = espn._get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/teams/{team_id}/schedule")
        evs = [e for e in sch.get("events", []) if (e.get("competitions") or [{}])[0].get("status", {}).get("type", {}).get("completed")]
        evs.sort(key=lambda e: e.get("date", ""), reverse=True)
        for e in evs[:5]:
            s = espn._get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/summary?event={e['id']}")
            comp = (s.get("header") or {}).get("competitions", [{}])[0]
            score = " - ".join(f"{c.get('team', {}).get('abbreviation', '')} {c.get('score', '')}" for c in comp.get("competitors", []))
            g = []
            for k in s.get("keyEvents") or []:
                if "Goal" in (k.get("type", {}).get("text") or "") and "Own" not in (k.get("type", {}).get("text") or ""):
                    if str((k.get("team") or {}).get("id")) == str(team_id):
                        nm_ = ((k.get("participants") or [{}])[0].get("athlete") or {}).get("displayName")
                        if nm_:
                            g.append(nm_); out["goals"][nm_] = out["goals"].get(nm_, 0) + 1
            out["games"].append({"date": e.get("date", "")[:10], "name": e.get("name"), "score": score, "scorers": g})
    except Exception as ex:
        out["error"] = str(ex)[:120]
    json.dump(out, open(cp, "w", encoding="utf-8"), ensure_ascii=False)
    return out


def players(code):
    """Maçın golcüleri: takım başına ilk 3 (sezon gol), sezon istatistiği, son 5 maçta gol, Nesine 'gol atar' oranı."""
    code = int(code)
    es = espn.load_all(); r = es.get(code)
    b = next((x for x in board()["matches"] if x["code"] == code), None)
    podds = (b or {}).get("players_odds") or []
    if not r:
        return {"ok": True, "teams": [], "note": "ESPN verisi yok (gözcü maç gününde çeker)", "players_odds": podds}
    slug = results.ESPN.get(r.get("sport") or (b or {}).get("sport") or "", "tur.1")
    day = datetime.now(TR).strftime("%Y-%m-%d")
    teams_info = r.get("teams") or {}
    if not teams_info and r.get("event_id"):   # eski kayıt: takım kimliklerini ESPN özetinden al (günlük önbellek)
        cp = f"{PDIR}/teams_{code}.json"
        if os.path.exists(cp):
            teams_info = json.load(open(cp, encoding="utf-8"))
        else:
            try:
                s = espn._get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/summary?event={r['event_id']}")
                for c in ((s.get("header") or {}).get("competitions") or [{}])[0].get("competitors", []):
                    t = c.get("team") or {}
                    teams_info[t.get("displayName") or t.get("name")] = {"id": t.get("id"), "home": c.get("homeAway") == "home", "logo": t.get("logo")}
                os.makedirs(PDIR, exist_ok=True); json.dump(teams_info, open(cp, "w", encoding="utf-8"), ensure_ascii=False)
            except Exception:
                teams_info = {}
    teams = []
    for tname, tinfo in teams_info.items():
        tid = tinfo.get("id") or (re.findall(r"/(\d+)\.png", tinfo.get("logo") or "") or [None])[0]
        l5 = _last5_goals(slug, tid, day) if tid else {"games": [], "goals": {}}
        lk = next((k for k in (r.get("leaders") or {}) if _norm(k) == _norm(tname) or _norm(k) in _norm(tname) or _norm(tname) in _norm(k)), tname)
        leaders = sorted([x for x in (r.get("leaders") or {}).get(lk, []) if x.get("goals") is not None], key=lambda x: (-(x.get("goals") or 0), -(x.get("assists") or 0)))
        rows = []
        for x in leaders[:3]:
            o = next((p["odds"] for p in podds if _same_player(p["player"], x["player"])), None)
            rows.append({"player": x["player"], "goals": x.get("goals"), "assists": x.get("assists"), "matches": x.get("matches"), "shots": x.get("shots"),
                         "last5_goals": sum(v for k, v in l5["goals"].items() if _same_player(k, x["player"])), "odds": o})
        # son 5'te gol atıp sezon ilk 3'e girmeyenler (form golcüsü)
        for k, v in sorted(l5["goals"].items(), key=lambda kv: -kv[1])[:3]:
            if not any(_same_player(k, rr["player"]) for rr in rows):
                o = next((p["odds"] for p in podds if _same_player(p["player"], k)), None)
                rows.append({"player": k, "goals": None, "assists": None, "matches": None, "shots": None, "last5_goals": v, "odds": o, "form_only": True})
        teams.append({"team": tname, "home": tinfo.get("home"), "players": rows, "last5": l5.get("games", []), "error": l5.get("error")})
    return {"ok": True, "teams": teams, "players_odds": podds}


# ---------------- kuponlar ----------------

def _load():
    try:
        return [json.loads(l) for l in open(FILE, encoding="utf-8") if l.strip()]
    except FileNotFoundError:
        return []


def _save_all(rows):
    os.makedirs(os.path.dirname(FILE), exist_ok=True)
    with open(FILE, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def build(legs_in, stake_tl=None, name=None):
    """legs_in: [{code, market, pick}] (market GOL: pick = oyuncu adı) → zenginleştirilmiş kupon."""
    b = {x["code"]: x for x in board()["matches"]}
    legs = []
    for l in legs_in:
        m = b.get(int(l["code"]))
        if not m:
            raise ValueError(f"maç bültende yok: {l['code']}")
        if l["market"] == "GOL":
            po = next((p for p in m["players_odds"] if p["player"] == l["pick"]), None)
            if not po:
                raise ValueError(f"oyuncu oranı yok: {l['pick']}")
            legs.append({"code": m["code"], "home": m["home"], "away": m["away"], "league": m["league"], "start": m["start"], "start_iso": m["start_iso"],
                         "market": "GOL", "pick": l["pick"], "label": f"{l['pick']} gol atar", "odds": po["odds"], "pin": None, "stat": None, "ai": None, "hook": m.get("hook")})
            continue
        cell = (m["markets"].get(l["market"]) or {}).get(l["pick"])
        if not cell:
            raise ValueError(f"seçim yok: {l}")
        legs.append({"code": m["code"], "home": m["home"], "away": m["away"], "league": m["league"], "start": m["start"], "start_iso": m["start_iso"],
                     "market": l["market"], "pick": l["pick"], "label": PICK_TR.get((l["market"], l["pick"]), l["pick"]), "odds": cell["odds"],
                     "pin": cell["pin"], "stat": cell["stat"], "ai": cell["ai"], "hook": m.get("hook")})
    if not legs:
        raise ValueError("kuponda maç yok")
    total = 1.0
    for l in legs:
        total *= l["odds"]
    def pprod(key):
        ps = [l[key] / 100 for l in legs if l.get(key)]
        if len(ps) != len(legs):
            return None
        p = 1.0
        for x in ps:
            p *= x
        return round(p * 100, 1)
    probs = {"pin": pprod("pin"), "stat": pprod("stat"), "ai": pprod("ai")}
    ev = {k: round((total * v / 100 - 1) * 100, 1) for k, v in probs.items() if v is not None}
    rows = _load()
    cid = (max((r["id"] for r in rows), default=0) + 1)
    c = {"id": cid, "name": name or f"Kupon #{cid}", "t": datetime.now(timezone.utc).isoformat(timespec="seconds"), "legs": legs, "n": len(legs),
         "odds": round(total, 2), "probs": probs, "ev": ev, "stake_tl": float(stake_tl) if stake_tl else None, "review": None, "result": None}
    rows.append(c); _save_all(rows)
    return c


def review(cid, log):
    """Yapay zekâ kupon yorumu (web aramalı; kısa). Maliyet kayda yazılır."""
    import claude_check
    rows = _load()
    c = next((r for r in rows if r["id"] == int(cid)), None)
    if not c:
        raise ValueError("kupon yok")
    log(f"Yorum isteniyor: {c['name']} ({c['n']} maç, oran {c['odds']})")
    res = claude_check.coupon_review(c)
    c["review"] = {"t": datetime.now(timezone.utc).isoformat(timespec="seconds"), **res}
    _save_all(rows)
    log(f"Yorum geldi (${res.get('cost_usd')}): {res.get('comment', '')[:200]}")
    return c["review"]


def settle():
    """records/results ile bacakları puanla (MS/AU25/KG; GOL bacağı skordan bilinemez, bekler)."""
    rows = _load()
    if not rows:
        return 0
    res = {}
    for p in glob.glob("records/results/*.jsonl"):
        for l in open(p, encoding="utf-8"):
            try:
                r = json.loads(l)
            except ValueError:
                continue
            res[(r.get("home", "").lower(), r.get("away", "").lower())] = r
    n = 0
    for c in rows:
        if c.get("result"):
            continue
        hits = 0; pending = False
        for l in c["legs"]:
            if l.get("result"):
                hits += l["result"] == "won"; continue
            r = res.get((l["home"].lower(), l["away"].lower()))
            if not r or r.get("hg") is None or l["market"] == "GOL":
                pending = True; continue
            hg, ag = int(r["hg"]), int(r["ag"])
            won = {("MS", "1"): hg > ag, ("MS", "X"): hg == ag, ("MS", "2"): hg < ag, ("AU25", "Alt"): hg + ag < 3, ("AU25", "Üst"): hg + ag > 2,
                   ("KG", "Var"): hg > 0 and ag > 0, ("KG", "Yok"): not (hg > 0 and ag > 0)}[(l["market"], l["pick"])]
            l["result"] = "won" if won else "lost"; l["score"] = f"{hg}-{ag}"; hits += won; n += 1
        if any(l.get("result") == "lost" for l in c["legs"]):
            c["result"] = "lost"
        elif not pending and hits == c["n"]:
            c["result"] = "won"
        c["legs_hit"] = hits
    _save_all(rows)
    return n


def list_coupons(limit=40):
    settle()
    rows = _load()
    for c in rows:
        c["when"] = datetime.fromisoformat(c["t"]).astimezone(TR).strftime("%d.%m %H:%M")
    return rows[::-1][:limit]


def delete(cid):
    rows = [r for r in _load() if r["id"] != int(cid)]
    _save_all(rows)
