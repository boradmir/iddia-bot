"""Haftalık puan durumu karuseli: takip edilen beş ligin tablosu (ESPN), kapak + lig başına bir kart (1080×1350).
Pazartesi 12:00 TSİ bekçi yayınlar (keeper.maybe_standings). Kartlar docs/social/puan/<hafta>/, anlık görüntü records/standings/<hafta>.json
(bir sonraki hafta sıra değişimi için). Bahis içeriği yok; dipnot aynı.
Kullanım: python standings.py            → kartları üret (yerelde önizleme için de)
          python standings.py --post     → Pages'te görseller yayına girince Instagram'a karusel gönder
          python standings.py --dry      → gönderme, açıklamayı yaz
"""
import json, os, sys, glob, shutil
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageDraw
import config, espn, social, instagram, logo, control

TR = timezone(timedelta(hours=3))
LEAGUES = [("soccer_turkey_super_league", "tur.1", "Süper Lig", "#SüperLig"),
           ("soccer_epl", "eng.1", "Premier Lig", "#PremierLeague"),
           ("soccer_spain_la_liga", "esp.1", "La Liga", "#LaLiga"),
           ("soccer_italy_serie_a", "ita.1", "Serie A", "#SerieA"),
           ("soccer_germany_bundesliga", "ger.1", "Bundesliga", "#Bundesliga")]
OUT = "docs/social/puan"
REC = "records/standings"
W, H = social.W, social.H
TEAM_TR = {"Bayern Munich": "Bayern Münih", "Internazionale": "Inter", "Borussia Dortmund": "Dortmund", "Manchester City": "Manchester City",
           "Atlético Madrid": "Atlético Madrid", "Fenerbahce": "Fenerbahçe", "Besiktas": "Beşiktaş", "Basaksehir": "Başakşehir"}
# Kart teması (STANDINGS_STYLE ortam değişkeni ya da --style): green (analiz kartlarıyla aynı), cream (açık zemin), navy (lacivert)
STYLES = {
    "green": {"light": False, "bg": None, "title": social.CREAM, "accent": social.YELLOW, "text": social.WHITE, "muted": social.PALE, "head": social.MUTED,
              "pts": social.YELLOW, "line": (60, 95, 78), "foot": (170, 190, 180), "motif": "pitch"},
    "cream": {"light": True, "bg": (247, 243, 233), "title": (11, 42, 31), "accent": (176, 118, 0), "text": (20, 38, 31), "muted": (110, 122, 115), "head": (125, 138, 131),
              "pts": (11, 42, 31), "line": (220, 214, 200), "foot": (125, 138, 131), "motif": None},
    "navy": {"light": False, "bg": ((8, 20, 54), (16, 36, 92)), "title": social.CREAM, "accent": social.YELLOW, "text": social.WHITE, "muted": (190, 200, 225), "head": (150, 165, 200),
             "pts": social.YELLOW, "line": (60, 80, 130), "foot": (170, 185, 215), "motif": "stars"},
}
STYLE = os.environ.get("STANDINGS_STYLE", "green")


def pal():
    return STYLES.get(STYLE, STYLES["green"])


def canvas():
    p = pal()
    if p["light"]:
        return Image.new("RGB", (W, H), p["bg"])
    if p["bg"] is None:
        return social.pitch_background(social.THEMES["default"])
    th = {"bg": p["bg"][0], "bg2": p["bg"][1], "motif": p["motif"]}
    return social.pitch_background(th)


def dark_mark(h):
    """Göz işaretinin açık zemin sürümü: kemik rengi pikseller koyu yeşile boyanır, sarı göz bebeği kalır."""
    img = logo.mark_image(h).copy(); px = img.load()
    for y in range(img.height):
        for x in range(img.width):
            r, g, b, a = px[x, y]
            if a and not (r > 200 and g > 170 and b < 140):
                px[x, y] = (11, 42, 31, a)
    return img


def topbar(d, img, label):
    p = pal()
    if not p["light"]:
        social.topbar(d, label); return
    social.text(d, (60, 50), social.tr_upper(label), social.font("displaysemi", 30), p["accent"])
    social.text(d, (W - 60, 50), social.HANDLE, social.font("semi", 26), p["text"], anchor="ra")
    hw = social.font("semi", 26).getlength(social.HANDLE)
    mk = dark_mark(54)
    img.paste(mk, (int(W - 60 - hw - 14 - mk.width), 62 - mk.height // 2), mk)


NOTE_TR = {"Champions League": "Şampiyonlar Ligi", "Europa League": "Avrupa Ligi", "Conference League": "Konferans Ligi",
           "Relegation": "Küme düşme", "Relegation Playoff": "Küme düşme play-off", "Promotion": "Yükselme",
           "Europa Conference League": "Konferans Ligi", "Champions League qualifying": "ŞL eleme", "Europa League qualifying": "AL eleme",
           "Conference League qualifying": "KL eleme", "Europa Conference League qualifying": "KL eleme", "Relegation playoff": "Küme düşme play-off", "Relegated": "Küme düşme", "Promotion playoff": "Yükselme play-off"}
SHORT_TR = {"Besiktas": "Beşiktaş", "Fenerbahce": "Fenerbahçe", "Goztepe": "Göztepe", "Kasimpasa": "Kasımpaşa", "Istanbul BB": "Başakşehir",
            "Genclerbirli": "Gençlerbirliği", "Genclerbirligi": "Gençlerbirliği", "Eyupspor": "Eyüpspor", "Caykur Rizespor": "Rizespor", "Erzurum": "Erzurumspor",
            "Gaziantep": "Gaziantep FK", "Spurs": "Tottenham", "Nottm Forest": "Nott. Forest", "C Palace": "Crystal Palace", "Bayern Munich": "Bayern Münih",
            "Internazionale": "Inter", "Dortmund": "Dortmund", "Atlético Madrid": "Atlético", "Athletic Club": "Athletic Bilbao", "Real Sociedad": "R. Sociedad",
            "Borussia Dortmund": "Dortmund", "Bayer Leverkusen": "Leverkusen", "Eintracht Frankfurt": "Frankfurt", "Mönchengladbach": "M'gladbach"}


def week_key(now=None):
    now = (now or datetime.now(TR)).astimezone(TR)
    iso = now.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def fetch(slug):
    d = espn._get(f"https://site.api.espn.com/apis/v2/sports/soccer/{slug}/standings")
    ch = d["children"][0] if d.get("children") else d
    rows = []
    for e in ch["standings"]["entries"]:
        st = {s["name"]: s.get("displayValue", "") for s in e["stats"]}
        note = e.get("note") or {}
        rows.append({"rank": int(st.get("rank") or len(rows) + 1), "team": e["team"]["displayName"], "short": e["team"].get("shortDisplayName") or e["team"]["displayName"],
                     "logo": (e["team"].get("logos") or [{}])[0].get("href"), "gp": st.get("gamesPlayed", ""), "w": st.get("wins", ""), "d": st.get("ties", ""),
                     "l": st.get("losses", ""), "gf": st.get("pointsFor", ""), "ga": st.get("pointsAgainst", ""), "gd": st.get("pointDifferential", ""),
                     "pts": st.get("points", ""), "note": note.get("description"), "note_color": note.get("color")})
    rows.sort(key=lambda r: r["rank"])
    return rows


def load_prev(week):
    """Önceki haftaların en yenisi (sıra değişimi için)."""
    files = sorted(glob.glob(f"{REC}/*.json"))
    files = [f for f in files if os.path.basename(f)[:-5] < week]
    if not files:
        return {}
    return json.load(open(files[-1], encoding="utf-8"))


def collect(week):
    data = {}
    for sport, slug, name, tag in LEAGUES:
        try:
            data[sport] = fetch(slug)
        except Exception as e:
            print(f"{name}: puan durumu alınamadı ({e})")
    os.makedirs(REC, exist_ok=True)
    json.dump({"week": week, "t": datetime.now(timezone.utc).isoformat(timespec="seconds"), "leagues": data},
              open(f"{REC}/{week}.json", "w", encoding="utf-8"), ensure_ascii=False)
    return data


# ----------------------------------------------------------------- kartlar

def _hex(c, default):
    try:
        c = c.lstrip("#"); return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return default


def cover_card(week, names, path, monday_note):
    p = pal()
    img = canvas(); d = ImageDraw.Draw(img)
    topbar(d, img, "Haftalık puan durumu")
    now = datetime.now(TR)
    social.text(d, (60, 300), "PUAN", social.font("display", 230), p["title"])
    social.text(d, (60, 505), "DURUMU", social.font("display", 230), p["accent"] if not p["light"] else social.YELLOW)
    social.text(d, (60, 770), f"{social.tr_date(now)} itibarıyla", social.font("semi", 34), p["muted"])
    y = 850
    for n in names:
        d.ellipse((60, y + 14, 76, y + 30), fill=social.YELLOW)
        social.text(d, (96, y), n, social.font("semi", 40), p["text"]); y += 58
    social.text(d, (60, H - 130), "Kaydırın → beş lig, beş tablo. " + monday_note, social.font("body", 26), p["muted"])
    light_footer(d)
    social.save(img, path)


def league_card(name, rows, prev_rows, path, monday_note):
    p = pal()
    img = canvas(); d = ImageDraw.Draw(img)
    topbar(d, img, "Puan durumu")
    social.text(d, (60, 100), name, social.font("display", 84), p["title"])
    md = matchday(rows)
    social.text(d, (W - 60, 112), f"{md}. hafta sonrası" if md else "", social.font("displaysemi", 40), p["accent"], anchor="ra")
    social.text(d, (W - 60, 160), datetime.now(TR).strftime("%d.%m.%Y"), social.font("semi", 26), p["muted"], anchor="ra")
    prev_rank = {r["team"]: r["rank"] for r in (prev_rows or [])}
    n = len(rows)
    top, bottom = 215, H - 140
    row_h = min(56, (bottom - top - 40) // max(n, 1))
    f_h = social.font("semi", 22); f_r = social.font("semi", 30); f_t = social.font("semi", 31); f_n = social.font("body", 28); f_p = social.font("display", 38)
    cols = {"O": 640, "G": 700, "B": 760, "M": 820, "Av": 900, "P": 1000}
    for k, x in cols.items():
        social.text(d, (x, top), k, f_h, p["head"], anchor="ma")
    y = top + 36
    legend = {}
    for r in rows:
        if r.get("note"):
            col = _hex(r.get("note_color"), social.SIGNAL)
            d.rectangle((44, y + 6, 50, y + row_h - 6), fill=col)
            legend.setdefault(NOTE_TR.get(r["note"], r["note"]), col)
        social.text(d, (92, y + row_h // 2), str(r["rank"]), f_r, p["accent"] if r["rank"] <= 4 else p["muted"], anchor="rm")
        crest = espn.team_logo(r.get("logo"), row_h - 14)
        if crest:
            img.paste(crest, (112, y + 7), crest)
        pr = prev_rank.get(r["team"])
        arrow = ""
        if pr and pr != r["rank"]:
            arrow = "▲" if r["rank"] < pr else "▼"
        social.text(d, (168, y + row_h // 2), social.fit(SHORT_TR.get(r["short"], r["short"]), f_t, 400), f_t, p["text"], anchor="lm")
        if arrow:
            social.text(d, (580, y + row_h // 2), arrow, social.font("semi", 22), social.SIGNAL if arrow == "▲" else social.RED, anchor="mm")
        for k, key in (("O", "gp"), ("G", "w"), ("B", "d"), ("M", "l"), ("Av", "gd")):
            social.text(d, (cols[k], y + row_h // 2), str(r.get(key, "")), f_n, p["muted"], anchor="mm")
        social.text(d, (cols["P"], y + row_h // 2), str(r.get("pts", "")), f_p, p["pts"], anchor="mm")
        y += row_h
    # efsane (renk çizgileri ne anlama geliyor); sığmazsa ikinci satıra geçer
    fl = social.font("body", 21)
    ly = H - 108; lx = 60
    for label, col in list(legend.items())[:6]:
        w = int(fl.getlength(label)) + 44
        if lx + w > W - 60:
            lx = 60; ly -= 28
        d.rectangle((lx, ly + 4, lx + 10, ly + 22), fill=col)
        social.text(d, (lx + 18, ly), label, fl, p["muted"]); lx += w
    if monday_note:
        social.text(d, (W - 60, 175), monday_note, fl, p["head"], anchor="ra")
    light_footer(d)
    social.save(img, path)


def matchday(rows):
    """Ligin haftası: en çok maç oynayan takımın maç sayısı (ESPN hafta numarası vermiyor)."""
    try:
        return max(int(r.get("gp") or 0) for r in rows)
    except ValueError:
        return None


def light_footer(d):
    """Puan durumu kartlarında 18+ dipnotu yok (bahis içeriği yok); yalnız ince bir ritim satırı."""
    p = pal(); f = social.font("body", 22)
    d.line((60, H - 70, W - 60, H - 70), fill=p["line"], width=2)
    social.text(d, (60, H - 54), "Her pazartesi 12:00 güncel tablo", f, p["foot"])
    social.text(d, (W - 60, H - 54), social.HANDLE, f, p["foot"], anchor="ra")


def monday_note_for(now=None):
    now = (now or datetime.now(TR)).astimezone(TR)
    return "Pazartesi maçları öncesi" if now.weekday() == 0 else ""


def build(week=None):
    week = week or week_key()
    data = collect(week)
    prev = load_prev(week).get("leagues", {})
    out_dir = f"{OUT}/{week}"; os.makedirs(out_dir, exist_ok=True)
    note = monday_note_for()
    names = [name for sport, _, name, _ in LEAGUES if sport in data]
    paths = [f"{out_dir}/00_kapak.jpg"]
    cover_card(week, names, paths[0], note)
    for i, (sport, slug, name, tag) in enumerate(LEAGUES, 1):
        if sport not in data:
            continue
        p = f"{out_dir}/{i:02d}_{slug.replace('.', '_')}.jpg"
        league_card(name, data[sport], prev.get(sport), p, note); paths.append(p)
    # eski haftalar: son 3 kalsın
    for old in sorted(glob.glob(f"{OUT}/*"))[:-3]:
        shutil.rmtree(old, ignore_errors=True)
    print(f"{len(paths)} kart: {out_dir}")
    return week, paths, data


def caption(week, data):
    now = datetime.now(TR)
    lines = [f"Puan durumu · {now.day} {social.MONTHS_TR[now.month]}", ""]
    for sport, slug, name, tag in LEAGUES:
        rows = data.get(sport)
        if not rows or len(rows) < 2:
            continue
        a, b = rows[0], rows[1]
        try:
            gap = int(a["pts"]) - int(b["pts"])
        except ValueError:
            gap = None
        ta, tb = TEAM_TR.get(a["team"], a["team"]), TEAM_TR.get(b["team"], b["team"])
        md = matchday(rows); hd = f" ({md}. hafta)" if md else ""
        if gap is None:
            lines.append(f"{name}{hd}: {ta} lider ({a['pts']} puan).")
        elif gap == 0:
            lines.append(f"{name}{hd}: {ta} ve {tb} aynı puanda ({a['pts']}), averaj {ta} lehine.")
        else:
            lines.append(f"{name}{hd}: {ta} lider ({a['pts']} puan), {tb} {gap} puan geride.")
    lines += ["", "Tablolar hafta sonu maçları sonrası; pazartesi oynanan maçlar dahil değil.", "Her hafta pazartesi 12:00'de güncel tablo burada.", "",
              instagram.NOTE, " ".join(["#puandurumu", "#futbol"] + [tag for _, _, _, tag in LEAGUES] + ["#analizveotesi"])]
    return "\n".join(lines)


def post(week=None, dry=False):
    week = week or week_key()
    rec = f"{REC}/{week}.json"
    if not os.path.exists(rec):
        print("önce kartlar üretilmeli"); return False
    data = json.load(open(rec, encoding="utf-8"))["leagues"]
    paths = sorted(glob.glob(f"{OUT}/{week}/*.jpg"))
    if len(paths) < 2:
        print("kart yok"); return False
    if any(x.get("type") == "standings" and x.get("day", "").startswith(week.split("-W")[0]) and x.get("week") == week for x in instagram.load_log()):
        print("bu hafta zaten yayınlandı"); return True
    cap = caption(week, data)
    if dry:
        print(cap); return True
    urls = [f"{instagram.PAGES}/social/puan/{week}/{os.path.basename(p)}" for p in paths]
    for p, u in zip(paths, urls):
        if not instagram.wait_public(u, timeout=420, size=os.path.getsize(p)):
            print(f"görsel yayına girmedi: {u}"); return False
    pid = instagram.publish_carousel(urls, cap)
    with open(instagram.LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"day": datetime.now(TR).strftime("%Y-%m-%d"), "type": "standings", "week": week, "code": None, "home": "Puan durumu", "away": week,
                            "post_id": pid, "t": datetime.now(timezone.utc).isoformat(timespec="seconds")}, ensure_ascii=False) + "\n")
    print(f"YAYINLANDI: {pid}")
    return True


if __name__ == "__main__":
    if "--style" in sys.argv:
        STYLE = sys.argv[sys.argv.index("--style") + 1]
    if "--post" in sys.argv:
        post(dry="--dry" in sys.argv)
    else:
        wk, paths, data = build()
        if "--dry" in sys.argv:
            print(caption(wk, data))
