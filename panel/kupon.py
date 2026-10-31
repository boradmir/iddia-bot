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


def data():
    return {"coupons": coupons(), "alerts": alerts(), "results": results()}
