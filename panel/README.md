# Yerel yönetim paneli

Çalıştır: `python -m panel` (tarayıcı açılır, http://127.0.0.1:8765). Seçenekler: `--port 8765`, `--no-browser`, `--check` (duman testi).

Panel yalnız bu bilgisayarda çalışır, şifre yoktur, dışarıya port açmaz. Sırlar `.env`'den okunur ve hiçbir yere yazılmaz.
Açılışta ve dakikada bir repoyu çeker (bekçinin kayıtları güncel görünsün).

Kararlar `records/control.json`'a yazılır ve repoya itilir; bekçi (keeper.py), gözcü (watch.py) ve instagram.py her döngüde okur:
- `paused_until`: bu saate kadar karusel, reels ve story gönderilmez.
- `posts["GÜN:KOD"]`: `at` (TSİ "HH:MM", maçtan en geç 1 saat önce) ve `skip`.
- `stories["GÜN:KOD"].skip`: kadro / devre / maç sonu story'leri kapalı.
- `reels["GÜN"]`: panelden hazırlanan reels (`status`: planned / ready / posted / cancelled / error; `asset` GitHub Release yolu). Bekçi `ready` olanı saatinde yayınlar.

Ekranlar: Bugün (günün maçları, karusel ve story durumu, saat/atla/durdur), Sistem (Actions çalışmaları ve log, kota, harcama, belirteç, "şimdi çalıştır").
Eylem günlüğü: `data/panel/actions.log` (yerel). Tasarım ve planlar: `data/panel/` (yerel).
