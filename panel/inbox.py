"""Gelen kutusu: Instagram yorumları (son gönderiler), mesajlar (DM), etiketlenmeler. 'Yeni' = son 'Gördüm' zamanından sonra gelenler.
Graph API ile okunur (belirteç yalnız istek içinde; kayda yazılmaz). Yanıt: yorum yanıtı ve DM yanıtı (izin varsa)."""
import json, os, time, urllib.parse, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta
import instagram

TR = timezone(timedelta(hours=3))
SEEN = "data/panel/inbox_seen.json"
_cache = {}


def _tok():
    return os.environ.get("IG_TOKEN"), os.environ.get("IG_USER_ID")


def _get(path, **params):
    tok, _ = _tok()
    q = urllib.parse.urlencode({**params, "access_token": tok})
    try:
        with urllib.request.urlopen(f"{instagram.API}/{path}?{q}", timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300].replace(tok or "x", "***")
        raise RuntimeError(f"API {e.code}: {body}")


def _post(path, **params):
    tok, _ = _tok()
    data = urllib.parse.urlencode({**params, "access_token": tok}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{instagram.API}/{path}", data=data), timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300].replace(tok or "x", "***")
        raise RuntimeError(f"API {e.code}: {body}")


def _ts(s):
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z").astimezone(TR)
    except Exception:
        return None


def seen():
    try:
        return json.load(open(SEEN, encoding="utf-8"))
    except Exception:
        return {}


def mark_seen(kind):
    s = seen(); s[kind] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    os.makedirs(os.path.dirname(SEEN), exist_ok=True)
    json.dump(s, open(SEEN, "w", encoding="utf-8"))
    return s


def _is_new(kind, when):
    last = seen().get(kind)
    if not last or not when:
        return bool(when)
    return when > datetime.fromisoformat(last).astimezone(TR)


def comments(limit_media=12):
    _, uid = _tok()
    media = _get(f"{uid}/media", fields="id,media_type,timestamp,comments_count,permalink,caption", limit=limit_media).get("data", [])
    out = []
    for m in media:
        if not m.get("comments_count"):
            continue
        cs = _get(f"{m['id']}/comments", fields="id,text,username,timestamp,like_count,replies{id,text,username,timestamp}", limit=50).get("data", [])
        title = (m.get("caption") or "")[:70]
        for c in cs:
            t = _ts(c.get("timestamp", ""))
            out.append({"id": c["id"], "media_id": m["id"], "permalink": m.get("permalink"), "post": title, "user": c.get("username"), "text": c.get("text"),
                        "t": t.strftime("%d.%m %H:%M") if t else "", "likes": c.get("like_count", 0), "new": _is_new("comments", t),
                        "replies": [{"user": r.get("username"), "text": r.get("text"), "t": (_ts(r.get("timestamp", "")) or datetime.now(TR)).strftime("%d.%m %H:%M")}
                                    for r in (c.get("replies") or {}).get("data", [])]})
    out.sort(key=lambda c: c["t"], reverse=True)
    return out


def messages(limit=15):
    _, uid = _tok()
    convs = _get(f"{uid}/conversations", platform="instagram", fields="id,updated_time,participants", limit=limit).get("data", [])
    out = []
    for cv in convs:
        who = [p.get("username") for p in (cv.get("participants") or {}).get("data", []) if p.get("id") != uid]
        try:
            ms = _get(cv["id"], fields="messages.limit(8){id,created_time,from,message,attachments}").get("messages", {}).get("data", [])
        except Exception as e:
            ms = []; err = str(e)[:120]
        else:
            err = None
        msgs = []
        for x in ms:
            t = _ts(x.get("created_time", ""))
            frm = (x.get("from") or {}).get("username")
            msgs.append({"from": frm, "mine": frm == "analizveotesi" or (x.get("from") or {}).get("id") == uid, "text": x.get("message") or ("[ek]" if x.get("attachments") else ""),
                         "t": t.strftime("%d.%m %H:%M") if t else ""})
        upd = _ts(cv.get("updated_time", ""))
        out.append({"id": cv["id"], "with": ", ".join(who) or "?", "updated": upd.strftime("%d.%m %H:%M") if upd else "", "new": _is_new("messages", upd) and not (msgs and msgs[0]["mine"]),
                    "messages": msgs[::-1], "error": err})
    return out


def tags(limit=10):
    _, uid = _tok()
    data = _get(f"{uid}/tags", fields="id,caption,timestamp,username,permalink", limit=limit).get("data", [])
    out = []
    for x in data:
        t = _ts(x.get("timestamp", ""))
        out.append({"id": x["id"], "user": x.get("username"), "caption": (x.get("caption") or "")[:120], "permalink": x.get("permalink"),
                    "t": t.strftime("%d.%m %H:%M") if t else "", "new": _is_new("tags", t)})
    return out


def data():
    tok, uid = _tok()
    if not (tok and uid):
        return {"ok": False, "error": "IG_TOKEN / IG_USER_ID yok"}
    now = time.time()
    v = _cache.get("inbox")
    if v and now - v[0] < 120:
        d = v[1]
    else:
        d = {"errors": []}
        for k, fn in (("comments", comments), ("messages", messages), ("tags", tags)):
            try:
                d[k] = fn()
            except Exception as e:
                d[k] = []; d["errors"].append(f"{k}: {str(e)[:160]}")
        _cache["inbox"] = (now, d)
    # 'yeni' bayrakları önbellekten bağımsız her seferinde hesaplanır (Gördüm sonrası hemen sönsün)
    for c in d.get("comments", []):
        c["new"] = _is_new("comments", _parse(c["t"]))
    for m in d.get("messages", []):
        m["new"] = _is_new("messages", _parse(m["updated"])) and not (m["messages"] and m["messages"][-1]["mine"])
    for x in d.get("tags", []):
        x["new"] = _is_new("tags", _parse(x["t"]))
    d["counts"] = {"comments": sum(1 for c in d.get("comments", []) if c["new"]), "messages": sum(1 for m in d.get("messages", []) if m["new"]),
                   "tags": sum(1 for x in d.get("tags", []) if x["new"])}
    return {"ok": True, **d, "seen": seen()}


def _parse(s):
    try:
        y = datetime.now(TR).year
        d = datetime.strptime(f"{y}.{s}", "%Y.%d.%m %H:%M").replace(tzinfo=TR)
        return d if d <= datetime.now(TR) + timedelta(days=1) else d.replace(year=y - 1)
    except Exception:
        return None


def invalidate():
    _cache.pop("inbox", None)


def reply_comment(comment_id, text):
    r = _post(f"{comment_id}/replies", message=text)
    invalidate(); return r


def reply_message(conversation_id, text):
    """DM yanıtı: Instagram Messaging API (me/messages, recipient = karşı taraf). Konuşmadan karşı tarafın IGSID'si alınır."""
    _, uid = _tok()
    cv = _get(conversation_id, fields="participants")
    other = next((p["id"] for p in (cv.get("participants") or {}).get("data", []) if p.get("id") != uid), None)
    if not other:
        raise RuntimeError("alıcı bulunamadı")
    r = _post(f"{uid}/messages", recipient=json.dumps({"id": other}), message=json.dumps({"text": text}))
    invalidate(); return r
