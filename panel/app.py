"""Yerel yönetim paneli: 127.0.0.1'de çalışır, dosyalardan durum okur, kararları records/control.json'a yazar.
Sır içermez; .env yalnız bu makinede (import config). Çalıştır: python -m panel [--port 8765] [--no-browser] [--check]"""
import json, os, sys, threading, webbrowser, urllib.request
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, unquote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # repo kökü
os.chdir(ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
import config  # noqa: F401  (.env)
from panel import jobs

STATIC = os.path.join(ROOT, "panel", "static")
IMG_ROOTS = ("docs/social", "data/reels", "assets/brand/v3")
TR = timezone(timedelta(hours=3))
MIME = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "application/javascript; charset=utf-8",
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".mp4": "video/mp4", ".mp3": "audio/mpeg", ".json": "application/json"}


def _state():
    from panel import state
    return {"ok": True, "now": datetime.now(TR).isoformat(timespec="seconds"), "today": state.today(), "system": state.system(), "jobs": jobs.list_jobs()}


def _action(body):
    from panel import actions
    return actions.run(body)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):   # sessiz
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store"); self.end_headers()
        self.wfile.write(data)

    def _file(self, path):
        if not os.path.isfile(path):
            return self._send(404, {"ok": False, "error": "yok"})
        with open(path, "rb") as f:
            self._send(200, f.read(), MIME.get(os.path.splitext(path)[1].lower(), "application/octet-stream"))

    def do_GET(self):
        u = urlparse(self.path); p = unquote(u.path)
        try:
            if p == "/":
                return self._file(os.path.join(STATIC, "index.html"))
            if p.startswith("/static/"):
                return self._file(os.path.join(STATIC, os.path.basename(p)))
            if p.startswith("/img/"):
                rel = os.path.normpath(p[5:]).replace("\\", "/")
                if rel.startswith("..") or not any(rel == r or rel.startswith(r + "/") for r in IMG_ROOTS):
                    return self._send(403, {"ok": False, "error": "izin yok"})
                return self._file(os.path.join(ROOT, rel))
            if p == "/api/state":
                return self._send(200, _state())
            if p == "/api/jobs":
                return self._send(200, jobs.list_jobs())
            if p.startswith("/api/log/"):
                from panel import state
                return self._send(200, state.run_log(p.rsplit("/", 1)[1]))
            self._send(404, {"ok": False, "error": "yol yok"})
        except Exception as e:
            self._send(500, {"ok": False, "error": str(e)})

    def do_POST(self):
        if self.path != "/api/action":
            return self._send(404, {"ok": False, "error": "yol yok"})
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
            self._send(200, _action(body))
        except Exception as e:
            self._send(500, {"ok": False, "error": str(e)})


def serve(port=8765, open_browser=True):
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    url = f"http://127.0.0.1:{port}/"
    print(f"Panel: {url}  (kapatmak için Ctrl+C)", flush=True)
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("Panel kapatıldı.")


def check(port=8799):
    """Duman testi: sunucuyu ayrı iplikte başlat, /api/state ve / oku, kapat."""
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=60) as r:
            d = json.loads(r.read())
        assert d.get("ok"), d
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as r:
            assert b"<html" in r.read().lower()
        errs = (d.get("today") or {}).get("errors", []) + (d.get("system") or {}).get("errors", [])
        print("panel --check: tamam", {k: type(v).__name__ for k, v in d.items()}, "hatalar:", errs or "yok")
        return 0
    finally:
        srv.shutdown()


def main(argv):
    port = int(argv[argv.index("--port") + 1]) if "--port" in argv else 8765
    if "--check" in argv:
        sys.exit(check())
    serve(port, open_browser="--no-browser" not in argv)
