"""Tek işçili iş kuyruğu: ağır yerel işler (kart üretimi, insights, instagram) sırayla çalışır, çıktı satırları toplanır."""
import subprocess, threading, time, queue, itertools, os

_q = queue.Queue()
_jobs = {}
_ids = itertools.count(1)
_lock = threading.Lock()


def submit(name, argv, cwd="."):
    """Alt süreç işi (argv listesi) ya da Python işi (çağrılabilir; log(satır) alır, sonucu döner)."""
    jid = next(_ids)
    with _lock:
        _jobs[jid] = {"id": jid, "name": name, "argv": argv, "cwd": cwd, "status": "bekliyor", "lines": [], "started": None, "ended": None, "result": None}
    _q.put(jid)
    return jid


def run_now(name, fn):
    """Kuyruğa girmeden hemen çalıştır (kısa işler); kayıt yine tutulur."""
    jid = next(_ids)
    with _lock:
        _jobs[jid] = {"id": jid, "name": name, "argv": fn, "cwd": ".", "status": "çalışıyor", "lines": [], "started": time.strftime("%H:%M:%S"), "ended": None, "result": None}
    _run_callable(_jobs[jid])
    return jid


def get(jid):
    with _lock:
        j = _jobs.get(jid)
        return dict(j) if j else None


def list_jobs(limit=20):
    with _lock:
        rows = sorted(_jobs.values(), key=lambda j: j["id"], reverse=True)[:limit]
        return [{k: v for k, v in j.items() if k != "argv"} | {"lines": j["lines"][-40:]} for j in rows]


def _run_callable(j):
    def log(line):
        with _lock:
            j["lines"].append(str(line))
    try:
        j["result"] = j["argv"](log)
        j["status"] = "bitti"
    except Exception as e:
        log(f"HATA: {e}")
        j["status"] = "hata"
    j["ended"] = time.strftime("%H:%M:%S")


def _worker():
    while True:
        jid = _q.get()
        j = _jobs[jid]
        j["status"] = "çalışıyor"; j["started"] = time.strftime("%H:%M:%S")
        if callable(j["argv"]):
            _run_callable(j); continue
        try:
            env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
            p = subprocess.Popen(j["argv"], cwd=j["cwd"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, encoding="utf-8", errors="replace", env=env)
            for line in p.stdout:
                with _lock:
                    j["lines"].append(line.rstrip())
            p.wait()
            j["status"] = "bitti" if p.returncode == 0 else "hata"
        except Exception as e:
            with _lock:
                j["lines"].append(f"iş çalıştırılamadı: {e}")
            j["status"] = "hata"
        j["ended"] = time.strftime("%H:%M:%S")


threading.Thread(target=_worker, daemon=True).start()
