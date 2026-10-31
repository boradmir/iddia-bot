"""Kademeler sayfası: kulüp/millî takım öncelik listeleri (records/clubs.json). Görüntü için koddaki adlar (büyük harf başlangıçlı)
yerine Nesine bültenindeki asıl yazımlar önerilir; kayıt küçük harfle yapılır (clubs.team_tier küçük harf karşılaştırır)."""
import json, os
import clubs, build_site

FILE = clubs.FILE


def _bulletin_names():
    try:
        rows = build_site.recent_nesine_rows(); _, last = build_site.recent_snapshot(rows)
        names = set()
        for m in build_site.nesine_matches(last):
            names.add(m["home"]); names.add(m["away"])
        return sorted(names, key=lambda s: s.lower())
    except Exception:
        return []


def _display(names, bulletin):
    """Küçük harfli kayıt → bültendeki yazım (varsa)."""
    by = {b.lower().replace("i̇", "i"): b for b in bulletin}
    return [by.get(n, n.title() if n.islower() else n) for n in sorted(names)]


def data():
    bulletin = _bulletin_names()
    tiers = {"0": _display(clubs.TIER0, bulletin), "1": _display(clubs.TIER1, bulletin), "2": _display(clubs.TIER2, bulletin)}
    listed = {n.lower() for t in tiers.values() for n in t}
    return {"ok": True, "tiers": tiers, "analyze_max_tier": clubs.ANALYZE_MAX_TIER, "max_per_day": int(os.environ.get("CLAUDE_MAX_PER_DAY", "3")),
            "suggestions": [b for b in bulletin if b.lower() not in listed], "file": FILE, "from_file": os.path.exists(FILE)}


def save(tiers, analyze_max_tier=None):
    d = {"tiers": {k: sorted({x.strip() for x in (tiers.get(k) or []) if x and x.strip()}, key=str.lower) for k in ("0", "1", "2")},
         "analyze_max_tier": int(analyze_max_tier) if analyze_max_tier is not None else clubs.ANALYZE_MAX_TIER}
    os.makedirs(os.path.dirname(FILE), exist_ok=True)
    json.dump(d, open(FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    clubs._load_file()
    return d
