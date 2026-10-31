const $ = s => document.querySelector(s);
let S = null, TAB = 'bugun', CONTENT_CODE = null, CONTENT = null, REELS = null;
const RS = { posted: 'yayında', ready: 'hazır, saat bekliyor', planned: 'seçildi (üretilmedi)', cancelled: 'iptal', error: 'HATA' };

document.querySelectorAll('nav button').forEach(b => b.onclick = () => openTab(b.dataset.tab));
function openTab(t) {
  document.querySelectorAll('nav button,.tab').forEach(x => x.classList.remove('on'));
  document.querySelector(`nav button[data-tab="${t}"]`).classList.add('on'); $('#tab-' + t).classList.add('on'); TAB = t;
  if (t === 'icerik') loadContent(); if (t === 'reels') loadReels(); if (t === 'istatistik') loadStats(); if (t === 'kupon') loadKupon();
  if (t === 'gelen') loadInbox(); if (t === 'gunluk') loadEvents();
}
function toast(msg, bad) {
  const t = $('#toast'); t.textContent = msg; t.style.display = 'block';
  t.style.background = bad ? '#D9534F' : '#FFCF4D'; t.style.color = bad ? '#fff' : '#0B2A1F';
  setTimeout(() => t.style.display = 'none', bad ? 6000 : 3500);
}
async function act(body, after) {
  const r = await fetch('/api/action', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const d = await r.json(); toast(d.ok ? (d.msg || 'Tamam') : ('Hata: ' + (d.error || '')), !d.ok); refresh(); if (after) after(d); return d;
}
function esc(s) { return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
function zoom(src) { const o = document.createElement('div'); o.id = 'overlay'; o.innerHTML = `<img src="${src}">`; o.onclick = () => o.remove(); document.body.appendChild(o); }
function cls(s) { return String(s).replace(/ı/g, 'i').replace(/ş/g, 's').replace(/ç/g, 'c'); }
function n(x, d = 0) { return (x === null || x === undefined || x === '') ? '–' : Number(x).toFixed(d); }
function renderJobs(jobs) {
  $('#jobs').innerHTML = '<h3>İşler <span class="meta">(arka planda çalışanlar; hata olursa burada yazar)</span></h3>' + (jobs.length ? jobs.map(j =>
    `<div class="job ${cls(j.status)}"><b>${esc(j.name)}</b> · ${esc(j.status)} ${j.started ? esc(j.started) : ''}${j.ended ? '–' + esc(j.ended) : ''}\n${esc(j.lines.slice(-10).join('\n'))}</div>`).join('')
    : '<div class="meta">İş yok</div>');
}
function stateClass(s) { return { 'planlı': 'planli', 'yayında': 'yayinda', 'atlandı': 'atlandi', 'durduruldu': 'durdu' }[s] || ''; }

// ---------------- Bugün ----------------
function renderToday(T) {
  if (!T || !T.day) { $('#matches').textContent = 'Veri yok'; return; }
  const w = T.watch || {};
  $('#pause').innerHTML = `<div class="card"><b>${T.day}</b> · karusel ${T.sent_count}/${T.max_per_day} · gözcü: ${esc(w.note || (w.active ? 'açık' : 'kapalı'))}
    <span class="btns" style="float:right;max-width:none">${T.paused_until
      ? `<span class="state durdu">Durduruldu, ${esc(T.paused_until.slice(11, 16))} kadar</span> <button class="act" onclick="act({action:'pause',until:null})">Aç</button>`
      : `<button class="act warn" title="Gece yarısına kadar karusel, reels ve story gönderilmez" onclick="act({action:'pause',until:'today'})">Bugün durdur</button>`}
    <button class="act" title="instagram.py'yi bu bilgisayarda hemen çalıştırır; saati gelmiş gönderi varsa gider" onclick="act({action:'instagram_now'})">Instagram'ı şimdi çalıştır</button></span>
    ${T.errors.length ? `<div class="err">${esc(T.errors.join(' · '))}</div>` : ''}</div>`;
  $('#matches').innerHTML = T.matches.length ? T.matches.map(m => {
    const c = m.cards, p = m.post, s = m.stories;
    const thumbs = ['match', 'yorum', 'story', 'devre', 'ft'].filter(k => c[k]).map(k => `<img src="${c[k]}" title="${k}" onclick="zoom('${c[k]}')">`).join('');
    const reels = m.reels ? `<div class="meta">Reels: ${esc(RS[m.reels.status] || m.reels.status)} ${esc(m.reels.at || '')}${m.reels.url ? ` · <a href="${m.reels.url}" target="_blank">aç</a>` : ''}</div>` : '';
    const editable = !(p.state === 'yayında' || p.state === 'süre geçti');
    return `<div class="card match"><div class="thumbs">${thumbs || '<div class="meta">kart yok</div>'}</div>
      <div><h3>${esc(m.home)} – ${esc(m.away)} <span class="meta">${esc(m.kickoff)} · ${esc(m.league)} · kademe ${m.tier}${m.analysis ? ' · analiz var' : ''}</span></h3>
        <div>Karusel: <span class="state ${stateClass(p.state)}">${esc(p.state)}${p.at ? ' ' + esc(p.at) : ''}</span>${p.override_at ? ` <span class="meta">(panel: ${esc(p.override_at)})</span>` : ''}${p.url ? ` · <a href="${p.url}" target="_blank">aç</a>` : ''}
          ${m.analysis ? ` · <a href="#" onclick="openContent(${m.code});return false">içeriği düzenle</a>` : ''}</div>
        <div class="meta">Story: kadro ${esc(s.kadro)} · devre ${esc(s.devre)} · maç sonu ${esc(s.ft)}</div>${reels}</div>
      <div class="btns">
        ${editable ? `<input type="time" value="${esc(p.override_at || p.at || '')}" id="t${m.code}" title="Karusel saati (TSİ)"><button class="act" onclick="act({action:'set_time',code:${m.code},at:$('#t${m.code}').value})">Saati yaz</button>
        <button class="act ${p.skip ? '' : 'warn'}" onclick="act({action:'skip',code:${m.code},skip:${!p.skip}})">${p.skip ? 'Atlamayı geri al' : 'Atla'}</button>` : ''}
        <button class="act ${s.skip ? '' : 'warn'}" onclick="act({action:'story_skip',code:${m.code},skip:${!s.skip}})">${s.skip ? "Story'leri aç" : "Story'leri atla"}</button>
      </div></div>`;
  }).join('') : '<div class="card meta">Bugün listelenecek maç yok</div>';
}

// ---------------- İçerik ----------------
function openContent(code) { CONTENT_CODE = code; openTab('icerik'); }
async function loadContent() {
  const ms = (S && S.today && S.today.matches || []).filter(m => m.analysis);
  if (!CONTENT_CODE && ms.length) CONTENT_CODE = ms[0].code;
  const sel = `<div class="card">Maç: <select id="csel" onchange="CONTENT_CODE=+this.value;loadContent()">${ms.map(m => `<option value="${m.code}" ${m.code == CONTENT_CODE ? 'selected' : ''}>${esc(m.home)} – ${esc(m.away)} ${esc(m.kickoff)}</option>`).join('')}</select>
    ${ms.length ? '' : '<span class="meta">Bugün analizli maç yok</span>'}</div>`;
  if (!CONTENT_CODE) { $('#content').innerHTML = sel; return; }
  $('#content').innerHTML = sel + '<div class="card meta">Yükleniyor…</div>';
  const d = await (await fetch('/api/content?code=' + CONTENT_CODE)).json(); CONTENT = d;
  if (!d.ok) { $('#content').innerHTML = sel + `<div class="card err">${esc(d.error)}</div>`; return; }
  const dis = d.posted ? 'disabled' : '';
  const fields = Object.keys(d.fields).map(k => `<label class="f">${esc(d.field_names[k] || k)}</label><textarea id="f_${k}" ${dis} rows="${k === 'comment' ? 7 : 2}">${esc(d.fields[k])}</textarea>`).join('');
  $('#content').innerHTML = sel + `<div class="card"><h3>${esc(d.home)} – ${esc(d.away)} <span class="meta">${esc(d.day)} · sürüm ${d.revision}${d.cost_usd ? ` · analiz maliyeti $${d.cost_usd}` : ''}${d.edited_at ? ' · düzenlendi' : ''}</span></h3>
    ${d.posted ? '<div class="err">Bu gönderi Instagram\'da yayınlandı; metinler değiştirilemez (Instagram düzenlemeyi kabul etmez). Yalnız görüntüleme.</div>' : ''}
    ${d.note ? `<div class="meta">Son yeniden çalıştırma notu: ${esc(d.note)}</div>` : ''}
    <div class="grid2"><div>
      <label class="f">Açıklama (Instagram'daki metin) ${d.caption_override ? '<span class="ok">· senin düzenlemen</span>' : '<span class="meta">· otomatik üretildi</span>'}</label>
      <textarea id="cap" rows="14" ${dis}>${esc(d.caption_override || d.caption)}</textarea>
      <div class="btns" style="justify-content:flex-start;max-width:none;margin-top:6px">
        <button class="act main" ${dis} onclick="saveContent(true)">Açıklamayı kaydet</button>
        <button class="act" ${dis} title="Senin düzenlemeni siler, otomatik metin kullanılır" onclick="clearCaption()">Otomatik metne dön</button></div>
      <div class="thumbs" style="margin-top:10px">${Object.values(d.cards).map(u => `<img src="${u}?t=${Date.now()}" style="width:130px" onclick="zoom('${u}?t=${Date.now()}')">`).join('')}</div>
    </div><div>
      ${fields}
      <div class="btns" style="justify-content:flex-start;max-width:none;margin-top:8px">
        <button class="act main" ${dis} onclick="saveContent(false)">Kart yazılarını kaydet</button>
        <button class="act" ${dis} title="Kaydedilen yazılarla günün kartlarını yeniden çizer (yerelde, ücretsiz)" onclick="act({action:'content_regen',code:${d.code}},()=>setTimeout(loadContent,4000))">Kartı yeniden üret</button>
        <button class="act" ${dis} title="Kart dosyalarını ve düzenlenmiş kaydı GitHub'a iter; bekçi bunları kullanır" onclick="act({action:'content_publish',code:${d.code}})">Yayına yaz</button></div>
      <label class="f">Yeniden çalıştırma notu (yapay zekâya: neye dikkat etsin?)</label>
      <input type="text" id="note" style="width:100%" ${dis} placeholder="örn. kaleci sakatlığı haberi var, kontrol et">
      <div class="btns" style="justify-content:flex-start;max-width:none;margin-top:6px">
        <button class="act warn" ${dis} title="Ücretli: yapay zekâ maçı yeniden araştırır, kayıt ve kartlar yenilenir" onclick="rerun(${d.code})">Analizi yeniden çalıştır (~$${d.est_cost})</button></div>
    </div></div></div>`;
}
async function saveContent(cap) {
  const body = { action: 'content_save', code: CONTENT_CODE };
  if (cap) body.caption_override = $('#cap').value; else body.fields = Object.fromEntries(Object.keys(CONTENT.fields).map(k => [k, $('#f_' + k).value]));
  await act(body, loadContent);
}
async function clearCaption() { await act({ action: 'content_save', code: CONTENT_CODE, caption_override: '' }, loadContent); }
async function rerun(code) {
  const note = $('#note').value;
  if (!confirm('Analiz yeniden çalıştırılsın mı? Ücretli (yaklaşık $' + CONTENT.est_cost + '). Eski kayıt saklanır, yeni sürüm geçerli olur.')) return;
  await act({ action: 'content_rerun', code, note }, () => setTimeout(loadContent, 5000));
}

// ---------------- Reels ----------------
async function loadReels() {
  const d = await (await fetch('/api/reels')).json(); REELS = d;
  const st = d.state || {}, rc = d.control || {}, v = d.voices || {};
  const cands = d.candidates.map(c => `<label style="display:block"><input type="radio" name="rc" value="${c.code}" ${st.code == c.code ? 'checked' : ''}> ${esc(c.home)} – ${esc(c.away)} <span class="meta">${esc(c.kickoff)} · kademe ${c.tier}</span>${d.posted[c.code] ? ' <span class="tag won">yayında</span>' : ''}</label>`).join('');
  const vopts = ['ahu', 'erkek'].filter(k => v[k]).map(k => `<option value="${k}" ${(st.voice || d.default_voice) === k ? 'selected' : ''}>${esc(v[k].name)}</option>`).join('');
  const ctl = rc.status ? `<div>Bekçi durumu: <span class="state ${rc.status === 'posted' ? 'yayinda' : rc.status === 'error' || rc.status === 'cancelled' ? 'durdu' : 'planli'}">${esc(RS[rc.status] || rc.status)}</span>
     ${rc.at ? ' · saat ' + esc(rc.at) : ''}${rc.error ? `<div class="err">${esc(rc.error)}</div>` : ''}${rc.post_id ? ` · gönderi ${esc(rc.post_id)}` : ''}</div>` : '<div class="meta">Bugün için reels seçilmedi.</div>';
  const steps = st.code ? `
    <div class="card"><h4>1. Metin</h4>${st.text ? `<p>${esc(st.text)}</p><div class="meta">${st.text.split(' ').length} kelime · metni İçerik sekmesinden (reels seslendirme metni) düzeltebilirsin</div>` : '<span class="meta">henüz üretilmedi</span>'}
      <div class="btns" style="justify-content:flex-start;max-width:none;margin-top:6px"><button class="act" onclick="act({action:'reels_script'},()=>setTimeout(loadReels,2500))">Metni (yeniden) üret</button></div></div>
    <div class="card"><h4>2. Ses</h4>${d.urls.mp3 ? `<audio controls src="${d.urls.mp3}?t=${Date.now()}"></audio> <span class="meta">${esc((v[st.voice] || {}).name || st.voice)} · deneme ${st.voice_n}</span>` : '<span class="meta">henüz üretilmedi</span>'}
      <div class="btns" style="justify-content:flex-start;max-width:none;margin-top:6px">Ses: <select id="vsel">${vopts}</select>
        <button class="act" title="Aynı metni yeni bir tohumla tekrar okutur (okunuş değişebilir)" onclick="act({action:'reels_voice',voice:$('#vsel').value,seed:Math.floor(Math.random()*1e6)},()=>setTimeout(loadReels,4000))">Sesi (yeniden) üret</button></div></div>
    <div class="card"><h4>3. Video</h4>${d.urls.mp4 ? `<video class="prev" controls src="${d.urls.mp4}?t=${Date.now()}"></video> <span class="meta">${st.seconds} sn</span>
        <div>${(st.issues || []).length ? `<div class="err">Denetim: ${esc(st.issues.join(' | '))} — yayına alınamaz, düzeltip yeniden üret</div>` : '<div class="ok">Denetim temiz (metin, ses, görüntü)</div>'}</div>
        <details><summary class="meta">Açıklama metni</summary><pre class="log">${esc(st.caption || '')}</pre></details>` : '<span class="meta">henüz üretilmedi</span>'}
      <div class="btns" style="justify-content:flex-start;max-width:none;margin-top:6px"><button class="act" onclick="act({action:'reels_render'},()=>setTimeout(loadReels,3000))">Videoyu (yeniden) üret</button></div></div>
    <div class="card"><h4>4. Yayın</h4>${ctl}
      <div class="btns" style="justify-content:flex-start;max-width:none;margin-top:6px">Saat (TSİ, boş = ilk turda): <input type="time" id="rat" value="${esc(st.at || rc.at || '')}">
        <button class="act main" ${d.urls.mp4 && !(st.issues || []).length && rc.status !== 'posted' ? '' : 'disabled'} title="Videoyu GitHub'a yükler; bekçi verilen saatte yayınlar" onclick="act({action:'reels_publish',at:$('#rat').value},()=>setTimeout(loadReels,3000))">Yayına al</button>
        <button class="act warn" ${rc.status === 'ready' || rc.status === 'planned' ? '' : 'disabled'} onclick="act({action:'reels_cancel'},()=>setTimeout(loadReels,3000))">İptal</button></div></div>` : '';
  const male = v.erkek ? `<div class="meta">Erkek ses: ${esc(v.erkek.name)} · <a href="#" onclick="loadVoices();return false">değiştir</a></div>`
    : `<div class="err">Erkek ses henüz seçilmedi. <a href="#" onclick="loadVoices();return false">Adayları dinle ve seç</a></div>`;
  $('#reels').innerHTML = `<div class="card"><h4>Maç</h4>${cands || '<span class="meta">Bugün analizli maç yok (reels için yapay zekâ paketi gerekir)</span>'}
      <div class="btns" style="justify-content:flex-start;max-width:none;margin-top:8px">Ses: <select id="vsel0">${vopts}</select>
        <button class="act main" ${cands ? '' : 'disabled'} title="Metin, ses ve video sırayla üretilir; sonra dinleyip izlersin" onclick="chooseReels(true)">Seç ve üret</button>
        <button class="act" ${cands ? '' : 'disabled'} onclick="chooseReels(false)">Sadece seç</button></div>${male}<div id="vcands"></div></div>` + steps;
}
async function chooseReels(produce) {
  const r = document.querySelector('input[name=rc]:checked'); if (!r) { toast('Önce maç seç', true); return; }
  await act({ action: 'reels_choose', code: +r.value, voice: $('#vsel0').value, produce }, () => setTimeout(loadReels, 2500));
}
async function loadVoices() {
  $('#vcands').innerHTML = '<div class="meta">Adaylar yükleniyor (ElevenLabs Türkçe erkek sesler)…</div>';
  const d = await act({ action: 'voice_candidates' });
  if (!d.ok) return;
  $('#vcands').innerHTML = '<h4>Erkek ses adayları</h4>' + d.voices.map(x => `<div class="voice"><audio controls preload="none" src="${x.preview_url}"></audio><div><b>${esc(x.name)}</b> <span class="meta">${esc(x.accent || '')} · ${esc(x.age || '')} · ${esc(x.use_case || '')}</span><div class="meta">${esc(x.desc)}</div></div>
    <button class="act" onclick="act({action:'voice_adopt',owner:'${x.owner}',voice_id:'${x.voice_id}',name:'${esc(x.name.split(' - ')[0])}'},loadReels)">Bunu seç</button></div>`).join('');
}

// ---------------- İstatistik ----------------
function chart(days, vals, color) {
  const v = vals.map(x => x || 0); if (!v.length) return '<div class="meta">veri yok</div>';
  const W = 600, H = 140, mx = Math.max(...v, 1), mn = Math.min(...v, 0);
  const pts = v.map((y, i) => `${(i / Math.max(v.length - 1, 1)) * (W - 20) + 10},${H - 20 - ((y - mn) / (mx - mn || 1)) * (H - 40)}`).join(' ');
  const dots = v.map((y, i) => `<circle cx="${(i / Math.max(v.length - 1, 1)) * (W - 20) + 10}" cy="${H - 20 - ((y - mn) / (mx - mn || 1)) * (H - 40)}" r="3" fill="${color}"/>`).join('');
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><polyline fill="none" stroke="${color}" stroke-width="2" points="${pts}"/>${dots}
    <text x="10" y="14" fill="#9FB3A8" font-size="11">en yüksek ${mx}</text><text x="10" y="${H - 4}" fill="#9FB3A8" font-size="11">${esc(days[0] || '')}</text><text x="${W - 80}" y="${H - 4}" fill="#9FB3A8" font-size="11">${esc(days[days.length - 1] || '')}</text></svg>`;
}
async function loadStats() {
  const d = await (await fetch('/api/stats')).json();
  const a = d.account, L = a.latest || {};
  const rows = d.media.map(m => `<tr><td>${esc(m.type || 'karusel')}</td><td>${esc(m.home)} – ${esc(m.away)}<div class="meta">${esc((m.posted_at || '').slice(0, 16).replace('T', ' '))} · ${esc(m.weekday || '')}${m.boosted ? ' · <span class="tag">reklam ' + m.ad_tl + ' TL</span>' : ''}</div></td>
    <td class="num">${n(m.reach)}</td><td class="num">${n(m.views)}</td><td class="num">${n(m.likes)}</td><td class="num">${n(m.saved)}</td><td class="num">${n(m.shares)}</td><td class="num">${n(m.comments)}</td><td class="num">${m.int_rate != null ? (m.int_rate * 100).toFixed(1) + '%' : '–'}</td></tr>`).join('');
  const opts = d.media.map(m => `<option value="${m.post_id}">${esc(m.type || 'karusel')} · ${esc(m.home)} – ${esc(m.away)} (${esc((m.posted_at || '').slice(0, 10))})</option>`).join('');
  const ads = d.ads.map(x => `<li>${esc(x.day)} · ${esc(x.type)} ${esc(x.home)} – ${esc(x.away)} · ${x.budget_tl} TL · ${x.days} gün</li>`).join('');
  $('#stats').innerHTML = `<div class="card"><span class="kpi"><b>${n(L.followers)}</b><span>takipçi</span></span><span class="kpi"><b>${n(L.views_today)}</b><span>görüntülenme (son gün)</span></span>
      <span class="kpi"><b>${n(L.profile_views_today)}</b><span>profil ziyareti</span></span><span class="kpi"><b>${n(L.accounts_engaged_today)}</b><span>etkileşen hesap</span></span>
      <span class="kpi"><b>${n(L.media)}</b><span>gönderi</span></span>
      <div class="btns" style="justify-content:flex-start;max-width:none"><button class="act" onclick="act({action:'insights_now'},()=>setTimeout(loadStats,15000))">Insights çek</button></div></div>
    <div class="grid2"><div class="card"><h4>Takipçi (günlük)</h4>${chart(a.days, a.followers, '#FFCF4D')}</div><div class="card"><h4>Hesap erişimi (günlük, reklam dahil)</h4>${chart(a.reach_days, a.reach, '#7ED6A5')}</div></div>
    <div class="card"><h4>Gönderiler (her gönderinin son ölçümü)</h4><table><tr><th>Tür</th><th>Maç</th><th class="num">Erişim</th><th class="num">Görüntü</th><th class="num">Beğeni</th><th class="num">Kaydet</th><th class="num">Paylaş</th><th class="num">Yorum</th><th class="num">Etk. oranı</th></tr>${rows || '<tr><td colspan="9" class="meta">veri yok</td></tr>'}</table></div>
    <div class="card"><h4>Reklam kaydı</h4><div class="meta">Instagram uygulamasından reklam bastığında buraya yaz; rapor bu gönderiyi organik sayılardan ayırır.</div>
      <div class="btns" style="justify-content:flex-start;max-width:none;margin-top:6px"><select id="adpost">${opts}</select> Bütçe <input type="number" id="adtl" value="200" style="width:80px"> TL · Gün <input type="number" id="addays" value="1" style="width:60px">
        <button class="act main" onclick="act({action:'add_ad',post_id:$('#adpost').value,budget_tl:$('#adtl').value,days:$('#addays').value},()=>setTimeout(loadStats,2000))">Kaydet</button></div>
      <ul class="meta">${ads || '<li>kayıt yok</li>'}</ul></div>
    <div class="card"><h4>Gönderi zaman serisi</h4><div class="meta">Bir gönderi seç: bekçi her sabah ölçer, çizgi gün gün erişimi gösterir (reklam gösterimleri buraya girmez).</div>
      <select id="serisel" onchange="renderSeries()">${d.media.map(m => `<option value="${m.post_id}">${esc(m.type || 'karusel')} · ${esc(m.home)} – ${esc(m.away)}</option>`).join('')}</select>
      <div id="seri"></div></div>
    <div class="card"><h4>Story'ler</h4><table><tr><th>Tür</th><th>Maç</th><th>Zaman</th><th class="num">Erişim</th><th class="num">Görüntü</th><th class="num">İleri</th><th class="num">Geri</th><th class="num">Çıkış</th><th class="num">Yanıt</th><th class="num">Paylaş</th></tr>
      ${d.stories.map(s => `<tr><td>${esc(s.type)}</td><td>${esc(s.home)} – ${esc(s.away)}</td><td>${esc((s.posted_at || '').slice(5, 16).replace('T', ' '))}</td><td class="num">${n(s.reach)}</td><td class="num">${n(s.views)}</td><td class="num">${n(s.forward)}</td><td class="num">${n(s.back)}</td><td class="num">${n(s.exit)}</td><td class="num">${n(s.replies)}</td><td class="num">${n(s.shares)}</td></tr>`).join('') || '<tr><td colspan="10" class="meta">veri yok</td></tr>'}</table>
      <div class="meta">İleri: izleyici sonraki story'ye geçti; çıkış: story'den çıktı (yüksekse içerik sıkıcı); geri: tekrar baktı (ilgi).</div></div>
    <div class="card"><h4>Gruplara göre ortalama (organik gönderiler)</h4><div class="grid2">${Object.entries(d.groups).map(([k, rows]) => `<div><b>${esc(k)}</b><table><tr><th>Grup</th><th class="num">N</th><th class="num">Erişim</th><th class="num">Görüntü</th><th class="num">Kaydet</th><th class="num">Etk.%</th></tr>
      ${rows.map(r => `<tr><td>${esc(r.grup)}</td><td class="num">${r.n}</td><td class="num">${r.erisim}</td><td class="num">${r.goruntu}</td><td class="num">${r.kaydet}</td><td class="num">${r.etk}</td></tr>`).join('')}</table></div>`).join('')}</div>
      <div class="meta">Az gönderiyle ortalamalar oynaktır; Kasım sonunda ilk sağlıklı karşılaştırma.</div></div>
    <div class="card"><h4>Hesap, gün gün</h4><table><tr><th>Gün</th><th class="num">Takipçi</th><th class="num">Erişim</th><th class="num">Görüntü</th><th class="num">Profil zy.</th><th class="num">Etkileşen</th><th class="num">Etkileşim</th><th class="num">Site tık</th></tr>
      ${d.account_table.map(r => `<tr><td>${esc(r.day)}</td><td class="num">${n(r.followers)}</td><td class="num">${n(r.reach_day)}</td><td class="num">${n(r.views_today)}</td><td class="num">${n(r.profile_views_today)}</td><td class="num">${n(r.accounts_engaged_today)}</td><td class="num">${n(r.total_interactions_today)}</td><td class="num">${n(r.website_clicks_today)}</td></tr>`).join('')}</table></div>
    <div class="card report"><h4>Haftalık iç rapor ${esc(d.report.name || '')}</h4>${d.report.html}</div>`;
  window.STATS = d; renderSeries();
}
function renderSeries() {
  const d = window.STATS; if (!d) return;
  const pid = $('#serisel').value; const rows = d.series[pid] || [];
  $('#seri').innerHTML = rows.length ? chart(rows.map(r => r.day), rows.map(r => r.reach), '#7ED6A5') + `<table><tr><th>Gün</th><th class="num">Yaş (sa)</th><th class="num">Erişim</th><th class="num">Görüntü</th><th class="num">Beğeni</th><th class="num">Yorum</th><th class="num">Kaydet</th><th class="num">Paylaş</th><th class="num">Takip</th><th class="num">Profil</th><th class="num">Etk.%</th></tr>
    ${rows.map(r => `<tr><td>${esc(r.day)}</td><td class="num">${n(r.age_h, 1)}</td><td class="num">${n(r.reach)}</td><td class="num">${n(r.views)}</td><td class="num">${n(r.likes)}</td><td class="num">${n(r.comments)}</td><td class="num">${n(r.saved)}</td><td class="num">${n(r.shares)}</td><td class="num">${n(r.follows)}</td><td class="num">${n(r.profile_visits)}</td><td class="num">${r.int_rate != null ? (r.int_rate * 100).toFixed(1) : '–'}</td></tr>`).join('')}</table>` : '<div class="meta">ölçüm yok</div>';
}

// ---------------- Gelen kutusu ----------------
async function loadInbox() {
  const d = await (await fetch('/api/inbox')).json();
  if (!d.ok) { $('#inbox').innerHTML = `<div class="card err">${esc(d.error)}</div>`; return; }
  const cm = d.comments.map(c => `<div class="cmt ${c.new ? 'new' : ''}"><b>@${esc(c.user)}</b> <span class="meta">${esc(c.t)} · ${esc(c.post)}${c.permalink ? ` · <a href="${c.permalink}" target="_blank">gönderi</a>` : ''}</span>${c.new ? ' <span class="badge">yeni</span>' : ''}
      <div>${esc(c.text)}</div>${c.replies.map(r => `<div class="meta">↳ @${esc(r.user)}: ${esc(r.text)} <span class="meta">${esc(r.t)}</span></div>`).join('')}
      <div class="btns" style="justify-content:flex-start;max-width:none;margin-top:4px"><input type="text" id="cr_${c.id}" placeholder="yanıt…" style="width:60%"><button class="act" onclick="act({action:'comment_reply',comment_id:'${c.id}',text:$('#cr_${c.id}').value},loadInbox)">Yanıtla</button></div></div>`).join('');
  const ms = d.messages.map(m => `<details class="card" ${m.new ? 'open' : ''}><summary><b>@${esc(m.with)}</b> <span class="meta">${esc(m.updated)}</span>${m.new ? ' <span class="badge">yeni</span>' : ''}${m.error ? ` <span class="err">${esc(m.error)}</span>` : ''}</summary>
      <div style="display:flex;flex-direction:column">${m.messages.map(x => `<div class="msg ${x.mine ? 'mine' : ''}"><span class="meta">${esc(x.from)} · ${esc(x.t)}</span><br>${esc(x.text)}</div>`).join('')}</div>
      <div class="btns" style="justify-content:flex-start;max-width:none;margin-top:6px"><input type="text" id="dm_${m.id.slice(0, 12)}" placeholder="mesaj…" style="width:60%"><button class="act" onclick="act({action:'dm_reply',conversation_id:'${m.id}',text:$('#dm_${m.id.slice(0, 12)}').value},loadInbox)">Gönder</button></div></details>`).join('');
  const tg = d.tags.map(x => `<div class="cmt ${x.new ? 'new' : ''}"><b>@${esc(x.user)}</b> <span class="meta">${esc(x.t)}</span> ${esc(x.caption)} ${x.permalink ? `<a href="${x.permalink}" target="_blank">aç</a>` : ''}</div>`).join('');
  $('#inbox').innerHTML = `${d.errors.length ? `<div class="card err">${esc(d.errors.join(' · '))}</div>` : ''}
    <div class="card"><h4>Yorumlar (${d.comments.length}, yeni ${d.counts.comments}) <button class="act" onclick="act({action:'inbox_seen',kind:'comments'},loadInbox)">Gördüm</button></h4>${cm || '<div class="meta">Son gönderilerde yorum yok.</div>'}</div>
    <div class="card"><h4>Mesajlar (${d.messages.length}, yeni ${d.counts.messages}) <button class="act" onclick="act({action:'inbox_seen',kind:'messages'},loadInbox)">Gördüm</button></h4>${ms || '<div class="meta">Mesaj yok.</div>'}</div>
    <div class="card"><h4>Etiketlenmeler (${d.tags.length}, yeni ${d.counts.tags}) <button class="act" onclick="act({action:'inbox_seen',kind:'tags'},loadInbox)">Gördüm</button></h4>${tg || '<div class="meta">Etiketlenme yok.</div>'}</div>`;
  badge(d.counts);
}
function badge(c) { const b = $('#inboxBadge'); const t = (c.comments || 0) + (c.messages || 0) + (c.tags || 0); b.style.display = t ? 'inline' : 'none'; b.textContent = t; }
async function pollInbox() { try { const d = await (await fetch('/api/inbox')).json(); if (d.ok) badge(d.counts); } catch (e) { } }

// ---------------- Günlük ----------------
let EV_LEVEL = '', EV_DAYS = 3;
async function loadEvents() {
  const d = await (await fetch(`/api/events?days=${EV_DAYS}&level=${EV_LEVEL}`)).json();
  const c = d.counts;
  $('#events').innerHTML = `<div class="card"><span class="btns" style="justify-content:flex-start;max-width:none">
      Göster: <select onchange="EV_LEVEL=this.value;loadEvents()"><option value="" ${!EV_LEVEL ? 'selected' : ''}>hepsi</option><option value="hata" ${EV_LEVEL === 'hata' ? 'selected' : ''}>yalnız hatalar</option><option value="uyarı" ${EV_LEVEL === 'uyarı' ? 'selected' : ''}>yalnız uyarılar</option></select>
      Süre: <select onchange="EV_DAYS=+this.value;loadEvents()">${[1, 3, 7, 14].map(x => `<option value="${x}" ${EV_DAYS === x ? 'selected' : ''}>${x} gün</option>`).join('')}</select>
      <span class="kpi"><b style="color:#D9534F">${c.hata}</b><span>hata</span></span><span class="kpi"><b>${c['uyarı']}</b><span>uyarı</span></span><span class="kpi"><b style="color:#9FB3A8">${c.bilgi}</b><span>bilgi</span></span>
      <button class="act" onclick="loadEvents()">Yenile</button></span></div>
    <div class="card">${d.events.map(e => `<div class="ev ${cls(e.level)}"><span class="meta">${esc(e.when)}</span><span class="lv">${esc(e.level)}</span><span>${esc(e.source)}</span><span>${esc(e.text)}${e.link ? ` <a href="${e.link}" target="_blank">↗</a>` : ''}</span></div>`).join('') || '<div class="meta">olay yok</div>'}</div>`;
}

// ---------------- Kupon ----------------
async function loadKupon() {
  const d = await (await fetch('/api/kupon')).json();
  const c = d.coupons, al = d.alerts;
  const summ = c.summary.map(s => `<span class="kpi"><b>${s.won}/${s.total}</b><span>${esc(s.kind)} tuttu · 1 birimle net ${s.pnl > 0 ? '+' : ''}${s.pnl}</span></span>`).join('') || '<span class="meta">Henüz sonuçlanmış kupon yok.</span>';
  const items = c.items.map(x => `<details class="card"><summary>#${x.no} · ${esc(x.kind)} · ${x.n} maç · oran ${x.odds} · ihtimal %${x.prob} · ${x.result === 'won' ? '<span class="tag won">tuttu</span>' : x.result === 'lost' ? '<span class="tag lost">tutmadı</span>' : `<span class="tag">bekliyor ${x.legs_hit}/${x.n}</span>`} <span class="meta">${esc(x.t)}</span></summary>
    <table>${x.legs.map(l => `<tr><td>${esc(l.home)} – ${esc(l.away)}<div class="meta">${esc(l.start)}${l.score ? ' · skor ' + esc(l.score) : ''}</div></td><td>${esc(l.pick)}</td><td class="num">${l.odds}</td><td>${l.result === 'won' ? '✓' : l.result === 'lost' ? '✗' : '…'}</td></tr>`).join('')}</table></details>`).join('');
  const alst = al.stats ? `<span class="kpi"><b>${al.stats.settled}</b><span>sonuçlanmış uyarı · net ${al.stats.pnl} birim (ROI ${al.stats.roi}%)</span></span>${al.stats.clv_avg != null ? `<span class="kpi"><b>${al.stats.clv_avg > 0 ? '+' : ''}${al.stats.clv_avg}%</b><span>ortalama kapanış farkı (CLV)</span></span>` : ''}` : '<span class="meta">Henüz uyarı yok (gözcü bulunca yazar).</span>';
  const alrows = al.items.map(a => `<tr><td>${esc(a.t)}</td><td>${esc(a.home)} – ${esc(a.away)}</td><td>${esc(a.pick)}</td><td class="num">${a.nesine}</td><td class="num">${a.fair}</td><td class="num">+${a.ev_pct}%</td><td>${a.result === 'won' ? '<span class="tag won">tuttu</span>' : a.result === 'lost' ? '<span class="tag lost">tutmadı</span>' : '…'}${a.clv_pct != null ? ` <span class="meta">CLV ${a.clv_pct > 0 ? '+' : ''}${a.clv_pct}%</span>` : ''}</td></tr>`).join('');
  const res = d.results.map(r => `<tr><td>${esc(r.day)}</td><td>${esc(r.home)} – ${esc(r.away)}</td><td class="num">${esc(r.score)}</td></tr>`).join('');
  $('#kupon').innerHTML = `<div class="card"><h4>Kuponlar (${c.total} kilitli, ${c.settled} sonuçlanmış)</h4>${summ}</div>${items}
    <div class="card"><h4>Gözcü uyarıları (${al.total})</h4>${alst}${alrows ? `<table><tr><th>Zaman</th><th>Maç</th><th>Seçim</th><th class="num">Nesine</th><th class="num">Adil</th><th class="num">Değer</th><th>Sonuç</th></tr>${alrows}</table>` : ''}</div>
    <div class="card"><h4>Skorlar (son 2 gün)</h4><table>${res || '<tr><td class="meta">yok</td></tr>'}</table></div>`;
}

// ---------------- Sistem ----------------
function renderSystem(Y) {
  if (!Y || !Y.keeper) { $('#system').textContent = 'Veri yok'; return; }
  const pre0 = $('#runlog'); const openLog = pre0 && pre0.style.display === 'block' ? pre0.textContent : null;
  const k = Y.keeper, q = Y.quota, s = Y.spend, t = Y.ig_token || {};
  const tokBad = t.valid === false || (t.days_left !== null && t.days_left !== undefined && t.days_left < 7);
  const ST = { in_progress: 'çalışıyor', queued: 'sırada', pending: 'sırada', success: 'başarılı', failure: 'HATA', cancelled: 'iptal', skipped: 'atlandı' };
  $('#system').innerHTML = `
  <div class="card"><b>Bekçi</b> son kayıt ${esc(k.last || '–')} (${k.age_min ?? '–'} dk önce) · ${k.running ? '<span class="state yayinda">çalışıyor</span>' : '<span class="state durdu">çalışmıyor</span>'}
    · sabah analizi ${esc(k.claude_morning || '–')} · insights ${esc(k.insights_day || '–')}
    <div class="btns" style="margin-top:8px;max-width:none;justify-content:flex-start"><button class="act" onclick="act({action:'workflow',name:'keeper.yml'})">Bekçiyi çalıştır</button>
    <button class="act" onclick="act({action:'workflow',name:'watch.yml'})">Gözcüyü çalıştır</button>
    <button class="act" onclick="act({action:'workflow',name:'results.yml'})">Skorları çalıştır</button>
    <button class="act" onclick="act({action:'insights_now'})">Insights çek</button>
    <button class="act" onclick="act({action:'retry_push'})">Yeniden it</button></div></div>
  <div class="card"><b>Kota</b> Odds API kalan ${q.remaining} istek · bugün ${q.spent_today} (${esc(q.day || '')}) <span class="meta">— gözcünün Pinnacle oran sorguları; aylık 500</span><br>
    <b>Harcama</b> yapay zekâ bugün $${s.ai_today_usd} · bu ay $${s.ai_month_usd}${s.eleven_limit ? ` · ElevenLabs ${s.eleven_used}/${s.eleven_limit} karakter (sıfırlama ${esc(s.eleven_reset)})` : ''}<br>
    <b>Instagram belirteci</b> <span class="state ${tokBad ? 'durdu' : 'yayinda'}">${t.valid === null || t.valid === undefined ? 'bilgi yok' : t.valid ? (esc(t.expires) + (t.days_left != null ? ` (${t.days_left} gün)` : '') + (t.username ? ' · @' + esc(t.username) : '')) : 'GEÇERSİZ'}</span>
    ${Y.errors.length ? `<div class="err">${esc(Y.errors.join(' · '))}</div>` : ''}</div>
  <div class="card"><b>Son çalışmalar</b> <span class="meta">(GitHub Actions)</span><table><tr><th>İş akışı</th><th>Durum</th><th>Başlangıç</th><th>Süre</th><th></th></tr>
    ${Y.runs.map(r => `<tr><td>${esc(r.name)}</td><td>${esc(ST[r.status === 'completed' ? r.conclusion : r.status] || r.conclusion || r.status)}</td><td>${esc(r.started)}</td><td>${r.minutes} dk</td>
      <td><a href="${r.url}" target="_blank">GitHub</a> · <a href="#" onclick="showLog(${r.id});return false">log</a>${r.status === 'in_progress' ? ` · <a href="#" style="color:#D9534F" onclick="if(confirm('Bu çalışma iptal edilsin mi?'))act({action:'cancel_run',run_id:${r.id}});return false">iptal</a>` : ''}</td></tr>`).join('')}</table>
    <pre class="log" id="runlog" style="display:none"></pre></div>`;
  if (openLog !== null) { const pre = $('#runlog'); pre.style.display = 'block'; pre.textContent = openLog; }
}
async function showLog(id) {
  const pre = $('#runlog'); pre.style.display = 'block'; pre.textContent = 'Log alınıyor…';
  const d = await (await fetch('/api/log/' + id)).json();
  pre.textContent = d.ok ? d.lines.join('\n') : ('Hata: ' + d.error); pre.scrollTop = pre.scrollHeight;
}

// ---------------- döngü ----------------
async function refresh() {
  try {
    const r = await fetch('/api/state'); S = await r.json();
    $('#conn').textContent = 'bağlı'; $('#conn').className = 'pill ok';
    $('#clock').textContent = S.now.slice(11, 16) + ' TSİ';
    renderToday(S.today); renderSystem(S.system); renderJobs(S.jobs || []);
  } catch (e) { $('#conn').textContent = 'bağlantı yok'; $('#conn').className = 'pill bad'; }
}
pollInbox(); setInterval(pollInbox, 120000);
const tab0 = new URLSearchParams(location.search).get('tab');
refresh().then(() => { if (tab0) openTab(tab0); });
setInterval(refresh, 3000);
