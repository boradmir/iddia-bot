"""Puanlama: uyarıları (records/alerts) ve kilitlenen kuponları (records/coupons) maç sonuçlarıyla eşler.

Eşleme: aynı lig (sport), başlama saati ±3 saat, iki takım adı benzerliği ≥0.6 (match.similarity).
Bahis değerlendirme: MS 1/X/2 · AU25 Alt/Üst (toplam gol > 2 → Üst) · KG Var/Yok (ikisi de gol → Var).
Kupon: tüm bacaklar tuttu → "won"; herhangi biri tutmadı → "lost"; eksik sonuç → bekler.

Kullanım: python settle.py
"""
import glob, json
from datetime import datetime, timedelta, timezone
import match, results

ALERT_GLOB = "records/alerts/*.jsonl"
COUPON_GLOB = "records/coupons/*.jsonl"


def read(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def write(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def find_result(res_rows, sport, start, home, away):
    start = datetime.fromisoformat(start)
    best, score = None, 0.0
    for r in res_rows:
        if r["sport"] != sport:
            continue
        d = datetime.fromisoformat(r["date"].replace("Z", "+00:00"))
        if abs((d - start).total_seconds()) > 3 * 3600:
            continue
        s = (match.similarity(home, r["home"]) + match.similarity(away, r["away"])) / 2
        if s > score and match.similarity(home, r["home"]) >= 0.5 and match.similarity(away, r["away"]) >= 0.5:
            best, score = r, s
    return best if score >= 0.6 else None


def judge(market, pick, hg, ag):
    if market == "MS":
        actual = "1" if hg > ag else "2" if hg < ag else "X"
        return "won" if pick == actual else "lost"
    if market == "AU25":
        return "won" if (pick == "Üst") == (hg + ag > 2) else "lost"
    if market == "KG":
        return "won" if (pick == "Var") == (hg > 0 and ag > 0) else "lost"
    return None


def settle_alerts(res_rows):
    n = 0
    for path in glob.glob(ALERT_GLOB):
        rows = read(path); changed = False
        for a in rows:
            if a.get("result"):
                continue
            r = find_result(res_rows, a.get("sport"), a["start"], a["home"], a["away"])
            if r:
                a["result"] = judge(a["market"], a["pick"], r["hg"], r["ag"])
                a["score"] = f'{r["hg"]}-{r["ag"]}'
                a["settled_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                changed = True; n += 1
        if changed:
            write(path, rows)
    return n


def settle_coupons(res_rows):
    n = 0
    for path in glob.glob(COUPON_GLOB):
        rows = read(path); changed = False
        for c in rows:
            if c.get("result"):
                continue
            hits, pending, lost = 0, 0, False
            for leg in c["legs"]:
                if not leg.get("result"):
                    r = find_result(res_rows, leg["sport"], leg["start"], leg["home"], leg["away"])
                    if r:
                        leg["result"] = judge(leg["market"], leg["pick"], r["hg"], r["ag"]); leg["score"] = f'{r["hg"]}-{r["ag"]}'
                        changed = True
                if leg.get("result") == "won":
                    hits += 1
                elif leg.get("result") == "lost":
                    lost = True
                else:
                    pending += 1
            c["legs_hit"] = hits
            if lost:
                c["result"] = "lost"
            elif pending == 0:
                c["result"] = "won"
            if c.get("result"):
                c["settled_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds"); changed = True; n += 1
        if changed:
            write(path, rows)
    return n


def _brier(probs, actual):
    """probs: {sonuç: p}, actual: gerçekleşen sonuç adı → Brier (küçük = iyi)."""
    return sum((p - (1.0 if k == actual else 0.0)) ** 2 for k, p in probs.items())


def settle_claude(res_rows):
    """Claude'un kör tahminlerini ve o anki piyasa ihtimallerini aynı sonuçla puanlar (kalibrasyon ölçümü)."""
    n = 0
    for path in glob.glob("records/claude/*.jsonl"):
        rows = read(path); changed = False
        for c in rows:
            if c.get("result") or not c.get("blind"):
                continue
            r = find_result(res_rows, c.get("sport"), c["start"], c["home"], c["away"])
            if not r:
                continue
            hg, ag = r["hg"], r["ag"]
            ms = "1" if hg > ag else "2" if hg < ag else "X"
            ou = "Üst" if hg + ag > 2 else "Alt"
            kg = "Var" if (hg > 0 and ag > 0) else "Yok"
            bl = c["blind"]
            cl = {"MS": {"1": bl["p_home"], "X": bl["p_draw"], "2": bl["p_away"]},
                  "AU25": {"Üst": bl["p_over25"], "Alt": 1 - bl["p_over25"]}, "KG": {"Var": bl["p_btts"], "Yok": 1 - bl["p_btts"]}}
            mk = c.get("market") or {}
            c["result"] = {"score": f"{hg}-{ag}", "MS": ms, "AU25": ou, "KG": kg,
                           "brier_claude": {k: round(_brier(cl[k], a), 4) for k, a in (("MS", ms), ("AU25", ou), ("KG", kg))},
                           "brier_market": {k: round(_brier(mk[k], a), 4) for k, a in (("MS", ms), ("AU25", ou), ("KG", kg)) if k in mk}}
            c["settled_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            changed = True; n += 1
        if changed:
            write(path, rows)
    return n


def main():
    res = results.load_all()
    print(f"Sonuç havuzu: {len(res)} maç")
    print(f"Puanlanan uyarı: {settle_alerts(res)}  |  puanlanan kupon: {settle_coupons(res)}  |  puanlanan Claude tahmini: {settle_claude(res)}")


if __name__ == "__main__":
    main()
