'use strict';
const $ = (s, parent = document) => parent.querySelector(s);
const $$ = (s, parent = document) => [...parent.querySelectorAll(s)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const icon = name => `<svg><use href="#i-${name}"/></svg>`;
const bytes = n => n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : n >= 1024 ? `${(n / 1024).toFixed(0)} KB` : `${n} B`;
const active = p => ['queued','running','stopping'].includes(p.status);
let projects = [], filter = 'all', step = 0, detailId = null, fetching = false, initialLoad = true;
let preferences = {max_pages:25, depth:2, delay:500, beautify:true, respect_robots:true};
try { preferences = {...preferences, ...JSON.parse(localStorage.getItem('turbo-preferences') || '{}')}; } catch (_) {}
let toastTimer, scanTimer, scanResult = null, scanGeneration = 0;
let storageRoot = '', nativeDesktop = false, deletingId = null;
const exporting = new Set();
api('/api/settings').then(s => { storageRoot = s.storage_root; nativeDesktop = s.native_desktop; }).catch(() => {});
function toast(text) { $('#toast').textContent = text; $('#toast').classList.add('visible'); clearTimeout(toastTimer); toastTimer = setTimeout(() => $('#toast').classList.remove('visible'), 4000); }
async function api(url, data) {
  const response = await fetch(url, data === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
  if (!response.ok) { let error; try { error = (await response.json()).error; } catch (_) {} throw new Error(error || `Request failed (${response.status}).`); }
  return response.json();
}
async function exportProject(project) {
  if(exporting.has(project.id)) return;
  exporting.add(project.id); renderDetail();
  try {
    if(nativeDesktop && !window.pywebview?.api?.export_project) throw new Error('Native Save As is not ready. Restart the updated desktop application.');
    if(window.pywebview?.api?.export_project) {
      const result = await window.pywebview.api.export_project(project.id);
      if(result.error) throw new Error(result.error);
      if(result.path) { project.last_export_path = result.path; toast('ZIP saved: ' + result.path); }
      return;
    }
    // Check failures before handing a disk-backed download to the browser.
    const response = await fetch(`/api/projects/${project.id}/export`, {method:'HEAD'});
    if(!response.ok) throw new Error('ZIP could not be created. Check that the archive exists and capture has finished.');
    const link = document.createElement('a');
    link.href = `/api/projects/${project.id}/export`; link.download = `TurboWebDownloader-${project.id}.zip`;
    document.body.appendChild(link); link.click(); link.remove();
    toast('Download requested. The ZIP uses your browser download folder or Save As setting.');
  } catch(error) { toast(error.message); }
  finally { exporting.delete(project.id); if($('#details').open) renderDetail(); }
}
function renderScan() {
  const el = $('#scan-summary'); if(!el) return;
  if(step === 2) renderReview();
  const running = scanResult && ['queued','running'].includes(scanResult.status);
  $('#scan-stop').hidden = !running;
  $('#scan-use').hidden = !scanResult || scanResult.status === 'failed';
  el.innerHTML = scanResult ? `<strong>${scanResult.discovered} known page URLs</strong><span>${scanResult.sitemap_count} in sitemaps · ${scanResult.inspected} pages inspected · ${esc(scanResult.status)}</span><p>${esc(scanResult.message)}</p>${scanResult.warnings?.length ? `<small>${scanResult.warnings.length} warnings. Some pages or sitemaps could not be read.</small>` : ''}` : 'Analyze the site to discover URLs before choosing a page limit.';
}
function stopScan() {
  clearTimeout(scanTimer); scanGeneration++;
  if(scanResult && ['queued','running'].includes(scanResult.status)) {
    api(`/api/scans/${scanResult.id}/cancel`, {}).catch(() => {});
    scanResult.status = 'cancelled'; scanResult.message = 'Stopped; discovered count is partial.'; renderScan();
  }
}
async function startScan() {
  stopScan(); const generation = scanGeneration;
  $('#scan-summary').textContent = 'Starting site analysis…';
  const url = $('#project-url').value.trim();
  try {
    const result = await api('/api/scans', {url, limit:Number($('#scan-limit').value), depth:3, respect_robots:$('#project-form [name="respect_robots"]').checked});
    if(generation !== scanGeneration) { api(`/api/scans/${result.id}/cancel`, {}).catch(() => {}); return; }
    scanResult = result; renderScan();
    const poll = async () => {
      try {
        const current = await api(`/api/scans/${result.id}`);
        if(generation !== scanGeneration) return;
        scanResult = current; renderScan();
        if(['queued','running'].includes(current.status)) scanTimer = setTimeout(poll, 1000);
      } catch(error) { if(generation === scanGeneration) { scanResult.status='failed'; scanResult.message=error.message; renderScan(); } }
    };
    if(['queued','running'].includes(result.status)) scanTimer = setTimeout(poll, 500);
  } catch(error) { if(generation === scanGeneration) $('#scan-summary').textContent = 'Analysis unavailable: ' + error.message; }
}
function changeFilter(value) {
  filter = value;
  $$('[data-filter]').forEach(b => b.classList.toggle('selected', b.dataset.filter === value));
  $$('[data-nav]').forEach(b => b.classList.toggle('active', b.dataset.nav === value));
  $('#crumb').textContent = value === 'all' ? 'Overview' : value === 'completed' ? 'My archives' : value === 'running' ? 'Download queue' : 'Needs attention';
  render();
}
function render() {
  $('#nav-count').textContent = projects.length;
  $('#queue-dot').hidden = !projects.some(active);
  $('#stat-projects').innerHTML = `${projects.length}<small>Your growing collection</small>`;
  $('#stat-ready').innerHTML = `${projects.filter(p => p.status === 'completed').length}<small>Available anytime</small>`;
  $('#stat-pages').innerHTML = `${projects.reduce((n,p)=>n+p.pages,0)}<small>Rendered pages saved</small>`;
  $('#stat-size').innerHTML = `${bytes(projects.reduce((n,p)=>n+p.bytes,0))}<small>Stored on your device</small>`;
  let shown = projects.filter(p => (filter === 'all' || (filter === 'running' ? active(p) : filter === 'failed' ? ['failed','interrupted','cancelled'].includes(p.status) : p.status === filter)) && `${p.name} ${p.url}`.toLowerCase().includes($('#search').value.toLowerCase()));
  const sort = $('#sort').value;
  shown.sort((a,b) => sort === 'name' ? a.name.localeCompare(b.name) : sort === 'oldest' ? a.created-b.created : b.created-a.created);
  $('#project-count').textContent = shown.length;
  $('#empty').hidden = shown.length > 0;
  if (!shown.length) {
    $('#empty h3').textContent = projects.length ? 'No projects here. Yet.' : 'Your offline world starts here.';
    $('#empty p').innerHTML = projects.length ? 'Try a different search or filter, or start a fresh capture.' : 'Save a documentation site, a portfolio, or something inspiring.<br>Your first archive is just a URL away.';
  }
  $('#projects').innerHTML = shown.map(p => `<article class="project-card"><div class="project-preview" data-detail="${p.id}" role="button" tabindex="0" aria-label="Open ${esc(p.name)}">${p.entry ? `<img src="/archive/${p.id}/preview.png" alt="Captured website preview" loading="lazy" onerror="this.hidden=true">` : icon('globe')}<span class="status ${p.status}">${esc(p.status)}</span></div><div class="card-body"><h3>${esc(p.name)}</h3><div class="card-url">${esc(p.url)}</div><div class="card-metrics"><span>${p.pages} pages</span><span>${p.assets} resources</span><span>${bytes(p.bytes)}</span></div><div class="card-bottom"><small>${new Date(p.created*1000).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'})}</small><button class="text-button" data-detail="${p.id}">${active(p) ? 'View progress' : 'Open project'} ↗</button></div></div></article>`).join('');
  if (detailId && $('#details').open) renderDetail();
}
async function refresh() {
  if (fetching) return;
  fetching = true;
  try { projects = await api('/api/projects'); render(); if(initialLoad) { initialLoad = false; if(!projects.length) openWizard(); } }
  catch (error) { if(initialLoad) { toast('Unable to load projects. Check the local server.'); initialLoad = false; } }
  finally { fetching = false; }
}
function openWizard(project = null) {
  stopScan(); scanResult = null; renderScan();
  $('#project-form').reset(); $('#form-error').textContent = ''; step = 0;
  const settings = project ? project.options : preferences;
  for (const [key,value] of Object.entries(settings)) { const field = $(`[name="${key}"]`, $('#project-form')); if(field) { if(field.type === 'checkbox') field.checked = value; else field.value = value; } }
  if(project) { $('#project-name').value = project.name; $('#project-url').value = project.url; }
  updateStep(); $('#wizard').showModal(); setTimeout(()=>$('#project-name').focus(),80);
}
function values() {
  const form = $('#project-form'), options = {};
  for (const input of $$('[name]', form)) {
    if(['name','url'].includes(input.name)) continue;
    options[input.name] = input.type === 'checkbox' ? input.checked : Number(input.value);
  }
  return {name:$('#project-name').value.trim(),url:$('#project-url').value.trim(),options};
}
function validateStep() {
  for(const input of $$(`[data-step="${step}"] input`)) { if(!input.checkValidity()) { input.reportValidity(); return false; } }
  if(step === 0) { try { const u = new URL($('#project-url').value); if(!['http:','https:'].includes(u.protocol)) throw new Error(); } catch (_) { $('#form-error').textContent='Enter a valid HTTP or HTTPS address.'; return false; } }
  return true;
}
function updateStep() {
  $$('[data-step]').forEach(el=>el.hidden=Number(el.dataset.step)!==step);
  $$('[data-step-dot]').forEach(el=>el.classList.toggle('current',Number(el.dataset.stepDot)<=step));
  $('#step-caption').textContent=`Step ${step+1} of 3`;
  $('#wizard-back').textContent=step===0?'Cancel':'Back';
  $('#wizard-next').innerHTML=step===2?`${icon('download')} Start capture`:'Continue <span>→</span>';
  $('#form-error').textContent='';
  if(step===2) renderReview();
}
function renderReview() { const v=values(); $('#review').innerHTML=`<h3>${esc(v.name)}</h3><p>${esc(v.url)}</p><div class="review-chips"><span>Up to ${v.options.max_pages} pages</span><span>${scanResult ? `${scanResult.discovered} known URLs (${esc(scanResult.status)})` : 'Site total unknown — not analyzed'}</span><span>Depth ${v.options.depth}</span><span>${v.options.delay}ms render wait</span>${['styles','images','fonts','scripts','media'].filter(k=>v.options[k]).map(k=>`<span>${k}</span>`).join('')}<span>${v.options.run_scripts?'Scripts enabled':'Static rendered snapshot'}</span></div>`; }
async function nextStep() {
  if(step<2) { if(validateStep()) { step++; updateStep(); if(step===1) startScan(); } return; }
  if(!$('#permission').checked) { $('#form-error').textContent='Please confirm you have permission to archive this website.'; return; }
  $('#wizard-next').disabled=true;
  try { const project=await api('/api/projects',values()); $('#wizard').close(); projects.unshift(project); render(); openDetail(project.id); toast('Project created. Your browser is getting ready.'); }
  catch(error) { $('#form-error').textContent=error.message; }
  finally { $('#wizard-next').disabled=false; }
}
function openDetail(id) { detailId=id; renderDetail(); $('#details').showModal(); }
function renderDetail() {
  const p=projects.find(p=>p.id===detailId); if(!p) return;
  const previousLog=$('.activity-log'), oldScroll=previousLog?.scrollTop || 0;
  const follow=!previousLog || previousLog.scrollHeight-previousLog.scrollTop-previousLog.clientHeight<40;
  $('#detail-content').innerHTML=`<div class="detail-main"><div class="detail-title"><h2>${esc(p.name)}</h2><span class="status ${p.status}">${esc(p.status)}</span></div><div class="detail-url">${esc(p.url)}</div><div class="detail-stats"><div><strong>${p.pages}</strong><small>PAGES</small></div><div><strong>${p.assets}</strong><small>RESOURCES</small></div><div><strong>${bytes(p.bytes)}</strong><small>ARCHIVE SIZE</small></div><div><strong>${p.failed}</strong><small>FAILED PAGES</small></div></div><div class="capture-message">${esc(p.message)}</div><div class="project-location"><strong>Saved on this device</strong><code>${esc(p.storage_path || storageRoot + '/' + p.id)}</code><span>Pages & resources: <code>${esc(p.files_path || (p.storage_path || storageRoot + '/' + p.id) + '/files')}</code></span><div><button class="text-button" id="copy-location">Copy path</button><button class="text-button" id="open-location" ${window.pywebview?.api?'':'hidden'}>Open folder ↗</button></div>${p.last_export_path?`<span>Last ZIP export: <code>${esc(p.last_export_path)}</code></span>`:''}<small>${p.discovered ?? p.pages} known page URLs · ${p.failed_assets || 0} failed resources. Details: missing-resources.json</small></div><div class="detail-actions">${active(p)?`<button class="secondary" id="cancel-capture" ${p.status==='stopping'?'disabled':''}>Stop capture</button>`:`${p.entry?`<a class="primary" target="_blank" rel="noopener" href="/archive/${p.id}/index.html">${icon('globe')} Browse offline</a><button class="secondary" id="export-zip" ${exporting.has(p.id)?'disabled':''}>${exporting.has(p.id)?'Preparing ZIP…':'Save as ZIP ↓'}</button>`:''}<button class="secondary" id="retry-capture">Capture again</button><button class="secondary danger-outline" id="delete-project">Delete project</button>`}</div>${p.entry?`<img class="preview-image" src="/archive/${p.id}/preview.png" alt="First captured page" onerror="this.hidden=true">`:''}<h4 class="log-heading">CAPTURE ACTIVITY</h4><div class="activity-log" aria-label="Capture activity">${p.logs.length?p.logs.map(l=>`<div class="${esc(l.level)}"><time>${esc(l.time)}</time>${esc(l.message)}</div>`).join(''):'Waiting for the browser…'}</div><p class="preference-note">Only captured links work offline. External and uncaptured links still point to the live web. Partial archives may be exported after stopping.</p></div>`;
  const log=$('.activity-log'); log.scrollTop=follow?log.scrollHeight:oldScroll;
  $('#delete-project')?.addEventListener('click', () => openDelete(p));
  $('#export-zip')?.addEventListener('click', () => exportProject(p));
  $('#copy-location')?.addEventListener('click', async () => { try { await navigator.clipboard.writeText(p.storage_path || storageRoot + '/' + p.id); toast('Project path copied.'); } catch (_) { toast('Copy the displayed path manually.'); } });
  $('#open-location')?.addEventListener('click', async () => { try { const result = await window.pywebview.api.open_project_folder(p.id); if(result.error) throw new Error(result.error); } catch(e) { toast(e.message); } });
  $('#cancel-capture')?.addEventListener('click',async()=>{ try { await api(`/api/projects/${p.id}/cancel`,{}); await refresh(); } catch(e) { toast(e.message); } });
  $('#retry-capture')?.addEventListener('click',()=>{$('#details').close();openWizard(p);});
}
function openDelete(project) {
  deletingId = project.id;
  $('#delete-name').textContent = project.name;
  $('#delete-path').textContent = project.storage_path || storageRoot + '/' + project.id;
  $('#delete-dialog [value="keep"]').checked = true;
  $('#delete-error').textContent = '';
  $('#delete-confirm').textContent = 'Remove from library';
  $('#delete-dialog').showModal();
}
$('#delete-cancel').addEventListener('click', () => $('#delete-dialog').close());
$$('[name="delete-mode"]').forEach(input => input.addEventListener('change', () => {
  $('#delete-confirm').textContent = $('#delete-dialog [value="files"]').checked ? 'Delete project & files' : 'Remove from library';
}));
$('#delete-confirm').addEventListener('click', async () => {
  const id = deletingId, deleteFiles = $('#delete-dialog [value="files"]').checked;
  $('#delete-confirm').disabled = true;
  try {
    const result = await api(`/api/projects/${id}/delete`, {delete_files:deleteFiles});
    $('#delete-dialog').close(); $('#details').close(); detailId = null;
    projects = projects.filter(p => p.id !== id); render();
    toast(result.files_deleted ? 'Project and downloaded files deleted.' : 'Removed from library. Files kept at: ' + result.storage_path);
  } catch(error) { $('#delete-error').textContent = error.message; }
  finally { $('#delete-confirm').disabled = false; }
});
function showInformation(type) {
  $('#info-label').textContent=type.toUpperCase();
  let html='';
  if(type==='about') html=`<img class="about-logo" src="/static/logo.svg" alt="TurboWebDownloader logo"><h2>TurboWebDownloader</h2><span class="version">VERSION 1.2.0 · GPL-3.0</span><p>Your web, offline. A local-first, browser-powered archiver built to make the useful corners of the web a little more permanent.</p><div class="author-box"><small>Designed & developed by</small><strong>behnam ehsani</strong><a href="mailto:inbox.ehsani@gmail.com">inbox.ehsani@gmail.com ↗</a><a href="https://github.com/wrappedman/TurboWebDownloader" target="_blank" rel="noopener">github.com/wrappedman/TurboWebDownloader ↗</a></div><p>Built with Python, Playwright and a little love for the open web. Your data stays on this device.</p>`;
  else if(type==='help') html=`<h2>Bring a piece of the web home.</h2><ol class="help-list"><li><strong>Create a project.</strong> Enter a public website URL and a friendly name.</li><li><strong>Choose the scope.</strong> Depth 0 captures one page. Higher depths follow links on the same domain, up to your page limit.</li><li><strong>Watch the capture.</strong> Chromium renders each page, collects selected resources, and rewrites captured links.</li><li><strong>Browse or export.</strong> Open the archive locally, or export a ZIP to take it with you.</li></ol><div class="info-box warning"><p>Not a server clone: login sessions, server-side search, forms, streaming media and API-driven interactions cannot be guaranteed. Static snapshot mode preserves rendered DOM but disables scripts to avoid rehydration changes. Missing resources and uncaptured links may still require internet.</p></div><p>Archive responsibly. Follow website terms, copyright rules and robots.txt. Public websites only; private network addresses are blocked.</p>`;
  else html=`<h2>Your workspace, your defaults.</h2><p>These settings are used for new projects. Existing projects are not affected.</p><form id="preferences-form"><div class="field-row"><label class="field">Page limit<input name="max_pages" type="number" min="1" max="500" value="${Number(preferences.max_pages)}" required></label><label class="field">Link depth<input name="depth" type="number" min="0" max="10" value="${Number(preferences.depth)}" required></label><label class="field">Wait (ms)<input name="delay" type="number" min="0" max="10000" value="${Number(preferences.delay)}" required></label></div><label class="toggle-row"><div><strong>Format source files</strong><small>Readable HTML, CSS and JavaScript</small></div><input name="beautify" type="checkbox" ${preferences.beautify?'checked':''}></label><label class="toggle-row"><div><strong>Respect robots.txt</strong><small>Honor site crawl policies</small></div><input name="respect_robots" type="checkbox" ${preferences.respect_robots?'checked':''}></label><p class="preference-note">Capture viewport: 1440 × 1000 · One capture at a time · Resource limit: 25 MB each / 500 MB total. Storage folder: ${esc(storageRoot || "Loading…")}. Each project has its own folder; ZIPs use your native Save As dialog or the browser download location.</p><button class="primary" type="submit">Save preferences</button></form>`;
  $('#info-content').innerHTML=`<div class="information-body">${html}</div>`;
  $('#preferences-form')?.addEventListener('submit',e=>{e.preventDefault();const form=e.currentTarget;for(const input of $$('input',form))preferences[input.name]=input.type==='checkbox'?input.checked:Number(input.value);try{localStorage.setItem('turbo-preferences',JSON.stringify(preferences));$('#information').close();toast('Preferences saved.');}catch(_){toast('Browser storage unavailable. Defaults saved for this session.');}});
  $('#information').showModal();
}
$$('[data-filter]').forEach(b=>b.addEventListener('click',()=>changeFilter(b.dataset.filter)));
$$('[data-nav]').forEach(b=>b.addEventListener('click',()=>changeFilter(b.dataset.nav)));
['new-project','hero-start','empty-start'].forEach(id=>$(`#${id}`).addEventListener('click',()=>openWizard()));
['about','preferences','help'].forEach(id=>$(`#${id}`).addEventListener('click',()=>showInformation(id)));
$$('[data-close]').forEach(b=>b.addEventListener('click',()=>b.closest('dialog').close()));
$$('dialog').forEach(d=>d.addEventListener('click',e=>{if(e.target===d){const r=d.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)d.close();}}));
$('#wizard').addEventListener('close', stopScan);
$('#scan-start').addEventListener('click', startScan);
$('#scan-stop').addEventListener('click', stopScan);
$('#scan-use').addEventListener('click', () => { if(scanResult) { $('#project-form [name="max_pages"]').value = Math.min(500, Math.max(1, scanResult.discovered)); toast(scanResult.discovered > 500 ? 'Limit set to the supported maximum of 500 pages.' : 'Page limit updated. Adjust link depth if needed.'); } });
$('#wizard-back').addEventListener('click',()=>{if(step===0)$('#wizard').close();else{step--;updateStep();}});
$('#wizard-next').addEventListener('click',nextStep);
$('#project-form').addEventListener('submit',e=>{e.preventDefault();nextStep();});
$('#search').addEventListener('input',render);$('#sort').addEventListener('change',render);
$('#view-toggle').addEventListener('click',()=>$('#projects').classList.toggle('compact'));
$('#projects').addEventListener('click',e=>{const b=e.target.closest('[data-detail]');if(b)openDetail(b.dataset.detail);});
$('#projects').addEventListener('keydown',e=>{if(e.target.matches('.project-preview')&&['Enter',' '].includes(e.key)){e.preventDefault();openDetail(e.target.dataset.detail);}});
refresh();setInterval(refresh,2000);
