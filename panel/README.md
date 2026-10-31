# Yerel yönetim paneli

Çalıştır: `python -m panel` (tarayıcı açılır, http://127.0.0.1:8765). Seçenekler: `--port 8765`, `--no-browser`, `--check` (duman testi).

Panel yalnız bu bilgisayarda çalışır, şifre yoktur, dışarıya port açmaz. Sırlar `.env`'den okunur ve hiçbir yere yazılmaz.
Açılışta ve dakikada bir repoyu çeker (bekçinin kayıtları güncel görünsün). Her sekmenin üstünde ne işe yaradığını anlatan bir kutu vardır.

## Sekmeler
- **Bugün**: günün maçları, karusel ve story durumu, saat yaz / atla / story atla / bugün durdur, kart önizleme, "Instagram'ı şimdi çalıştır".
- **İçerik**: açıklama metni (caption_override) ve kart yazıları düzenleme, kartı yeniden üretme, yayına yazma (repoya it), analizi editör notuyla yeniden çalıştırma (ücretli; eski kayıt `superseded`).
- **Reels**: maç seç → metin → ses (Ahu / erkek, dönüşümlü) → video → denetim → önizleme → saat → yayına al (GitHub Release + control.reels `ready`; bekçi yayınlar). Erkek ses adayları ElevenLabs paylaşılan kütüphanesinden dinlenip seçilir (`data/panel/voices.json`).
- **İstatistik**: takipçi ve erişim grafikleri, gönderi tablosu, gönderi başına gün gün seri, story tablosu (ileri/geri/çıkış), gruplara göre ortalama, hesap gün gün tablosu, reklam kaydı formu (`records/insights/ads.jsonl`), haftalık iç rapor.
- **Kupon**: kilitlenen kuponların puanı, gözcü uyarıları ve CLV, skorlar (eski Pages vitrininin içeriği).
- **Gelen kutusu**: Instagram yorumları, mesajlar (DM), etiketlenmeler; yeni işaretleri, "Gördüm", yanıt verme.
- **Günlük**: tüm olaylar ve hatalar tek zaman çizgisinde (yayınlar, analizler, panel eylemleri, GitHub çalışmaları ve log hata satırları, uyarılar, reklamlar); seviye ve gün süzgeci.
- **Sistem**: Actions çalışmaları (log, iptal), bekçi durumu, kota, harcama (yapay zekâ, ElevenLabs), Instagram belirteci, "şimdi çalıştır" düğmeleri, "Yeniden it".

## Kontrol dosyası `records/control.json`
Kararlar buraya yazılır ve repoya itilir; bekçi (keeper.py), gözcü (watch.py) ve instagram.py her döngüde okur:
- `paused_until`: bu saate kadar karusel, reels ve story gönderilmez.
- `posts["GÜN:KOD"]`: `at` (TSİ "HH:MM", maçtan en geç 1 saat önce) ve `skip`.
- `stories["GÜN:KOD"].skip`: kadro / devre / maç sonu story'leri kapalı.
- `reels["GÜN"]`: panelden hazırlanan reels (`status`: planned / ready / posted / cancelled / error; `asset` GitHub Release yolu). Bekçi `ready` olanı saatinde yayınlar. `reels_post.py` (yerel zamanlayıcı) yedek olarak durur.

Pages (`docs/index.html`) artık boş bir sayfadır; yalnız kart ve kapak görsellerini sunar (Instagram API görselleri oradan çeker).
Eylem günlüğü: `data/panel/actions.log`. Tasarım ve planlar: `data/panel/` (yerel, repoya girmez).
