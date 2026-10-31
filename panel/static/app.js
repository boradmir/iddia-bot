// Panel arayüzü: sol menü, sayfa başına tek işlev, hiçbir kutu diğerini bekletmez (veriler arka planda önbellekten gelir).
const $ = s => document.querySelector(s);
let S = null, PAGE = 'genel', CONTENT_CODE = null, CONTENT = null, STATS = null, EV = { level: '', days: 3 };
const RS = { posted: 'yayında', ready: 'hazır, saat bekliyor', planned: 'seçildi', cancelled: 'iptal', error: 'HATA' };
const HELP = {
  genel: '<b>Genel bakış.</b> Sistemin sağlığı ve bugünün özeti. Kırmızı bir şey görürsen ilgili sayfaya git; her şey yeşilse yapacak iş yok, bot kendi çalışıyor.',
  bugun: '<b>Bugün.</b> Bot paylaşımları kendi yapar; burası müdahale yeri. <b>Saat</b>: karusel o saatte gider (maçtan en az 1 saat önce). <b>Atla</b>: bu maç paylaşılmaz. <b>Story kapat</b>: kadro / devre / maç sonu story\'leri gitmez. <b>Bugün durdur</b>: gece yarısına kadar hiçbir şey paylaşılmaz. Kararlar en geç 20 dakikada etki eder (bekçi döngüsü).',
  icerik: '<b>İçerik.</b> Bir maç seç. Açıklama Instagram\'daki metindir; düzenleyip kaydedersen senin yazdığın gider (kutuyu boşaltırsan otomatik metne döner). Kart yazılarını kaydettikten sonra <b>Kartı yeniden üret</b>, önizle, <b>Yayına yaz</b>. <b>Analizi yeniden çalıştır</b> ücretlidir (yaklaşık maliyet düğmede). Yayınlanmış gönderi değiştirilemez.',
  reels: '<b>Reels.</b> Maçı seç, <b>Seç ve üret</b>: metin, ses, video sırayla üretilir; dinle, izle; beğenmediysen yeniden üret. <b>Yayına al</b>: video GitHub\'a yüklenir, bekçi verdiğin saatte yayınlar (bilgisayar kapalı olsa da). Sesler: Ahu ve erkek ses dönüşümlü; erkek ses seçilmediyse adayları dinleyip seç.',
  veri: '<b>Instagram verileri.</b> Bekçi her sabah ölçer. <b>Erişim</b>: gönderiyi gören tekil hesap; <b>etkileşim</b>: (beğeni+yorum+kaydet+paylaş)/erişim. Reklam bastığın gönderiyi kaydet, rapor onu organik tablolardan ayırır. Ayrıntılar aşağıdaki açılır bölümlerde.',
  gelen: '<b>Gelen kutusu.</b> Yorumlar, mesajlar, etiketlenmeler. "Yeni" son <b>Gördüm</b>\'den sonra gelenlerdir. Buradan yanıt verebilirsin, hesap adıyla gider.',
  kupon: '<b>Kupon ve uyarılar.</b> Eski vitrin sayfasının içeriği: kilitlenen kuponların puanı (1 birim oynanmış gibi), gözcü fırsat uyarıları ve kapanış farkı (CLV: artıysa yöntem çalışıyor), skorlar.',
  gunluk: '<b>Günlük.</b> Ne olup bittiğinin tek listesi: yayınlar, analizler (maliyetiyle), panel eylemleri, reels, GitHub çalışmaları ve loglarındaki hata satırları. Kırmızı hata, sarı uyarı. GitHub logları 5 dakikada bir taranır.',
  sistem: '<b>Sistem.</b> Bekçi (GitHub\'da 20 dakikada bir: kayıt, analiz, kartlar, karusel, insights, reels, story yedeği), gözcü (maç günü oran takibi ve story\'ler), skorlar. Çalışmıyorsa düğmeyle başlat; <b>log</b> son 200 satır. <b>Yeniden it</b>: yerel değişiklikler GitHub\'a gitmediyse tekrar dener.'
};
const TITLE = { genel: 'Genel bakış', bugun: 'Bugün', icerik: 'İçerik', reels: 'Reels', veri: 'Instagram verileri', gelen: 'Gelen kutusu', olustur: 'Kupon oluştur', kupon: 'Kupon ve uyarılar', gunluk: 'Günlük', sistem: 'Sistem' };
HELP.olustur = '<b>Kupon oluştur.</b> Önümüzdeki 48 saatin maçları ve Nesine oranları. Her oranın altında üç ihtimal: <span class="src-ai"><b>yeşil</b> bizim yapay zekâ analizi</span>, <span class="src-stat"><b>mavi</b> istatistik modeli</span>, <span class="src-pin"><b>turuncu</b> piyasa (Pinnacle)</span>. Orana tıkla, sağdaki kupona eklenir (maç başına bir seçim). <b>Golcüler</b> ile oyuncuların sezon ve son 5 maç istatistiği ve "gol atar" oranı açılır. <b>Kaydet ve yorumlat</b>: yapay zekâ maçların haberlerine bakıp kısa bir kupon yorumu yazar (ücretli, ~$0,3-0,6). Kuponlar bu bilgisayarda saklanır, maçlar bitince puanlanır.';

// ---------- yardımcılar
function esc(s) { return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
function n(x, d = 0) { return (x === null || x === undefined || x === '') ? '–' : Number(x).toFixed(d); }
function cls(s) { return String(s || '').replace(/ı/g, 'i').replace(/ş/g, 's').replace(/ç/g, 'c'); }
function toast(msg, bad) { const t = $('#toast'); t.textContent = msg; t.style.display = 'block'; t.style.background = bad ? '#C8423A' : '#0B2A1F'; setTimeout(() => t.style.display = 'none', bad ? 6000 : 3000); }
function zoom(src) { const o = document.createElement('div'); o.id = 'overlay'; o.innerHTML = `<img src="${src}">`; o.onclick = () => o.remove(); document.body.appendChild(o); }
async function api(path) { const r = await fetch(path); return r.json(); }
async function act(body, after) {
  const r = await fetch('/api/action', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const d = await r.json(); toast(d.ok ? (d.msg || 'Tamam') : ('Hata: ' + (d.error || '')), !d.ok); tick(); if (after) after(d); return d;
}
function loading(text) { return `<div class="load">${esc(text || 'Yükleniyor')}</div>`; }
function chip(text, kind) { return `<span class="chip ${kind || ''}">${esc(text)}</span>`; }
function stateChip(s) { const k = { 'yayında': 'ok', 'planlı': 'info', 'atlandı': 'bad', 'durduruldu': 'bad', 'sırada': 'info', 'bekliyor': '', 'kart yok': '', 'süre geçti': '' }[s] || ''; return chip(s, k); }
function chart(days, vals, color) {
  const v = (vals || []).map(x => x || 0); if (!v.length) return '<div class="muted small">veri yok</div>';
  const W = 600, H = 130, mx = Math.max(...v, 1), mn = Math.min(...v, 0);
  const X = i => (i / Math.max(v.length - 1, 1)) * (W - 24) + 12, Y = y => H - 22 - ((y - mn) / (mx - mn || 1)) * (H - 44);
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><polyline fill="none" stroke="${color}" stroke-width="2" points="${v.map((y, i) => `${X(i)},${Y(y)}`).join(' ')}"/>${v.map((y, i) => `<circle cx="${X(i)}" cy="${Y(y)}" r="3" fill="${color}"/>`).join('')}
    <text x="12" y="14" fill="#6B7A74" font-size="11">en yüksek ${mx}</text><text x="12" y="${H - 6}" fill="#6B7A74" font-size="11">${esc(days[0] || '')}</text><text x="${W - 90}" y="${H - 6}" fill="#6B7A74" font-size="11">${esc(days[days.length - 1] || '')}</text></svg>`;
}

// ---------- sayfa yönetimi
document.querySelectorAll('#nav a').forEach(a => a.onclick = () => open(a.dataset.page));
$('#helpBtn').onclick = () => { const h = $('#help'); h.style.display = h.style.display === 'none' ? 'block' : 'none'; };
function open(p) {
  PAGE = p; document.querySelectorAll('#nav a').forEach(a => a.classList.toggle('on', a.dataset.page === p));
  $('#title').textContent = TITLE[p]; $('#help').innerHTML = HELP[p]; $('#help').style.display = 'none'; $('#topActions').innerHTML = '';
  $('#page').innerHTML = loading();
  render();
}
function render() {
  ({ genel: rGenel, bugun: rBugun, icerik: rIcerik, reels: rReels, veri: rVeri, gelen: rGelen, olustur: rOlustur, kupon: rKupon, gunluk: rGunluk, sistem: rSistem })[PAGE]();
}
async function tick() {
  try {
    S = await api('/api/state');
    $('#conn').className = 'dot ok'; $('#clock').textContent = S.now.slice(11, 16) + ' TSİ';
    renderJobs(S.jobs || []);
    if (PAGE === 'genel' || PAGE === 'bugun' || PAGE === 'sistem') render();
  } catch (e) { $('#conn').className = 'dot'; }
}
function renderJobs(jobs) {
  $('#jobList').innerHTML = jobs.length ? jobs.map(j => `<div class="job ${cls(j.status)}"><b>${esc(j.name)}</b> · ${esc(j.status)} ${esc(j.started || '')}\n${esc(j.lines.slice(-8).join('\n'))}</div>`).join('') : '<span class="muted">İş yok</span>';
}

// ---------- Genel bakış
function rGenel() {
  const T = S && S.today, Y = S && S.system;
  if (!T || T.loading || !Y || Y.loading) { $('#page').innerHTML = loading('Veriler hazırlanıyor (ilk açılışta 10-20 saniye)'); return; }
  const k = Y.keeper, w = T.watch || {}, t = Y.ig_token || {};
  const posts = T.matches.filter(m => m.post.state === 'yayında').length, planned = T.matches.filter(m => m.post.state === 'planlı').map(m => `${m.home} – ${m.away} ${m.post.at}`);
  const stories = T.matches.filter(m => m.tier === 0).map(m => `${m.home} – ${m.away}: kadro ${m.stories.kadro}, devre ${m.stories.devre}, maç sonu ${m.stories.ft}`);
  const health = [
    ['Bekçi', k.running ? 'çalışıyor' : 'çalışmıyor', k.running ? 'ok' : 'bad', `son kayıt ${k.last || '–'} (${k.age_min ?? '–'} dk önce)`],
    ['Gözcü', w.active ? 'açık' : 'kapalı', w.active ? 'ok' : '', w.note || ''],
    ['Instagram belirteci', t.valid === false ? 'GEÇERSİZ' : t.valid ? 'geçerli' : 'bilgi yok', t.valid === false ? 'bad' : t.valid ? 'ok' : 'warn', t.username ? '@' + t.username : ''],
    ['Odds API kotası', `${Y.quota.remaining} istek`, Y.quota.remaining < 60 ? 'warn' : 'ok', `bugün ${Y.quota.spent_today}`],
    ['Paylaşımlar', T.paused_until ? 'DURDURULDU' : 'açık', T.paused_until ? 'bad' : 'ok', T.paused_until ? `${T.paused_until.slice(11, 16)} kadar` : '']];
  $('#page').innerHTML = `
    <div class="card"><h3>Sağlık</h3><div class="row">${health.map(h => `<div class="kpi ${h[2] === 'bad' ? 'bad' : h[2] === 'warn' ? 'warn' : ''}"><b style="font-size:16px">${esc(h[1])}</b><span>${esc(h[0])}${h[3] ? ' · ' + esc(h[3]) : ''}</span></div>`).join('')}</div>
      ${(T.errors || []).concat(Y.errors || []).length ? `<div class="err">${esc(T.errors.concat(Y.errors).join(' · '))}</div>` : ''}</div>
    <div class="grid2">
      <div class="card"><h3>Bugün <small>${esc(T.day)}</small></h3>
        <div>Karusel: ${posts}/${T.max_per_day} yayında${planned.length ? ' · planlı: ' + esc(planned.join(', ')) : ''}</div>
        <div class="small muted" style="margin-top:4px">${stories.length ? stories.map(esc).join('<br>') : 'Bugün story\'li (büyük kulüp) maç yok'}</div>
        ${T.standings ? `<div class="small" style="margin-top:6px">Puan durumu karuseli: ${T.standings.posted ? chip('bu hafta yayında', 'ok') : T.standings.skip ? chip('bu hafta atlanacak', 'bad') : chip('sıradaki ' + T.standings.next, 'info')}</div>` : ''}
        <div class="row" style="margin-top:10px"><button class="btn sec sm" onclick="open('bugun')">Bugün sayfasına git</button></div></div>
      <div class="card"><h3>Hızlı işlemler</h3><div class="row">
        <button class="btn sec" onclick="act({action:'workflow',name:'keeper.yml'})">Bekçiyi çalıştır</button>
        <button class="btn sec" onclick="act({action:'workflow',name:'watch.yml'})">Gözcüyü çalıştır</button>
        <button class="btn sec" onclick="act({action:'insights_now'})">Insights çek</button>
        <button class="btn sec" onclick="act({action:'retry_push'})">Yeniden it</button>
        ${T.paused_until ? `<button class="btn" onclick="act({action:'pause',until:null})">Paylaşımları aç</button>` : `<button class="btn warn" onclick="act({action:'pause',until:'today'})">Bugün durdur</button>`}</div>
        <div class="small muted" style="margin-top:8px">Günlük ve gelen kutusu sayıları sol menüde kırmızı rozetle görünür.</div></div>
    </div>`;
}

// ---------- Bugün
function rBugun() {
  const T = S && S.today;
  if (!T || T.loading) { $('#page').innerHTML = loading('Günün planı hazırlanıyor'); return; }
  $('#topActions').innerHTML = T.paused_until ? `<span class="chip bad">Durduruldu, ${esc(T.paused_until.slice(11, 16))} kadar</span> <button class="btn" onclick="act({action:'pause',until:null})">Aç</button>`
    : `<button class="btn warn" title="Gece yarısına kadar hiçbir şey paylaşılmaz" onclick="act({action:'pause',until:'today'})">Bugün durdur</button> <button class="btn sec" title="instagram.py'yi şimdi çalıştırır; saati gelmiş gönderi varsa gider" onclick="act({action:'instagram_now'})">Instagram'ı şimdi çalıştır</button>`;
  const st = T.standings || {};
  const rows = T.matches.map(m => {
    const p = m.post, s = m.stories, c = m.cards;
    const thumbs = ['match', 'yorum', 'story', 'devre', 'macsonu'].filter(k => c[k]).map(k => `<img class="thumb" src="${c[k]}" title="${k}" onclick="zoom('${c[k]}')">`).join('');
    const editable = !(p.state === 'yayında' || p.state === 'süre geçti');
    const storyTxt = m.tier === 0 ? `kadro ${s.kadro} · devre ${s.devre} · maç sonu ${s.ft}` : '<span class="muted">yok (yalnız dört büyük)</span>';
    const reels = m.reels ? `<div class="small">Reels: ${esc(RS[m.reels.status] || m.reels.status)}${m.reels.url ? ` · <a href="${m.reels.url}" target="_blank">aç</a>` : ''}</div>` : '';
    return `<tr><td>${thumbs}</td><td><b>${esc(m.home)} – ${esc(m.away)}</b><div class="small muted">${esc(m.kickoff)} · ${esc(m.league)} · kademe ${m.tier}${m.analysis ? ' · <a href="#" onclick="CONTENT_CODE=' + m.code + ';open(\'icerik\');return false">analiz var, düzenle</a>' : ''}</div></td>
      <td>${stateChip(p.state)}${p.at ? ' ' + esc(p.at) : ''}${p.override_at ? `<div class="small muted">panel saati ${esc(p.override_at)}</div>` : ''}${p.url ? `<div class="small"><a href="${p.url}" target="_blank">gönderiyi aç</a></div>` : ''}</td>
      <td class="small">${storyTxt}${reels}</td>
      <td><div class="row" style="gap:6px">${editable ? `<input type="time" id="t${m.code}" value="${esc(p.override_at || p.at || '')}" style="padding:3px 5px"><button class="btn sec sm" onclick="act({action:'set_time',code:${m.code},at:$('#t${m.code}').value})">Saat</button>
        <button class="btn ${p.skip ? 'sec' : 'warn'} sm" onclick="act({action:'skip',code:${m.code},skip:${!p.skip}})">${p.skip ? 'Atlamayı geri al' : 'Atla'}</button>` : ''}
        ${m.tier === 0 ? `<button class="btn ${s.skip ? 'sec' : 'warn'} sm" onclick="act({action:'story_skip',code:${m.code},skip:${!s.skip}})">${s.skip ? "Story'leri aç" : 'Story kapat'}</button>` : ''}</div></td></tr>`;
  }).join('');
  $('#page').innerHTML = `
    <div class="card"><h3>Haftalık puan durumu karuseli <small>her pazartesi 12:00 · sıradaki ${esc(st.next || '')}</small></h3>
      <div class="row">${st.posted ? chip('bu hafta yayında', 'ok') + (st.url ? ` <a href="${st.url}" target="_blank">aç</a>` : '') : st.skip ? chip('bu hafta atlanacak', 'bad') : chip('bu hafta gönderilecek', 'info')}
        <button class="btn sec sm" title="Kartları şimdi üretir, önizlersin; yayın pazartesi bekçide" onclick="act({action:'standings_preview'},()=>setTimeout(tick,8000))">Önizleme üret</button>
        <button class="btn ${st.skip ? 'sec' : 'warn'} sm" onclick="act({action:'standings_skip',skip:${!st.skip}})">${st.skip ? 'Atlamayı geri al' : 'Bu hafta atla'}</button></div>
      ${st.cards && st.cards.length ? `<div style="margin-top:8px">${st.cards.map(u => `<img class="thumb" src="${u}" onclick="zoom('${u}')">`).join('')}</div>` : ''}</div>
    <div class="card"><h3>Maçlar <small>karusel ${T.sent_count}/${T.max_per_day} · gözcü: ${esc((T.watch || {}).note || '–')}</small></h3>
      ${(T.errors || []).length ? `<div class="err">${esc(T.errors.join(' · '))}</div>` : ''}
      <table><tr><th>Kartlar</th><th>Maç</th><th>Karusel</th><th>Story / Reels</th><th>İşlem</th></tr>${rows || '<tr><td colspan="5" class="muted">Bugün listelenecek maç yok</td></tr>'}</table></div>`;
}

// ---------- İçerik
async function rIcerik() {
  const T = S && S.today; const ms = (T && T.matches || []).filter(m => m.analysis);
  if (!CONTENT_CODE && ms.length) CONTENT_CODE = ms[0].code;
  $('#topActions').innerHTML = '';
  const list = `<div class="card"><div class="row">${ms.map(m => `<button class="btn ${m.code == CONTENT_CODE ? '' : 'sec'}" onclick="CONTENT_CODE=${m.code};rIcerik()">${esc(m.home)} – ${esc(m.away)} <span style="opacity:.7;font-weight:400">${esc(m.kickoff)}${m.post.state === 'yayında' ? ' · yayında' : ''}</span></button>`).join('')}
    ${ms.length ? '' : '<span class="muted">Bugün analizli maç yok.</span>'}</div></div>`;
  if (!CONTENT_CODE) { $('#page').innerHTML = list; return; }
  $('#page').innerHTML = list + loading();
  const d = await api('/api/content?code=' + CONTENT_CODE); CONTENT = d;
  if (!d.ok) { $('#page').innerHTML = list + `<div class="card err">${esc(d.error)}</div>`; return; }
  const dis = d.posted ? 'disabled' : '';
  $('#page').innerHTML = list + `
    <div class="card"><h3>${esc(d.home)} – ${esc(d.away)} <small>${esc(d.day)} · sürüm ${d.revision}${d.cost_usd ? ` · maliyet $${d.cost_usd}` : ''}${d.edited_at ? ' · düzenlendi' : ''}</small></h3>
      ${d.posted ? '<div class="err">Bu gönderi yayınlandı; Instagram metin düzenlemeyi kabul etmez. Yalnız görüntüleme.</div>' : ''}
      ${d.note ? `<div class="small muted">Son yeniden çalıştırma notu: ${esc(d.note)}</div>` : ''}
      <div>${Object.values(d.cards).map(u => `<img class="thumb" style="height:110px" src="${u}?t=${Date.now()}" onclick="zoom('${u}?t=${Date.now()}')">`).join('')}</div></div>
    <div class="grid2">
      <div class="card"><h3>Açıklama <small>${d.caption_override ? 'senin düzenlemen' : 'otomatik üretildi'}</small></h3>
        <textarea id="cap" rows="16" ${dis}>${esc(d.caption_override || d.caption)}</textarea>
        <div class="row" style="margin-top:8px"><button class="btn" ${dis} onclick="saveContent(true)">Açıklamayı kaydet</button><button class="btn sec" ${dis} onclick="act({action:'content_save',code:CONTENT_CODE,caption_override:''},rIcerik)">Otomatik metne dön</button></div></div>
      <div class="card"><h3>Kart yazıları</h3>
        ${Object.keys(d.fields).map(k => `<label class="f">${esc(d.field_names[k] || k)}</label><textarea id="f_${k}" ${dis} rows="${k === 'comment' ? 6 : 2}">${esc(d.fields[k])}</textarea>`).join('')}
        <div class="row" style="margin-top:8px"><button class="btn" ${dis} onclick="saveContent(false)">Kaydet</button>
          <button class="btn sec" ${dis} title="Kaydedilen yazılarla kartları yeniden çizer (ücretsiz)" onclick="act({action:'content_regen',code:${d.code}},()=>setTimeout(rIcerik,5000))">Kartı yeniden üret</button>
          <button class="btn sec" ${dis} title="Kartları ve kaydı GitHub'a iter" onclick="act({action:'content_publish',code:${d.code}})">Yayına yaz</button></div>
        <label class="f">Yeniden çalıştırma notu (yapay zekâya: neye dikkat etsin?)</label>
        <div class="row"><input type="text" id="note" ${dis} style="flex:1" placeholder="örn. kaleci sakatlığı haberi var, kontrol et"><button class="btn warn" ${dis} onclick="rerun(${d.code})">Analizi yeniden çalıştır (~$${d.est_cost})</button></div></div>
    </div>`;
}
async function saveContent(cap) {
  const body = { action: 'content_save', code: CONTENT_CODE };
  if (cap) body.caption_override = $('#cap').value; else body.fields = Object.fromEntries(Object.keys(CONTENT.fields).map(k => [k, $('#f_' + k).value]));
  await act(body, rIcerik);
}
async function rerun(code) {
  if (!confirm('Analiz yeniden çalıştırılsın mı? Ücretli (yaklaşık $' + CONTENT.est_cost + '). Eski kayıt saklanır, yeni sürüm geçerli olur.')) return;
  await act({ action: 'content_rerun', code, note: $('#note').value }, () => setTimeout(rIcerik, 6000));
}

// ---------- Reels
async function rReels() {
  const d = await api('/api/reels');
  const st = d.state || {}, rc = d.control || {}, v = d.voices || {};
  const vopts = ['ahu', 'erkek'].filter(k => v[k]).map(k => `<option value="${k}" ${(st.voice || d.default_voice) === k ? 'selected' : ''}>${esc(v[k].name)}</option>`).join('');
  const cands = (d.candidates || []).map(c => `<label style="display:block;padding:3px 0"><input type="radio" name="rc" value="${c.code}" ${st.code == c.code ? 'checked' : ''}> ${esc(c.home)} – ${esc(c.away)} <span class="muted small">${esc(c.kickoff)} · kademe ${c.tier}</span>${d.posted && d.posted[c.code] ? ' ' + chip('yayında', 'ok') : ''}</label>`).join('');
  const male = v.erkek ? `<span class="small muted">Erkek ses: ${esc(v.erkek.name)} · <a href="#" onclick="loadVoices();return false">değiştir</a></span>` : `<span class="small err">Erkek ses seçilmedi · <a href="#" onclick="loadVoices();return false">adayları dinle ve seç</a></span>`;
  const step = (no, title, done, body) => `<div class="step ${done ? 'done' : ''}"><div class="n">${done ? '✓' : no}</div><div class="body"><b>${title}</b><div>${body}</div></div></div>`;
  const ctl = rc.status ? `${chip(RS[rc.status] || rc.status, rc.status === 'posted' ? 'ok' : rc.status === 'error' || rc.status === 'cancelled' ? 'bad' : 'info')}${rc.at ? ' saat ' + esc(rc.at) : ''}${rc.error ? `<div class="err">${esc(rc.error)}</div>` : ''}` : '<span class="muted small">Bekçiye henüz bir şey verilmedi.</span>';
  $('#page').innerHTML = `
    <div class="card"><h3>Maç ve ses</h3>${cands || '<div class="muted">Bugün analizli maç yok (reels için yapay zekâ paketi gerekir).</div>'}
      <div class="row" style="margin-top:8px">Ses: <select id="vsel0">${vopts}</select><button class="btn" ${cands ? '' : 'disabled'} onclick="chooseReels(true)">Seç ve üret</button><button class="btn sec" ${cands ? '' : 'disabled'} onclick="chooseReels(false)">Sadece seç</button>${male}</div><div id="vcands"></div></div>
    ${st.code ? `<div class="card">
      ${step(1, 'Metin', !!st.text, st.text ? `<p style="margin:4px 0">${esc(st.text)}</p><span class="small muted">${st.text.split(' ').length} kelime · metni İçerik sayfasından düzeltebilirsin</span> <button class="btn sec sm" onclick="act({action:'reels_script'},()=>setTimeout(rReels,2500))">Yeniden üret</button>` : `<button class="btn sec sm" onclick="act({action:'reels_script'},()=>setTimeout(rReels,2500))">Üret</button>`)}
      ${step(2, 'Ses', !!d.urls.mp3, `${d.urls.mp3 ? `<audio controls src="${d.urls.mp3}?t=${Date.now()}"></audio> <span class="small muted">${esc((v[st.voice] || {}).name || st.voice)} · deneme ${st.voice_n}</span><br>` : ''}
        <span class="row" style="margin-top:4px">Ses: <select id="vsel">${vopts}</select><button class="btn sec sm" title="Yeni tohumla tekrar okutur" onclick="act({action:'reels_voice',voice:$('#vsel').value,seed:Math.floor(Math.random()*1e6)},()=>setTimeout(rReels,4000))">${d.urls.mp3 ? 'Yeniden üret' : 'Üret'}</button></span>`)}
      ${step(3, 'Video', !!d.urls.mp4, `${d.urls.mp4 ? `<video class="prev" controls src="${d.urls.mp4}?t=${Date.now()}"></video> <span class="small muted">${st.seconds} sn</span>
        <div>${(st.issues || []).length ? `<span class="err">Denetim: ${esc(st.issues.join(' | '))} — düzeltip yeniden üret</span>` : '<span class="okt">Denetim temiz</span>'}</div>
        <details><summary class="small">Açıklama metni</summary><pre class="log">${esc(st.caption || '')}</pre></details>` : ''}
        <button class="btn sec sm" onclick="act({action:'reels_render'},()=>setTimeout(rReels,3000))">${d.urls.mp4 ? 'Yeniden üret' : 'Üret'}</button>`)}
      ${step(4, 'Yayın', rc.status === 'ready' || rc.status === 'posted', `${ctl}<div class="row" style="margin-top:6px">Saat (TSİ, boş = ilk turda): <input type="time" id="rat" value="${esc(st.at || rc.at || '')}">
        <button class="btn" ${d.urls.mp4 && !(st.issues || []).length && rc.status !== 'posted' ? '' : 'disabled'} onclick="act({action:'reels_publish',at:$('#rat').value},()=>setTimeout(rReels,3000))">Yayına al</button>
        <button class="btn warn" ${rc.status === 'ready' || rc.status === 'planned' ? '' : 'disabled'} onclick="act({action:'reels_cancel'},()=>setTimeout(rReels,3000))">İptal</button></div>`)}
    </div>` : ''}`;
}
async function chooseReels(produce) {
  const r = document.querySelector('input[name=rc]:checked'); if (!r) { toast('Önce maç seç', true); return; }
  await act({ action: 'reels_choose', code: +r.value, voice: $('#vsel0').value, produce }, () => setTimeout(rReels, 2500));
}
async function loadVoices() {
  $('#vcands').innerHTML = loading('Adaylar yükleniyor');
  const d = await act({ action: 'voice_candidates' }); if (!d.ok) return;
  $('#vcands').innerHTML = '<h3 style="margin-top:12px">Erkek ses adayları</h3>' + d.voices.map(x => `<div class="voice"><audio controls preload="none" src="${x.preview_url}"></audio><div><b>${esc(x.name)}</b> <span class="muted small">${esc(x.accent || '')} · ${esc(x.use_case || '')}</span><div class="small muted">${esc(x.desc)}</div></div>
    <button class="btn sec sm" onclick="act({action:'voice_adopt',owner:'${x.owner}',voice_id:'${x.voice_id}',name:'${esc(x.name.split(' - ')[0])}'},rReels)">Bunu seç</button></div>`).join('');
}

// ---------- Instagram verileri
async function rVeri() {
  const d = await api('/api/stats'); STATS = d;
  if (d.loading) { $('#page').innerHTML = loading('Instagram verileri hazırlanıyor'); setTimeout(() => PAGE === 'veri' && rVeri(), 3000); return; }
  $('#topActions').innerHTML = `<button class="btn sec" onclick="act({action:'insights_now'},()=>setTimeout(rVeri,15000))">Insights çek</button>`;
  const a = d.account, L = a.latest || {};
  const rows = d.media.map(m => `<tr><td>${esc(m.type || 'karusel')}</td><td>${esc(m.home)} – ${esc(m.away)}<div class="small muted">${esc((m.posted_at || '').slice(0, 16).replace('T', ' '))}${m.boosted ? ' · ' + chip('reklam ' + m.ad_tl + ' TL', 'warn') : ''}</div></td>
    <td class="num">${n(m.reach)}</td><td class="num">${n(m.views)}</td><td class="num">${n(m.likes)}</td><td class="num">${n(m.saved)}</td><td class="num">${n(m.shares)}</td><td class="num">${n(m.comments)}</td><td class="num">${m.int_rate != null ? (m.int_rate * 100).toFixed(1) + '%' : '–'}</td></tr>`).join('');
  $('#page').innerHTML = `
    <div class="card"><div class="row"><div class="kpi"><b>${n(L.followers)}</b><span>takipçi</span></div><div class="kpi"><b>${n(L.views_today)}</b><span>görüntülenme (son gün)</span></div><div class="kpi"><b>${n(L.profile_views_today)}</b><span>profil ziyareti</span></div><div class="kpi"><b>${n(L.accounts_engaged_today)}</b><span>etkileşen hesap</span></div><div class="kpi"><b>${n(L.media)}</b><span>gönderi</span></div></div></div>
    <div class="grid2"><div class="card"><h3>Takipçi</h3>${chart(a.days, a.followers, '#0B6B45')}</div><div class="card"><h3>Hesap erişimi <small>günlük, reklam dahil</small></h3>${chart(a.reach_days, a.reach, '#2B5EA7')}</div></div>
    <div class="card"><h3>Gönderiler <small>her gönderinin son ölçümü</small></h3><table><tr><th>Tür</th><th>Maç</th><th class="num">Erişim</th><th class="num">Görüntü</th><th class="num">Beğeni</th><th class="num">Kaydet</th><th class="num">Paylaş</th><th class="num">Yorum</th><th class="num">Etk.</th></tr>${rows || '<tr><td colspan="9" class="muted">veri yok</td></tr>'}</table></div>
    <div class="card"><details><summary>Gönderi zaman serisi</summary><div class="small muted">Bir gönderi seç; bekçi her sabah ölçer, çizgi gün gün erişimi gösterir.</div>
      <select id="serisel" onchange="renderSeries()">${d.media.map(m => `<option value="${m.post_id}">${esc(m.type || 'karusel')} · ${esc(m.home)} – ${esc(m.away)}</option>`).join('')}</select><div id="seri" style="margin-top:8px"></div></details></div>
    <div class="card"><details><summary>Story'ler</summary><table><tr><th>Tür</th><th>Maç</th><th>Zaman</th><th class="num">Erişim</th><th class="num">Görüntü</th><th class="num">İleri</th><th class="num">Geri</th><th class="num">Çıkış</th><th class="num">Yanıt</th></tr>
      ${(d.stories || []).map(s => `<tr><td>${esc(s.type)}</td><td>${esc(s.home)} – ${esc(s.away)}</td><td>${esc((s.posted_at || '').slice(5, 16).replace('T', ' '))}</td><td class="num">${n(s.reach)}</td><td class="num">${n(s.views)}</td><td class="num">${n(s.forward)}</td><td class="num">${n(s.back)}</td><td class="num">${n(s.exit)}</td><td class="num">${n(s.replies)}</td></tr>`).join('') || '<tr><td colspan="9" class="muted">veri yok</td></tr>'}</table>
      <div class="small muted">İleri: sonraki story'ye geçti · çıkış: story'den çıktı (yüksekse sıkıcı) · geri: tekrar baktı (ilgi).</div></details></div>
    <div class="card"><details><summary>Gruplara göre ortalama <span class="muted small">(organik gönderiler)</span></summary><div class="grid2">${Object.entries(d.groups || {}).map(([k, rows]) => `<div><b>${esc(k)}</b><table><tr><th>Grup</th><th class="num">N</th><th class="num">Erişim</th><th class="num">Görüntü</th><th class="num">Kaydet</th><th class="num">Etk.%</th></tr>
      ${rows.map(r => `<tr><td>${esc(r.grup)}</td><td class="num">${r.n}</td><td class="num">${r.erisim}</td><td class="num">${r.goruntu}</td><td class="num">${r.kaydet}</td><td class="num">${r.etk}</td></tr>`).join('')}</table></div>`).join('')}</div><div class="small muted">Az gönderiyle ortalamalar oynaktır; Kasım sonunda ilk sağlıklı karşılaştırma.</div></details></div>
    <div class="card"><details><summary>Hesap, gün gün</summary><table><tr><th>Gün</th><th class="num">Takipçi</th><th class="num">Erişim</th><th class="num">Görüntü</th><th class="num">Profil</th><th class="num">Etkileşen</th><th class="num">Etkileşim</th></tr>
      ${(d.account_table || []).map(r => `<tr><td>${esc(r.day)}</td><td class="num">${n(r.followers)}</td><td class="num">${n(r.reach_day)}</td><td class="num">${n(r.views_today)}</td><td class="num">${n(r.profile_views_today)}</td><td class="num">${n(r.accounts_engaged_today)}</td><td class="num">${n(r.total_interactions_today)}</td></tr>`).join('')}</table></details></div>
    <div class="card"><h3>Reklam kaydı</h3><div class="small muted">Instagram uygulamasından reklam bastığında buraya yaz; rapor bu gönderiyi organik sayılardan ayırır.</div>
      <div class="row" style="margin-top:6px"><select id="adpost">${d.media.map(m => `<option value="${m.post_id}">${esc(m.type || 'karusel')} · ${esc(m.home)} – ${esc(m.away)} (${esc((m.posted_at || '').slice(0, 10))})</option>`).join('')}</select> Bütçe <input type="number" id="adtl" value="200" style="width:80px"> TL · Gün <input type="number" id="addays" value="1" style="width:60px">
        <button class="btn" onclick="act({action:'add_ad',post_id:$('#adpost').value,budget_tl:$('#adtl').value,days:$('#addays').value},()=>setTimeout(rVeri,2000))">Kaydet</button></div>
      <ul class="small muted">${(d.ads || []).map(x => `<li>${esc(x.day)} · ${esc(x.type)} ${esc(x.home)} – ${esc(x.away)} · ${x.budget_tl} TL · ${x.days} gün</li>`).join('') || '<li>kayıt yok</li>'}</ul></div>
    <div class="card"><details><summary>Haftalık iç rapor <span class="muted small">${esc(d.report.name || '')}</span></summary><div class="report">${d.report.html}</div></details></div>`;
  renderSeries();
}
function renderSeries() {
  const d = STATS; if (!d || !$('#serisel')) return;
  const rows = (d.series || {})[$('#serisel').value] || [];
  $('#seri').innerHTML = rows.length ? chart(rows.map(r => r.day), rows.map(r => r.reach), '#0B6B45') + `<table><tr><th>Gün</th><th class="num">Yaş (sa)</th><th class="num">Erişim</th><th class="num">Görüntü</th><th class="num">Beğeni</th><th class="num">Yorum</th><th class="num">Kaydet</th><th class="num">Paylaş</th><th class="num">Takip</th><th class="num">Profil</th></tr>
    ${rows.map(r => `<tr><td>${esc(r.day)}</td><td class="num">${n(r.age_h, 1)}</td><td class="num">${n(r.reach)}</td><td class="num">${n(r.views)}</td><td class="num">${n(r.likes)}</td><td class="num">${n(r.comments)}</td><td class="num">${n(r.saved)}</td><td class="num">${n(r.shares)}</td><td class="num">${n(r.follows)}</td><td class="num">${n(r.profile_visits)}</td></tr>`).join('')}</table>` : '<div class="muted small">ölçüm yok</div>';
}

// ---------- Gelen kutusu
async function rGelen() {
  const d = await api('/api/inbox');
  if (d.loading) { $('#page').innerHTML = loading('Instagram\'dan çekiliyor'); setTimeout(() => PAGE === 'gelen' && rGelen(), 3000); return; }
  if (!d.ok) { $('#page').innerHTML = `<div class="card err">${esc(d.error)}</div>`; return; }
  $('#topActions').innerHTML = `<button class="btn sec" onclick="api('/api/inbox?refresh=1').then(rGelen)">Yenile</button>`;
  const cm = (d.comments || []).map(c => `<div class="cmt ${c.new ? 'new' : ''}"><b>@${esc(c.user)}</b> <span class="muted small">${esc(c.t)} · ${esc(c.post)}${c.permalink ? ` · <a href="${c.permalink}" target="_blank">gönderi</a>` : ''}</span>${c.new ? ' ' + chip('yeni', 'warn') : ''}
      <div>${esc(c.text)}</div>${c.replies.map(r => `<div class="small muted">↳ @${esc(r.user)}: ${esc(r.text)} · ${esc(r.t)}</div>`).join('')}
      <div class="row" style="margin-top:4px"><input type="text" id="cr_${c.id}" placeholder="yanıt…" style="flex:1"><button class="btn sec sm" onclick="act({action:'comment_reply',comment_id:'${c.id}',text:$('#cr_${c.id}').value},rGelen)">Yanıtla</button></div></div>`).join('');
  const ms = (d.messages || []).map(m => `<details ${m.new ? 'open' : ''}><summary>@${esc(m.with)} <span class="muted small">${esc(m.updated)}</span>${m.new ? ' ' + chip('yeni', 'warn') : ''}${m.error ? ` <span class="err">${esc(m.error)}</span>` : ''}</summary>
      <div style="display:flex;flex-direction:column">${m.messages.map(x => `<div class="msg ${x.mine ? 'mine' : ''}"><span class="small muted">${esc(x.from)} · ${esc(x.t)}</span><br>${esc(x.text)}</div>`).join('')}</div>
      <div class="row" style="margin-top:6px"><input type="text" id="dm_${m.id.slice(0, 12)}" placeholder="mesaj…" style="flex:1"><button class="btn sec sm" onclick="act({action:'dm_reply',conversation_id:'${m.id}',text:$('#dm_${m.id.slice(0, 12)}').value},rGelen)">Gönder</button></div></details>`).join('');
  const tg = (d.tags || []).map(x => `<div class="cmt ${x.new ? 'new' : ''}"><b>@${esc(x.user)}</b> <span class="muted small">${esc(x.t)}</span> ${esc(x.caption)} ${x.permalink ? `<a href="${x.permalink}" target="_blank">aç</a>` : ''}</div>`).join('');
  $('#page').innerHTML = `${(d.errors || []).length ? `<div class="card err">${esc(d.errors.join(' · '))}</div>` : ''}
    <div class="card"><h3>Yorumlar <small>${d.comments.length}, yeni ${d.counts.comments}</small> <button class="btn sec sm" onclick="act({action:'inbox_seen',kind:'comments'},rGelen)">Gördüm</button></h3>${cm || '<div class="muted small">Son gönderilerde yorum yok.</div>'}</div>
    <div class="card"><h3>Mesajlar <small>${d.messages.length}, yeni ${d.counts.messages}</small> <button class="btn sec sm" onclick="act({action:'inbox_seen',kind:'messages'},rGelen)">Gördüm</button></h3>${ms || '<div class="muted small">Mesaj yok.</div>'}</div>
    <div class="card"><h3>Etiketlenmeler <small>${d.tags.length}, yeni ${d.counts.tags}</small> <button class="btn sec sm" onclick="act({action:'inbox_seen',kind:'tags'},rGelen)">Gördüm</button></h3>${tg || '<div class="muted small">Etiketlenme yok.</div>'}</div>`;
  badge('#inboxBadge', (d.counts.comments || 0) + (d.counts.messages || 0) + (d.counts.tags || 0));
}
function badge(sel, t) { const b = $(sel); b.style.display = t ? 'inline' : 'none'; b.textContent = t; }
async function pollBadges() {
  try { const d = await api('/api/inbox'); if (d.ok && d.counts) badge('#inboxBadge', (d.counts.comments || 0) + (d.counts.messages || 0) + (d.counts.tags || 0)); } catch (e) { }
  try { const e = await api('/api/events'); if (e.ok && e.counts) badge('#errBadge', e.counts.hata || 0); } catch (e) { }
}

// ---------- Kupon oluştur
let CART = {}, BOARD = null, PL = {}, OL_FILTER = '';
function cartKey(code) { return String(code); }
function togglePick(code, market, pick, odds, label, home, away) {
  const k = cartKey(code);
  if (CART[k] && CART[k].market === market && CART[k].pick === pick) delete CART[k]; else CART[k] = { code, market, pick, odds, label, home, away };
  rOlustur(true);
}
function cartSummary() {
  const legs = Object.values(CART); if (!legs.length) return '<div class="muted small">Soldan oran seçerek kupon kur.</div>';
  let total = 1; legs.forEach(l => total *= l.odds);
  const src = k => { const m = BOARD.matches; let p = 1, ok = true; legs.forEach(l => { const mm = m.find(x => x.code == l.code); const v = l.market === 'GOL' ? null : (((mm || {}).markets || {})[l.market] || {})[l.pick]; if (!v || v[k] == null) ok = false; else p *= v[k] / 100; }); return ok ? (p * 100).toFixed(1) : null; };
  const pa = src('ai'), ps = src('stat'), pp = src('pin');
  const ev = p => p ? ((total * p / 100 - 1) * 100).toFixed(0) : null;
  return `${legs.map(l => `<div class="row" style="justify-content:space-between;border-bottom:1px solid var(--line);padding:4px 0"><span class="small"><b>${esc(l.home)} – ${esc(l.away)}</b><br>${esc(l.label)}</span><span><b>${l.odds}</b> <a href="#" onclick="delete CART['${cartKey(l.code)}'];rOlustur(true);return false" style="color:#C8423A">✕</a></span></div>`).join('')}
    <div style="margin-top:8px"><b>${legs.length} maç · toplam oran ${total.toFixed(2)}</b></div>
    <div class="small">Tutma ihtimali: <span class="src-ai">biz ${pa ? '%' + pa : '–'}</span> · <span class="src-stat">istatistik ${ps ? '%' + ps : '–'}</span> · <span class="src-pin">piyasa ${pp ? '%' + pp : '–'}</span></div>
    <div class="small muted">Beklenen değer: biz ${ev(pa) != null ? ev(pa) + '%' : '–'} · istatistik ${ev(ps) != null ? ev(ps) + '%' : '–'} · piyasa ${ev(pp) != null ? ev(pp) + '%' : '–'} <span title="(toplam oran × ihtimal − 1); artı ise oran ihtimale göre cömert">ⓘ</span></div>
    <div class="row" style="margin-top:8px"><input type="text" id="cname" placeholder="kupon adı (isteğe bağlı)" style="flex:1"><input type="number" id="cstake" placeholder="TL" style="width:70px"></div>
    <div class="row" style="margin-top:8px"><button class="btn" onclick="saveCoupon(true)">Kaydet ve yorumlat</button><button class="btn sec" onclick="saveCoupon(false)">Sadece kaydet</button><button class="btn sec sm" onclick="CART={};rOlustur(true)">Temizle</button></div>`;
}
async function saveCoupon(review) {
  const legs = Object.values(CART).map(l => ({ code: l.code, market: l.market, pick: l.pick }));
  if (!legs.length) { toast('Kupon boş', true); return; }
  const d = await act({ action: 'coupon_save', legs, review, name: $('#cname').value, stake_tl: $('#cstake').value });
  if (d.ok) { CART = {}; rOlustur(); }
}
function pickCell(m, mk, pk, label) {
  const v = (m.markets[mk] || {})[pk]; if (!v) return '<span class="pick" style="opacity:.35">–</span>';
  const on = CART[cartKey(m.code)] && CART[cartKey(m.code)].market === mk && CART[cartKey(m.code)].pick === pk;
  return `<span class="pick ${on ? 'on' : ''}" onclick="togglePick(${m.code},'${mk}','${pk}',${v.odds},'${esc(label)}','${esc(m.home)}','${esc(m.away)}')" title="${esc(label)}"><b>${v.odds}</b><span class="p"><span class="src-ai">${v.ai != null ? v.ai : '·'}</span> <span class="src-stat">${v.stat != null ? v.stat : '·'}</span> <span class="src-pin">${v.pin != null ? v.pin : '·'}</span></span></span>`;
}
async function loadPlayers(code) {
  const row = $('#plr' + code), box = $('#pl' + code); if (!box) return;
  if (box.dataset.open === '1') { row.style.display = 'none'; box.dataset.open = '0'; return; }
  row.style.display = ''; box.dataset.open = '1'; box.innerHTML = loading('Golcüler ve son 5 maç alınıyor (ESPN)');
  const d = PL[code] || await api('/api/kupon_players?code=' + code); PL[code] = d;
  const m = BOARD.matches.find(x => x.code == code);
  const oddBtn = (name, o) => { const on = CART[cartKey(code)] && CART[cartKey(code)].market === 'GOL' && CART[cartKey(code)].pick === name; return o ? `<span class="pick ${on ? 'on' : ''}" style="min-width:58px" onclick="togglePick(${code},'GOL','${esc(name)}',${o},'${esc(name)} gol atar','${esc(m.home)}','${esc(m.away)}')"><b>${o}</b></span>` : '<span class="muted small">–</span>'; };
  const teamBox = t => `<div><h4 style="margin:4px 0 6px">${esc(t.team)} <span class="muted small">${t.home ? 'ev sahibi' : 'deplasman'}</span></h4>
    <table><tr><th>Oyuncu</th><th class="num">Gol</th><th class="num">Asist</th><th class="num">Maç</th><th class="num">Son 5'te gol</th><th>Gol atar</th></tr>
    ${t.players.map(p => `<tr><td>${esc(p.player)}${p.form_only ? ' <span class="chip warn" title="sezon ilk üçte değil, son 5 maçta gol attı">form</span>' : ''}</td><td class="num">${p.goals != null ? p.goals : '–'}</td><td class="num">${p.assists != null ? p.assists : '–'}</td><td class="num">${p.matches != null ? p.matches : '–'}</td><td class="num">${p.last5_goals}</td><td>${oddBtn(p.player, p.odds)}</td></tr>`).join('')}</table>
    <div class="small muted" style="margin-top:6px">Son 5 maç: ${t.last5.map(g => `<span class="chip" title="${esc(g.scorers.join(', ') || 'gol yok')}">${esc(g.score)}</span>`).join(' ') || '–'}${t.error ? ' · ' + esc(t.error) : ''}</div></div>`;
  const other = (d.players_odds || []).filter(p => !(d.teams || []).some(t => t.players.some(q => q.player === p.player)));
  box.innerHTML = `<div class="card" style="background:#F7F9F8;margin:0">${d.note ? `<div class="muted small">${esc(d.note)}</div>` : ''}
    <div class="grid2">${(d.teams || []).map(teamBox).join('')}</div>
    ${other.length ? `<details style="margin-top:8px"><summary class="small">Diğer oyuncular · gol atar oranı (${other.length})</summary><div class="row" style="margin-top:6px">${other.map(p => `<span class="row" style="gap:4px;font-size:13px">${esc(p.player)} ${oddBtn(p.player, p.odds)}</span>`).join('')}</div></details>` : ''}
    <div class="small muted" style="margin-top:6px">Gol ve asist: bu sezon (ESPN). Son 5: takımın son 5 maçı; skorun üstüne gelince gol atanlar görünür. Oran: Nesine "oyuncu gol atar".</div></div>`;
}
async function rOlustur(keep) {
  if (!keep || !BOARD) {
    $('#topActions').innerHTML = `<input type="text" placeholder="takım / lig ara" oninput="OL_FILTER=this.value.toLowerCase();rOlustur(true)" value="${esc(OL_FILTER)}"><button class="btn sec" onclick="BOARD=null;rOlustur()">Yenile</button>`;
    const d = await api('/api/kupon_board');
    if (d.loading) { $('#page').innerHTML = loading('Bülten ve ihtimaller hazırlanıyor'); setTimeout(() => PAGE === 'olustur' && rOlustur(), 2500); return; }
    BOARD = d;
  }
  const open = {}; document.querySelectorAll('td[id^=pl]').forEach(b => { if (b.dataset.open === '1') open[b.id] = b.innerHTML; });
  const ms = BOARD.matches.filter(m => !OL_FILTER || (m.home + ' ' + m.away + ' ' + m.league).toLowerCase().includes(OL_FILTER));
  const rows = ms.map(m => `<tr><td><b>${esc(m.home)} – ${esc(m.away)}</b><div class="small muted">${esc(m.start)} · ${esc(m.league)}${m.analysis ? ' · <span class="chip ok">analiz var</span>' : ''}</div>${m.hook ? `<div class="small muted">${esc(m.hook)}</div>` : ''}
      <div style="margin-top:4px"><button class="btn sec sm" onclick="loadPlayers(${m.code})">Golcüler${m.players_odds.length ? ' · ' + m.players_odds.length + ' oran' : ''}</button></div></td>
    <td class="odds">${pickCell(m, 'MS', '1', 'Ev')}${pickCell(m, 'MS', 'X', 'Beraberlik')}${pickCell(m, 'MS', '2', 'Deplasman')}</td>
    <td class="odds">${pickCell(m, 'AU25', 'Alt', '2,5 alt')}${pickCell(m, 'AU25', 'Üst', '2,5 üst')}</td>
    <td class="odds">${pickCell(m, 'KG', 'Var', 'KG var')}${pickCell(m, 'KG', 'Yok', 'KG yok')}</td></tr>
    <tr id="plr${m.code}" style="display:none"><td colspan="4" id="pl${m.code}" style="padding:6px 8px 12px"></td></tr>`).join('');
  $('#page').innerHTML = `<div style="display:grid;grid-template-columns:minmax(0,1fr) 270px;gap:14px"><div style="min-width:0">
    <div class="card legend"><span class="src-ai">■ bizim yapay zekâ</span><span class="src-stat">■ istatistik modeli</span><span class="src-pin">■ piyasa (Pinnacle)</span><span class="muted">rakamlar: ihtimal % · bülten ${esc(BOARD.t)} · ${ms.length} maç</span></div>
    <div class="card" style="overflow-x:auto"><table><tr><th>Maç</th><th>Maç sonucu (1 · X · 2)</th><th>2,5 gol (alt · üst)</th><th>Karşılıklı gol (var · yok)</th></tr>${rows || '<tr><td colspan="4" class="muted">maç yok</td></tr>'}</table></div>
    <div class="card"><h3>Kuponlarım</h3><div id="mycoupons">${loading()}</div></div></div>
    <div><div class="card cart"><h3>Kupon</h3>${cartSummary()}</div></div></div>`;
  Object.entries(open).forEach(([id, html]) => { const b = document.getElementById(id); if (b) { b.dataset.open = '1'; b.innerHTML = html; const r = document.getElementById('plr' + id.slice(2)); if (r) r.style.display = ''; } });
  loadMyCoupons();
  const pl0 = new URLSearchParams(location.search).get('pl'); if (pl0 && !keep) setTimeout(() => loadPlayers(+pl0), 300);
}
async function loadMyCoupons() {
  const d = await api('/api/kuponlarim'); const box = $('#mycoupons'); if (!box) return;
  box.innerHTML = (d.coupons || []).map(c => `<details ${c.review ? '' : ''}><summary>${esc(c.name)} · ${c.n} maç · oran ${c.odds} ${c.result === 'won' ? chip('tuttu', 'ok') : c.result === 'lost' ? chip('tutmadı', 'bad') : chip('bekliyor' + (c.legs_hit ? ' ' + c.legs_hit + '/' + c.n : ''))} <span class="muted small">${esc(c.when)}${c.stake_tl ? ' · ' + c.stake_tl + ' TL' : ''}</span></summary>
    <table>${c.legs.map(l => `<tr><td>${esc(l.home)} – ${esc(l.away)}<div class="small muted">${esc(l.start)}${l.score ? ' · ' + esc(l.score) : ''}</div></td><td>${esc(l.label)}</td><td class="num">${l.odds}</td><td class="small"><span class="src-ai">${l.ai != null ? '%' + l.ai : ''}</span> <span class="src-stat">${l.stat != null ? '%' + l.stat : ''}</span> <span class="src-pin">${l.pin != null ? '%' + l.pin : ''}</span></td><td>${l.result === 'won' ? '✓' : l.result === 'lost' ? '✗' : '…'}</td></tr>`).join('')}</table>
    <div class="small">İhtimal: <span class="src-ai">biz ${c.probs.ai != null ? '%' + c.probs.ai : '–'}</span> · <span class="src-stat">istatistik ${c.probs.stat != null ? '%' + c.probs.stat : '–'}</span> · <span class="src-pin">piyasa ${c.probs.pin != null ? '%' + c.probs.pin : '–'}</span></div>
    ${c.review ? `<div class="card" style="background:#F7F9F8;margin-top:8px"><b>Yapay zekâ yorumu</b> <span class="muted small">güven ${(c.review.confidence * 100).toFixed(0)}% · $${c.review.cost_usd}</span><p style="margin:6px 0">${esc(c.review.comment)}</p><div class="small">En zayıf bacak: ${esc(c.review.weakest)}</div>
      ${(c.review.legs || []).map(x => `<div class="small">${chip(x.verdict, x.verdict === 'sağlam' ? 'ok' : x.verdict === 'riskli' ? 'bad' : 'warn')} ${esc(x.match)}: ${esc(x.note)}</div>`).join('')}</div>`
      : `<div class="row" style="margin-top:6px"><button class="btn sec sm" onclick="act({action:'coupon_review',id:${c.id}},()=>setTimeout(loadMyCoupons,8000))">Yapay zekâ yorumu al</button></div>`}
    <div class="row" style="margin-top:6px"><button class="btn warn sm" onclick="if(confirm('Silinsin mi?'))act({action:'coupon_delete',id:${c.id}},loadMyCoupons)">Sil</button></div></details>`).join('') || '<div class="muted small">Henüz kupon yok.</div>';
}

// ---------- Kupon
async function rKupon() {
  const d = await api('/api/kupon');
  if (d.loading) { $('#page').innerHTML = loading(); setTimeout(() => PAGE === 'kupon' && rKupon(), 2000); return; }
  const c = d.coupons, al = d.alerts;
  const summ = c.summary.map(s => `<div class="kpi"><b>${s.won}/${s.total}</b><span>${esc(s.kind)} tuttu · 1 birimle net ${s.pnl > 0 ? '+' : ''}${s.pnl}</span></div>`).join('') || '<span class="muted">Henüz sonuçlanmış kupon yok.</span>';
  const items = c.items.map(x => `<details><summary>#${x.no} · ${esc(x.kind)} · ${x.n} maç · oran ${x.odds} · ihtimal %${x.prob} ${x.result === 'won' ? chip('tuttu', 'ok') : x.result === 'lost' ? chip('tutmadı', 'bad') : chip(`bekliyor ${x.legs_hit}/${x.n}`)} <span class="muted small">${esc(x.t)}</span></summary>
    <table>${x.legs.map(l => `<tr><td>${esc(l.home)} – ${esc(l.away)}<div class="small muted">${esc(l.start)}${l.score ? ' · skor ' + esc(l.score) : ''}</div></td><td>${esc(l.pick)}</td><td class="num">${l.odds}</td><td>${l.result === 'won' ? '✓' : l.result === 'lost' ? '✗' : '…'}</td></tr>`).join('')}</table></details>`).join('');
  const alst = al.stats ? `<div class="kpi"><b>${al.stats.settled}</b><span>sonuçlanmış uyarı · net ${al.stats.pnl} birim (ROI ${al.stats.roi}%)</span></div>${al.stats.clv_avg != null ? `<div class="kpi"><b>${al.stats.clv_avg > 0 ? '+' : ''}${al.stats.clv_avg}%</b><span>ortalama kapanış farkı (CLV)</span></div>` : ''}` : '<span class="muted">Henüz uyarı yok (gözcü bulunca yazar).</span>';
  const alrows = al.items.map(a => `<tr><td>${esc(a.t)}</td><td>${esc(a.home)} – ${esc(a.away)}</td><td>${esc(a.pick)}</td><td class="num">${a.nesine}</td><td class="num">${a.fair}</td><td class="num">+${a.ev_pct}%</td><td>${a.result === 'won' ? chip('tuttu', 'ok') : a.result === 'lost' ? chip('tutmadı', 'bad') : '…'}${a.clv_pct != null ? ` <span class="muted small">CLV ${a.clv_pct > 0 ? '+' : ''}${a.clv_pct}%</span>` : ''}</td></tr>`).join('');
  $('#page').innerHTML = `<div class="card"><h3>Kuponlar <small>${c.total} kilitli, ${c.settled} sonuçlanmış</small></h3><div class="row">${summ}</div></div>
    <div class="card">${items || '<span class="muted">kupon yok</span>'}</div>
    <div class="card"><h3>Gözcü uyarıları <small>${al.total}</small></h3><div class="row">${alst}</div>${alrows ? `<table style="margin-top:8px"><tr><th>Zaman</th><th>Maç</th><th>Seçim</th><th class="num">Nesine</th><th class="num">Adil</th><th class="num">Değer</th><th>Sonuç</th></tr>${alrows}</table>` : ''}</div>
    <div class="card"><h3>Skorlar <small>son 2 gün</small></h3><table>${d.results.map(r => `<tr><td>${esc(r.day)}</td><td>${esc(r.home)} – ${esc(r.away)}</td><td class="num">${esc(r.score)}</td></tr>`).join('') || '<tr><td class="muted">yok</td></tr>'}</table></div>`;
}

// ---------- Günlük
async function rGunluk() {
  $('#topActions').innerHTML = `Göster: <select onchange="EV.level=this.value;rGunluk()"><option value="" ${!EV.level ? 'selected' : ''}>hepsi</option><option value="hata" ${EV.level === 'hata' ? 'selected' : ''}>yalnız hatalar</option><option value="uyarı" ${EV.level === 'uyarı' ? 'selected' : ''}>yalnız uyarılar</option></select>
    <select onchange="EV.days=+this.value;rGunluk()">${[1, 3, 7, 14].map(x => `<option value="${x}" ${EV.days === x ? 'selected' : ''}>${x} gün</option>`).join('')}</select><button class="btn sec" onclick="api('/api/events?refresh=1').then(rGunluk)">Yenile</button>`;
  const d = await api(`/api/events?days=${EV.days}&level=${encodeURIComponent(EV.level)}`);
  if (d.loading) { $('#page').innerHTML = loading('Günlük hazırlanıyor (GitHub logları taranıyor, ilk seferde 20-40 sn)'); setTimeout(() => PAGE === 'gunluk' && rGunluk(), 4000); return; }
  const c = d.counts || {};
  $('#page').innerHTML = `<div class="card"><div class="row"><div class="kpi bad"><b>${c.hata || 0}</b><span>hata</span></div><div class="kpi warn"><b>${c['uyarı'] || 0}</b><span>uyarı</span></div><div class="kpi"><b>${c.bilgi || 0}</b><span>bilgi</span></div><span class="muted small">GitHub logları ${d.meta && d.meta.age != null ? d.meta.age + ' sn önce' : ''} tarandı</span></div></div>
    <div class="card">${(d.events || []).map(e => `<div class="ev ${cls(e.level)}"><span class="muted">${esc(e.when)}</span><span class="lv">${esc(e.level)}</span><span>${esc(e.source)}</span><span>${esc(e.text)}${e.link ? ` <a href="${e.link}" target="_blank">↗</a>` : ''}</span></div>`).join('') || '<div class="muted">olay yok</div>'}</div>`;
  badge('#errBadge', c.hata || 0);
}

// ---------- Sistem
function rSistem() {
  const Y = S && S.system;
  if (!Y || Y.loading) { $('#page').innerHTML = loading('GitHub çalışmaları alınıyor'); return; }
  const openLog = $('#runlog') && $('#runlog').style.display === 'block' ? $('#runlog').textContent : null;
  const k = Y.keeper, q = Y.quota, s = Y.spend, t = Y.ig_token || {};
  const ST = { in_progress: ['çalışıyor', 'info'], queued: ['sırada', ''], pending: ['sırada', ''], success: ['başarılı', 'ok'], failure: ['HATA', 'bad'], cancelled: ['iptal', 'warn'], skipped: ['atlandı', ''] };
  $('#topActions').innerHTML = `<button class="btn sec" onclick="act({action:'workflow',name:'keeper.yml'})">Bekçiyi çalıştır</button><button class="btn sec" onclick="act({action:'workflow',name:'watch.yml'})">Gözcüyü çalıştır</button><button class="btn sec" onclick="act({action:'workflow',name:'results.yml'})">Skorları çalıştır</button><button class="btn sec" onclick="act({action:'retry_push'})">Yeniden it</button>`;
  $('#page').innerHTML = `
    <div class="grid3">
      <div class="card"><h3>Bekçi</h3>${k.running ? chip('çalışıyor', 'ok') : chip('çalışmıyor', 'bad')}<div class="small muted" style="margin-top:6px">son kayıt ${esc(k.last || '–')} (${k.age_min ?? '–'} dk önce)<br>sabah analizi ${esc(k.claude_morning || '–')} · insights ${esc(k.insights_day || '–')}</div></div>
      <div class="card"><h3>Kota ve harcama</h3><div class="small">Odds API kalan <b>${q.remaining}</b> istek · bugün ${q.spent_today}<br>Yapay zekâ bugün <b>$${s.ai_today_usd}</b> · bu ay $${s.ai_month_usd}${s.eleven_limit ? `<br>ElevenLabs ${s.eleven_used}/${s.eleven_limit} karakter (sıfırlama ${esc(s.eleven_reset)})` : ''}
        ${(() => { const h = s.higgsfield || {}; return `<br>Higgsfield ${h.remaining != null ? `tahmini kalan <b>$${h.remaining}</b> (giriş $${h.balance_entered}, ${esc(h.entered_at)}; sonra ${h.clips_since} klip ≈ $${h.spent_since})` : 'bakiye girilmedi'} · bu ay ${h.month_clips || 0} klip ≈ $${h.month_spent || 0}
        <div class="row" style="margin-top:4px"><input type="number" step="0.1" id="hfbal" placeholder="bakiye $" style="width:110px"><button class="btn sec sm" title="Higgsfield hesabındaki bakiyeyi yaz; panel üretilen klipleri düşerek kalanı tahmin eder" onclick="act({action:'set_balance',service:'higgsfield',amount:$('#hfbal').value})">Bakiyeyi kaydet</button></div>`; })()}</div></div>
      <div class="card"><h3>Instagram belirteci</h3>${t.valid === false ? chip('GEÇERSİZ', 'bad') : t.valid ? chip('geçerli', 'ok') : chip('bilgi yok', 'warn')}<div class="small muted" style="margin-top:6px">${esc(t.expires || '')}${t.username ? ' · @' + esc(t.username) : ''}</div></div>
    </div>
    ${(Y.errors || []).length ? `<div class="card err">${esc(Y.errors.join(' · '))}</div>` : ''}
    <div class="card"><h3>GitHub çalışmaları</h3><table><tr><th>İş akışı</th><th>Durum</th><th>Başlangıç</th><th>Süre</th><th></th></tr>
      ${Y.runs.map(r => { const st = ST[r.status === 'completed' ? r.conclusion : r.status] || [r.conclusion || r.status, '']; return `<tr><td>${esc(r.name)}</td><td>${chip(st[0], st[1])}</td><td>${esc(r.started)}</td><td>${r.minutes} dk</td>
        <td><a href="${r.url}" target="_blank">GitHub</a> · <a href="#" onclick="showLog(${r.id});return false">log</a>${r.status === 'in_progress' ? ` · <a href="#" style="color:#C8423A" onclick="if(confirm('Bu çalışma iptal edilsin mi?'))act({action:'cancel_run',run_id:${r.id}});return false">iptal</a>` : ''}</td></tr>`; }).join('')}</table>
      <pre class="log" id="runlog" style="display:none"></pre></div>`;
  if (openLog !== null) { $('#runlog').style.display = 'block'; $('#runlog').textContent = openLog; }
}
async function showLog(id) {
  const pre = $('#runlog'); pre.style.display = 'block'; pre.textContent = 'Log alınıyor…';
  const d = await api('/api/log/' + id); pre.textContent = d.ok ? d.lines.join('\n') : ('Hata: ' + d.error); pre.scrollTop = pre.scrollHeight;
}

// ---------- başlat
const p0 = new URLSearchParams(location.search).get('tab');
tick().then(() => open(p0 && TITLE[p0] ? p0 : 'genel'));
setInterval(tick, 5000); pollBadges(); setInterval(pollBadges, 120000);
