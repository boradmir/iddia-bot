"""Önbellek katmanı: ağır veriler (bülten, GitHub çalışmaları, Instagram, günlük) arka planda hesaplanır; API her zaman hazır sonucu anında döner.
Her yükleyicinin bir süresi (ttl) vardır; süresi dolan arka plan ipliğinde sırayla yenilenir. İlk yüklemede sonuç yoksa {"loading": True} döner,
arayüz o kutuda 'yükleniyor' gösterir, diğer kutular beklemez."""
import threading, time, traceback

_loaders = {}     # name → (fn, ttl)
_store = {}       # name → {"t": zaman, "v": değer, "err": str|None, "ms": süre}
_lock = threading.Lock()
_wake = threading.Event()
_busy = set()


def register(name, fn, ttl, prio=5):
    """prio küçük = önce yüklenir (ilk açılışta bugün/sistem verisi, ağır günlük taraması en son)."""
    _loaders[name] = (fn, ttl, prio)


def get(name, max_age=None):
    """Hazır değeri döner (yoksa loading). Süresi dolmuşsa arka planda yenilenir."""
    fn, ttl, _prio = _loaders[name]
    with _lock:
        e = _store.get(name)
    if e is None or time.time() - e["t"] > (max_age if max_age is not None else ttl):
        _wake.set()
    if e is None:
        return {"loading": True}
    return e["v"]


def meta(name):
    with _lock:
        e = _store.get(name)
    return {"age": round(time.time() - e["t"]) if e else None, "err": e and e["err"], "ms": e and e["ms"], "busy": name in _busy} if e or name in _busy else {"age": None}


def refresh(name, wait=False):
    """Zorla yenile: süreyi sıfırla, iplik uyandır. wait=True ise bitmesini bekler (en çok 60 sn)."""
    with _lock:
        if name in _store:
            _store[name]["t"] = 0
    _wake.set()
    if wait:
        t0 = time.time()
        while time.time() - t0 < 60:
            with _lock:
                e = _store.get(name)
            if e and time.time() - e["t"] < 5 and name not in _busy:
                return e["v"]
            time.sleep(0.3)
    return get(name)


def _run_one(name):
    fn, ttl, _prio = _loaders[name]
    t0 = time.time()
    try:
        v = fn(); err = None
    except Exception as e:
        v = None; err = f"{type(e).__name__}: {str(e)[:200]}"
        traceback.print_exc()
    with _lock:
        prev = _store.get(name)
        if v is None and prev:          # hata: eski değer kalsın, hata notu düşsün
            prev["err"] = err; prev["t"] = time.time()
        else:
            _store[name] = {"t": time.time(), "v": v if v is not None else {"loading": False, "error": err}, "err": err, "ms": int((time.time() - t0) * 1000)}


def _worker():
    while True:
        _wake.wait(timeout=5); _wake.clear()
        now = time.time()
        due = []
        with _lock:
            for name, (fn, ttl, prio) in _loaders.items():
                e = _store.get(name)
                if (e is None or now - e["t"] > ttl) and name not in _busy:
                    due.append((0 if e is None else 1, prio, name))   # ilk yüklemeler önce, sonra öncelik
        for _, _, name in sorted(due):
            with _lock:
                _busy.add(name)
            try:
                _run_one(name)
            finally:
                with _lock:
                    _busy.discard(name)


def start():
    threading.Thread(target=_worker, daemon=True).start()
    _wake.set()
