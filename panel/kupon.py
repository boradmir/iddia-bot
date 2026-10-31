"""Kupon ve uyarılar ekranı: records/coupons (kilitlenen kuponlar ve puanları), records/alerts (gözcü fırsat uyarıları, kapanış CLV),
records/results (skorlar). Eskiden Pages sayfasında gösteriliyordu; hesaplama build_site ile aynı."""
import glob, json, os
from datetime import datetime, timezone, timedelta
import build_site

TR = timezone(timedelta(hours=3))
KIND_TR = getattr(build_site, "KIND_TR", {"safest": "En güvenli", "balanced": "Dengeli", "least_loss": "En az kayıp", "value": "Değer"})
PICK_SHORT = getattr(build_site, "PICK_SHORT", {})


def _read(pattern):
    try:
        return build_site.read_jsonl(pattern)
    except Exception:
        return []


def _t(s, day=False):
    try:
        d = datetime.fromisoformat(s).astimezone(TR)
        return d.strftime("%d.%m %H:%M") if day else d.strftime("%H:%M")
    except Exception:
        return s or ""


def coupons():
    rows = sorted(_read("records/coupons/*.jsonl"), key=lambda c: c["t"], reverse=True)
    settled = [c for c in rows if c.get("result") in ("won", "lost")]
    summary = []
    for kind in ("safest", "balanced", "least_loss", "value"):
        ks = [c for c in settled if c["kind"] == kind]
        if not ks:
            continue
        won = sum(1 for c in ks if c["result"] == "won")
        pnl = sum((c["odds"] - 1) if c["result"] == "won" else -1 for c in ks)
        summary.append({"kind": KIND_TR.get(kind, kind), "won": won, "total": len(ks), "pnl": round(pnl, 1)})
    items = []
    for c in rows[:40]:
        items.append({"no": c.get("no"), "kind": KIND_TR.get(c["kind"], c["kind"]), "n": c["n"], "odds": c["odds"], "prob": round(c["prob"] * 100),
                      "ev_pct": c.get("ev_pct"), "result": c.get("result"), "legs_hit": c.get("legs_hit", 0), "t": _t(c["t"], True),
                      "legs": [{"home": l["home"], "away": l["away"], "pick": PICK_SHORT.get((l["market"], l["pick"]), f"{l['market']} {l['pick']}"),
                                "start": _t(l["start"], True), "odds": l["odds"], "result": l.get("result"), "score": l.get("score")} for l in c["legs"]]})
    return {"summary": summary, "items": items, "total": len(rows), "settled": len(settled)}


def alerts():
    rows = sorted(_read("records/alerts/*.jsonl"), key=lambda a: a.get("t", ""), reverse=True)
    settled = [a for a in rows if a.get("result") in ("won", "lost")]
    stats = None
    if settled:
        pnl = sum((a["nesine_odds"] - 1) if a["result"] == "won" else -1 for a in settled)
        clvs = [a["clv_pct"] for a in settled if a.get("clv_pct") is not None]
        stats = {"settled": len(settled), "pnl": round(pnl, 1), "roi": round(100 * pnl / len(settled)), "clv_avg": round(sum(clvs) / len(clvs), 1) if clvs else None}
    items = [{"t": _t(a.get("t", ""), True), "home": a.get("home"), "away": a.get("away"), "pick": PICK_SHORT.get((a.get("market"), a.get("pick")), f"{a.get('market')} {a.get('pick')}"),
              "nesine": a.get("nesine_odds"), "fair": a.get("fair_odds"), "ev_pct": a.get("ev_pct"), "stake": a.get("stake"), "result": a.get("result"),
              "clv_pct": a.get("clv_pct")} for a in rows[:40]]
    return {"stats": stats, "items": items, "total": len(rows)}


def results(days=2):
    out = []
    for p in sorted(glob.glob("records/results/*.jsonl"))[-days:]:
        day = os.path.basename(p)[:10]
        for r in _read(p):
            out.append({"day": day, "home": r.get("home"), "away": r.get("away"), "score": f"{r.get('hg')}-{r.get('ag')}", "sport": r.get("sport")})
    return out[::-1]


def _pick_from_probs(mk, probs):
    if not probs:
        return None
    if mk == "MS":
        return max(probs, key=probs.get)
    if mk == "AU25":
        return "Üst" if probs.get("Üst", 0) >= 0.5 else "Alt"
    if mk == "KG":
        return "Var" if probs.get("Var", 0) >= 0.5 else "Yok"
    return None


def accuracy():
    """Tahmin isabeti: yapay zekâ analizlerinin pazar başına favori seçimi (ve piyasanın favorisi) gerçek sonuçla kıyaslanır;
    bot kuponu bacakları ve gözcü uyarıları seçim bazında sayılır. 'Tuttu/Toplam' biçiminde."""
    rows = _read("records/claude/*.jsonl")
    settled = [r for r in rows if isinstance(r.get("result"), dict) and r.get("blind") and not r.get("superseded")]
    per_market = {}      # (kaynak, pazar) → [tuttu, toplam]
    per_pick = {}        # (kaynak, pazar, seçim) → [tuttu, toplam]
    matches = []
    brier = {"ai": [], "market": []}
    for r in settled:
        bl, res, mk = r["blind"], r["result"], r.get("market") or {}
        ai_probs = {"MS": {"1": bl.get("p_home"), "X": bl.get("p_draw"), "2": bl.get("p_away")},
                    "AU25": {"Üst": bl.get("p_over25"), "Alt": 1 - bl["p_over25"]} if bl.get("p_over25") is not None else None,
                    "KG": {"Var": bl.get("p_btts"), "Yok": 1 - bl["p_btts"]} if bl.get("p_btts") is not None else None}
        row = {"home": r["home"], "away": r["away"], "day": (r.get("start") or "")[:10], "score": res.get("score"), "markets": {}}
        for m in ("MS", "AU25", "KG"):
            actual = res.get(m)
            if not actual:
                continue
            ap = _pick_from_probs(m, ai_probs.get(m)); pp = _pick_from_probs(m, mk.get(m))
            cell = {"actual": PICK_SHORT.get((m, actual), actual)}
            if ap:
                hit = ap == actual
                per_market.setdefault(("ai", m), [0, 0]); per_market[("ai", m)][0] += hit; per_market[("ai", m)][1] += 1
                per_pick.setdefault(("ai", m, ap), [0, 0]); per_pick[("ai", m, ap)][0] += hit; per_pick[("ai", m, ap)][1] += 1
                cell["ai"] = PICK_SHORT.get((m, ap), ap); cell["ai_hit"] = hit
            if pp:
                hit = pp == actual
                per_market.setdefault(("market", m), [0, 0]); per_market[("market", m)][0] += hit; per_market[("market", m)][1] += 1
                cell["market"] = PICK_SHORT.get((m, pp), pp); cell["market_hit"] = hit
            row["markets"][m] = cell
        for k, key in (("ai", "brier_claude"), ("market", "brier_market")):
            b = res.get(key) or {}
            if b.get("MS") is not None:
                brier[k].append(b["MS"])
        matches.append(row)
    # bot kuponu bacakları ve uyarılar (seçim bazında)
    for c in _read("records/coupons/*.jsonl"):
        for l in c.get("legs", []):
            if l.get("result") in ("won", "lost"):
                k = ("coupon", l["market"], l["pick"]); per_pick.setdefault(k, [0, 0]); per_pick[k][0] += l["result"] == "won"; per_pick[k][1] += 1
                km = ("coupon", l["market"]); per_market.setdefault(km, [0, 0]); per_market[km][0] += l["result"] == "won"; per_market[km][1] += 1
    for a in _read("records/alerts/*.jsonl"):
        if a.get("result") in ("won", "lost"):
            k = ("alert", a.get("market"), a.get("pick")); per_pick.setdefault(k, [0, 0]); per_pick[k][0] += a["result"] == "won"; per_pick[k][1] += 1
    MK = {"MS": "Maç sonucu", "AU25": "2,5 gol", "KG": "Karşılıklı gol"}
    SRC = {"ai": "Yapay zekâ favorisi", "market": "Piyasa favorisi", "coupon": "Bot kuponu bacağı", "alert": "Gözcü uyarısı"}
    def rowsof(d, keyf):
        out = []
        for k, (h, t) in sorted(d.items(), key=lambda kv: (kv[0][0], kv[0][1], str(kv[0][2:]))):
            out.append({**keyf(k), "hit": h, "total": t, "pct": round(100 * h / t) if t else None})
        return out
    return {"by_market": rowsof(per_market, lambda k: {"source": SRC.get(k[0], k[0]), "src": k[0], "market": MK.get(k[1], k[1])}),
            "by_pick": rowsof(per_pick, lambda k: {"source": SRC.get(k[0], k[0]), "src": k[0], "market": MK.get(k[1], k[1]), "pick": PICK_SHORT.get((k[1], k[2]), k[2])}),
            "matches": sorted(matches, key=lambda r: r["day"], reverse=True), "n_settled": len(settled),
            "brier": {k: round(sum(v) / len(v), 3) if v else None for k, v in brier.items()}}


def data():
    return {"coupons": coupons(), "alerts": alerts(), "results": results(), "accuracy": accuracy()}
