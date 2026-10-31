const $ = s => document.querySelector(s);
let S = null;
document.querySelectorAll('nav button').forEach(b => b.onclick = () => {
  document.querySelectorAll('nav button,.tab').forEach(x => x.classList.remove('on'));
  b.classList.add('on'); $('#tab-' + b.dataset.tab).classList.add('on');
});
function toast(msg, bad) {
  const t = $('#toast'); t.textContent = msg; t.style.display = 'block';
  t.style.background = bad ? '#D9534F' : '#FFCF4D'; t.style.color = bad ? '#fff' : '#0B2A1F';
  setTimeout(() => t.style.display = 'none', 3500);
}
async function act(body) {
  const r = await fetch('/api/action', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const d = await r.json(); toast(d.ok ? (d.msg || 'Tamam') : ('Hata: ' + (d.error || '')), !d.ok); refresh(); return d;
}
function esc(s) { return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
function zoom(src) { const o = document.createElement('div'); o.id = 'overlay'; o.innerHTML = `<img src="${src}">`; o.onclick = () => o.remove(); document.body.appendChild(o); }
function cls(s) { return s.replace(/ı/g, 'i').replace(/ş/g, 's').replace(/ç/g, 'c'); }
function renderJobs(jobs) {
  $('#jobs').innerHTML = '<h3>İşler</h3>' + (jobs.length ? jobs.map(j =>
    `<div class="job ${cls(j.status)}"><b>${esc(j.name)}</b> · ${esc(j.status)} ${j.started ? esc(j.started) : ''}\n${esc(j.lines.slice(-8).join('\n'))}</div>`).join('')
    : '<div class="meta">İş yok</div>');
}
function stateClass(s) { return { 'planlı': 'planli', 'yayında': 'yayinda', 'atlandı': 'atlandi', 'durduruldu': 'durdu' }[s] || ''; }

function renderToday(T) {
  if (!T || !T.day) { $('#matches').textContent = 'Veri yok'; return; }
  const w = T.watch || {};
  $('#pause').innerHTML = `<div class="card"><b>${T.day}</b> · karusel ${T.sent_count}/${T.max_per_day} · gözcü: ${esc(w.note || (w.active ? 'açık' : 'kapalı'))}
    <span class="btns" style="float:right;max-width:none">${T.paused_until
      ? `<span class="state durdu">Durduruldu, ${esc(T.paused_until.slice(11, 16))} kadar</span> <button class="act" onclick="act({action:'pause',until:null})">Aç</button>`
      : `<button class="act warn" onclick="act({action:'pause',until:'today'})">Bugün durdur</button>`}
    <button class="act" onclick="act({action:'instagram_now'})">Instagram'ı şimdi çalıştır</button></span>
    ${T.errors.length ? `<div class="err">${esc(T.errors.join(' · '))}</div>` : ''}</div>`;
  $('#matches').innerHTML = T.matches.length ? T.matches.map(m => {
    const c = m.cards, p = m.post, s = m.stories;
    const thumbs = ['match', 'yorum', 'story', 'devre', 'ft'].filter(k => c[k]).map(k => `<img src="${c[k]}" title="${k}" onclick="zoom('${c[k]}')">`).join('');
    const RS = { posted: 'yayında', ready: 'hazır, saat bekliyor', planned: 'planlandı', cancelled: 'iptal', error: 'hata' };
    const reels = m.reels ? `<div class="meta">Reels: ${esc(RS[m.reels.status] || m.reels.status)} ${esc(m.reels.at || '')}${m.reels.url ? ` · <a href="${m.reels.url}" target="_blank">aç</a>` : ''}</div>` : '';
    return `<div class="card match"><div class="thumbs">${thumbs || '<div class="meta">kart yok</div>'}</div>
      <div><h3>${esc(m.home)} – ${esc(m.away)} <span class="meta">${esc(m.kickoff)} · ${esc(m.league)} · kademe ${m.tier}${m.analysis ? ' · analiz var' : ''}</span></h3>
        <div>Karusel: <span class="state ${stateClass(p.state)}">${esc(p.state)}${p.at ? ' ' + esc(p.at) : ''}</span>${p.override_at ? ` <span class="meta">(panel: ${esc(p.override_at)})</span>` : ''}${p.url ? ` · <a href="${p.url}" target="_blank">aç</a>` : ''}</div>
        <div class="meta">Story: kadro ${esc(s.kadro)} · devre ${esc(s.devre)} · maç sonu ${esc(s.ft)}</div>${reels}</div>
      <div class="btns">
        ${(p.state === 'yayında' || p.state === 'süre geçti') ? '' : `<input type="time" value="${esc(p.override_at || p.at || '')}" id="t${m.code}"><button class="act" onclick="act({action:'set_time',code:${m.code},at:$('#t${m.code}').value})">Saati yaz</button>
        <button class="act ${p.skip ? '' : 'warn'}" onclick="act({action:'skip',code:${m.code},skip:${!p.skip}})">${p.skip ? 'Atlamayı geri al' : 'Atla'}</button>`}
        <button class="act ${s.skip ? '' : 'warn'}" onclick="act({action:'story_skip',code:${m.code},skip:${!s.skip}})">${s.skip ? "Story'leri aç" : "Story'leri atla"}</button>
      </div></div>`;
  }).join('') : '<div class="card meta">Bugün listelenecek maç yok</div>';
}

function renderSystem(Y) {
  if (!Y || !Y.keeper) { $('#system').textContent = 'Veri yok'; return; }
  const pre0 = $('#runlog'); const openLog = pre0 && pre0.style.display === 'block' ? pre0.textContent : null;
  const k = Y.keeper, q = Y.quota, s = Y.spend, t = Y.ig_token || {};
  const tokBad = t.valid === false || (t.days_left !== null && t.days_left !== undefined && t.days_left < 7);
  $('#system').innerHTML = `
  <div class="card"><b>Bekçi</b> son kayıt ${esc(k.last || '–')} (${k.age_min ?? '–'} dk önce) · ${k.running ? '<span class="state yayinda">çalışıyor</span>' : '<span class="state durdu">çalışmıyor</span>'}
    · sabah analizi ${esc(k.claude_morning || '–')} · insights ${esc(k.insights_day || '–')}
    <div class="btns" style="margin-top:8px;max-width:none;justify-content:flex-start"><button class="act" onclick="act({action:'workflow',name:'keeper.yml'})">Bekçiyi çalıştır</button>
    <button class="act" onclick="act({action:'workflow',name:'watch.yml'})">Gözcüyü çalıştır</button>
    <button class="act" onclick="act({action:'workflow',name:'results.yml'})">Skorları çalıştır</button>
    <button class="act" onclick="act({action:'insights_now'})">Insights çek</button>
    <button class="act" onclick="act({action:'retry_push'})">Yeniden it</button></div></div>
  <div class="card"><b>Kota</b> Odds API kalan ${q.remaining} · bugün ${q.spent_today} (${esc(q.day || '')})<br>
    <b>Harcama</b> yapay zekâ bugün $${s.ai_today_usd} · bu ay $${s.ai_month_usd}${s.eleven_limit ? ` · ElevenLabs ${s.eleven_used}/${s.eleven_limit} karakter (sıfırlama ${esc(s.eleven_reset)})` : ''}<br>
    <b>Instagram belirteci</b> <span class="state ${tokBad ? 'durdu' : 'yayinda'}">${t.valid === null || t.valid === undefined ? 'bilgi yok' : t.valid ? (esc(t.expires) + (t.days_left != null ? ` (${t.days_left} gün)` : '')) : 'GEÇERSİZ'}</span>
    ${Y.errors.length ? `<div class="err">${esc(Y.errors.join(' · '))}</div>` : ''}</div>
  <div class="card"><b>Son çalışmalar</b><table><tr><th>İş akışı</th><th>Durum</th><th>Başlangıç</th><th>Süre</th><th></th></tr>
    ${Y.runs.map(r => `<tr><td>${esc(r.name)}</td><td>${esc({in_progress:'çalışıyor',queued:'sırada',pending:'sırada',success:'başarılı',failure:'HATA',cancelled:'iptal',skipped:'atlandı'}[r.status === 'completed' ? r.conclusion : r.status] || r.conclusion || r.status)}</td><td>${esc(r.started)}</td><td>${r.minutes} dk</td>
      <td><a href="${r.url}" target="_blank">GitHub</a> · <a href="#" onclick="showLog(${r.id});return false">log</a></td></tr>`).join('')}</table>
    <pre class="log" id="runlog" style="display:none"></pre></div>`;
  if (openLog !== null) { const pre = $('#runlog'); pre.style.display = 'block'; pre.textContent = openLog; }
}
async function showLog(id) {
  const pre = $('#runlog'); pre.style.display = 'block'; pre.textContent = 'Log alınıyor…';
  const d = await (await fetch('/api/log/' + id)).json();
  pre.textContent = d.ok ? d.lines.join('\n') : ('Hata: ' + d.error); pre.scrollTop = pre.scrollHeight;
}
async function refresh() {
  try {
    const r = await fetch('/api/state'); S = await r.json();
    $('#conn').textContent = 'bağlı'; $('#conn').className = 'pill ok';
    $('#clock').textContent = S.now.slice(11, 16) + ' TSİ';
    renderToday(S.today); renderSystem(S.system); renderJobs(S.jobs || []);
  } catch (e) { $('#conn').textContent = 'bağlantı yok'; $('#conn').className = 'pill bad'; }
}
const tab0 = new URLSearchParams(location.search).get('tab');
if (tab0) { const b = document.querySelector(`nav button[data-tab="${tab0}"]`); if (b) b.click(); }
refresh(); setInterval(refresh, 3000);
