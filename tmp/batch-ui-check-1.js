
const $ = (id) => document.getElementById(id);
const esc = (s) => (s ?? "").toString().replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const enc = encodeURIComponent;
// Safe localStorage: accessing localStorage THROWS in Firefox when site storage is
// blocked (strict tracking protection / blocked cookies). Always go through these so
// a blocked store degrades gracefully instead of aborting the whole script.
const lsGet = (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } };
const lsSet = (k, v) => { try { localStorage.setItem(k, v); } catch (e) {} };

async function api(path, opts) {
  const r = await fetch(path, { cache: 'no-store', ...opts });
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return r.json();
}
let toastT;
function toast(msg, isErr) {
  const t = $('toast'); t.textContent = msg; t.className = 'toast show' + (isErr ? ' err' : '');
  clearTimeout(toastT); toastT = setTimeout(() => t.className = 'toast', 2600);
}

/* ---------- Nav ---------- */
function showView(view) {
  const btn = document.querySelector(`.nav button[data-view="${view}"]`);
  if (!btn) return;
  document.querySelectorAll('.nav button').forEach(x => x.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  $('view-' + view).classList.add('active');
  lsSet('view', view);   // remember across refresh
  renderHealth();
  if (view === 'scraper') loadJobs();
  if (view === 'apply-center') loadApplyCenter();
  if (view === 'repeatable') loadRepeatable();
  if (view === 'companies') loadCompanies();
  if (view === 'scrape') { renderSetup(); renderScrapedJobs(); }
  if (view === 'profile') renderSetup();   // fills #sk-applyprofile, #pf-repeats, #pf-saved
  if (view === 'hermes-scrape') { $('cs-enabled-note').innerHTML = CLOUD_ENABLED ? '' : '<b style="color:var(--warn)">Set HERMES_API_KEY in .env (the Hermes gateway API_SERVER_KEY) to enable.</b>'; }
  if (view === 'library') loadLibrary();
}
document.querySelectorAll('.nav button').forEach(b => b.onclick = () => showView(b.dataset.view));
// Tooltips so the icon-only rail (collapsed sidebar) stays readable.
document.querySelectorAll('.nav button').forEach(b => { if (!b.title) b.title = b.textContent.trim(); });

/* ---------- Collapsible sidebar (hamburger) ---------- */
function setNavCollapsed(collapsed) {
  document.querySelector('.app').classList.toggle('collapsed', collapsed);
  try { lsSet('nav-collapsed', collapsed ? '1' : '0'); } catch {}
}
$('nav-toggle')?.addEventListener('click', () =>
  setNavCollapsed(!document.querySelector('.app').classList.contains('collapsed')));
try { if (lsGet('nav-collapsed') === '1') setNavCollapsed(true); } catch {}

/* ---------- Health + models ---------- */
let ollamaUp = null;   // null = unknown, true/false from /health
// Single global model picker (sidebar) drives every generation + the badge.
function activeModel() { return $('model').value || ''; }
// Global persona picker. 'auto' (or empty) => let the backend auto-detect.
function activePersona() { const v = $('persona').value; return v && v !== 'auto' ? v : 'auto'; }
async function loadPersonas() {
  try {
    const { personas } = await api('/personas');
    const sel = $('persona');
    sel.innerHTML = '<option value="auto">Auto-detect</option>';
    personas.forEach(p => {
      const o = document.createElement('option');
      o.value = p.id; o.textContent = p.label; sel.appendChild(o);
    });
  } catch { /* personas optional; Auto-detect still works */ }
}
function renderHealth() {
  $('hdot').className = 'dot ' + (ollamaUp === false ? 'down' : ollamaUp ? 'up' : '');
  if (ollamaUp === null) { $('htext').textContent = 'checking…'; return; }
  if (!ollamaUp) { $('htext').textContent = 'Ollama offline'; return; }
  const m = activeModel();
  if (m === 'split') { $('htext').textContent = 'Ollama résumé · 🤖 Hermes letters'; return; }
  if (m === 'auto') { $('htext').textContent = 'Ollama · Auto (⭐→Hermes)'; return; }
  $('htext').textContent = m ? `Ollama · ${m}` : 'Ollama up';
}
async function loadHealth() {
  try { ollamaUp = (await api('/health')).ollama; }
  catch { ollamaUp = false; $('hdot').className = 'dot down'; $('htext').textContent = 'API offline'; return; }
  renderHealth();
}
let OLLAMA_DEFAULT = '', HERMES_DEFAULT = '', CLOUD_ENABLED = false;
async function loadModels() {
  try {
    const m = await api('/models');
    OLLAMA_DEFAULT = m.default;
    CLOUD_ENABLED = !!(m.cloud && m.cloud.length);
    HERMES_DEFAULT = CLOUD_ENABLED ? m.cloud[0].id : '';
    const sel = $('model'); sel.innerHTML = '';
    const addOpt = (val, label, parent, selected) => {
      const o = document.createElement('option');
      o.value = val; o.textContent = label; if (selected) o.selected = true;
      (parent || sel).appendChild(o);
    };
    const locals = (m.models && m.models.length) ? m.models : [m.default];
    if (CLOUD_ENABLED) {
      addOpt(HERMES_DEFAULT, '🤖 Hermes · optimized single call', sel, true);  // DEFAULT
      addOpt('split', 'Split · résumé local + letters 🤖 Hermes', sel, false);
      addOpt('auto', 'Auto · ⭐ priority → Hermes, else local', sel, false);
      const g1 = document.createElement('optgroup'); g1.label = 'Local (Ollama)';
      locals.forEach(n => addOpt(n, n, g1, false)); sel.appendChild(g1);
      const g2 = document.createElement('optgroup'); g2.label = '🤖 Hermes (agent)';
      m.cloud.forEach(c => addOpt(c.id, c.label, g2, false)); sel.appendChild(g2);
    } else {
      locals.forEach(n => addOpt(n, n, sel, n === m.default));
      // Hermes not detected — AI will run on local Ollama. Tell the user once.
      if (!window._hermesNotice) { window._hermesNotice = true;
        toast('⚠ Hermes not running — AI is using local Ollama.', true); }
    }
    sel.onchange = renderHealth;
    renderHealth();
    loadUsage();
  } catch {}
}

// Resolve which model to use for a generation given the job's priority.
// 'split' is passed through untouched — the backend routes the résumé to Ollama
// and the cover letter + email to Hermes.
function resolveModel(isPriority) {
  const v = $('model').value;
  if (v === 'auto') return isPriority ? (HERMES_DEFAULT || OLLAMA_DEFAULT) : OLLAMA_DEFAULT;
  return v;
}
// True if a resolved engine selection involves the Hermes agent (whole-run or split).
function usesHermes(model) { const m = (model || ''); return m.startsWith('hermes') || m === 'split'; }
// Surface a notice when a generation fell back from Hermes to Ollama mid-run.
function notifyFallback(res) {
  if (res && res.hermes_fallback) toast('⚠ Hermes wasn’t reachable — generated with Ollama instead.', true);
}
function performanceText(res) {
  const p = (res && res.performance) || {};
  if (!p.calls) return '';
  const tokens = p.total_tokens ? ` · ${Number(p.total_tokens).toLocaleString()} tokens` : '';
  const seconds = p.seconds ? ` · ${fmtSecs(p.seconds)}` : '';
  return ` · ${p.calls} AI call${p.calls === 1 ? '' : 's'}${tokens}${seconds}`;
}

// Styled single-field prompt → resolves with the value, or null if cancelled.
// Replaces the native browser prompt(): matches the app, Enter saves, Esc cancels.
function uiPrompt({ title = 'Edit', label = '', value = '', placeholder = '', ok = 'Save' } = {}) {
  return new Promise((resolve) => {
    const ov = $('prompt-overlay'), inp = $('prompt-input');
    $('prompt-title').textContent = title;
    $('prompt-label').textContent = label; $('prompt-label').style.display = label ? '' : 'none';
    inp.value = value; inp.placeholder = placeholder; $('prompt-ok').textContent = ok;
    ov.classList.add('show');
    setTimeout(() => { inp.focus(); inp.select(); }, 30);
    let done = false;
    const finish = (val) => {
      if (done) return; done = true; ov.classList.remove('show');
      $('prompt-ok').onclick = $('prompt-cancel').onclick = $('prompt-x').onclick = null;
      inp.onkeydown = null; ov.onclick = null;
      resolve(val);
    };
    $('prompt-ok').onclick = () => finish(inp.value);
    $('prompt-cancel').onclick = $('prompt-x').onclick = () => finish(null);
    inp.onkeydown = (e) => { if (e.key === 'Enter') { e.preventDefault(); finish(inp.value); } else if (e.key === 'Escape') finish(null); };
    ov.onclick = (e) => { if (e.target === ov) finish(null); };
  });
}

// Styled replacement for the browser's native confirm(). Returns a Promise<bool>.
// `danger:true` paints the confirm button red (for destructive actions).
function uiConfirm({ title = 'Are you sure?', message = '', ok = 'Confirm', cancel = 'Cancel', danger = false } = {}) {
  return new Promise((resolve) => {
    const ov = $('confirm-overlay'), okb = $('confirm-ok');
    $('confirm-title').textContent = title;
    $('confirm-msg').textContent = message;
    okb.textContent = ok; $('confirm-cancel').textContent = cancel;
    okb.className = 'btn sm ' + (danger ? 'danger' : 'primary');
    ov.classList.add('show');
    setTimeout(() => okb.focus(), 30);
    let done = false;
    const finish = (val) => {
      if (done) return; done = true; ov.classList.remove('show');
      okb.onclick = $('confirm-cancel').onclick = $('confirm-x').onclick = null;
      document.removeEventListener('keydown', onKey, true); ov.onclick = null;
      resolve(val);
    };
    const onKey = (e) => { if (e.key === 'Enter') { e.preventDefault(); finish(true); } else if (e.key === 'Escape') finish(false); };
    okb.onclick = () => finish(true);
    $('confirm-cancel').onclick = $('confirm-x').onclick = () => finish(false);
    document.addEventListener('keydown', onKey, true);
    ov.onclick = (e) => { if (e.target === ov) finish(false); };
  });
}

async function loadUsage() {
  try {
    const u = await api('/usage');
    // Hermes is locally hosted but may consume a remote provider quota. Show tokens
    // even when dollar pricing is unknown/zero.
    const line = $('usage-line');
    const tokens = (u.total_input || 0) + (u.total_output || 0);
    if (u.enabled && (u.calls || tokens)) {
      line.style.display = '';
      $('usage-tokens').textContent = tokens.toLocaleString() + ' tokens';
      $('usage-calls').textContent = u.calls || 0;
    } else {
      line.style.display = 'none';
    }
    // AI timing line — shown for any engine (Ollama or Hermes) once we have data.
    const tline = $('gentime-line');
    if (u.timed_calls) {
      tline.style.display = '';
      $('gentime-last').textContent = fmtSecs(u.last_seconds);
      $('gentime-avg').textContent = fmtSecs(u.avg_seconds);
    } else {
      tline.style.display = 'none';
    }
  } catch {}
}

function fmtSecs(s) {
  s = Number(s) || 0;
  if (s < 60) return s.toFixed(1) + 's';
  const m = Math.floor(s / 60), r = Math.round(s % 60);
  return `${m}m ${r}s`;
}

/* Click-to-copy a value (LinkedIn, portfolio, phone, …) for pasting into forms. */
function copyVal(text, label) {
  const t = String(text ?? '');
  (navigator.clipboard?.writeText(t) || Promise.reject()).then(
    () => toast(`Copied ${label}.`),
    () => {
      const ta = document.createElement('textarea');
      ta.value = t; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy'); toast(`Copied ${label}.`); } catch { toast('Copy failed.', true); }
      ta.remove();
    }
  );
}

/* Profile fields → click-to-copy chips for the Apply-profile section. */
function pfChips(p) {
  p = p || {};
  const rows = [
    ['Full name', p.fullName || p.firstName], ['Email', p.email], ['Phone', p.phone],
    ['LinkedIn', p.linkedin], ['Portfolio', p.portfolio], ['GitHub', p.github],
    ['City', p.city], ['Province', p.province], ['Country', p.country],
    ['Postal code', p.postalCode], ['Work auth', p.workAuthorization],
    ['Experience', p.experienceYears], ['Education', p.education],
    ['Salary', p.salaryExpectation], ['Start date', p.availableStartDate],
  ];
  Object.entries(p.commonAnswers || {}).forEach(([q, a]) => { if (a) rows.push([q, a]); });
  const chips = rows.filter(([, v]) => v).map(([k, v]) =>
    `<button class="btn ghost sm pf-copy" data-copy="${esc(v)}" data-label="${esc(k)}" title="Click to copy: ${esc(v)}" style="margin:0 6px 6px 0">
       <span style="opacity:.65">${esc(k)}:</span> ${esc(String(v).length > 36 ? String(v).slice(0,36)+'…' : v)} ⧉</button>`).join('');
  return chips || '<div class="muted">No apply-profile data. Edit data/apply_profile.json.</div>';
}

/* ---------- Shared rendering ---------- */
function qaCount(qa) {
  if (!qa) return 0;
  return ['identity_fixed','skills_dropped','fabricated_numbers','experience_fixed','unmatched_experience','ungrounded_in_bullets']
    .reduce((n,k) => n + ((qa[k]||[]).length), 0);
}
// A compact page-validation warning (count overflow / wrong page size). Empty when fine.
function pageWarn(pages) {
  if (!pages) return '';
  const probs = [];
  for (const key of ['resume', 'cover_letter']) {
    const p = pages[key]; if (!p || !p.available) continue;
    if (!p.pages_ok) probs.push(`${p.label} is ${p.pages} page${p.pages>1?'s':''} (max ${p.limit})`);
    if (!p.size_ok) probs.push(`${p.label} is ${p.page_size}, expected ${p.expected_size}`);
  }
  return probs.length
    ? `<div class="qa dirty" style="margin-top:6px"><span class="tag">📄 Page check</span> ${esc(probs.join('; '))}</div>` : '';
}
// Hermes-led QA result (the semantic audit that runs before the deterministic guard).
function hermesQALine(hq) {
  if (!hq || !hq.ran) return '';
  const f = hq.unsupported_findings || [];
  if (!f.length)
    return `<div class="qa clean" style="margin-top:6px"><span class="tag">🤖 Hermes QA</span> — every claim checked against your profile; nothing unsupported.</div>`;
  return `<div class="qa dirty" style="margin-top:6px"><span class="tag">🤖 Hermes QA removed unsupported claims</span><ul>${f.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div>`;
}
function renderQA(qa, hasViol) {
  if (!qa) return '';
  const extra = hermesQALine(qa.hermes_qa) + pageWarn(qa.pages);
  if (!hasViol && !qaCount(qa))
    return `<div class="qa clean"><span class="tag">✓ Truth-guard</span> — all facts verified against your profile.</div>` + extra;
  let items = [];
  (qa.identity_fixed || []).forEach(f => items.push(`<li><span class="tag">identity</span>: ${esc(f)}</li>`));
  if ((qa.skills_dropped || []).length)
    items.push(`<li><span class="tag">dropped invented skills/certs</span>: ${esc(qa.skills_dropped.join(', '))}</li>`);
  (qa.experience_fixed || []).forEach(e =>
    items.push(`<li><span class="tag">experience</span> (${esc(e.company)}): ${esc((e.changes||[]).join('; '))}</li>`));
  (qa.unmatched_experience || []).forEach(u =>
    items.push(`<li class="crit"><span class="tag">UNMATCHED</span>: ${esc(u.role)} @ ${esc(u.company)} — review manually</li>`));
  (qa.ungrounded_in_bullets || []).forEach(b =>
    items.push(`<li class="crit"><span class="tag">ungrounded term</span> (${esc(b.company)}): ${esc((b.terms||[]).join(', '))}</li>`));
  (qa.fabricated_numbers || []).forEach(f =>
    items.push(`<li><span class="tag">fabricated number</span> (${esc(f.company)}): ${esc((f.numbers||[]).join(', '))}</li>`));
  if (!items.length) items.push('<li>see qa_report.json</li>');
  return `<div class="qa dirty"><span class="tag">Truth-guard caught issues:</span><ul>${items.join('')}</ul></div>` + extra;
}

// Downloadable artifacts for a run. Nothing is stored on disk — each link hits
// /download/<run_id>/<artifact>, which renders (PDF/DOCX) or serves (JSON/email)
// the artifact on demand. `download` attr forces a save rather than navigation.
const RUN_ARTIFACTS = [
  ['resume.pdf','Resume PDF'], ['resume.docx','Resume DOCX'],
  ['cover.pdf','Cover PDF'], ['cover.docx','Cover DOCX'],
  ['email.txt','Email'], ['resume.json','resume.json'],
  ['cover_letter.json','cover_letter.json'], ['qa_report.json','qa_report.json'],
  ['target_role.json','target_role.json'],
];
function runIdOf(data) {
  return (data && (data.run_id || data.folder_name || data.folder)) || '';
}
function filesForRun(data) {
  const runId = typeof data === 'string' ? data : runIdOf(data);
  if (!runId) return '';
  const links = RUN_ARTIFACTS.map(([art, label]) =>
    `<a class="dl-link" href="/download/${enc(runId)}/${art}" download>${label}</a>`).join('');
  return `<div class="files">${links}</div>`;
}
// Download a file WITHOUT opening a new tab. The server sends Content-Disposition:
// attachment, so loading the URL in a hidden iframe triggers a save to disk while
// the current page/state is untouched. This avoids relying on the <a download>
// attribute (which some browsers/webviews ignore, opening the PDF in a tab/Adobe).
function dlFile(url) {
  let ifr = document.getElementById('tm-dl-frame');
  if (!ifr) {
    ifr = document.createElement('iframe');
    ifr.id = 'tm-dl-frame';
    ifr.style.display = 'none';
    document.body.appendChild(ifr);
  }
  ifr.src = url;
}
// Delegated: any .dl-link anywhere downloads in place (no new tab).
document.addEventListener('click', (e) => {
  const a = e.target.closest && e.target.closest('a.dl-link');
  if (!a) return;
  e.preventDefault();
  dlFile(a.getAttribute('href'));
});
// Delegated: any [data-copy] button copies its text to the clipboard.
document.addEventListener('click', (e) => {
  const b = e.target.closest && e.target.closest('[data-copy]');
  if (!b) return;
  const text = b.getAttribute('data-copy') || '';
  const done = () => toast(`Copied ${b.dataset.copylabel || 'text'}.`);
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(done, () => fallbackCopy(text, done));
  } else { fallbackCopy(text, done); }
});
function fallbackCopy(text, done) {
  const ta = document.createElement('textarea');
  ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
  document.body.appendChild(ta); ta.focus(); ta.select();
  try { document.execCommand('copy'); done(); } catch { toast('Copy failed.', true); }
  ta.remove();
}

// Résumé text marks key phrases as **phrase**; the documents print them bold.
const rich = s => esc(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/\*\*/g, '');
function resumeHTML(r) {
  if (!r || !r.fullName) return '<div class="empty">No resume.</div>';
  const c = r.contact || {};
  const links = (c.links || []).map(l => esc((l.url||'').replace(/^https?:\/\/(www\.)?/i, '').replace(/\/$/, '') || l.label)).join('  |  ');
  const contact = [esc(c.location), esc(c.email), esc(c.phone), links].filter(Boolean).join('  |  ');
  const skills = (r.skills||[]).map(s => `<span>${esc(s)}</span>`).join('');
  const exp = (r.experience||[]).map(e => `
    <div class="job">
      <div class="hd"><span class="co">${esc(e.role)}  |  ${esc(e.company)}</span><span class="dt">${esc(e.dates || [e.start, e.end].filter(Boolean).join(' to '))}</span></div>
      <ul>${(e.bullets||[]).map(b => `<li>${rich(b)}</li>`).join('')}</ul>
    </div>`).join('');
  const edu = (r.education||[]).map(e =>
    `<div class="edu"><b>${esc(e.credential)}</b>  |  ${esc(e.institution)}${e.year ? ', ' + esc(e.year) : ''}</div>`).join('');
  const certs = (r.certifications||[]).length
    ? `<div class="sec">Certifications</div>${r.certifications.map(x=>`<div class="edu">${esc(x)}</div>`).join('')}` : '';
  const points = r.summaryPoints || [];
  const summary = points.length
    ? `<ul>${points.map(p => `<li>${rich(p)}</li>`).join('')}</ul>`
    : `<div>${rich(r.summary)}</div>`;
  return `<div class="doc">
    <h3>${esc(r.fullName)}</h3>
    ${r.headline ? `<div class="headline">${esc(r.headline)}</div>` : ''}
    <div class="contact">${contact}</div>
    <div class="sec">Career Summary</div>${summary}
    ${skills ? `<div class="sec">Skills</div><div class="skills">${skills}</div>` : ''}
    <div class="sec">Professional Experience</div>${exp}
    <div class="sec">Education</div>${edu}
    ${certs}
  </div>`;
}
function coverHTML(c) {
  if (!c || !c.fullName) return '<div class="empty">No cover letter.</div>';
  const paras = (c.body||[]).map(p => `<p>${esc(p)}</p>`).join('');
  return `<div class="doc">
    <h3>${esc(c.fullName)}</h3>
    <div class="contact">${esc(c.contactLine)}</div>
    <p>${esc(c.greeting)}</p>${paras}
    <p>${esc(c.signOff)}<br>${esc(c.signature)}</p>
  </div>`;
}
function emailHTML(e) {
  if (!e || (!e.subject && !e.body)) return '<div class="empty">No email.</div>';
  const subj = e.subject || '', body = e.body || '';
  const full = `Subject: ${subj}\n\n${body}`;
  return `<div style="display:flex;gap:8px;justify-content:flex-end;margin-bottom:8px;flex-wrap:wrap">
      <button class="btn subtle sm" data-copy="${esc(subj)}" data-copylabel="subject">📋 Copy subject</button>
      <button class="btn subtle sm" data-copy="${esc(body)}" data-copylabel="body">📋 Copy body</button>
      <button class="btn primary sm" data-copy="${esc(full)}" data-copylabel="email">📋 Copy email</button>
    </div>
    <pre class="email"><b>Subject:</b> ${esc(subj)}\n\n${esc(body)}</pre>`;
}
function previewBlock(data) {
  const tabs = [
    ['Resume', resumeHTML(data.resume)],
    ['Cover letter', coverHTML(data.cover_letter)],
    ['Email', emailHTML(data.email)],
  ];
  const head = tabs.map((t,i) => `<div class="pvtab ${i===0?'active':''}" data-pv="${i}">${t[0]}</div>`).join('');
  const bodies = tabs.map((t,i) => `<div data-pvbody="${i}" style="display:${i===0?'block':'none'}">${t[1]}</div>`).join('');
  return `<div class="preview"><div class="pvtabs">${head}</div><div class="pvbody">${bodies}</div></div>`;
}
function wirePreview(root) {
  root.querySelectorAll('.pvtab').forEach(t => t.onclick = () => {
    root.querySelectorAll('.pvtab').forEach(x => x.classList.remove('active'));
    t.classList.add('active');
    root.querySelectorAll('[data-pvbody]').forEach(b =>
      b.style.display = b.dataset.pvbody === t.dataset.pv ? 'block' : 'none');
  });
}
// Build the full application block (QA + files + preview) into a container.
function renderApplication(container, data, filesHTML) {
  const viol = data.qa_has_violations ?? (qaCount(data.qa) > 0);
  container.classList.add('app-block');   // marker so Apply can refresh the preview
  container.innerHTML = renderQA(data.qa, viol) + reviewBlock(data) + filesHTML + previewBlock(data);
  wirePreview(container);
  wireReview(container, data);
}
// Re-render the preview tabs in place (after a rewrite is applied) so the editor
// shows the rewritten résumé/cover, not the original generated text.
function refreshPreview(fromEl, data) {
  const root = fromEl.closest('.app-block'); if (!root) return;
  const pv = root.querySelector('.preview'); if (!pv) return;
  pv.outerHTML = previewBlock(data);
  wirePreview(root);
}

/* ---------- Hermes review (LLM critique of the generated resume) ---------- */
function reviewBlock(data) {
  const note = CLOUD_ENABLED
    ? 'Ask the Hermes agent to critique this resume against the job description (alignment, gaps, missing keywords, suggestions). If it judges a rewrite necessary, it proposes a truth-guarded rewritten résumé you can apply with one click — it never invents facts.'
    : 'Set <code>HERMES_API_KEY</code> in .env (the Hermes gateway key) to enable the Hermes review.';
  return `<div class="hr-review" style="margin:6px 0 14px">
    <button class="btn subtle sm" data-act="hr-review" ${CLOUD_ENABLED?'':'disabled'}>🤖 Review with Hermes</button>
    <button class="btn subtle sm" data-act="hr-gaps" ${CLOUD_ENABLED?'':'disabled'} title="Hermes lists the job's skills/tools not in your résumé and asks if you have them. Confirm yes/no, then it rewrites using only what you confirm.">🔎 Skill gap check</button>
    <span class="muted" style="font-size:12px;margin-left:8px">${note}</span>
    <textarea class="hr-instr" placeholder="(optional) specific change suggestions for Hermes — e.g. 'lead with my IT support experience', 'surface n8n and automation', 'shorten the summary to 2 lines'. Hermes applies them only where your real facts support it (never invents)." style="width:100%;min-height:60px;margin-top:8px;font-size:13px" ${CLOUD_ENABLED?'':'disabled'}></textarea>
    <div class="hr-gaps-out" style="margin-top:10px"></div>
    <div class="hr-review-out" style="margin-top:10px"></div>
  </div>`;
}
function wireReview(container, data) {
  const btn = container.querySelector('[data-act="hr-review"]');
  if (!btn) return;
  btn.onclick = async () => {
    const out = container.querySelector('.hr-review-out');
    const label = btn.textContent; btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Hermes is reviewing…';
    out.innerHTML = '';
    const instr = (container.querySelector('.hr-instr')?.value || '').trim();
    const body = data.folder_name ? { folder_name: data.folder_name }
               : { resume: data.resume, target: data.target };
    if (instr) body.instructions = instr;
    try {
      const r = await api('/review', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
      out.innerHTML = renderReview(r, data.folder_name);
      wireApplyRewrite(out, data);
      loadUsage();
    } catch (e) {
      out.innerHTML = `<div class="qa dirty">${esc(e.message)}</div>`;
    } finally { btn.disabled = false; btn.textContent = label; }
  };

  // Skill-gap Q&A: Hermes asks which JD skills you have; confirmed ones drive a rewrite.
  const gbtn = container.querySelector('[data-act="hr-gaps"]');
  if (gbtn) gbtn.onclick = async () => {
    const gout = container.querySelector('.hr-gaps-out');
    const label = gbtn.textContent; gbtn.disabled = true; gbtn.innerHTML = '<span class="spinner"></span> Analyzing…';
    gout.innerHTML = '';
    const body = data.folder_name ? { folder_name: data.folder_name } : { resume: data.resume, target: data.target };
    try {
      const r = await api('/review/skill-gaps', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
      const gaps = (r && r.gaps) || [];
      if (!gaps.length) { gout.innerHTML = `<div class="qa clean">No missing JD skills found — your résumé already covers them.</div>`; loadUsage(); return; }
      gout.innerHTML = `<div class="card" style="padding:12px 14px">
        <div style="font-weight:700;margin-bottom:6px">🔎 Do you have these skills the job wants? <span class="muted" style="font-weight:400;font-size:12px">Tick the ones you genuinely have.</span></div>
        ${gaps.map((g,i) => `<label class="checks" style="display:flex;gap:8px;margin:4px 0;font-size:13px"><input type="checkbox" class="gap-ck" value="${esc(g.skill)}" style="width:auto"> <span><b>${esc(g.skill)}</b>${g.why ? ` <span class="muted">— ${esc(g.why)}</span>` : ''}</span></label>`).join('')}
        <div style="margin-top:10px"><button class="btn primary sm" data-act="gap-rewrite">✍️ Rewrite with my confirmed skills</button> <span class="muted" style="font-size:12px;margin-left:6px">Only ticked skills are added — and only where they fit truthfully.</span></div>
        <div class="hr-gap-review" style="margin-top:10px"></div>
      </div>`;
      gout.querySelector('[data-act="gap-rewrite"]').onclick = async (e) => {
        const rb = e.currentTarget;
        const confirmed = [...gout.querySelectorAll('.gap-ck:checked')].map(c => c.value);
        if (!confirmed.length) { toast('Tick at least one skill you have.', true); return; }
        const rout = gout.querySelector('.hr-gap-review');
        const lbl = rb.textContent; rb.disabled = true; rb.innerHTML = '<span class="spinner"></span> Hermes is rewriting…';
        try {
          const rr = await api('/review', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ ...body, confirmed_skills: confirmed }) });
          rout.innerHTML = renderReview(rr, data.folder_name);
          wireApplyRewrite(rout, data);
          loadUsage();
        } catch (err) { rout.innerHTML = `<div class="qa dirty">${esc(err.message)}</div>`; }
        finally { rb.disabled = false; rb.textContent = lbl; }
      };
      loadUsage();
    } catch (e) {
      gout.innerHTML = `<div class="qa dirty">${esc(e.message)}</div>`;
    } finally { gbtn.disabled = false; gbtn.textContent = label; }
  };
}
// Wire every "Apply rewrite" button (résumé and/or cover letter) in the review panel.
function wireApplyRewrite(out, data) {
  out.querySelectorAll('[data-act="hr-apply"]').forEach(ab => {
    const kind = ab.dataset.kind || 'resume';
    if (!data.folder_name) {  // inline review (not a saved run) — nothing to re-render
      ab.disabled = true; ab.title = 'Generate/save this application first to apply a rewrite.';
      return;
    }
    ab.onclick = async () => {
      const lbl = ab.textContent; ab.disabled = true; ab.innerHTML = '<span class="spinner"></span> Applying…';
      try {
        const res = await api('/review/apply', { method: 'POST', headers: {'Content-Type':'application/json'},
          body: JSON.stringify({ folder_name: data.folder_name, kind }) });
        if (res.resume) data.resume = res.resume;            // reflect in the live preview
        if (res.cover_letter) data.cover_letter = res.cover_letter;
        refreshPreview(ab, data);                            // update the editor/preview tabs in place
        ab.textContent = '✓ Applied · preview + DOCX/PDF updated';
        toast(`Rewrite applied. Originals backed up in ${res.backup}.`);
      } catch (e) {
        ab.disabled = false; ab.textContent = lbl; toast('Apply failed: ' + e.message, true);
      }
    };
  });
}
function scoreColor(n) { n = Number(n)||0; return n>=75 ? '#1a9e5f' : n>=50 ? '#b8860b' : '#d94646'; }
// The full review panel: a critique card for the résumé, one for the cover letter,
// and a deterministic page-validation card.
function renderReview(r, folderName) {
  if (!r) return '';
  const resumeCard = reviewCard(r, {
    title: '📃 Résumé', label: 'résumé', kind: 'resume', folderName,
    recommended: r.rewrite_recommended, rewrite: r.rewrite, changes: r.rewrite_changes,
    qaViol: r.rewrite_qa_has_violations, error: r.rewrite_error,
  });
  let coverCard = '';
  if (r.cover_review) {
    coverCard = reviewCard(r.cover_review, {
      title: '✉️ Cover letter', label: 'cover letter', kind: 'cover', folderName,
      recommended: r.cover_review.rewrite_recommended, rewrite: r.cover_rewrite,
      changes: r.cover_rewrite_changes, error: r.cover_review_error,
      qaViol: !!(r.cover_rewrite_qa && r.cover_rewrite_qa.claims_stripped),
    });
  } else if (r.cover_review_error) {
    coverCard = `<div class="hr-card"><div class="hr-h crit">✉️ Cover letter review failed</div><div class="muted">${esc(r.cover_review_error)}</div></div>`;
  }
  return resumeCard + coverCard + pagesCard(r.pages);
}
// One critique card (shared by résumé + cover letter). `rev` is a ResumeReview dump;
// `opts` carries the title and this artifact's rewrite payload + apply kind.
function reviewCard(rev, opts) {
  if (!rev) return '';
  opts = opts || {};
  const list = (title, items, cls) => (items && items.length)
    ? `<div class="hr-sec"><div class="hr-h ${cls||''}">${title}</div><ul>${items.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div>` : '';
  const chips = items => (items && items.length)
    ? items.map(k=>`<span class="rp-chip">${esc(k)}</span>`).join(' ') : '<span class="muted">none</span>';
  return `<div class="hr-card">
    ${opts.title ? `<div class="hr-h" style="font-size:13px;margin-bottom:8px">${opts.title}</div>` : ''}
    <div class="hr-scores">
      <div class="hr-score"><div class="hr-num" style="color:${scoreColor(rev.overall_score)}">${rev.overall_score|0}</div><div class="hr-lbl">overall</div></div>
      <div class="hr-score"><div class="hr-num" style="color:${scoreColor(rev.jd_match_score)}">${rev.jd_match_score|0}</div><div class="hr-lbl">JD match</div></div>
      <div class="hr-verdict">${esc(rev.verdict||'')}</div>
    </div>
    ${list('✅ Strengths', rev.strengths)}
    ${list('⚠️ Weaknesses', rev.weaknesses)}
    <div class="hr-sec"><div class="hr-h">🔑 Missing keywords</div><div style="display:flex;gap:6px;flex-wrap:wrap">${chips(rev.missing_keywords)}</div></div>
    ${list('💡 Suggestions', rev.suggestions)}
    ${list('🚩 Risk flags — verify before sending', rev.risk_flags, 'crit')}
    ${rewriteSection(opts)}
  </div>`;
}
// Hermes-proposed rewrite for one artifact (only when it judged one necessary).
// Truth-guarded server-side; applying re-renders the DOCX/PDF and backs up originals.
function rewriteSection(o) {
  if (o.error) return `<div class="hr-sec"><div class="hr-h crit">✍️ Rewrite failed</div><div class="muted">${esc(o.error)}</div></div>`;
  if (!o.recommended) return '';
  if (!o.rewrite) return `<div class="hr-sec"><div class="hr-h">✍️ Rewrite</div><div class="muted">Hermes suggested a rewrite but none was produced.</div></div>`;
  const changes = (o.changes && o.changes.length)
    ? `<ul>${o.changes.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`
    : '<div class="muted">Presentation tweaks only.</div>';
  const scrub = o.qaViol
    ? '<div class="muted" style="margin-top:6px">⚠️ The truth-guard removed unsupported claims the rewrite introduced — facts preserved.</div>' : '';
  const hint = o.folderName ? '' : '<div class="muted" style="margin-top:6px">Generate/save this application to enable Apply.</div>';
  return `<div class="hr-sec" style="border-top:1px solid var(--line);padding-top:10px;margin-top:10px">
    <div class="hr-h">✍️ Hermes ${esc(o.label||'')} rewrite — truth-guarded, facts unchanged</div>
    ${changes}${scrub}
    <button class="btn primary sm" data-act="hr-apply" data-kind="${esc(o.kind)}" style="margin-top:10px">⬆ Apply rewrite (re-render DOCX/PDF)</button>
    <span class="muted" style="font-size:12px;margin-left:8px">Backs up the originals first.</span>${hint}
  </div>`;
}
// Deterministic page validation: count vs limit + physical Letter/A4 size.
function pagesCard(pages) {
  if (!pages) return '';
  const row = (p) => {
    if (!p || !p.available) return '';
    const cIcon = p.pages_ok ? '✅' : '⚠️', sIcon = p.size_ok ? '✅' : '⚠️';
    return `<div class="hr-sec" style="display:flex;gap:14px;align-items:center;flex-wrap:wrap">
      <b>${esc(p.label)}</b>
      <span>${cIcon} ${p.pages}/${p.limit} page${p.limit>1?'s':''}${p.pages_ok?'':' — too long, tighten it'}</span>
      <span>${sIcon} ${esc(p.page_size)}${p.size_ok?'':` (expected ${esc(p.expected_size)})`}</span>
    </div>`;
  };
  const rows = row(pages.resume) + row(pages.cover_letter);
  if (!rows) return '';
  return `<div class="hr-card"><div class="hr-h" style="font-size:13px;margin-bottom:6px">📄 Page validation</div>${rows}</div>`;
}

/* ---------- Generate ---------- */
$('g-go').onclick = async () => {
  const btn = $('g-go');
  const body = {
    company: $('g-company').value.trim(), title: $('g-title').value.trim(),
    description: $('g-description').value.trim(), location: $('g-location').value.trim(),
    model: resolveModel(false), persona: activePersona(), strict: $('g-strict').checked, pdf: $('g-pdf').checked,
  };
  if (!body.company || !body.title || !body.description) { toast('Company, title, and description are required.', true); return; }
  const box = $('g-result');
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Generating…';
  box.innerHTML = '<div class="empty"><span class="spinner dark"></span><div style="margin-top:10px">Generating — this can take a minute…</div></div>';
  try {
    const res = await api('/generate', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
    renderApplication(box, res, filesForRun(res));
    toast('Generated' + (res.persona_label ? ` · ${res.persona_label} persona` : ' · neutral') + performanceText(res));
    notifyFallback(res);
    loadUsage();
  } catch (e) {
    box.innerHTML = `<div class="qa dirty"><b>Generation failed:</b> ${esc(e.message)}</div>`;
  } finally { btn.disabled = false; btn.textContent = 'Generate application'; }
};

/* Job picker — three modes: 'generate' (load one into the form), 'qa' (pick one
   for screening Q&A), and 'bulk' (multi-select many → add to the Bulk list). */
const gPick = { rows: [], sel: new Set() };
// Rebuild the source dropdown from the sources actually present in the loaded
// jobs (dynamic — never hardcoded). Preserves the current selection if it survives.
function gSyncPickSources() {
  const sel = $('g-pick-source'); if (!sel) return;
  const cur = sel.value;
  const names = [...new Set((gPick.all || []).map(j => (j.source || '').trim()).filter(Boolean))].sort();
  sel.innerHTML = '<option value="">All sources</option>' +
    names.map(n => `<option value="${esc(n)}">${esc(n)}</option>`).join('');
  sel.value = names.includes(cur) ? cur : '';
}
function gRenderPick(all) {
  if (all) { gPick.all = all; gSyncPickSources(); }
  const q = $('g-pick-search').value.trim().toLowerCase();
  const daysVal = $('g-pick-days').value;
  const source = $('g-pick-source').value;
  const bulk = gPick.mode === 'bulk';
  const rows = gPick.rows = (gPick.all || []).filter(j => {
    if (j.irrelevant) return false;   // never offer not-relevant jobs for bulk
    if (source && (j.source || '').trim() !== source) return false;
    if (!jobInRange(j, daysVal)) return false;
    return !q || [j.title, j.company, j.location].join(' ').toLowerCase().includes(q);
  });
  $('g-pick-list').innerHTML = rows.length ? rows.map((j, i) => `
    <div class="g-pick-row" data-i="${i}" style="display:flex;gap:10px;align-items:flex-start;padding:10px 12px;border:1px solid var(--line);border-radius:10px;margin-bottom:8px;cursor:pointer">
      ${bulk ? `<input type="checkbox" class="g-pick-ck" ${gPick.sel.has(j.key_id)?'checked':''} style="width:auto;margin-top:3px;pointer-events:none">` : ''}
      <div style="flex:1">
        <div style="font-weight:600">${esc(j.title || 'Untitled')}${(j.contact_email||'').trim()?' 📧':''}</div>
        <div style="font-size:13px;color:var(--muted)">${esc([j.company, j.location].filter(Boolean).join(' · '))} · <span class="jl-st ${esc(j.status)}">${esc(j.status)}</span> · ${esc(jobDate(j))}</div>
      </div>
    </div>`).join('') : '<div class="empty">No jobs match. Adjust the day filter or search.</div>';
  $('g-pick-list').querySelectorAll('.g-pick-row').forEach(el => el.onclick = () => {
    const j = gPick.rows[+el.dataset.i];
    if (bulk) {
      if (j.key_id == null) return;
      if (gPick.sel.has(j.key_id)) gPick.sel.delete(j.key_id); else gPick.sel.add(j.key_id);
      const ck = el.querySelector('.g-pick-ck'); if (ck) ck.checked = gPick.sel.has(j.key_id);
      gUpdatePickFoot();
      return;
    }
    if (gPick.mode === 'qa') { qaSetJob(j); $('g-pick').classList.remove('show'); return; }
    $('g-company').value = j.company || ''; $('g-title').value = j.title || '';
    $('g-location').value = j.location || ''; $('g-description').value = j.description || '';
    $('g-pick').classList.remove('show');
    toast(`Loaded "${j.title || 'job'}" into the form.`);
  });
  $('g-pick-foot').style.display = bulk ? '' : 'none';
  $('g-pick-allbtn').style.display = bulk ? '' : 'none';
  $('g-pick-h').textContent = bulk ? 'Add jobs from the queue to Bulk'
    : gPick.mode === 'qa' ? 'Pick a job for screening Q&A' : 'Load a job into the form';
  gUpdatePickFoot();
}
function gUpdatePickFoot() {
  const n = gPick.sel.size, b = $('g-pick-add');
  if (b) { b.textContent = `Add selected (${n})`; b.disabled = !n; }
}
async function openPick(mode) {
  gPick.mode = mode || 'generate';
  gPick.sel = new Set();
  $('g-pick').classList.add('show');
  $('g-pick-list').innerHTML = '<div class="empty"><span class="spinner dark"></span></div>';
  try {
    const { jobs } = await api('/jobs' + (mode === 'bulk' ? '?status=new' : ''));
    gRenderPick(jobs); $('g-pick-search').focus();
  } catch (e) { $('g-pick-list').innerHTML = `<div class="qa dirty">${esc(e.message)}</div>`; }
}
$('g-fromjob').onclick = () => openPick('generate');
$('g-pick-search').oninput = () => gRenderPick();
$('g-pick-days').onchange = () => gRenderPick();
$('g-pick-source').onchange = () => gRenderPick();
$('g-pick-x').onclick = () => $('g-pick').classList.remove('show');
$('g-pick').onclick = (e) => { if (e.target === $('g-pick')) $('g-pick').classList.remove('show'); };
// Bulk mode: select-all (filtered) + add selected to the Bulk list.
$('g-pick-allbtn').onclick = () => {
  const ids = gPick.rows.map(j => j.key_id).filter(x => x != null);
  const turnOn = !ids.every(id => gPick.sel.has(id));
  ids.forEach(id => turnOn ? gPick.sel.add(id) : gPick.sel.delete(id));
  gRenderPick();
};
$('g-pick-add').onclick = () => {
  let added = 0;
  (gPick.all || []).forEach(j => {
    if (j.key_id != null && gPick.sel.has(j.key_id)) {
      bulkAdd({ key_id: j.key_id, company: j.company||'', title: j.title||'', location: j.location||'', description: j.description||'' }, false);
      added++;
    }
  });
  $('g-pick').classList.remove('show');
  if (!added) { toast('No jobs selected.', true); return; }
  toast(`Added ${added} job${added===1?'':'s'} to the bulk list.`);
  if ($('b-autogen').checked) runBulk();
};

/* ---------- Q&A (screening questions) ---------- */
let qaJob = null;   // {key_id, priority, ...} when a queued job is selected
function qaSetJob(j) {
  qaJob = j;
  $('qa-jobkey').value = j.key_id || '';
  $('qa-company').value = j.company || ''; $('qa-title').value = j.title || '';
  $('qa-location').value = j.location || ''; $('qa-description').value = j.description || '';
  $('qa-jobline').innerHTML = `Selected: <b>${esc(j.title || 'job')}</b>${j.company ? ' @ ' + esc(j.company) : ''}${j.priority ? ' ⭐' : ''}`;
}
$('qa-fromjob').onclick = () => openPick('qa');
// Editing the role fields by hand detaches from the queued job (use inline fields).
['qa-company','qa-title','qa-location','qa-description'].forEach(id => $(id).addEventListener('input', () => {
  if (qaJob) { qaJob = null; $('qa-jobkey').value = ''; $('qa-jobline').textContent = 'Using the fields above (not linked to a saved job).'; }
}));
/* Dynamic question rows — answer several screening questions at once. */
function qaAddRow(focus) {
  const list = $('qa-qlist');
  const row = document.createElement('div');
  row.className = 'qa-qrow';
  row.style = 'border:1px solid var(--line);border-radius:10px;padding:10px;margin-bottom:10px';
  row.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
      <span class="fld qa-qnum" style="margin:0"></span>
      <button class="btn ghost sm qa-rm" type="button" title="Remove question">✕</button>
    </div>
    <textarea class="qa-q" placeholder="e.g. Why do you want to work here? / Tell me about a time you solved a hard problem." style="min-height:64px;width:100%"></textarea>
    <textarea class="qa-d" placeholder="(optional) your rough draft — I'll rephrase it truthfully for this role" style="min-height:44px;width:100%;margin-top:6px"></textarea>`;
  list.appendChild(row);
  row.querySelector('.qa-rm').onclick = () => {
    if (list.querySelectorAll('.qa-qrow').length <= 1) { row.querySelector('.qa-q').value = ''; row.querySelector('.qa-d').value = ''; }
    else { row.remove(); }
    qaRenumber();
  };
  qaRenumber();
  if (focus) row.querySelector('.qa-q').focus();
}
function qaRenumber() {
  const rows = $('qa-qlist').querySelectorAll('.qa-qrow');
  rows.forEach((r, i) => { r.querySelector('.qa-qnum').textContent = `Question ${i + 1}`; });
  rows.forEach(r => { r.querySelector('.qa-rm').style.display = rows.length > 1 ? '' : 'none'; });
}
// Start with one row.
qaAddRow(false);
$('qa-add').onclick = () => qaAddRow(true);

$('qa-go').onclick = async () => {
  const rows = [...$('qa-qlist').querySelectorAll('.qa-qrow')];
  const items = rows.map(r => ({
    question: r.querySelector('.qa-q').value.trim(),
    draft: r.querySelector('.qa-d').value.trim(),
  })).filter(it => it.question);
  if (!items.length) { toast('Type or paste at least one question.', true); return; }
  const mw = parseInt($('qa-length').value, 10);
  const btn = $('qa-go'), box = $('qa-result');
  const body = {
    items,
    model: resolveModel(!!(qaJob && qaJob.priority)),
    max_words: Number.isFinite(mw) ? mw : null,
    job_key: $('qa-jobkey').value || '',
    company: $('qa-company').value.trim(), title: $('qa-title').value.trim(),
    description: $('qa-description').value.trim(), location: $('qa-location').value.trim(),
  };
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Writing…';
  box.innerHTML = `<div class="empty"><span class="spinner dark"></span><div style="margin-top:10px">Writing ${items.length} answer${items.length>1?'s':''}…</div></div>`;
  try {
    const res = await api('/answers', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
    qaRenderAnswers(res.answers || []);
    const ok = (res.answers || []).filter(a => !a.error).length;
    toast(`${ok} answer${ok!==1?'s':''} ready.`);
    loadUsage();
  } catch (e) {
    box.innerHTML = `<div class="qa dirty"><b>Failed:</b> ${esc(e.message)}</div>`;
  } finally { btn.disabled = false; btn.textContent = 'Generate answers'; }
};

function wordCount(s) { return (String(s).trim().match(/\S+/g) || []).length; }

function qaRenderAnswers(answers) {
  const box = $('qa-result');
  if (!answers.length) { box.innerHTML = '<div class="empty"><div class="big">💬</div>No answers.</div>'; return; }
  const allText = answers.filter(a => a.answer).map(a => `Q: ${a.question}\n${a.answer}`).join('\n\n');
  box.innerHTML =
    `<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
       <div class="sec-title" style="margin:0">Answers (${answers.length})</div>
       <button class="btn ghost sm" id="qa-copyall">📋 Copy all</button>
     </div>` +
    answers.map((a, i) => a.error
      ? `<div class="qa dirty" style="margin-bottom:12px"><b>Q${i+1} failed:</b> ${esc(a.error)}</div>`
      : `<div style="border:1px solid var(--line);border-radius:10px;padding:12px;margin-bottom:12px">
           <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px">
             <div style="font-size:13px;color:var(--muted);font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">Q${i+1}: ${esc(a.question)}</div>
             <button class="btn ghost sm qa-copy1" data-i="${i}">📋 <span style="opacity:.6">${wordCount(a.answer)}w</span></button>
           </div>
           <div style="white-space:pre-wrap;line-height:1.55">${esc(a.answer)}</div>
         </div>`).join('');
  const copyBtn = $('qa-copyall');
  if (copyBtn) copyBtn.onclick = () => { navigator.clipboard.writeText(allText); toast('All answers copied.'); };
  box.querySelectorAll('.qa-copy1').forEach(b => b.onclick = () => {
    navigator.clipboard.writeText(answers[+b.dataset.i].answer || ''); toast('Answer copied.');
  });
}

/* ---------- Repeatable roles ---------- */
let rpRoles = [], rpFacets = { sectors: [], statuses: [], tags: [] };
let rpCompanies = [];          // repeat-companies list (clickable company filter tags)
let rpCompanyFilter = '';      // active company tag ('' = all)
const RP_STATUSES = ['tracked', 'applied', 'interview', 'offer', 'closed'];
async function loadRepeatable() {
  const box = $('rp-list');
  box.innerHTML = '<div class="empty"><span class="spinner dark"></span></div>';
  try {
    const r = await api('/repeatable');
    rpRoles = r.roles || [];
    rpFacets = { sectors: r.sectors || [], statuses: r.statuses || [], tags: r.tags || [] };
    rpFillFilters();
    rpRender();
    rpRenderCompanies();   // repeat-companies chips (best-effort)
  } catch (e) { box.innerHTML = `<div class="qa dirty">${esc(e.message)}</div>`; }
}
// Repeat companies list (data/repeat_companies.json) — these companies post the
// same/similar roles you reapply to. Lives in the Repeatable tab.
async function rpRenderCompanies() {
  const el = $('rp-companies'); if (!el) return;
  try {
    const ap = await api('/apply-profile');
    rpCompanies = ap.repeat_companies || [];
  } catch { rpCompanies = []; }
  rpDrawCompanies();
}
// Render the repeat companies as clickable filter tags — click one to show only
// its roles, "All" to clear. Counts come from the loaded repeatable roles.
function rpDrawCompanies() {
  const el = $('rp-companies'); if (!el) return;
  if (!rpCompanies.length) {
    el.innerHTML = '<span class="muted">None yet — add companies you reapply to in data/repeat_companies.json.</span>';
    return;
  }
  const counts = {};
  rpRoles.forEach(r => { const c = r.company || ''; if (c) counts[c] = (counts[c] || 0) + 1; });
  const chip = (label, co, active) =>
    `<span class="rp-cochip" data-co="${esc(co)}" style="display:inline-block;padding:3px 11px;margin:0 6px 6px 0;border-radius:999px;cursor:pointer;font-size:12px;border:1px solid ${active ? 'var(--accent)' : 'var(--line)'};${active ? 'background:var(--accent);color:#fff' : 'color:var(--muted)'}">${esc(label)}</span>`;
  el.innerHTML =
    chip('All', '', rpCompanyFilter === '') +
    rpCompanies.map(c => chip(counts[c] ? `${c} · ${counts[c]}` : c, c, rpCompanyFilter === c)).join('');
  el.querySelectorAll('.rp-cochip').forEach(ch => ch.onclick = () => {
    rpCompanyFilter = ch.dataset.co || '';
    rpDrawCompanies();   // refresh active highlight
    rpRender();          // re-filter the grouped list
  });
}
function rpFillFilters() {
  const keep = (sel) => sel.value;
  const fill = (sel, vals, all) => {
    const cur = keep(sel);
    sel.innerHTML = `<option value="">${all}</option>` + vals.map(v => `<option>${esc(v)}</option>`).join('');
    if ([...sel.options].some(o => o.value === cur)) sel.value = cur;
  };
  fill($('rp-fsector'), rpFacets.sectors, 'All sectors');
  fill($('rp-fstatus'), rpFacets.statuses.length ? rpFacets.statuses : RP_STATUSES, 'All statuses');
  fill($('rp-ftag'), rpFacets.tags, 'All tags');
}
function rpFiltered() {
  const q = ($('rp-q').value || '').toLowerCase().trim();
  const fs = $('rp-fsector').value, fst = $('rp-fstatus').value, ft = $('rp-ftag').value;
  return rpRoles.filter(r => {
    if (rpCompanyFilter && (r.company || '') !== rpCompanyFilter) return false;
    if (fs && r.sector !== fs) return false;
    if (fst && (r.status || 'tracked') !== fst) return false;
    if (ft && !(r.tags || []).includes(ft)) return false;
    if (q) {
      const hay = `${r.company} ${r.title} ${r.location} ${r.job_id} ${(r.tags||[]).join(' ')}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}
const RP_STATUS_COLORS = { tracked:'#7e8ba3', applied:'#2d7ff9', interview:'#b8860b', offer:'#1a9e5f', closed:'#9aa3b2' };
// Some job_ids are full apply URLs (import sets job_id = apply_url). Show a short token,
// not the whole URL, so the chip doesn't blow up into a full-width box.
function shortJobId(s) {
  s = String(s || '');
  if (/^https?:\/\//i.test(s)) {
    const m = s.match(/[?&](?:jk|id|gh_jid|jobid|currentjobid)=([^&]+)/i);
    return m ? m[1] : 'link';
  }
  return s.length > 22 ? s.slice(0, 22) + '…' : s;
}
function rpRender() {
  const box = $('rp-list');
  if (!rpRoles.length) {
    $('rp-count').textContent = '';
    box.innerHTML = `<div class="empty"><div class="big">🔁</div>No repeatable roles yet. In <b>Jobs</b>, click the 🔁 on a job you reapply to often, or paste a job email above.</div>`;
    return;
  }
  const rows = rpFiltered();
  $('rp-count').textContent = `${rows.length} of ${rpRoles.length}`;
  if (!rows.length) { box.innerHTML = `<div class="empty">No roles match these filters.</div>`; return; }
  const rpCard = (r) => {
    const i = rpRoles.indexOf(r);
    const applied = r.times_applied ? `applied ${r.times_applied}×${r.last_applied ? ' · last ' + esc(r.last_applied) : ''}` : 'never generated yet';
    const jd = (r.description || '').trim();
    const st = r.status || 'tracked';
    const chips = [
      `<span class="rp-chip" style="background:${RP_STATUS_COLORS[st]||'#7e8ba3'}1a;color:${RP_STATUS_COLORS[st]||'#7e8ba3'}">${esc(st)}</span>`,
      r.sector ? `<span class="rp-chip">${esc(r.sector)}</span>` : '',
      r.job_id ? `<span class="rp-chip" title="Source job ID: ${esc(r.job_id)}">#${esc(shortJobId(r.job_id))}</span>` : '',
      ...(r.tags || []).map(t => `<span class="rp-chip">🏷 ${esc(t)}</span>`),
    ].join('');
    return `<div class="card rp-card" data-i="${i}">
      <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;flex-wrap:wrap">
        <div style="min-width:0">
          <div style="font-weight:700;font-size:15px">${esc(r.title || 'Untitled')}${r.priority ? ' ⭐' : ''}</div>
          <div class="muted" style="font-size:13px">${esc(r.company || '')}${r.location ? ' · ' + esc(r.location) : ''} · <span style="color:var(--accent)">${applied}</span></div>
          <div class="rp-chips" style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap">${chips}</div>
        </div>
        <div class="jl-rowbtns">
          ${r.last_folder_name ? `<button class="btn ghost sm" data-rpa="open" data-i="${i}" title="Open the last generated docs">📂 Last docs</button>` : ''}
          ${r.apply_url ? `<a class="btn subtle sm" href="${esc(r.apply_url)}" target="_blank" rel="noreferrer">Open ↗</a>` : ''}
          <button class="btn subtle sm" data-rpa="edit" data-i="${i}">✎ Edit</button>
          <button class="btn primary sm" data-rpa="gen" data-i="${i}">⟳ Regenerate</button>
          <button class="btn danger sm" data-rpa="del" data-i="${i}" title="Remove this role from Repeatable (asks first; keeps generated files)">🚫 Unrepeat</button>
        </div>
      </div>
      <div style="margin-top:8px">
        <input class="rp-skills jl-inp" data-i="${i}" placeholder="Skills to emphasise this regenerate (optional, comma-separated)" style="width:100%;font-size:12px" title="Re-orders and surfaces these skills in the résumé — only ones you genuinely have (truth-guard strips anything else). Leave blank for the default tailoring.">
      </div>
      <details style="margin-top:10px">
        <summary style="cursor:pointer;font-size:13px;color:var(--muted)">Tracking & tags</summary>
        <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:8px;align-items:flex-end">
          <label style="font-size:12px;color:var(--muted)">Status<br><select class="rp-status side-select" data-i="${i}" style="width:auto">${RP_STATUSES.map(s => `<option${s===st?' selected':''}>${s}</option>`).join('')}</select></label>
          <label style="font-size:12px;color:var(--muted)">Sector<br><input class="rp-sector" data-i="${i}" value="${esc(r.sector||'')}" placeholder="Banking…" style="width:140px" /></label>
          <label style="font-size:12px;color:var(--muted)">Job ID<br><input class="rp-jobid" data-i="${i}" value="${esc(r.job_id||'')}" placeholder="source id" style="width:140px" /></label>
          <label style="font-size:12px;color:var(--muted);flex:1;min-width:160px">Tags (comma-separated)<br><input class="rp-tags" data-i="${i}" value="${esc((r.tags||[]).join(', '))}" placeholder="remote, referral, urgent" style="width:100%" /></label>
          <button class="btn ghost sm" data-rpa="savemeta" data-i="${i}">Save</button>
        </div>
      </details>
      <details style="margin-top:8px"${jd ? '' : ' open'}>
        <summary style="cursor:pointer;font-size:13px;color:var(--muted)">Job description (${jd ? jd.length + ' chars' : 'empty — add one'})</summary>
        <textarea class="rp-jd" data-i="${i}" style="min-height:120px;margin-top:8px" placeholder="Paste the latest job description here…">${esc(jd)}</textarea>
        <div style="margin-top:6px"><button class="btn ghost sm" data-rpa="save" data-i="${i}">Save JD</button></div>
      </details>
      <div class="rp-out" data-i="${i}"></div>
    </div>`;
  };
  // Sort by COMPANY (these companies post the same/similar roles), companies A→Z,
  // and roles A→Z by title within each company.
  const byCompany = {};
  rows.forEach(r => { const c = r.company || '—'; (byCompany[c] = byCompany[c] || []).push(r); });
  box.innerHTML = Object.keys(byCompany)
    .sort((a, b) => a.toLowerCase().localeCompare(b.toLowerCase()))
    .map(co => {
      const roles = byCompany[co].slice()
        .sort((a, b) => (a.title || '').toLowerCase().localeCompare((b.title || '').toLowerCase()));
      return `<div class="rp-group" style="margin:0 0 18px">
        <div class="rp-head" style="display:flex;align-items:center;gap:10px;margin:0 0 10px;padding-bottom:6px;border-bottom:2px solid var(--accent)">
          <span style="font-weight:800;font-size:16px;color:var(--accent)">🏢 ${esc(co)}</span>
          <span class="jl-src" style="margin:0">${roles.length} role${roles.length > 1 ? 's' : ''}</span>
        </div>
        ${roles.map(rpCard).join('')}
      </div>`;
    }).join('');
  box.querySelectorAll('[data-rpa="gen"]').forEach(b => b.onclick = () => rpGenerate(rpRoles[+b.dataset.i], b));
  box.querySelectorAll('[data-rpa="save"]').forEach(b => b.onclick = () => rpSaveJd(rpRoles[+b.dataset.i], b));
  box.querySelectorAll('[data-rpa="savemeta"]').forEach(b => b.onclick = () => rpSaveMeta(rpRoles[+b.dataset.i], b));
  box.querySelectorAll('[data-rpa="edit"]').forEach(b => b.onclick = () => {
    b.closest('.rp-card').querySelectorAll('details').forEach(d => d.open = true);
  });
  box.querySelectorAll('[data-rpa="open"]').forEach(b => b.onclick = () => openLibrary(rpRoles[+b.dataset.i].last_folder_name));
  box.querySelectorAll('[data-rpa="del"]').forEach(b => b.onclick = () => rpDelete(rpRoles[+b.dataset.i], b));
}
async function rpSaveMeta(role, btn) {
  const i = rpRoles.indexOf(role), box = $('rp-list');
  const status = box.querySelector(`.rp-status[data-i="${i}"]`)?.value || 'tracked';
  const sector = box.querySelector(`.rp-sector[data-i="${i}"]`)?.value.trim() || '';
  const job_id = box.querySelector(`.rp-jobid[data-i="${i}"]`)?.value.trim() || '';
  const tags = box.querySelector(`.rp-tags[data-i="${i}"]`)?.value || '';
  btn.disabled = true;
  try {
    await api(`/repeatable/${enc(role.key)}/update`, { method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ status, sector, job_id, tags }) });
    Object.assign(role, { status, sector, job_id, tags: tags.split(',').map(s=>s.trim()).filter(Boolean) });
    toast('Saved.'); loadRepeatable();
  } catch (e) { toast('Save failed: ' + e.message, true); } finally { btn.disabled = false; }
}
async function rpSaveJd(role, btn) {
  const ta = $('rp-list').querySelector(`textarea.rp-jd[data-i="${rpRoles.indexOf(role)}"]`);
  const description = (ta?.value || '').trim();
  btn.disabled = true;
  try {
    await api(`/repeatable/${enc(role.key)}/update`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ description }) });
    role.description = description; toast('Job description saved.');
  } catch (e) { toast('Save failed: ' + e.message, true); } finally { btn.disabled = false; }
}
async function rpGenerate(role, btn) {
  const i = rpRoles.indexOf(role);
  const out = $('rp-list').querySelector(`.rp-out[data-i="${i}"]`);
  const skills_focus = ($('rp-list').querySelector(`.rp-skills[data-i="${i}"]`)?.value || '').trim();
  const model = resolveModel(!!role.priority);
  const label = btn.textContent; btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>' + (usesHermes(model) ? ' 🤖' : '');
  out.innerHTML = '<div class="empty" style="padding:18px"><span class="spinner dark"></span><div style="margin-top:8px">Regenerating a fresh tuned copy…</div></div>';
  try {
    const res = await api(`/repeatable/${enc(role.key)}/generate`, { method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ model, persona: activePersona(), strict: true, pdf: true, skills_focus }) });
    out.innerHTML = `<div style="margin-top:10px"><b>New docs ready</b> — download, tweak, reapply:</div>` + filesForRun(res);
    toast('Regenerated' + (res.persona_label ? ` · ${res.persona_label}` : ''));
    loadUsage();
    // refresh counts
    const upd = (await api('/repeatable')).roles.find(x => x.key === role.key);
    if (upd) { Object.assign(role, upd); }
    const meta = btn.closest('.rp-card').querySelector('.muted span'); if (meta && upd) meta.textContent = `applied ${upd.times_applied}× · last ${upd.last_applied}`;
  } catch (e) {
    out.innerHTML = `<div class="qa dirty" style="margin-top:10px"><b>Failed:</b> ${esc(e.message)}</div>`;
  } finally { btn.disabled = false; btn.innerHTML = label; }
}
async function rpDelete(role, btn) {
  if (!await uiConfirm({ title: 'Unrepeat this role?', message: `${role.title} @ ${role.company}\n\nIt will be removed from Repeatable. Generated files are kept.` })) return;
  btn.disabled = true;
  try { await api(`/repeatable/${enc(role.key)}`, { method: 'DELETE' }); toast('Unrepeated — removed from Repeatable.'); loadRepeatable(); }
  catch (e) { toast('Unrepeat failed: ' + e.message, true); btn.disabled = false; }
}
$('rp-refresh').onclick = () => loadRepeatable();
['rp-fsector', 'rp-fstatus', 'rp-ftag'].forEach(id => $(id).onchange = rpRender);
$('rp-q').oninput = rpRender;
$('rp-email-go').onclick = async () => {
  const text = $('rp-email-text').value.trim();
  if (!text) { toast('Paste an email first.', true); return; }
  const btn = $('rp-email-go'), status = $('rp-email-status'), out = $('rp-email-result');
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Extracting…'; status.textContent = ''; out.innerHTML = '';
  try {
    const res = await api('/jobs/from-email', { method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ text, model: resolveModel(false), repeatable: $('rp-email-keep').checked }) });
    const p = res.parsed || {};
    const tag = res.matched_repeatable ? '<span style="color:var(--accent)">matched an existing repeatable role</span>'
      : res.duplicate ? 'already in your queue' : res.queued ? 'added to Jobs' : 'parsed';
    out.innerHTML = `<div class="card" style="margin-top:12px;background:var(--input-bg)">
      <div style="font-weight:600">${esc(p.title || '(no title found)')}</div>
      <div class="muted" style="font-size:13px;margin-bottom:6px">${esc(p.company || '(no company)')}${p.location ? ' · ' + esc(p.location) : ''} · ${tag}</div>
      <div style="font-size:13px;white-space:pre-wrap;max-height:160px;overflow:auto">${esc((p.description || '').slice(0, 1200))}${(p.description||'').length>1200?'…':''}</div>
    </div>`;
    toast(res.matched_repeatable ? 'Matched a repeatable role — JD refreshed.' : res.queued ? 'Job extracted and queued.' : res.duplicate ? 'Already queued.' : 'Parsed.');
    $('rp-email-text').value = '';
    loadRepeatable(); loadUsage();
  } catch (e) {
    out.innerHTML = `<div class="qa dirty" style="margin-top:12px"><b>Couldn't extract:</b> ${esc(e.message)}</div>`;
  } finally { btn.disabled = false; btn.textContent = 'Extract job'; }
};

/* ---------- Bulk ---------- */
let bulk = [];   // {company,title,location,description,status,result,editing}
let bulkRunning = false;
const bf = { q: '', status: '', ready: '', company: '' };   // bulk filters

function bulkReady(j) {
  return !!(j.company.trim() && j.title.trim() && j.description.trim());
}
function bulkMatch(j) {
  if (bf.status && (j.status || 'queued') !== bf.status) return false;
  if (bf.ready === 'ready' && !bulkReady(j)) return false;
  if (bf.ready === 'incomplete' && bulkReady(j)) return false;
  if (bf.company && (j.company || '').trim() !== bf.company) return false;
  if (bf.q) {
    const hay = `${j.company} ${j.title} ${j.location} ${j.description}`.toLowerCase();
    if (!hay.includes(bf.q)) return false;
  }
  return true;
}
const bulkFiltered = () => bulk.filter(bulkMatch);
const bulkActiveFilter = () => !!(bf.q || bf.status || bf.ready || bf.company);
// Rows that "Generate all" will run: the ready ones, narrowed to the current
// filter when one is active (so you can generate just a slice).
const bulkTargets = () => (bulkActiveFilter() ? bulkFiltered() : bulk).filter(bulkReady);

function bulkSyncCompanyOptions() {
  const sel = $('b-fcompany'); if (!sel) return;
  const cur = sel.value;
  const names = [...new Set(bulk.map(j => (j.company || '').trim()).filter(Boolean))].sort();
  sel.innerHTML = '<option value="">All companies</option>' +
    names.map(n => `<option value="${esc(n)}">${esc(n)}</option>`).join('');
  sel.value = names.includes(cur) ? cur : '';
  if (sel.value !== cur) bf.company = sel.value;
}

function bulkRender() {
  const list = $('b-list');
  bulkSyncCompanyOptions();
  $('b-filterbar').style.display = bulk.length ? '' : 'none';
  $('b-empty').style.display = bulk.length ? 'none' : '';
  const ready = bulk.filter(bulkReady).length;
  const shown = bulkFiltered().length;
  const tgt = bulkTargets().length;
  $('b-count').textContent = `${shown}/${bulk.length} shown · ${ready} ready` +
    (bulkActiveFilter() ? ` · ${tgt} match filter` : '');
  $('b-filterempty').style.display = (bulk.length && shown === 0) ? '' : 'none';
  const runBtn = $('b-run');
  if (runBtn && !bulkRunning) runBtn.textContent = bulkActiveFilter()
    ? `Generate filtered (${tgt})` : `Generate all (${ready})`;
  list.innerHTML = bulk.map((j, i) => {
    if (!bulkMatch(j)) return '';
    const title = (j.title || 'Untitled role');
    const sub = [j.company, j.location].filter(Boolean).join(' · ');
    const stIcon = { running: '<span class="spinner dark"></span>', done: '✓', failed: '✕', queued: '•' }[j.status] || '•';
    const stColor = j.status === 'done' ? 'var(--ok)' : j.status === 'failed' ? 'var(--err)' : 'var(--faint)';
    const resultBtn = j.status === 'done'
      ? `<button class="btn ghost sm" data-act="view" data-i="${i}">Preview</button>` : '';
    // Re-run a single row: Regenerate a done one, Retry a failed (couldn't-be-generated) one.
    const regenBtn = (j.status === 'done' || j.status === 'failed')
      ? `<button class="btn subtle sm" data-act="regen" data-i="${i}" title="${j.status==='failed'?'Retry generating this job':'Regenerate this job (replaces the previous result)'}">${j.status==='failed'?'↻ Retry':'↻ Regenerate'}</button>` : '';
    return `<div class="bj ${j.editing?'editing':''}" data-i="${i}">
      <div class="bj-top">
        <div class="bj-st" style="color:${stColor}">${stIcon}</div>
        <div class="bj-main">
          <div class="bj-title">${esc(title)}</div>
          <div class="bj-co">${esc(sub) || '<i>incomplete</i>'} ${j.error?`· <span style="color:var(--err)">${esc(j.error)}</span>`:''}</div>
        </div>
        <span class="stm ${j.status}">${j.status}</span>
        <div class="bj-acts">
          ${resultBtn}
          ${regenBtn}
          <button class="btn subtle sm" data-act="edit" data-i="${i}">${j.editing?'Close':'Edit'}</button>
          <button class="btn danger sm" data-act="del" data-i="${i}">✕</button>
        </div>
      </div>
      <div class="bj-fields">
        <div class="row"><div><label class="fld">Company</label><input type="text" data-f="company" data-i="${i}" value="${esc(j.company)}"></div>
        <div><label class="fld">Location</label><input type="text" data-f="location" data-i="${i}" value="${esc(j.location)}"></div></div>
        <label class="fld">Job title</label><input type="text" data-f="title" data-i="${i}" value="${esc(j.title)}">
        <label class="fld">Job description</label><textarea data-f="description" data-i="${i}">${esc(j.description)}</textarea>
      </div>
    </div>`;
  }).join('');

  list.querySelectorAll('[data-act]').forEach(el => el.onclick = () => {
    const i = +el.dataset.i;
    if (el.dataset.act === 'del') { bulk.splice(i,1); bulkRender(); }
    else if (el.dataset.act === 'edit') { bulk[i].editing = !bulk[i].editing; bulkRender(); }
    else if (el.dataset.act === 'view') openModalFor(bulk[i].result);
    else if (el.dataset.act === 'regen') { if (!bulkRunning) bulkRegenRow(i); }
  });
  list.querySelectorAll('[data-f]').forEach(el => el.oninput = () => { bulk[+el.dataset.i][el.dataset.f] = el.value; });
}
function bulkAdd(job, open) {
  bulk.push(Object.assign({ company:'', title:'', location:'', description:'', status:'queued', editing: !!open }, job));
  bulkRender();
}
// Add one job (from the Jobs list / RSS pull) to the Bulk generate list.
function bulkAddFromJob(j) {
  if (!j) return;
  // jobFromApi maps the queue key onto `id`; keep it so bulk generation can flip
  // the queue row to 'generated' and link it to the produced run.
  bulkAdd({ key_id: j.id || j.key_id, company: j.company || '', title: j.title || '', location: j.location || '', description: j.description || '' }, false);
  toast(`Added "${j.title || 'job'}" to Bulk generate.`);
}

function bulkOpts() {
  return { model: resolveModel(false), persona: activePersona(), strict: $('b-strict').checked, pdf: $('b-pdf').checked };
}
// Generate (or regenerate) ONE bulk row. Sets j.status/result/error. Passes key_id
// so the server flips the source queue job to 'generated' (ignored for free-form rows).
async function bulkGenOne(j, opts) {
  opts = opts || bulkOpts();
  try {
    j.result = await api('/generate', { method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ company:(j.company||'').trim(), title:(j.title||'').trim(),
        location:(j.location||'').trim(), description:(j.description||'').trim(),
        key_id: j.key_id || undefined, ...opts }) });
    j.status = 'done'; j.error = '';
  } catch (e) { j.status = 'failed'; j.error = e.message; }
}

// Regenerate/retry a single row (from its Regenerate/Retry button).
async function bulkRegenRow(i) {
  const j = bulk[i]; if (!j) return;
  if (!bulkReady(j)) { toast('Add company, title, and description first.', true); return; }
  j.status = 'running'; j.error = ''; bulkRender();
  await bulkGenOne(j);
  bulkRender();
  toast(j.status === 'done' ? 'Regenerated.' : 'Failed: ' + (j.error || 'unknown error'), j.status !== 'done');
  loadJobs(); loadLibrary(); loadUsage();
}

async function runBulk() {
  if (bulkRunning) return;
  // Ready rows, narrowed to the active filter. Rows already generated are skipped
  // so a second Run doesn't spend AI calls again; use a row's Regenerate for that.
  const ready = bulkTargets();
  const jobs = ready.filter(j => j.status !== 'done');
  if (ready.length && !jobs.length) {
    toast('Every ready row is already generated. Use Regenerate on a row to redo one.');
    return;
  }
  if (!jobs.length) {
    toast(bulkActiveFilter()
      ? 'No ready rows match the current filter.'
      : 'Add at least one role with company, title, and description.', true);
    return;
  }
  bulkRunning = true;
  const btn = $('b-run'); btn.disabled = true; btn.textContent = 'Generating…';
  const prog = $('b-progress'); prog.className = 'progress show'; prog.firstElementChild.style.width = '0%';
  const opts = bulkOpts();
  try {
    const batch = await queueGenerationItems(jobs.map(j => ({ key_id: j.key_id || null,
      target: {company:j.company, title:j.title, location:j.location || '', description:j.description}, options:opts })));
    jobs.forEach((j, index) => { j.batchId = batch.id; j.batchIndex = index; });
    toast(`Saved ${jobs.length} jobs. Generation continues in the app even if this page closes.`);
  } catch (error) { toast(error.message, true); }
  finally { bulkRunning = false; btn.disabled = false; bulkRender(); }
}
$('b-run').onclick = runBulk;

/* Bulk filter controls + list-management actions. */
$('b-search').oninput = (e) => { bf.q = e.target.value.trim().toLowerCase(); bulkRender(); };
$('b-fstatus').onchange = (e) => { bf.status = e.target.value; bulkRender(); };
$('b-fready').onchange = (e) => { bf.ready = e.target.value; bulkRender(); };
$('b-fcompany').onchange = (e) => { bf.company = e.target.value; bulkRender(); };
$('b-dedupe').onclick = () => {
  const seen = new Set(); let removed = 0;
  bulk = bulk.filter(j => {
    const k = `${(j.company||'').trim().toLowerCase()}|${(j.title||'').trim().toLowerCase()}`;
    if (k === '|') return true;             // keep blank rows you're still editing
    if (seen.has(k)) { removed++; return false; }
    seen.add(k); return true;
  });
  bulkRender(); toast(removed ? `Removed ${removed} duplicate${removed===1?'':'s'}.` : 'No duplicates found.');
};
$('b-clrdone').onclick = () => {
  const n = bulk.filter(j => j.status==='done').length;
  bulk = bulk.filter(j => j.status!=='done'); bulkRender();
  toast(n ? `Cleared ${n} generated row${n===1?'':'s'}.` : 'No generated rows.');
};
$('b-clrfailed').onclick = () => {
  const n = bulk.filter(j => j.status==='failed').length;
  bulk = bulk.filter(j => j.status!=='failed'); bulkRender();
  toast(n ? `Cleared ${n} failed row${n===1?'':'s'}.` : 'No failed rows.');
};
$('b-clrall').onclick = async () => {
  if (!bulk.length) return;
  if (!await uiConfirm({ title: 'Clear the bulk list?', message: `Remove all ${bulk.length} row${bulk.length === 1 ? '' : 's'} from the bulk list?`, ok: 'Clear', danger: true })) return;
  bulk = []; bulkRender();
};

/* CSV → Bulk: parse a CSV (quoted fields, flexible column names) into bulk rows. */
function parseCsvRows(text) {
  const rows = []; let row = [], field = '', inQ = false;
  text = String(text || '').replace(/\r\n?/g, '\n');
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQ) {
      if (c === '"') { if (text[i+1] === '"') { field += '"'; i++; } else inQ = false; }
      else field += c;
    } else if (c === '"') inQ = true;
    else if (c === ',') { row.push(field); field = ''; }
    else if (c === '\n') { row.push(field); rows.push(row); row = []; field = ''; }
    else field += c;
  }
  if (field.length || row.length) { row.push(field); rows.push(row); }
  return rows.filter(r => r.some(x => (x || '').trim()));
}
function parseCsvJobs(text) {
  const rows = parseCsvRows(text);
  if (rows.length < 2) return [];
  const header = rows[0].map(h => h.trim().toLowerCase());
  const col = (...names) => { for (const n of names) { const k = header.indexOf(n); if (k >= 0) return k; } return -1; };
  const ci = col('company','employer','organization','business'),
        ti = col('title','job_title','position','role'),
        li = col('location','city','place'),
        di = col('description','description_summary','summary','jd'),
        ui = col('apply_url','url','link','source_url','job_url'),
        ei = col('contact_email','email','contact_emails','hr_email');
  const out = [];
  for (let r = 1; r < rows.length; r++) {
    const row = rows[r], g = k => (k >= 0 && k < row.length ? (row[k] || '').trim() : '');
    const company = g(ci), title = g(ti);
    if (!company && !title) continue;
    out.push({ company, title, location: g(li), description: g(di), apply_url: g(ui), contact_email: g(ei) });
  }
  return out;
}
$('b-csv').onclick = () => $('b-csv-file').click();
$('b-csv-file').onchange = async (e) => {
  const file = e.target.files && e.target.files[0]; if (!file) return;
  try {
    const rows = parseCsvJobs(await file.text());
    if (!rows.length) { toast('No valid rows found. Need at least company or title.', true); return; }
    rows.forEach(r => bulkAdd(r, false));
    toast(`Loaded ${rows.length} row${rows.length===1?'':'s'} from CSV.`);
    if ($('b-autogen').checked) runBulk();
  } catch (err) { toast('CSV read failed: ' + err.message, true); }
  finally { e.target.value = ''; }
};
$('b-csv-tpl').onclick = () => {
  const csv = 'company,title,location,description,apply_url,contact_email\n'
    + '"Acme Inc","Full-Stack Developer","Remote","Build React + Node apps. TypeScript, REST, Postgres. 0-3 yrs.","https://acme.com/jobs/123","jobs@acme.com"\n'
    + '"Globex","Backend Developer","Remote","Python, FastAPI, Docker, AWS.","https://globex.com/careers/45",""\n';
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
  a.download = 'bulk_jobs_template.csv'; a.click(); URL.revokeObjectURL(a.href);
};

/* from scraper queue: filtered, multi-select picker → add chosen jobs to the bulk list */
$('b-queue').onclick = () => openPick('bulk');

/* ---------- Apply Center (human approval gate) ---------- */
const APPLY_PROMPT = `Use Resume Studio MCP and browser control only; do not use a userscript. Work through generated, unapplied jobs from the past seven days, one application at a time. Reuse each generated resume and cover letter. Fill the current form from the MCP plan and pause only for login, CAPTCHA, consent/legal attestation, sensitive demographic choices, missing required facts, or ambiguous options. For review, show only new answers, required blanks, and warnings; if there are none, say it is clean. Leave the final Submit button for me. When I say done, verify/log the outcome, return to Resume Studio, and continue with the next eligible job.`;

function acList(values, empty = 'None') {
  if (!values || !values.length) return `<span class="muted">${empty}</span>`;
  return `<ul style="margin:6px 0 0;padding-left:20px">${values.map(v => `<li style="margin:5px 0">${esc(typeof v === 'string' ? v : JSON.stringify(v))}</li>`).join('')}</ul>`;
}

function acSessionCard(s) {
  const summary = s.summary || {}, counts = summary.counts || {};
  const pending = s.status === 'prepared';
  const warnings = summary.warnings || s.warnings || [];
  const newAnswers = summary.answers_new || [];
  const blanks = summary.left_blank || [];
  const statusTone = s.status === 'submitted' ? 'color:var(--ok)' :
    s.status === 'rejected' || s.status === 'failed' ? 'color:var(--err)' :
    s.status === 'approved' ? 'color:var(--warn)' : 'color:var(--accent)';
  return `<div class="card" data-ac-session="${esc(s.session_id)}" style="margin-bottom:12px">
    <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;flex-wrap:wrap">
      <div><div style="font-weight:800;font-size:16px">${esc(s.title || 'Untitled role')}</div>
        <div class="muted">${esc(s.company || '')} · ${esc((s.created_at || '').replace('T',' ').slice(0,16))}</div></div>
      <div style="font-weight:800;text-transform:uppercase;font-size:12px;${statusTone}">${esc(s.status || '')}</div>
    </div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin:12px 0;font-size:12px">
      <span class="jl-src">${Number(counts.standard_fields || 0)} fields</span>
      <span class="jl-src">${Number(counts.reused || 0)} reused answers</span>
      <span class="jl-src">${Number(counts.newly_drafted || 0)} new answers</span>
      <span class="jl-src">${Number(counts.left_blank || 0)} blanks</span>
    </div>
    <details ${pending && (warnings.length || newAnswers.length || blanks.length) ? 'open' : ''}>
      <summary style="cursor:pointer;font-weight:700">Review exact application packet</summary>
      <div style="margin-top:10px;font-size:13px">
        ${warnings.length ? `<b style="color:var(--warn)">Warnings</b>${acList(warnings)}` : ''}
        ${newAnswers.length ? `<div style="margin-top:10px"><b>New AI-drafted answers — read closely</b>${acList(newAnswers.map(a => `${a.question}: ${a.answer}`))}</div>` : ''}
        ${blanks.length ? `<div style="margin-top:10px"><b>Left blank</b>${acList(blanks.map(b => `${b.label}${b.required ? ' (required)' : ''}: ${b.reason}`))}</div>` : ''}
        <div style="margin-top:10px"><b>Documents:</b> ${Object.entries(summary.documents || {}).map(([k,v]) => v.url ? `<a href="${esc(v.url)}" target="_blank">${esc(k)}</a>` : esc(`${k}: ${v.error || 'unavailable'}`)).join(' · ') || '<span class="muted">not prepared</span>'}</div>
      </div>
    </details>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px">
      ${s.job_url ? `<a class="btn subtle sm" href="${esc(s.job_url)}" target="_blank" rel="noreferrer">Open portal ↗</a>` : ''}
      ${pending ? `<button class="btn primary sm" data-ac="approve-me">Approve answers · I'll submit</button>
        <button class="btn danger sm" data-ac="reject">No · reject</button>` : ''}
    </div>
  </div>`;
}

async function loadApplyCenter() {
  const out = $('ac-list');
  try {
    const { sessions } = await api('/apply/sessions?limit=50');
    const full = await Promise.all((sessions || []).map(async s => {
      try { return await api(`/apply/${enc(s.session_id)}`); } catch { return s; }
    }));
    out.innerHTML = full.length ? full.map(acSessionCard).join('') :
      '<div class="empty"><div class="big">✅</div>No application sessions yet. Start from a job with <b>AI Apply</b> or ask ChatGPT to prepare one.</div>';
    out.querySelectorAll('[data-ac-session]').forEach(card => {
      const id = card.dataset.acSession;
      card.querySelector('[data-ac="approve-me"]')?.addEventListener('click', () => acDecide(id, true, 'me'));
      card.querySelector('[data-ac="reject"]')?.addEventListener('click', () => acDecide(id, false, 'me'));
    });
  } catch (e) {
    out.innerHTML = `<div class="empty">Could not load approval sessions: ${esc(e.message)}</div>`;
  }
}

async function acDecide(sessionId, approved, submitBy) {
  const verb = approved ? (submitBy === 'agent' ? 'authorize the agent to submit' : 'approve and submit it yourself') : 'reject this application';
  if (!await uiConfirm({
    title: approved ? 'Final application decision' : 'Reject application?',
    message: `This decision applies only to session ${sessionId}.\n\nDo you want to ${verb}?`,
    ok: approved ? 'Yes, approve' : 'No, reject it',
    danger: !approved,
  })) return;
  try {
    const result = await api(`/apply/${enc(sessionId)}/confirm`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({approved, submit_by: submitBy})
    });
    toast(result.note || (approved ? 'Application approved.' : 'Application rejected.'));
    loadApplyCenter();
  } catch (e) { toast('Decision failed: ' + e.message, true); }
}

$('ac-refresh')?.addEventListener('click', loadApplyCenter);
$('ac-copy-prompt')?.addEventListener('click', () => {
  (navigator.clipboard?.writeText(APPLY_PROMPT) || Promise.reject()).then(
    () => toast('ChatGPT application request copied.'),
    () => uiPrompt({title:'Copy this into ChatGPT', value:APPLY_PROMPT, ok:'Close'}));
});

/* ---------- Jobs (native list) ---------- */
// Collector (capture dashboard) on the same host, port 8765. Tracks how the app
// was opened (localhost / Tailscale).
const COLLECTOR = `http://${location.hostname || '127.0.0.1'}:8765`;

const jl = { all: [], rows: [], sort: { key: 'priority', dir: 'desc' }, sel: new Set() };

function jobFromApi(j) {
  const hasGenerated = !!j.has_generated;
  const folder = hasGenerated ? (j.notes || '').split(/[\\/]/).pop() : '';
  const found = (j.found_at || '').slice(0, 10);
  return { id: j.key_id, title: j.title || 'Untitled', company: j.company || '',
    location: j.location || '', source: j.source || '', date: jobDate(j), found,
    status: j.status, gen: hasGenerated, folder, email: (j.contact_email || '').trim(),
    applied: !!j.applied, repeat: !!j.repeat, priority: !!j.priority, repeatable: !!j.repeatable, irrelevant: !!j.irrelevant, lane: j.lane || '', apply_url: j.apply_url || '', description: j.description || '', company_email: (j.company_email || '').trim(), generated_at: (j.generated_at || '').replace('T', ' ').slice(0, 16),
    sent_at: (j.sent_at || '').replace('T', ' ').slice(0, 16), sent_to: (j.sent_to || '').trim(), followups: Array.isArray(j.followups) ? j.followups : [], hr_emailed_at: (j.hr_emailed_at || '').replace('T', ' ').slice(0, 16), sent_log: Array.isArray(j.sent_log) ? j.sent_log : [],
    priority_level: j.priority_level || 'low', priority_override: j.priority_override || '', priority_score: typeof j.priority_score === 'number' ? j.priority_score : 0,
    // v3.5: lane, matrix grade, seniority guard, pathway tags (batch import)
    lane_slug: j.lane_slug || '', grade: j.grade || {}, seniority: j.seniority || {}, stream: j.stream || '',
    pathway: j.pathway_type ? `${j.pathway_type}: ${j.pathway_detail}` : '', remote_type: j.remote_type || '', hire_type: j.hire_type || '', noc: j.noc || '' };
}

// Source-of-truth date for a queue job: the real posted date when it parses to
// a calendar date, else the day we found it. Job Bank / RSS posted dates are
// normalized to ISO at intake; this also tolerates ISO timestamps from ATS feeds.
function isoDay(s) {
  s = (s || '').trim();
  if (!s) return '';
  const m = s.match(/^(\d{4}-\d{2}-\d{2})/);
  if (m) return m[1];
  const t = Date.parse(s);
  if (isNaN(t)) return '';
  const d = new Date(t);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
function jobDate(j) {
  return isoDay(j.posted) || (j.found_at || '').slice(0, 10);
}

// Start-of-day (local) cutoff for "the last N calendar days, including today".
// N=1 => today only, N=2 => today + yesterday, etc.
function dayWindowStart(days) {
  const n = new Date();
  return new Date(n.getFullYear(), n.getMonth(), n.getDate() - (days - 1)).getTime();
}
// Parse a "YYYY-MM-DD[...]" string as LOCAL midnight. Date.parse() treats a
// date-only string as UTC, so west-of-UTC users (e.g. Eastern) got UTC-midnight,
// which is the evening *before* — a job found today then fell just outside the
// "Today" window. Build the date from its parts in local time instead.
function parseLocalDay(dateStr) {
  const m = String(dateStr || '').match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (m) return new Date(+m[1], +m[2] - 1, +m[3]).getTime();
  const t = Date.parse(dateStr);
  return isNaN(t) ? NaN : t;
}
function inRange(dateStr, daysVal) {
  if (!daysVal) return true;                       // All time
  const t = parseLocalDay(dateStr); if (isNaN(t)) return false;
  if (daysVal === 'month') {                       // since the 1st of this month
    const n = new Date();
    return t >= new Date(n.getFullYear(), n.getMonth(), 1).getTime();
  }
  return t >= dayWindowStart(Number(daysVal));     // calendar days, incl. today
}
// A job belongs in the date window if EITHER it was posted in range OR we found/
// saved it in range. Browser-saved jobs carry the employer's original posted date
// (often weeks old), so filtering on posted date alone hid jobs you just scraped
// today — "Today" would show almost nothing even right after saving a batch.
// Accepts either a mapped job (jobFromApi: .date/.found) or a raw API job
// (.posted/.found_at), so every picker/list can share one window rule.
function jobInRange(j, daysVal) {
  if (!daysVal) return true;
  const posted = j.date || jobDate(j);
  const found = j.found || (j.found_at || '').slice(0, 10);
  return inRange(posted, daysVal) || inRange(found, daysVal);
}

// Pull browser-saved (collector) jobs into the queue. Fast: collector source only.
// Best-effort — if the collector is down we still show whatever's queued.
async function syncCollector() {
  try {
    const r = await api('/intake/run?source_type=collector', { method: 'POST' });
    if (r && r.committed) toast(`${r.committed} new saved job${r.committed > 1 ? 's' : ''} synced.`);
    return r && r.committed ? r.committed : 0;
  } catch { return 0; }
}

// Fetch the queue, rebuild the source dropdown, and render. No network beyond /jobs.
async function _fetchAndRenderJobs() {
  const jr = await api('/jobs');                 // Jobs = the queue; generated apps live in Library
  jl.all = (jr.jobs || []).map(jobFromApi);
  const sel = $('jl-source'), cur = sel.value;
  const sources = [...new Set(jl.all.map(j => j.source).filter(Boolean))].sort();
  sel.innerHTML = '<option value="">All sources</option>' +
    sources.map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join('');
  sel.value = sources.includes(cur) ? cur : '';
  renderJobs();
}

// Unified list: queue jobs (generated + not). Renders IMMEDIATELY, then syncs the
// browser-capture collector in the BACKGROUND — that POST can be slow / time out when
// the capture app (:8765) is down, so it must never block the table from showing.
async function loadJobs(_attempt = 0) {
  const body = $('jl-body'), empty = $('jl-empty');
  if (!_attempt) body.innerHTML = '<tr><td colspan="9" class="empty"><span class="spinner dark"></span></td></tr>';
  try {
    await _fetchAndRenderJobs();
  } catch (e) {
    // Cold start: the app can open before the server/DB is ready (e.g. just after a
    // container (re)start). Retry a few times so the data appears on its own instead
    // of staying empty until a manual refresh.
    if (_attempt < 5) { setTimeout(() => loadJobs(_attempt + 1), 1500); return; }
    body.innerHTML = ''; empty.style.display = '';
    toast('Jobs unavailable: ' + e.message, true);
    return;
  }
  syncCollector().then(n => { if (n) _fetchAndRenderJobs().catch(() => {}); }).catch(() => {});
}

function jlFiltered() {
  const q = $('jl-search').value.trim().toLowerCase();
  const status = $('jl-status').value, source = $('jl-source').value, daysVal = $('jl-days').value;
  const channel = $('jl-channel').value, applied = $('jl-applied').value, repeat = $('jl-repeat').value;
  const relevance = $('jl-relevance').value;
  let rows = jl.all.filter(j => {
    if (relevance === 'active' && j.irrelevant) return false;   // default: hide not-relevant
    if (relevance === 'irrel' && !j.irrelevant) return false;   // only not-relevant
    if (status === 'ungenerated') { if (j.gen) return false; }  // anything not yet generated
    else if (status && j.status !== status) return false;
    if (source && j.source !== source) return false;
    if (channel === 'email' && !j.email) return false;
    if (channel === 'noemail' && j.email) return false;
    if (applied === 'yes' && !j.applied) return false;
    if (applied === 'no' && j.applied) return false;
    if (repeat === 'yes' && !j.repeat) return false;
    if (!jobInRange(j, daysVal)) return false;
    if (!q) return true;
    return [j.title, j.company, j.location, j.source].join(' ').toLowerCase().includes(q);
  });
  const { key, dir } = jl.sort, f = dir === 'asc' ? 1 : -1;
  if (key === 'priority') {
    // Numeric, high→low by default; tiebreak by most recent date.
    rows.sort((a, b) => ((a.priority_score - b.priority_score) * f) || String(b.date).localeCompare(String(a.date)));
  } else {
    rows.sort((a, b) => String(a[key] ?? '').toLowerCase() < String(b[key] ?? '').toLowerCase() ? -f : f);
  }
  return rows;
}

// Info shown in the row's ℹ tooltip. Extensible — add more lines here later.
function jobInfoTitle(j) {
  const fups = (j.followups || []);
  const lastFup = fups.length ? (fups[fups.length - 1] || '').replace('T', ' ').slice(0, 16) : '';
  const g = j.grade || {};
  return [
    j.gen ? `Last generated: ${j.generated_at || '—'}` : 'Not generated yet',
    g.tier ? `Tier ${g.tier}: ${g.tier_reason || ''}` : '',
    g.tier ? `Gaps: ${(g.gap_flags || []).join(' | ') || 'none'}` : '',
    g.fit_sentence ? `Fit: ${g.fit_sentence}` : '',
    (j.seniority && j.seniority.warning) ? `Seniority warning: ${j.seniority.reason}` : '',
    j.pathway ? `Pathway: ${j.pathway}` : '',
    j.noc ? `NOC: ${j.noc}${j.stream ? ' · ' + j.stream : ''}` : '',
    j.found ? `Found: ${j.found}` : '',
    j.source ? `Source: ${j.source}` : '',
    j.applied ? 'Applied: yes' : '',
    j.sent_at ? `Emailed: ${j.sent_at}${j.sent_to ? ' → ' + j.sent_to : ''}` : '',
    fups.length ? `Follow-ups: ${fups.length} (last ${lastFup})` : '',
    j.email ? `Contact: ${j.email}` : (j.company_email ? `Company HR: ${j.company_email}` : ''),
  ].filter(Boolean).join('\n');
}

const PRIO_TXT = { high: 'High', medium: 'Med', low: 'Low' };
function prioBadge(j, i) {
  const lv = j.priority_level || 'low', pinned = !!j.priority_override;
  return `<span class="prio prio-${lv}${pinned ? ' pinned' : ''}" data-act="prio" data-i="${i}" title="Priority: ${lv}${pinned ? ' (pinned — click to change)' : ' (auto — click to pin)'}">${pinned ? '📌 ' : ''}${PRIO_TXT[lv] || 'Low'}</span>`;
}

function renderJobs() {
  const body = $('jl-body'), empty = $('jl-empty');
  const rows = jl.rows = jlFiltered();
  empty.style.display = rows.length ? 'none' : '';
  document.querySelectorAll('.jl-sort').forEach(th => {
    th.classList.toggle('on', th.dataset.sort === jl.sort.key);
    th.textContent = th.textContent.replace(/ [▲▼]$/, '') +
      (th.dataset.sort === jl.sort.key ? (jl.sort.dir === 'asc' ? ' ▲' : ' ▼') : '');
  });
  body.innerHTML = rows.map((j, i) => {
    const canSelect = !!j.id;   // generated jobs too — so a bad batch can be re-selected & regenerated
    return `<tr${j.irrelevant ? ' style="opacity:.5"' : ''}>
      <td class="jl-ck">${canSelect ? `<input type="checkbox" class="jl-rowck" data-k="${esc(j.id)}" ${jl.sel.has(j.id)?'checked':''}>` : ''}</td>
      <td>${j.id ? prioBadge(j, i) : ''}</td>
      <td><span class="t" data-act="detail" data-i="${i}" style="cursor:pointer" title="View details">${esc(j.title)}</span>${typeof tierBadge === 'function' ? tierBadge(j) : ''}${j.id?`<span class="jl-emailbtn ${j.email?'on':''}" data-act="email" data-i="${i}" title="${j.email?'Email: '+esc(j.email)+' — click to edit':'Add an HR email (for the n8n email path)'}" style="cursor:pointer">${j.email?'📧':'✉️'}</span><span data-act="repeatable" data-i="${i}" title="${j.repeatable?'Repeatable role — saved. Click to remove':'Mark as a repeatable role (reapply often)'}" style="cursor:pointer;margin-left:4px;opacity:${j.repeatable?1:.3}">🔁</span><span data-act="irrelevant" data-i="${i}" title="${j.irrelevant?'Not relevant — hidden from active lists. Click to restore':'Flag as not relevant (hide it)'}" style="cursor:pointer;margin-left:4px;opacity:${j.irrelevant?1:.3}">🚫</span><span class="jl-info" title="${esc(jobInfoTitle(j))}" style="cursor:help;margin-left:5px;opacity:.55">ℹ️</span>`:''}</td>
      <td class="muted">${esc(j.company)}${j.repeat?` <span class="jl-rep" title="Repeat company — saved details reused">🔁</span>`:''}</td>
      <td class="muted">${esc(j.location)}</td>
      <td><span class="jl-src">${esc(j.source || '—')}</span></td>
      <td class="muted" title="${j.found && j.found !== j.date ? 'Found '+esc(j.found) : ''}">${esc(j.date)}</td>
      <td><span class="jl-st ${esc(j.status)}">${esc(j.status)}</span></td>
      <td>${j.id ? `<input type="checkbox" class="jl-applied" data-i="${i}" ${j.applied?'checked':''} title="Mark applied">` : (j.applied?'✓':'')}</td>
      <td><div class="jl-rowbtns">
        ${j.gen ? `<button class="btn ghost sm" data-act="preview" data-i="${i}">Preview</button>` : ''}
        ${(j.gen && (j.email || j.company_email) && j.id) ? `<button class="btn ghost sm" data-act="send" data-i="${i}" title="${j.sent_at ? 'Resend the existing generated package through n8n' : 'Send the generated package through n8n'}">${j.sent_at ? '↻ Resend n8n' : '📧 Send n8n'}</button>` : ''}
        ${(j.id && (j.email || j.company_email)) ? `<button class="btn ghost sm" data-act="emailhr" data-i="${i}" title="${j.hr_emailed_at ? 'HR emailed ' + esc(j.hr_emailed_at) + ' — click to email again' : 'Email HR about this posting (' + esc(j.email || j.company_email) + ')'}">${j.hr_emailed_at ? '✅ HR' : '✉️ HR'}</button>` : ''}
        ${(j.id && j.sent_at) ? `<button class="btn ghost sm" data-act="followup" data-i="${i}" title="Send a follow-up to ${esc(j.sent_to || j.email || j.company_email)}${j.followups && j.followups.length ? ' ('+j.followups.length+' sent)' : ''}">🔔 Follow up</button>` : ''}
        ${j.apply_url ? `<a class="btn subtle sm" href="${esc(j.apply_url)}" target="_blank" rel="noreferrer" title="Open the application portal">Open ↗</a>` : ''}
        ${(j.apply_url && j.id) ? `<button class="btn subtle sm" data-act="autofill" data-i="${i}" title="Copy an approval-first ChatGPT/Codex application request">🤖 AI Apply</button>` : ''}
        ${j.id ? `<a class="btn subtle sm" href="/jobs/${enc(j.id)}/download" download title="Download this job as JSON">⬇ JSON</a>` : ''}
        ${j.id ? `<button class="btn ghost sm" data-act="bulk" data-i="${i}" title="Add this job to the Bulk generate queue">➕ Bulk</button>` : ''}
        ${j.id ? `<button class="btn primary sm" data-act="gen" data-i="${i}">${j.gen?'Regenerate':'Generate'}</button>` : ''}
        ${j.gen ? `<button class="btn subtle sm" data-act="del" data-i="${i}" title="Delete just the generated application (keep the job)">🗑 Output</button>` : ''}
        ${j.id ? `<button class="btn danger sm" data-act="deljob" data-i="${i}" title="Delete this job from the queue (and its application)">🗑 Job</button>` : ''}
      </div></td>
    </tr>`;
  }).join('');

  body.querySelectorAll('.jl-rowck').forEach(cb => cb.onclick = (e) => {
    e.stopPropagation();
    cb.checked ? jl.sel.add(cb.dataset.k) : jl.sel.delete(cb.dataset.k);
    syncBulkBtn();
  });
  body.querySelectorAll('[data-act="bulk"]').forEach(b => b.onclick = () => bulkAddFromJob(jl.rows[+b.dataset.i]));
  body.querySelectorAll('[data-act="gen"]').forEach(b => b.onclick = () => genJob(jl.rows[+b.dataset.i], b));
  body.querySelectorAll('[data-act="preview"]').forEach(b => b.onclick = () => {
    const f = jl.rows[+b.dataset.i].folder; if (f) openLibrary(f);
  });
  body.querySelectorAll('[data-act="send"]').forEach(b => b.onclick = () => sendToN8n(jl.rows[+b.dataset.i].id, b));
  body.querySelectorAll('[data-act="followup"]').forEach(b => b.onclick = () => sendFollowup(jl.rows[+b.dataset.i].id, b));
  body.querySelectorAll('[data-act="emailhr"]').forEach(b => b.onclick = () => emailHr(jl.rows[+b.dataset.i].id, b));
  body.querySelectorAll('[data-act="del"]').forEach(b => b.onclick = () => delJob(jl.rows[+b.dataset.i], b));
  body.querySelectorAll('[data-act="deljob"]').forEach(b => b.onclick = () => deleteJobEntry(jl.rows[+b.dataset.i], b));
  body.querySelectorAll('[data-act="detail"]').forEach(el => el.onclick = () => openJobDetail(jl.rows[+el.dataset.i]));
  body.querySelectorAll('[data-act="email"]').forEach(el => el.onclick = async () => {
    const j = jl.rows[+el.dataset.i];
    const val = await uiPrompt({ title: 'HR / application email', label: `${esc(j.title)} @ ${esc(j.company)}`, value: j.email || '', placeholder: 'hr@company.com' });
    if (val === null) return;                       // cancelled
    try {
      await api(`/jobs/${j.id}/update`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ contact_email: val.trim() }) });
      j.email = val.trim();                              // jl.rows entries are jl.all references
      toast(val.trim() ? 'Email saved.' : 'Email cleared.');
      if (!bulkRunning) renderJobs();                    // light, in place — never reload mid-generation
    } catch (e) { toast('Update failed: ' + e.message, true); }
  });
  body.querySelectorAll('[data-act="prio"]').forEach(el => el.onclick = async (e) => {
    e.stopPropagation();
    const j = jl.rows[+el.dataset.i];
    const order = ['', 'high', 'medium', 'low'];
    const next = order[(order.indexOf(j.priority_override || '') + 1) % order.length];
    try {
      await api(`/jobs/${j.id}/priority`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ level: next }) });
      loadJobs();   // recompute the auto level when the pin is cleared
    } catch (err) { toast('Update failed: ' + err.message, true); }
  });
  body.querySelectorAll('[data-act="repeatable"]').forEach(el => el.onclick = async (e) => {
    e.stopPropagation();
    const j = jl.rows[+el.dataset.i], val = !j.repeatable;
    try {
      await api(`/jobs/${j.id}/repeatable`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ repeatable: val }) });
      j.repeatable = val; el.style.opacity = val ? 1 : .3;
      el.title = val ? 'Repeatable role — saved. Click to remove' : 'Mark as a repeatable role (reapply often)';
      toast(val ? 'Saved as a repeatable role → see the Repeatable tab.' : 'Removed from repeatable roles.');
    } catch (err) { toast('Update failed: ' + err.message, true); }
  });
  body.querySelectorAll('[data-act="irrelevant"]').forEach(el => el.onclick = async (e) => {
    e.stopPropagation();
    const j = jl.rows[+el.dataset.i], val = !j.irrelevant;
    try {
      await api(`/jobs/${j.id}/irrelevant`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ irrelevant: val }) });
      j.irrelevant = val;
      toast(val ? 'Flagged not relevant — hidden from the active lists.' : 'Restored — no longer flagged.');
      renderJobs();   // re-apply the relevance filter (row hides unless "Show all")
    } catch (err) { toast('Update failed: ' + err.message, true); }
  });
  body.querySelectorAll('[data-act="autofill"]').forEach(b => b.onclick = () => {
    const j = jl.rows[+b.dataset.i];
    const request = `Use Job Application Copilot and Chrome/browser control. Apply to ${j.title} at ${j.company}. Resume Studio job key: ${j.id}. Application URL: ${j.apply_url}. Inspect and fill the live form, upload the tailored documents, then stop before Submit and show me the exact approval packet. Ask me yes or no for this application.`;
    (navigator.clipboard?.writeText(request) || Promise.reject()).then(
      () => { toast('ChatGPT/Codex request copied — paste it into a chat with both plugins enabled.'); showView('apply-center'); },
      () => uiPrompt({title:'Copy this into ChatGPT/Codex', value:request, ok:'Close'}));
  });
  body.querySelectorAll('.jl-applied').forEach(cb => cb.onclick = async (e) => {
    e.stopPropagation();
    const j = jl.rows[+cb.dataset.i];
    try {
      await api(`/jobs/${j.id}/applied`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ applied: cb.checked }) });
      j.applied = cb.checked;
      toast(cb.checked ? 'Marked applied.' : 'Marked not applied.');
    } catch (err) { cb.checked = !cb.checked; toast('Update failed: ' + err.message, true); }
  });
  syncBulkBtn();
}

async function delJob(row, btn) {
  if (!row.folder) return;
  if (!await uiConfirm({ title: 'Delete generated files?', message: `${row.title}\n\nRemoves the generated application. The job stays in the queue.`, ok: 'Delete', danger: true })) return;
  btn.disabled = true;
  try {
    await api('/run?folder=' + enc(row.folder), { method: 'DELETE' });
    if (row.id) {  // reset the queue job so it can be generated again (no dangling link)
      try { await api(`/jobs/${row.id}/status`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'new' }) }); } catch {}
    }
    toast('Deleted.'); loadJobs(); loadLibrary();
  } catch (e) { toast('Delete failed: ' + e.message, true); btn.disabled = false; }
}

async function deleteScrapedJob(row, btn) {
  if (!row?.id) return;
  if (!await uiConfirm({ title: 'Delete this scraped job?', message: `${row.title}\n${row.company}\n\nIt will be removed from the queue.`, ok: 'Delete', danger: true })) return;
  const label = btn.textContent; btn.disabled = true; btn.textContent = 'Deleting...';
  try {
    await api(`/jobs/${row.id}`, { method: 'DELETE' });
    jl.sel.delete(row.id);
    toast('Scraped job deleted.');
    await loadJobs(); renderScrapedJobs();
  } catch (e) {
    toast('Delete failed: ' + e.message, true); btn.disabled = false; btn.textContent = label;
  }
}

// Delete a whole job from the queue (and its generated application, if any), so
// nothing dangles in the Library. This is distinct from delJob() which only
// removes the generated FILES and keeps the job.
async function deleteJobEntry(row, btn) {
  if (!row?.id) return;
  if (!await uiConfirm({ title: 'Delete this job?', message: `${row.title || ''}${row.company ? ' @ ' + row.company : ''}\n\nRemoves the job${row.folder ? ' AND its generated application' : ''}. This can't be undone.`, ok: 'Delete', danger: true })) return;
  if (btn) btn.disabled = true;
  try {
    if (row.folder) { try { await api('/run?folder=' + enc(row.folder), { method: 'DELETE' }); } catch {} }
    await api(`/jobs/${row.id}`, { method: 'DELETE' });
    jl.sel.delete(row.id);
    toast('Job deleted.');
    loadJobs(); loadLibrary(); renderScrapedJobs();
  } catch (e) { toast('Delete failed: ' + e.message, true); if (btn) btn.disabled = false; }
}

function n8nTestMode() { const c = $('n8n-test'); return !!(c && c.checked); }
async function verifyN8n(btn) {
  const test = n8nTestMode(), status = $('n8n-verify-status');
  const label = btn.textContent; btn.disabled = true; btn.textContent = '⏳ Verifying…';
  status.textContent = test ? 'Waiting for the n8n test listener…' : 'Checking the active production workflow…';
  try {
    const res = await api(`/n8n/verify${test ? '?test=true' : ''}`, { method: 'POST' });
    status.textContent = `✓ ${res.mode || (test ? 'test' : 'production')} webhook verified`;
    status.style.color = '#63d49a';
    toast('n8n webhook verified. The check did not send an email.');
  } catch (e) {
    status.textContent = '✕ Verification failed'; status.style.color = '#ff8d8d';
    toast('n8n verification failed: ' + e.message, true);
  } finally { btn.disabled = false; btn.textContent = label; }
}
async function sendToN8n(key, btn) {
  const test = n8nTestMode();
  const known = jl.all.find(j => j.id === key) || ((typeof coState !== 'undefined' && coState.jobs) ? coState.jobs.find(j => j.id === key) : null);
  if (known && known.sent_at && !await uiConfirm({
    title: 'Resend this application?',
    message: `The existing generated resume, cover letter, and email will be submitted to n8n again.${test ? '\n\nTEST mode still executes the n8n workflow; use Verify n8n webhook for a no-email check.' : ''}`,
    ok: 'Resend',
  })) return false;
  const label = btn.textContent; btn.disabled = true; btn.textContent = '⏳';
  try {
    const res = await api(`/jobs/${key}/send-n8n${test ? '?test=true' : ''}`, { method: 'POST' });
    if (test) {
      toast('Posted to n8n TEST webhook (arm "Listen for test event" first). Job not marked applied.');
      btn.disabled = false; btn.textContent = label;
    } else {
      toast(`${res && res.resent ? 'Resent' : 'Sent'} to ${res && res.to ? res.to : 'n8n'} and acknowledged. Marked applied.`);
      loadJobs();
    }
    return true;
  } catch (e) {
    toast('Send failed: ' + e.message, true); btn.disabled = false; btn.textContent = label;
    return false;
  }
}
// One-click: email this job's company HR an "I applied to your posting" note.
async function emailHr(key, btn) {
  const test = n8nTestMode();
  const label = btn.textContent; btn.disabled = true; btn.textContent = '⏳';
  try {
    const res = await api(`/jobs/${key}/email-hr${test ? '?test=true' : ''}`, { method: 'POST' });
    if (test) { toast('Posted HR note to n8n TEST webhook (not recorded).'); btn.disabled = false; btn.textContent = label; }
    else { toast(`Emailed HR${res && res.to ? ' (' + (Array.isArray(res.to) ? res.to.join(', ') : res.to) + ')' : ''}.`); loadJobs(); loadCompanies(); }
    return true;
  } catch (e) {
    toast('Email HR failed: ' + e.message, true); btn.disabled = false; btn.textContent = label;
    return false;
  }
}
async function sendFollowup(key, btn) {
  const test = n8nTestMode();
  const label = btn.textContent; btn.disabled = true; btn.textContent = '⏳';
  try {
    const res = await api(`/jobs/${key}/followup${test ? '?test=true' : ''}`, { method: 'POST' });
    if (test) {
      toast('Posted follow-up to n8n TEST webhook (arm "Listen for test event" first). Not recorded.');
      btn.disabled = false; btn.textContent = label;
    } else {
      toast(`Follow-up sent to ${res && res.to ? res.to : 'n8n'}.`);
      loadJobs();
    }
    return true;
  } catch (e) {
    toast('Follow-up failed: ' + e.message, true); btn.disabled = false; btn.textContent = label;
    return false;
  }
}

function syncBulkBtn() {
  const n = jl.sel.size;
  const btn = $('jl-bulk'); btn.textContent = `⚡ Generate selected (${n})`; btn.disabled = !n;
  const tb = $('jl-tobulk'); if (tb) { tb.textContent = `➕ Add to Bulk (${n})`; tb.disabled = !n; }
  const ds = $('jl-del-sel'); if (ds) { ds.textContent = `🗑 Delete selected (${n})`; ds.disabled = !n; }
  const sel = jlFiltered().filter(r => r.id);
  $('jl-all').checked = sel.length > 0 && sel.every(r => jl.sel.has(r.id));
}

async function genJob(job, btn) {
  const label = btn.textContent; btn.disabled = true; btn.textContent = '⏳';
  const model = resolveModel(job.priority_level === 'high');
  const viaHermes = usesHermes(model);
  if (viaHermes) btn.textContent = '⏳🤖';
  try {
    const result = await api(`/jobs/${job.id}/generate`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ persona: activePersona(), strict: true, pdf: true, model }),
    });
    toast(`Generated${viaHermes ? ' · Hermes' : ''}${result.persona_label ? ' · ' + result.persona_label : ''}${performanceText(result)}.`);
    notifyFallback(result);
    // Update this job in place — no full table reload / spinner flash, so the view
    // stays put and you don't lose your place. Library/RSS refresh on their own tab.
    job.status = 'generated'; job.gen = true;
    job.folder = result.folder || result.folder_name || result.run_id || job.folder;
    renderJobs();
    openModalFor(result); loadUsage();
    // Library / RSS reload on their own tabs (showView) — no need to re-fetch them
    // here; that just adds network latency after every single generation.
  } catch (e) {
    toast('Generation failed: ' + e.message, true); btn.disabled = false; btn.textContent = label;
  }
}

/* filters + sort wiring */
['jl-search','jl-status','jl-source','jl-channel','jl-applied','jl-repeat','jl-relevance','jl-days'].forEach(id => {
  $(id).addEventListener(id === 'jl-search' ? 'input' : 'change', renderJobs);
});
// Persist the Jobs day filter across reloads.
try { const d = lsGet('jl-days'); if (d !== null) $('jl-days').value = d; } catch {}
$('jl-days').addEventListener('change', () => { try { lsSet('jl-days', $('jl-days').value); } catch {} });
document.querySelectorAll('.jl-sort').forEach(th => th.onclick = () => {
  const k = th.dataset.sort;
  jl.sort = { key: k, dir: jl.sort.key === k && jl.sort.dir === 'asc' ? 'desc' : 'asc' };
  renderJobs();
});
$('jl-all').onclick = () => {
  const rows = jlFiltered().filter(r => r.id);
  const turnOn = !rows.every(r => jl.sel.has(r.id));
  rows.forEach(r => turnOn ? jl.sel.add(r.id) : jl.sel.delete(r.id));
  renderJobs();
};

/* bulk generate selected, sequentially — engine per job priority */
let generationBatchPolling = false;
let generationBatchId = '';
let generationBatchFinished = '';
async function showGenerationBatch(batch) {
  if (!batch) return;
  generationBatchId = batch.id;
  lsSet('generation-batch-id', batch.id);
  let banner = $('generation-batch-status');
  if (!banner) {
    banner = document.createElement('div'); banner.id = 'generation-batch-status';
    banner.className = 'card';
    banner.style.cssText = 'position:fixed;bottom:18px;right:18px;z-index:900;max-width:440px;padding:14px';
    document.body.append(banner);
  }
  const counts = batch.counts || {};
  banner.replaceChildren();
  const message = document.createElement('div');
  message.textContent = `Resume batch: ${counts.done || 0}/${batch.total} completed · ${counts.failed || 0} failed · ${counts.running || 0} running · ${counts.pending || 0} queued. ${batch.complete ? 'Finished.' : 'Saved in the app; you can leave this page.'}`;
  banner.append(message);
  if (counts.failed) {
    const error = document.createElement('p');
    error.textContent = batch.items.find(item => item.state === 'failed')?.error || '';
    const retry = document.createElement('button'); retry.className = 'btn sm'; retry.textContent = 'Retry failed only';
    retry.onclick = async () => showGenerationBatch(await api(`/generation-batches/${batch.id}/retry`, { method: 'POST' }));
    banner.append(error, retry);
  }
  for (const row of bulk) {
    if (row.batchId !== batch.id) continue;
    const item = batch.items[row.batchIndex];
    if (!item) continue;
    row.status = item.state === 'pending' ? 'pending' : item.state;
    row.result = item.result || null; row.error = item.error || '';
  }
  if (bulk.some(row => row.batchId === batch.id)) bulkRender();
  if (batch.complete && generationBatchFinished !== batch.id) {
    generationBatchFinished = batch.id; loadJobs(); loadLibrary(); loadUsage();
  }
}
async function queueGenerationItems(items) {
  const batch = await api('/generation-batches', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({items}) });
  await showGenerationBatch(batch);
  return batch;
}
setInterval(async () => {
  if (generationBatchPolling) return;
  generationBatchPolling = true;
  try {
    const batch = await api(generationBatchId ? `/generation-batches/${generationBatchId}` : '/generation-batches/latest');
    if (batch) await showGenerationBatch(batch);
  } catch (error) { /* A restart does not clear the persisted batch. Poll again. */ }
  finally { generationBatchPolling = false; }
}, 5000);
$('jl-bulk').onclick = async () => {
  const picked = [...jl.sel]; if (!picked.length) return;
  const byId = Object.fromEntries(jl.all.map(j => [j.id, j]));
  // Each generation is an AI call. Jobs that already have an application are
  // skipped; the row's Regenerate button is the deliberate way to redo one.
  const keys = picked.filter(k => !(byId[k] || {}).gen);
  const skipped = picked.length - keys.length;
  if (!keys.length) {
    toast(`All ${skipped} selected job${skipped === 1 ? ' is' : 's are'} already generated. Use Regenerate on a row to redo one.`);
    return;
  }
  const btn = $('jl-bulk'); btn.disabled = true;
  try {
    await queueGenerationItems(keys.map(key_id => ({key_id, options: {persona: activePersona(), strict: true, pdf: true, model: resolveModel((byId[key_id] || {}).priority_level === 'high')}})));
    toast(`Saved ${keys.length} jobs to the background generation queue. Completed jobs are skipped.`);
    jl.sel.clear();
  } catch (error) { toast(error.message, true); }
  finally { btn.disabled = false; loadJobs(); }
};

/* Jobs: delete all selected jobs (and any generated applications). */
$('jl-del-sel').onclick = async () => {
  const keys = [...jl.sel]; if (!keys.length) return;
  const byId = Object.fromEntries(jl.all.map(j => [j.id, j]));
  const withGen = keys.filter(k => (byId[k] || {}).folder).length;
  if (!await uiConfirm({
    title: `Delete ${keys.length} job${keys.length === 1 ? '' : 's'}?`,
    message: `This removes the selected job${keys.length === 1 ? '' : 's'} from the queue${withGen ? ` AND ${withGen} generated application${withGen === 1 ? '' : 's'}` : ''}. This can't be undone.`,
    ok: 'Delete', danger: true,
  })) return;
  const btn = $('jl-del-sel'); btn.disabled = true;
  let ok = 0, fail = 0;
  for (let i = 0; i < keys.length; i++) {
    btn.textContent = `⏳ Deleting ${i + 1}/${keys.length}…`;
    const j = byId[keys[i]] || {};
    try {
      if (j.folder) { try { await api('/run?folder=' + enc(j.folder), { method: 'DELETE' }); } catch {} }
      await api(`/jobs/${keys[i]}`, { method: 'DELETE' });
      jl.sel.delete(keys[i]); ok++;
    } catch { fail++; }
  }
  toast(`Deleted ${ok} job${ok === 1 ? '' : 's'}${fail ? `, ${fail} failed` : ''}.`, fail > 0);
  loadJobs(); loadLibrary(); renderScrapedJobs();
};

/* Jobs: add the selected jobs to the Bulk generate list (keeps key_id so bulk
   generation flips each queue row to 'generated'). */
$('jl-tobulk').onclick = () => {
  const byId = Object.fromEntries(jl.all.map(j => [j.id, j]));
  const sel = [...jl.sel].map(id => byId[id]).filter(Boolean);
  if (!sel.length) return;
  sel.forEach(j => bulkAdd({ key_id: j.id || j.key_id, company: j.company || '', title: j.title || '',
    location: j.location || '', description: j.description || '' }, false));
  jl.sel.clear(); renderJobs();
  toast(`Added ${sel.length} job${sel.length>1?'s':''} to Bulk → open Bulk Generate to run them.`);
};

/* Jobs: remove duplicate rows (same company + title + location), keep the best. */
async function runDedupe(btn) {
  if (!await uiConfirm({ title: 'Remove duplicate jobs?', message: 'Duplicates share company + title + location (format-tolerant).\n\nThe best copy of each (generated/applied/repeatable/priority, else newest) is kept; the rest are deleted.', ok: 'Dedupe', danger: true })) return;
  const label = btn.textContent; btn.disabled = true; btn.textContent = '⏳ Deduping…';
  try {
    const r = await api('/jobs/dedupe', { method: 'POST' });
    toast(r.removed ? `Removed ${r.removed} duplicate${r.removed>1?'s':''} across ${r.groups} role${r.groups>1?'s':''}.` : 'No duplicates found.');
    loadJobs(); loadLibrary(); renderScrapedJobs();
  } catch (e) { toast('Dedupe failed: ' + e.message, true); }
  finally { btn.disabled = false; btn.textContent = label; }
}
$('jl-dedupe').onclick = () => runDedupe($('jl-dedupe'));
$('sk-dedupe').onclick = () => runDedupe($('sk-dedupe'));

/* Jobs: refresh the list */
$('jl-refresh').onclick = () => loadJobs();

/* Hermes Scraping: the Hermes agent searches the web for jobs and queues them */
$('cs-go').onclick = async (e) => {
  const role = $('cs-role').value.trim();
  if (!role) { toast('Enter a role / keywords.', true); return; }
  const btn = e.currentTarget, label = btn.textContent;
  btn.disabled = true; btn.textContent = '🔎🤖 Hermes is searching…';
  const box = $('cs-results'); box.innerHTML = '<span class="spinner dark"></span> Searching the web…';
  try {
    const res = await api('/scrape/hermes', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role, location: $('cs-loc').value.trim(), limit: Number($('cs-limit').value) || 15 }) });
    toast(`Hermes found ${res.found}, queued ${res.queued} new.`);
    box.innerHTML = (res.new_jobs && res.new_jobs.length)
      ? res.new_jobs.map(j => `<div class="src-row"><span style="flex:1">${esc(j.title)}</span><span class="muted">${esc(j.company)}${j.location?' · '+esc(j.location):''}</span></div>`).join('')
      : '<div class="muted">No new jobs (already in your queue, or none found). Try different keywords.</div>';
    loadJobs(); loadUsage();
  } catch (err) {
    box.innerHTML = `<div class="qa dirty">${esc(err.message)}</div>`;
    toast('Hermes scraping failed: ' + err.message, true);
  } finally { btn.disabled = false; btn.textContent = label; }
};

/* Scrape tab: fetch new jobs (intake) */
$('sk-fetch').onclick = async (e) => {
  const btn = e.currentTarget, label = btn.textContent; btn.disabled = true; btn.textContent = '⏳ Fetching…';
  try {
    const res = await api('/intake/run', { method: 'POST' });
    const errs = (res.errors && res.errors.length) ? ` · ${res.errors.length} source error(s)` : '';
    toast(`Scraped ${res.fetched}, queued ${res.committed} new${errs}.`);
    await loadJobs(); renderScrapedJobs();
  } catch (err) { toast('Fetch failed: ' + err.message, true); }
  finally { btn.disabled = false; btn.textContent = label; }
};

/* Scrape tab: re-render the scraped list when the day filter changes */
$('sk-days').onchange = renderScrapedJobs;

/* Scrape tab: import a CSV (e.g. from n8n) into the queue */
$('sk-csv').onclick = () => $('sk-csv-file').click();
$('sk-csv-file').onchange = async (e) => {
  const file = e.target.files[0]; if (!file) return;
  try {
    const text = await file.text();
    const res = await api('/jobs/import', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ csv: text }) });
    toast(`CSV: ${res.rows} rows, ${res.committed} new jobs added.`);
    await loadJobs(); renderScrapedJobs();
  } catch (err) { toast('Import failed: ' + err.message, true); }
  finally { e.target.value = ''; }
};

/* Scrape tab: list the scraped jobs, grouped by source */
let skSel = new Set();   // selected scraped-job ids (for bulk delete)
function skSyncDelBtn() {
  const b = $('sk-del-sel'); if (b) { b.textContent = `🗑 Delete selected (${skSel.size})`; b.disabled = !skSel.size; }
}
async function renderScrapedJobs() {
  const box = $('sk-jobs'); if (!box) return;
  box.innerHTML = '<span class="spinner dark"></span>';
  try {
    const { jobs } = await api('/jobs');
    if (!jobs.length) { box.innerHTML = '<div class="muted">No jobs scraped yet. Add a source above and hit Fetch new jobs.</div>'; return; }
    const daysVal = ($('sk-days') || {}).value || '';
    const bySrc = {};
    // This tab = source-feed + CSV intake only. Browser-capture (collector) has its
    // own dashboard and lives in the Jobs tab, so don't mix it in here.
    const rows = jobs.map(jobFromApi).filter(j => !j.irrelevant && (j.source || 'other') !== 'collector' && jobInRange(j, daysVal));
    if (!rows.length) { box.innerHTML = '<div class="muted">No feed/CSV jobs match this date filter. (Browser-capture jobs are in the Jobs tab.)</div>'; return; }
    rows.forEach(j => { (bySrc[j.source || 'other'] = bySrc[j.source || 'other'] || []).push(j); });
    const allIds = rows.map(j => j.id);
    const groups = Object.entries(bySrc).sort((a, b) => b[1].length - a[1].length).map(([src, js]) =>
      `<div style="margin-bottom:14px">
         <div class="sec-title" style="margin:0 0 6px">${esc(src)} <span style="color:var(--faint);font-weight:500;text-transform:none">(${js.length})</span></div>
         ${js.map(j => `<div class="src-row" style="align-items:flex-start">
           <input type="checkbox" class="sk-rowck" data-id="${esc(j.id)}" ${skSel.has(j.id)?'checked':''} style="width:auto;margin-top:5px" title="Select">
           <div style="flex:1;min-width:0">
             <div style="font-weight:600">${esc(j.title)}${j.email?' 📧':''}${j.repeat?' 🔁':''}</div>
             <div class="muted">${esc(j.company)}${j.location?' · '+esc(j.location):''} · ${esc(j.status)} · ${esc(j.date)}</div>
           </div>
           <div class="jl-rowbtns">
             <button class="btn subtle sm" data-skact="view" data-id="${esc(j.id)}">View</button>
             ${j.gen ? `<button class="btn ghost sm" data-skact="preview" data-id="${esc(j.id)}">Preview</button>` : ''}
             <button class="btn ghost sm" data-skact="bulk" data-id="${esc(j.id)}" title="Add this job to the Bulk generate queue">➕ Bulk</button>
             <button class="btn primary sm" data-skact="gen" data-id="${esc(j.id)}">${j.gen?'Regenerate':'Generate'}</button>
             <button class="btn danger sm" data-skact="delete" data-id="${esc(j.id)}">Delete</button>
           </div>
         </div>`).join('')}
       </div>`).join('');
    box.innerHTML = `<div class="src-row" style="margin-bottom:10px;border:none;padding:0">
        <label class="checks" style="margin:0;font-size:13px"><input type="checkbox" id="sk-all" style="width:auto"> Select all (${allIds.length})</label>
        <span style="flex:1"></span>
        <button class="btn danger sm" id="sk-del-sel" disabled>🗑 Delete selected (0)</button>
      </div>` + groups;
    const byId = Object.fromEntries(rows.map(j => [j.id, j]));
    box.querySelectorAll('[data-skact="view"]').forEach(b => b.onclick = () => openJobDetail(byId[b.dataset.id]));
    box.querySelectorAll('[data-skact="preview"]').forEach(b => b.onclick = () => {
      const j = byId[b.dataset.id]; if (j?.folder) openLibrary(j.folder);
    });
    box.querySelectorAll('[data-skact="bulk"]').forEach(b => b.onclick = () => bulkAddFromJob(byId[b.dataset.id]));
    box.querySelectorAll('[data-skact="gen"]').forEach(b => b.onclick = () => genJob(b.dataset.id, b));
    box.querySelectorAll('[data-skact="delete"]').forEach(b => b.onclick = () => deleteScrapedJob(byId[b.dataset.id], b));

    // Multi-select + bulk delete.
    const refreshAll = () => { const sa = $('sk-all'); if (sa) sa.checked = allIds.length > 0 && allIds.every(id => skSel.has(id)); };
    box.querySelectorAll('.sk-rowck').forEach(cb => cb.onclick = () => {
      cb.checked ? skSel.add(cb.dataset.id) : skSel.delete(cb.dataset.id);
      skSyncDelBtn(); refreshAll();
    });
    const sa = $('sk-all');
    if (sa) {
      refreshAll();
      sa.onclick = () => { const on = sa.checked; allIds.forEach(id => on ? skSel.add(id) : skSel.delete(id)); renderScrapedJobs(); };
    }
    $('sk-del-sel').onclick = async () => {
      const ids = allIds.filter(id => skSel.has(id)); if (!ids.length) return;
      const withGen = ids.filter(id => (byId[id] || {}).folder).length;
      if (!await uiConfirm({
        title: `Delete ${ids.length} scraped job${ids.length === 1 ? '' : 's'}?`,
        message: `Removes the selected job${ids.length === 1 ? '' : 's'} from the queue${withGen ? ` AND ${withGen} generated application${withGen === 1 ? '' : 's'}` : ''}. This can't be undone.`,
        ok: 'Delete', danger: true,
      })) return;
      const btn = $('sk-del-sel'); btn.disabled = true;
      let ok = 0, fail = 0;
      for (let i = 0; i < ids.length; i++) {
        btn.textContent = `⏳ Deleting ${i + 1}/${ids.length}…`;
        const j = byId[ids[i]] || {};
        try {
          if (j.folder) { try { await api('/run?folder=' + enc(j.folder), { method: 'DELETE' }); } catch {} }
          await api(`/jobs/${ids[i]}`, { method: 'DELETE' });
          skSel.delete(ids[i]); ok++;
        } catch { fail++; }
      }
      toast(`Deleted ${ok} job${ok === 1 ? '' : 's'}${fail ? `, ${fail} failed` : ''}.`, fail > 0);
      loadJobs(); renderScrapedJobs(); loadLibrary();
    };
    skSyncDelBtn();
  } catch (e) { box.innerHTML = `<div class="muted">Unavailable: ${esc(e.message)}</div>`; }
}

/* Scrape tab: job sources (add/remove) + filters. Profile tab: saved companies + apply profile. */
async function renderSetup() {
  const panel = $('sk-setup');
  panel.innerHTML = '<span class="spinner dark"></span>';
  try {
    const [src, ap, co, st] = await Promise.all([
      api('/sources'), api('/apply-profile'), api('/companies'), api('/source-types')]);
    const stypes = st.addable || [];                     // dynamic source-type catalogue
    const stMap = Object.fromEntries(stypes.map(t => [t.type, t]));
    const f = src.filters || {};
    const sec = (t) => `<div class="sec-title" style="margin:14px 0 8px">${t}</div>`;
    const sources = (src.sources || []).length
      ? `<div class="src-chips">${src.sources.map((s, i) =>
          `<span class="src-chip" title="${esc(s.type)}: ${esc(s.label)}"><span class="src-chip-type">${esc(s.type)}</span><span class="src-chip-l">${esc(s.label)}</span><button class="src-chip-x" data-rmsrc="${i}" title="Remove source">✕</button></span>`).join('')}</div>`
      : '<div class="muted">No sources configured.</div>';
    const addForm =
      `<div class="src-row" style="gap:6px;margin-top:8px;flex-wrap:wrap">
         <select id="add-src-type" class="jl-inp" style="width:auto">
           ${stypes.map(t => `<option value="${esc(t.type)}">${esc(t.label)}</option>`).join('')}
         </select>
         <input id="add-src-val" class="jl-inp" style="flex:1;min-width:160px" placeholder="${esc((stypes[0]||{}).hint||'')}">
         <input id="add-src-loc" class="jl-inp" style="width:150px" placeholder="Location (optional)">
         <button class="btn primary sm" id="add-src-btn">＋ Add</button>
       </div>`;
    const saved = (co.companies || []).map(c =>
      `<div class="src-row"><span class="src-type">${esc(c.company||'')}</span><span class="muted">${esc(c.ats||'')} ${c.last_apply_url||c.careers_url?'· saved URL':''}</span></div>`).join('')
      || '<div class="muted">None saved yet — the autofill assistant saves company details as you use it.</div>';
    const p = ap.profile || {};
    // RSS tab: only the job-source config + filters belong here.
    panel.innerHTML =
      sec('Job sources <span style="color:var(--faint);font-weight:500;text-transform:none">— fetched by “🔄 Fetch new jobs”</span>') +
      sources + addForm +
      `<div class="src-row" style="border-top:1px solid var(--line);margin-top:8px;padding-top:10px">
         <span class="src-type">filters</span>
         <span class="muted">${(f.title_keywords||[]).length} title keyword(s)${f.require_email?' · email required':''}</span></div>`;

    // Profile tab: saved company details (apply profile rendered below). Repeat
    // companies now live in the Repeatable tab (rpRenderCompanies).
    const savedPanel = $('pf-saved'); if (savedPanel) savedPanel.innerHTML = saved;

    const apPanel = $('sk-applyprofile');
    if (apPanel) {
      apPanel.innerHTML = pfChips(p);
      apPanel.querySelectorAll('.pf-copy').forEach(b =>
        b.onclick = () => copyVal(b.dataset.copy, b.dataset.label));
    }

    panel.querySelectorAll('[data-rmsrc]').forEach(b => b.onclick = async () => {
      if (!await uiConfirm({ title: 'Remove this source?', message: 'It will no longer be scraped.', ok: 'Remove', danger: true })) return;
      try { await api('/sources/' + b.dataset.rmsrc, { method: 'DELETE' }); toast('Source removed.'); renderSetup(); }
      catch (e) { toast('Remove failed: ' + e.message, true); }
    });
    const syncAddForm = () => {
      const t = stMap[$('add-src-type').value] || {};
      $('add-src-loc').style.display = t.needs_location ? '' : 'none';
      $('add-src-val').placeholder = t.hint || 'Value';
    };
    $('add-src-type').onchange = syncAddForm; syncAddForm();
    $('add-src-btn').onclick = async () => {
      const type = $('add-src-type').value, val = $('add-src-val').value.trim();
      if (!val) { toast('Enter a value.', true); return; }
      const meta = stMap[type] || {};
      const field = meta.input || 'url';          // search | company | url
      const body = { type, [field]: val };
      if (meta.needs_location) body.location = $('add-src-loc').value.trim();
      try {
        await api('/sources/add', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        toast('Source added. Hit “🔄 Fetch new jobs” to pull it in.');
        renderSetup();
      } catch (e) { toast('Add failed: ' + e.message, true); }
    };
  } catch (e) { panel.innerHTML = `<span class="muted">Setup unavailable: ${esc(e.message)}</span>`; }
}

/* manual add (Scrape tab) -> writes to the queue; shows up in Jobs */
$('sk-manual').onclick = () => { $('sc-modal').classList.add('show'); };
$('sc-modal-x').onclick = () => $('sc-modal').classList.remove('show');
$('sc-modal').onclick = (e) => { if (e.target === $('sc-modal')) $('sc-modal').classList.remove('show'); };
$('sk-capture').href = COLLECTOR + '/';

$('s-add').onclick = async () => {
  const payload = {
    company: $('s-company').value.trim(), title: $('s-title').value.trim(),
    location: $('s-location').value.trim(), contact_email: $('s-email').value.trim(),
    apply_url: $('s-url').value.trim(), description: $('s-description').value.trim(),
  };
  if (!payload.title && !payload.company) { toast('Enter at least a title or company.', true); return; }
  const btn = $('s-add'); btn.disabled = true; const label = btn.textContent; btn.textContent = 'Saving…';
  try {
    const res = await api('/jobs/manual', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    });
    toast(res.duplicate ? 'Already in the list.' : 'Added to Jobs.');
    ['s-company','s-title','s-location','s-email','s-url','s-description'].forEach(id => $(id).value = '');
    $('sc-modal').classList.remove('show');
    $('jl-status').value = ''; loadJobs(); showView('scraper');   // show it in Jobs
  } catch (e) { toast('Add failed: ' + e.message, true); }
  finally { btn.disabled = false; btn.textContent = label; }
};

/* ---------- Companies (HR contacts + jobs grouped by company) ---------- */
const coState = { saved: [], jobs: [], expanded: new Set() };
async function loadCompanies() {
  const box = $('co-list'); if (!box) return;
  box.innerHTML = '<div class="empty"><span class="spinner dark"></span></div>';
  try {
    const [co, jr] = await Promise.all([api('/companies'), api('/jobs')]);
    coState.saved = co.companies || [];
    coState.jobs = (jr.jobs || []).map(jobFromApi);
    coRender();
  } catch (e) { box.innerHTML = `<div class="qa dirty">${esc(e.message)}</div>`; }
}
let coTab = 'all', coSort = 'name';
const hrSel = new Set();   // selected company names for HR batch send
function hrSyncBatch() {
  const b = $('hr-batch'); if (b) { b.textContent = `📤 Send batch (${hrSel.size})`; b.disabled = !hrSel.size; }
}
const coNorm = s => (s || '').trim().toLowerCase();
function coContacts(hr) {
  if (!hr) return [];
  if (Array.isArray(hr.hr_contacts) && hr.hr_contacts.length) return hr.hr_contacts;
  if (hr.hr_email) return [{ name: hr.hr_name || '', email: hr.hr_email }];
  return [];
}
function withinDays(d, n) {
  d = (d || '').slice(0, 10); if (!d) return false;
  const t = Date.parse(d); if (isNaN(t)) return false;
  return (Date.now() - t) / 86400000 <= n;
}
function coGroups() {
  const savedMap = {};
  coState.saved.forEach(r => { if (r.company) savedMap[coNorm(r.company)] = r; });
  const byCo = {};
  coState.jobs.forEach(j => { const k = coNorm(j.company || '—'); (byCo[k] = byCo[k] || { name: j.company || '—', jobs: [] }).jobs.push(j); });
  coState.saved.forEach(r => { const k = coNorm(r.company); if (r.company && !byCo[k]) byCo[k] = { name: r.company, jobs: [] }; });
  return Object.keys(byCo).map(k => {
    const jobs = byCo[k].jobs;
    return {
      name: byCo[k].name, jobs, hr: savedMap[k] || null,
      lastScraped: jobs.reduce((m, j) => ((j.found || '') > m ? j.found : m), ''),
      lastApplied: jobs.reduce((m, j) => ((j.sent_at || '') > m ? j.sent_at : m), ''),
    };
  });
}
function coFollowScore(g) {
  if (!coContacts(g.hr).length) return -1;
  const recent = g.jobs.some(j => withinDays(j.found, 14));
  const fups = (g.hr && g.hr.hr_followups) || [];
  const stale = !fups.length || !withinDays(fups[fups.length - 1], 10);
  return (recent ? 2 : 0) + (stale ? 1 : 0);
}
function coRender() {
  const allOn = coTab === 'all';
  $('co-filters').style.display = allOn ? 'flex' : 'none';
  $('co-list').style.display = allOn ? '' : 'none';
  $('hr-filters').style.display = allOn ? 'none' : 'flex';
  $('hr-list').style.display = allOn ? 'none' : '';
  document.querySelectorAll('#co-tabs button').forEach(b => b.classList.toggle('on', b.dataset.cotab === coTab));
  if (!allOn) { hrRender(); return; }
  const box = $('co-list'); if (!box) return;
  const q = coNorm($('co-q').value), hideEmpty = $('co-hideempty').checked;
  let groups = coGroups().filter(g => {
    if (hideEmpty && !coContacts(g.hr).length) return false;
    if (!q) return true;
    return coNorm(g.name).includes(q) || g.jobs.some(j => coNorm(j.title).includes(q));
  });
  const byName = (a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase());
  if (coSort === 'scraped') groups.sort((a, b) => (b.lastScraped || '').localeCompare(a.lastScraped || '') || byName(a, b));
  else if (coSort === 'applied') groups.sort((a, b) => (b.lastApplied || '').localeCompare(a.lastApplied || '') || byName(a, b));
  else if (coSort === 'followup') groups.sort((a, b) => coFollowScore(b) - coFollowScore(a) || byName(a, b));
  else groups.sort(byName);
  const withHr = coGroups().filter(g => coContacts(g.hr).length).length;
  $('co-count').textContent = `${groups.length} companies · ${withHr} with HR email`;
  if (!groups.length) { box.innerHTML = `<div class="empty"><div class="big">🏢</div>No companies yet. Upload an HR CSV or scrape some jobs.</div>`; return; }
  box.innerHTML = groups.map(coCard).join('');
  coWire(box);
  applyCoView();
}
function coWire(box) {
  const byId = Object.fromEntries(coState.jobs.map(j => [j.id, j]));
  box.querySelectorAll('.co-copy').forEach(el => el.onclick = () => { (navigator.clipboard?.writeText(el.dataset.copy) || Promise.resolve()); toast('Copied: ' + el.dataset.copy); });
  box.querySelectorAll('[data-coact="toggle"]').forEach(el => el.onclick = () => {
    const name = el.dataset.co, open = !coState.expanded.has(name);
    open ? coState.expanded.add(name) : coState.expanded.delete(name);
    const card = el.closest('.co-card');
    card.querySelector('.co-jobs').style.display = open ? 'block' : 'none';
    const ar = card.querySelector('.co-toggle'); if (ar) ar.textContent = open ? '▾' : '▸';
  });
  box.querySelectorAll('[data-coact="edit"]').forEach(b => b.onclick = () => {
    const ed = b.closest('.co-card').querySelector('.co-hr-edit');
    ed.style.display = ed.style.display === 'none' ? 'block' : 'none';
  });
  box.querySelectorAll('[data-coact="addrow"]').forEach(b => b.onclick = () => {
    const rows = b.closest('.co-card').querySelector('.co-hr-rows');
    const tmp = document.createElement('div'); tmp.innerHTML = coEditRow({});
    const row = tmp.firstElementChild; rows.appendChild(row);
    row.querySelector('[data-coact="rmrow"]').onclick = () => row.remove();
  });
  box.querySelectorAll('[data-coact="rmrow"]').forEach(b => b.onclick = () => b.closest('.co-hr-row').remove());
  box.querySelectorAll('[data-coact="save"]').forEach(b => b.onclick = async () => {
    const card = b.closest('.co-card');
    const contacts = [...card.querySelectorAll('.co-hr-row')]
      .map(r => ({ name: r.querySelector('.co-c-name').value.trim(), email: r.querySelector('.co-c-email').value.trim() }))
      .filter(c => c.email);
    try {
      await api(`/companies/${encodeURIComponent(b.dataset.co)}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ hr_contacts: contacts }) });
      toast('HR contacts saved.'); loadCompanies(); loadJobs();
    } catch (e) { toast('Save failed: ' + e.message, true); }
  });
  box.querySelectorAll('[data-coact="view"]').forEach(b => b.onclick = () => openJobDetail(byId[b.dataset.jid]));
  box.querySelectorAll('[data-coact="bulk"]').forEach(b => b.onclick = () => bulkAddFromJob(byId[b.dataset.jid]));
  box.querySelectorAll('[data-coact="gen"]').forEach(b => b.onclick = () => genJob(byId[b.dataset.jid], b));
  box.querySelectorAll('[data-coact="send"]').forEach(b => b.onclick = async () => { if (await sendToN8n(b.dataset.jid, b)) loadCompanies(); });
  box.querySelectorAll('[data-coact="followup"]').forEach(b => b.onclick = async () => { if (await sendFollowup(b.dataset.jid, b)) loadCompanies(); });
  box.querySelectorAll('[data-coact="emailhr"]').forEach(b => b.onclick = () => emailHr(b.dataset.jid, b));
  box.querySelectorAll('[data-coact="sendall"]').forEach(b => b.onclick = () => sendCompanyJobs(b.dataset.co, b));
}
// Send a separate, tailored application email per GENERATED job for one company.
async function sendCompanyJobs(companyName, btn) {
  const g = coGroups().find(x => coNorm(x.name) === coNorm(companyName));
  const hrEmail = (coContacts(g && g.hr)[0] || {}).email || '';
  const test = n8nTestMode();
  const jobs = coState.jobs.filter(j => coNorm(j.company) === coNorm(companyName) && j.id);
  // Bulk company send is first-send only; resends must be deliberate per-job clicks.
  const sendable = jobs.filter(j => j.gen && !j.sent_at && ((j.email || '').trim() || hrEmail));
  const needGen = jobs.filter(j => !j.gen).length;
  if (!sendable.length) { toast(needGen ? `Nothing generated yet (${needGen} need generating).` : 'No unsent generated jobs. Use the per-job Resend button when needed.', true); return; }
  if (!await uiConfirm({ title: 'Email HR per job?', message: `Send ${sendable.length} separate email${sendable.length === 1 ? '' : 's'} to ${hrEmail}${test ? ' (TEST mode)' : ''}.${needGen ? `\n${needGen} job(s) not generated will be skipped.` : ''}`, ok: 'Send' })) return;
  const label = btn.textContent; btn.disabled = true; btn.textContent = '⏳';
  let sent = 0, failed = 0;
  for (const j of sendable) {
    try { await api(`/jobs/${j.id}/send-n8n${test ? '?test=true' : ''}`, { method: 'POST' }); sent++; }
    catch (e) { failed++; }
  }
  toast(`${sent} sent${failed ? ` · ${failed} failed` : ''}${needGen ? ` · ${needGen} need generating` : ''}.`, failed > 0);
  btn.disabled = false; btn.textContent = label;
  loadCompanies(); loadJobs();
}
function coEditRow(c) {
  return `<div class="co-hr-row" style="display:flex;gap:8px;flex-wrap:wrap">
    <input class="jl-inp co-c-name" placeholder="HR name" value="${esc((c && c.name) || '')}" style="flex:1;min-width:130px">
    <input class="jl-inp co-c-email" placeholder="hr@company.com" value="${esc((c && c.email) || '')}" style="flex:1;min-width:150px">
    <button class="btn subtle sm" data-coact="rmrow" title="Remove this contact">✕</button>
  </div>`;
}
function coCard(g) {
  const contacts = coContacts(g.hr), primary = contacts[0];
  const expanded = coState.expanded.has(g.name);
  const hrInline = primary
    ? `<span class="co-hr-inline">✎ ${primary.name ? esc(primary.name) + ' · ' : ''}<span class="co-copy" data-copy="${esc(primary.email)}" style="cursor:pointer;color:var(--accent)" title="Click to copy">${esc(primary.email)}</span>${contacts.length > 1 ? ` <span class="muted">+${contacts.length - 1} more</span>` : ''}</span>`
    : '';
  const jobs = g.jobs.slice().sort((a, b) => (a.title || '').toLowerCase().localeCompare((b.title || '').toLowerCase()));
  const jobsHtml = jobs.length ? jobs.map(j => coJobRow(j, primary ? primary.email : '')).join('')
    : '<div class="muted" style="font-size:12px;padding:4px 0">No jobs for this company yet.</div>';
  const editRows = (contacts.length ? contacts : [{}]).map(coEditRow).join('');
  return `<div class="card co-card" data-co="${esc(g.name)}">
    <div class="co-head">
      <span class="co-toggle" data-coact="toggle" data-co="${esc(g.name)}" style="cursor:pointer;color:var(--muted)">${expanded ? '▾' : '▸'}</span>
      <span class="co-name" data-coact="toggle" data-co="${esc(g.name)}" style="cursor:pointer">🏢 ${esc(g.name)}</span>
      <span class="jl-src" style="margin:0">${g.jobs.length} job${g.jobs.length === 1 ? '' : 's'}</span>
      ${hrInline}
      <span style="flex:1"></span>
      ${(primary && g.jobs.some(j => j.gen && !j.sent_at && j.id)) ? `<button class="btn ghost sm" data-coact="sendall" data-co="${esc(g.name)}" title="Send each unsent generated job to ${esc(primary.email)}">📧 Email HR</button>` : ''}
      <button class="btn subtle sm" data-coact="edit" data-co="${esc(g.name)}" title="${primary ? 'Edit HR contacts' : 'Add HR contacts'}">✎ HR</button>
    </div>
    <div class="co-hr-edit" style="display:none;margin:8px 0">
      <div class="co-hr-rows" style="display:flex;flex-direction:column;gap:8px">${editRows}</div>
      <div style="display:flex;gap:8px;margin-top:8px;align-items:center">
        <button class="btn ghost sm" data-coact="addrow">＋ Add contact</button>
        <span style="flex:1"></span>
        <button class="btn primary sm" data-coact="save" data-co="${esc(g.name)}">Save</button>
      </div>
    </div>
    <div class="co-jobs" style="margin-top:6px;display:${expanded ? 'block' : 'none'}">${jobsHtml}</div>
  </div>`;
}
function coJobRow(j, hrEmail) {
  const email = (j.email || '').trim() || hrEmail;   // effective: job email, else company HR
  const fromHr = !(j.email || '').trim() && hrEmail;
  return `<div class="src-row" style="align-items:flex-start">
    <div style="flex:1;min-width:0">
      <div style="font-weight:600">${esc(j.title || 'Untitled')}${email ? ' 📧' : ''}</div>
      <div class="muted" style="font-size:12px">${j.location ? esc(j.location) + ' · ' : ''}<span class="jl-st ${esc(j.status)}">${esc(j.status)}</span> · ${esc(j.date || '')}${email ? ` · ${esc(email)}${fromHr ? ' <span style="color:var(--accent)">(HR)</span>' : ''}` : ''}</div>
    </div>
    <div class="jl-rowbtns">
      ${j.id ? `<button class="btn subtle sm" data-coact="view" data-jid="${esc(j.id)}">View</button>` : ''}
      ${j.id && !j.gen ? `<button class="btn ghost sm" data-coact="bulk" data-jid="${esc(j.id)}">➕ Bulk</button>` : ''}
      ${(j.id && j.gen && email) ? `<button class="btn ghost sm" data-coact="send" data-jid="${esc(j.id)}" title="${j.sent_at ? 'Resend the existing generated package' : 'Send to ' + esc(email)}">${j.sent_at ? '↻ Resend' : '📧 Send'}</button>` : ''}
      ${(j.id && email) ? `<button class="btn ghost sm" data-coact="emailhr" data-jid="${esc(j.id)}" title="${j.hr_emailed_at ? 'HR emailed ' + esc(j.hr_emailed_at) : 'Email HR about this posting'}">${j.hr_emailed_at ? '✅ HR' : '✉️ HR'}</button>` : ''}
      ${(j.id && j.sent_at) ? `<button class="btn ghost sm" data-coact="followup" data-jid="${esc(j.id)}" title="Send a follow-up${j.followups && j.followups.length ? ' ('+j.followups.length+' sent)' : ''}">🔔 Follow up</button>` : ''}
      ${j.id ? `<button class="btn primary sm" data-coact="gen" data-jid="${esc(j.id)}">${j.gen ? 'Regenerate' : 'Generate'}</button>` : ''}
    </div>
  </div>`;
}
/* HR follow-ups sub-view: companies with saved HR (optionally only recent postings). */
function hrFilteredGroups() {
  const win = parseInt($('hr-window').value) || 30, q = coNorm($('hr-q').value);
  const recentOnly = $('hr-recent').checked;
  let groups = coGroups().filter(g => coContacts(g.hr).length
    && (!recentOnly || g.jobs.some(j => withinDays(j.found, win)))
    && (!q || coNorm(g.name).includes(q)));
  groups.sort((a, b) => (b.lastScraped || '').localeCompare(a.lastScraped || '') || a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
  return groups;
}
function hrRender() {
  const box = $('hr-list'); if (!box) return;
  const win = parseInt($('hr-window').value) || 30, recentOnly = $('hr-recent').checked;
  const groups = hrFilteredGroups();
  $('hr-count').textContent = recentOnly
    ? `${groups.length} compan${groups.length === 1 ? 'y' : 'ies'} with a posting in ${win} days`
    : `${groups.length} compan${groups.length === 1 ? 'y' : 'ies'} with saved HR`;
  if (!groups.length) { box.innerHTML = `<div class="empty"><div class="big">✉️</div>${recentOnly ? `No companies with saved HR and a posting in the last ${win} days. Untick "Recent posting only" to see all, or import HR via CSV.` : 'No companies with a saved HR email yet. Import HR via CSV in the All companies tab.'}</div>`; return; }
  box.innerHTML = groups.map(g => hrCard(g, win)).join('');
  box.querySelectorAll('.co-copy').forEach(el => el.onclick = () => { navigator.clipboard?.writeText(el.dataset.copy); toast('Copied: ' + el.dataset.copy); });
  box.querySelectorAll('[data-hract]').forEach(b => b.onclick = () => {
    const k = b.dataset.hract;
    if (k === 'edit') openHrCompose(b.dataset.co, 'first');
    else sendHrDirect(b.dataset.co, k === 'send2' ? 'second' : 'first', b);
  });
  applyCoView();
}
// One-click HR follow-up: auto-build the template + send to all saved HR contacts.
async function sendHrDirect(company, kind, btn) {
  const g = coGroups().find(x => coNorm(x.name) === coNorm(company));
  const contacts = coContacts(g && g.hr);
  if (!contacts.length) { toast('No HR email saved for this company.', true); return; }
  const test = n8nTestMode();
  if (!await uiConfirm({
    title: `Send ${kind === 'second' ? '2nd' : '1st'} follow-up to ${company}?`,
    message: `To: ${contacts.map(c => c.email).join(', ')}${test ? '\n(TEST mode)' : ''}`, ok: 'Send',
  })) return;
  const lbl = btn.textContent; btn.disabled = true; btn.textContent = '⏳';
  try {
    await api('/companies/hr-followup/send', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ company, kind, test }) });
    toast(test ? 'Posted to n8n TEST webhook (not recorded).' : 'Follow-up sent to HR.');
    if (!test) loadCompanies(); else { btn.disabled = false; btn.textContent = lbl; }
  } catch (e) { toast('Send failed: ' + e.message, true); btn.disabled = false; btn.textContent = lbl; }
}
function hrCard(g, win) {
  const contacts = coContacts(g.hr), fups = (g.hr && g.hr.hr_followups) || [];
  const recent = g.jobs.filter(j => withinDays(j.found, win)).sort((a, b) => (b.found || '').localeCompare(a.found || ''));
  const roles = recent.slice(0, 3).map(j => esc(j.title)).join(', ') + (recent.length > 3 ? ' …' : '');
  const status = fups.length ? `${fups.length} sent · last ${esc(fups[fups.length - 1])}` : 'no follow-up yet';
  const emails = contacts.map(c => `<span class="co-copy" data-copy="${esc(c.email)}" style="cursor:pointer;color:var(--accent)" title="Click to copy">${esc(c.email)}</span>`).join(', ');
  return `<div class="card co-card" data-co="${esc(g.name)}">
    <div class="co-head">
      <span class="co-name">🏢 ${esc(g.name)}</span>
      <span class="jl-src" style="margin:0">${recent.length} new</span>
      <span class="co-hr-inline">${emails}</span>
      <span style="flex:1"></span>
      <button class="btn primary sm" data-hract="send1" data-co="${esc(g.name)}" title="One-click: email all saved HR the 1st follow-up">📧 Send 1st</button>
      <button class="btn subtle sm" data-hract="send2" data-co="${esc(g.name)}" title="One-click: 2nd follow-up">2nd</button>
      <button class="btn subtle sm" data-hract="edit" data-co="${esc(g.name)}" title="Edit before sending">✎ Edit</button>
    </div>
    <div class="muted" style="font-size:12px;margin-top:6px">Recent: ${roles || '—'} · <span style="color:var(--accent)">${status}</span></div>
  </div>`;
}
let hrcCompany = '';
async function openHrCompose(company, kind) {
  hrcCompany = company;
  const g = coGroups().find(x => coNorm(x.name) === coNorm(company));
  const contacts = coContacts(g && g.hr);
  $('hrc-title').textContent = `${kind === 'second' ? 'Second' : 'First'} follow-up · ${company}`;
  $('hrc-recips').innerHTML = contacts.length
    ? contacts.map((c, i) => `<label class="checks" style="margin:0;font-size:13px"><input type="checkbox" class="hrc-r" value="${esc(c.email)}" ${i === 0 ? 'checked' : ''} style="width:auto"> ${c.name ? esc(c.name) + ' · ' : ''}${esc(c.email)}</label>`).join('')
    : '<span class="muted">No HR emails saved for this company.</span>';
  $('hrc-subject').value = 'Loading…'; $('hrc-body').value = 'Loading…';
  $('hrc-overlay').classList.add('show');
  try {
    const res = await api('/companies/hr-followup/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ company, kind, window_days: parseInt($('hr-window').value) || 30 }) });
    $('hrc-subject').value = res.subject || ''; $('hrc-body').value = res.body || '';
  } catch (e) { toast('Preview failed: ' + e.message, true); $('hrc-subject').value = ''; $('hrc-body').value = ''; }
}
// Grid / list view toggle for Companies + Repeatable (default grid, persisted).
let coView = lsGet('co-view') || 'grid';
let rpView = lsGet('rp-view') || 'grid';
function applyCoView() {
  ['co-list', 'hr-list'].forEach(id => { const box = $(id); if (box) box.classList.toggle('cards-grid', coView === 'grid'); });
  document.querySelectorAll('#co-view button').forEach(b => b.classList.toggle('on', b.dataset.cv === coView));
}
function applyRpView() {
  const box = $('rp-list'); if (box) box.classList.toggle('cards-grid', rpView === 'grid');
  document.querySelectorAll('#rp-view button').forEach(b => b.classList.toggle('on', b.dataset.rv === rpView));
}
document.querySelectorAll('#co-view button').forEach(b => b.onclick = () => { coView = b.dataset.cv; try { lsSet('co-view', coView); } catch {} applyCoView(); });
document.querySelectorAll('#rp-view button').forEach(b => b.onclick = () => { rpView = b.dataset.rv; try { lsSet('rp-view', rpView); } catch {} applyRpView(); });
applyCoView(); applyRpView();

$('co-refresh').onclick = loadCompanies;
$('co-q').oninput = coRender;
$('co-hideempty').onchange = coRender;
$('co-sort').onchange = () => { coSort = $('co-sort').value; coRender(); };
document.querySelectorAll('#co-tabs button').forEach(b => b.onclick = () => { coTab = b.dataset.cotab; coRender(); });
$('hr-window').onchange = () => { hrSel.clear(); hrRender(); };
$('hr-recent').onchange = () => { hrSel.clear(); hrRender(); };
$('hr-q').oninput = hrRender;
$('hr-all').onclick = () => {
  const names = hrFilteredGroups().map(g => g.name);
  const on = $('hr-all').checked;
  names.forEach(n => on ? hrSel.add(n) : hrSel.delete(n));
  hrRender();
};
$('hr-batch').onclick = async () => {
  const companies = [...hrSel]; if (!companies.length) return;
  const kind = $('hr-kind').value, test = n8nTestMode();
  if (!await uiConfirm({
    title: `Send ${kind === 'second' ? '2nd' : '1st'} follow-up to ${companies.length} compan${companies.length === 1 ? 'y' : 'ies'}?`,
    message: `One email per saved HR contact, auto-built from the ${kind === 'second' ? 'second' : 'first'}-follow-up template${test ? ' (TEST mode)' : ''}. Logs to the HR Outreach sheet.`,
    ok: 'Send batch',
  })) return;
  const btn = $('hr-batch'); btn.disabled = true; const lbl = btn.textContent; btn.textContent = '⏳ Sending…';
  try {
    const res = await api('/companies/hr-batch/send', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ companies, kind, window_days: parseInt($('hr-window').value) || 30, test }) });
    toast(test ? `Posted ${res.rows} test row${res.rows === 1 ? '' : 's'} to n8n (not recorded).`
               : `Batch sent: ${res.rows} email${res.rows === 1 ? '' : 's'} across ${res.companies} compan${res.companies === 1 ? 'y' : 'ies'}.`);
    if (!test) { hrSel.clear(); loadCompanies(); } else { btn.disabled = false; btn.textContent = lbl; }
  } catch (e) { toast('Batch failed: ' + e.message, true); btn.disabled = false; btn.textContent = lbl; }
};
// HR follow-up compose modal
$('hrc-x').onclick = $('hrc-cancel').onclick = () => $('hrc-overlay').classList.remove('show');
$('hrc-overlay').onclick = (e) => { if (e.target === $('hrc-overlay')) $('hrc-overlay').classList.remove('show'); };
$('hrc-send').onclick = async () => {
  const recipients = [...document.querySelectorAll('.hrc-r:checked')].map(c => c.value);
  if (!recipients.length) { toast('Pick at least one recipient.', true); return; }
  const test = n8nTestMode();
  const btn = $('hrc-send'); btn.disabled = true; const lbl = btn.textContent; btn.textContent = '⏳';
  try {
    await api('/companies/hr-followup/send', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ company: hrcCompany, recipients, subject: $('hrc-subject').value, body: $('hrc-body').value, test }) });
    toast(test ? 'Posted to n8n TEST webhook (not recorded).' : `Follow-up sent to ${recipients.length} recipient${recipients.length === 1 ? '' : 's'}.`);
    $('hrc-overlay').classList.remove('show');
    if (!test) loadCompanies();
  } catch (e) { toast('Send failed: ' + e.message, true); }
  finally { btn.disabled = false; btn.textContent = lbl; }
};
$('co-csv').onclick = () => $('co-csv-file').click();
$('co-csv-file').onchange = async (e) => {
  const file = e.target.files[0]; if (!file) return;
  try {
    const text = await file.text();
    const res = await api('/companies/import', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ csv: text }) });
    toast(`Imported HR details for ${res.saved} compan${res.saved === 1 ? 'y' : 'ies'}.`);
    loadCompanies(); loadJobs();
  } catch (err) { toast('Import failed: ' + err.message, true); }
  finally { e.target.value = ''; }
};
$('co-tpl').onclick = () => {
  const csv = 'company,hr_name,hr_email,hr_phone,ats,careers_url,notes\n'
    + '"Acme Inc","Jane Doe","jane.doe@acme.com","555-0100","greenhouse","https://acme.com/careers","Prefers email applications"\n'
    + '"Globex","Recruiting Team","jobs@globex.com","","lever","https://globex.com/jobs",""\n';
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
  a.download = 'companies_hr_template.csv'; a.click(); URL.revokeObjectURL(a.href);
};

/* ---------- Library (all generated applications) ---------- */
let libCache = [];
// Unified timestamp (ms) for a library item — from a run's created_at or a job's
// posted/found_at. 0 when unparseable (sorts last, never excluded by the day filter).
function libTs(s) { const t = Date.parse(s || ''); return isNaN(t) ? 0 : t; }

// The Library lists EVERYTHING: generated applications (the runs table) AND every
// queued job not yet generated. Two sources, merged into one unified card list.
async function loadLibrary(_attempt = 0) {
  const grid = $('lib-grid'); if (!grid) return;
  if (!_attempt) grid.innerHTML = '<div class="empty"><span class="spinner dark"></span></div>';
  try {
    const [out, jr] = await Promise.all([api('/outputs'), api('/jobs')]);
    const generated = (out.outputs || []).map(o => ({
      folder: o.folder, company: o.company || '', title: o.title || '',
      persona: o.persona || '', has_pdf: !!o.has_pdf, generated: true,
      ts: libTs(o.created_at),
    }));
    const pending = (jr.jobs || []).filter(j => j.status !== 'generated' && !j.irrelevant).map(j => {
      const job = jobFromApi(j);            // shape openJobDetail() expects
      return {
        folder: '', key_id: j.key_id, company: job.company, title: job.title,
        persona: '', has_pdf: false, generated: false, status: job.status,
        ts: libTs(j.posted) || libTs(j.found_at), job,
      };
    });
    libCache = [...generated, ...pending];
    libFilter();
  } catch (e) {
    if (_attempt < 5) { setTimeout(() => loadLibrary(_attempt + 1), 1500); return; }   // cold-start retry
    grid.innerHTML = `<div class="qa dirty">${esc(e.message)}</div>`;
  }
}
function libFilter() {
  const q = $('lib-search').value.trim().toLowerCase();
  const days = $('lib-days').value ? Number($('lib-days').value) : null;
  const sort = $('lib-sort').value;
  const gen = $('lib-gen').value;                       // '' | 'gen' | 'pending'
  const dupKey = o => ((o.company||'') + '|' + (o.title||'')).toLowerCase();
  const counts = {}; libCache.forEach(o => { counts[dupKey(o)] = (counts[dupKey(o)]||0) + 1; });
  let items = libCache.filter(o => {
    if (gen === 'gen' && !o.generated) return false;
    if (gen === 'pending' && o.generated) return false;
    if (days !== null && o.ts && (Date.now() - o.ts) / 86400000 > days) return false;
    return !q || (o.title||'').toLowerCase().includes(q) || (o.company||'').toLowerCase().includes(q)
      || (o.persona||'').toLowerCase().includes(q) || (o.folder||'').toLowerCase().includes(q);
  });
  $('lib-empty').style.display = items.length ? 'none' : '';
  const dups = Object.values(counts).filter(n => n > 1).length;
  const nGen = libCache.filter(o => o.generated).length;
  $('lib-count').textContent = libCache.length
    ? `${items.length} of ${libCache.length} · ${nGen} generated, ${libCache.length-nGen} pending${dups?` · ${dups} duplicate`:''}` : '';

  // Fold into monthly "folders" (newest month first); sort WITHIN each month.
  const mKey = o => { const d = new Date(o.ts || 0); return d.getFullYear()*12 + d.getMonth(); };
  const mLabel = o => o.ts ? new Date(o.ts).toLocaleString(undefined, { month: 'long', year: 'numeric' }) : 'Undated';
  const within = sort === 'company'
    ? (a,b) => (a.company||'').toLowerCase().localeCompare((b.company||'').toLowerCase()) || b.ts-a.ts
    : sort === 'persona'
    ? (a,b) => (a.persona||'~').toLowerCase().localeCompare((b.persona||'~').toLowerCase()) || b.ts-a.ts
    : (a,b) => b.ts - a.ts;
  const groups = {};
  items.forEach(o => { (groups[mKey(o)] = groups[mKey(o)] || []).push(o); });
  const card = o => `
    <div class="lib-card" data-folder="${esc(o.folder)}" data-key="${esc(o.key_id||'')}" data-gen="${o.generated?1:0}" style="${o.generated?'':'opacity:.82'}">
      ${o.generated
        ? `<button class="x" data-del="${esc(o.folder)}" title="Delete application">🗑</button>`
        : `<button class="x" data-deljob="${esc(o.key_id||'')}" title="Delete job from the queue">🗑</button>`}
      <div class="ttl">${esc(o.title || o.folder || 'Untitled')}${counts[dupKey(o)]>1?' <span class="pill" style="background:var(--warn-bg);color:var(--warn)">dup ×'+counts[dupKey(o)]+'</span>':''}</div>
      <div class="co">${esc(o.company || '—')}</div>
      <div class="meta">${o.generated
        ? (o.persona?'<span class="pill">'+esc(o.persona)+'</span>':'')+(o.has_pdf?'<span class="pill">PDF</span>':'')
        : '<span class="pill" style="background:var(--soft-bg);color:var(--muted)">not generated</span>'}<span>${o.ts?new Date(o.ts).toLocaleDateString():'—'}</span></div>
    </div>`;
  $('lib-grid').innerHTML = Object.keys(groups).map(Number).sort((a,b)=>b-a).map(mk => {
    const g = groups[mk].sort(within);
    return `<div class="lib-month">${esc(mLabel(g[0]))} <span class="muted" style="font-weight:500">(${g.length})</span></div>` +
      g.map(card).join('');
  }).join('');
  $('lib-grid').querySelectorAll('.lib-card').forEach(c => {
    if (c.dataset.gen === '1') {
      c.onclick = () => openLibrary(c.dataset.folder);
      const x = c.querySelector('.x'); if (x) x.onclick = (e) => { e.stopPropagation(); deleteRun(x.dataset.del); };
    } else {
      const item = items.find(o => !o.generated && (o.key_id||'') === c.dataset.key);
      c.onclick = () => openJobDetail(item && item.job);
      const x = c.querySelector('.x');
      if (x) x.onclick = (e) => { e.stopPropagation(); deleteJobEntry({ id: x.dataset.deljob, title: item?.title, company: item?.company }, x); };
    }
  });
}
$('lib-search').oninput = libFilter;
$('lib-gen').onchange = libFilter;
$('lib-days').onchange = libFilter;
$('lib-sort').onchange = libFilter;
$('lib-refresh').onclick = loadLibrary;

/* ---------- Preview / delete a generated application ---------- */
async function openLibrary(folder) {
  openModalShell('Loading…', '');
  $('modal-body').innerHTML = '<div class="empty"><span class="spinner dark"></span></div>';
  try {
    const data = await api('/run?folder=' + enc(folder));
    const t = data.target || {};
    openModalShell(t.title || folder, [t.company, t.location].filter(Boolean).join(' · '), folder);
    renderApplication($('modal-body'), data, filesForRun(data));
  } catch (e) { $('modal-body').innerHTML = `<div class="qa dirty">${esc(e.message)}</div>`; }
}
async function deleteRun(folder) {
  if (!await uiConfirm({ title: 'Delete this application?', message: `${folder}\n\nThis permanently removes the generated application.`, ok: 'Delete', danger: true })) return;
  try {
    await api('/run?folder=' + enc(folder), { method: 'DELETE' });
    toast('Deleted.'); loadLibrary(); loadJobs();
  } catch (e) { toast('Delete failed: ' + e.message, true); }
}

/* ---------- Modal ---------- */
let modalDeleteFolder = null;
function openModalShell(title, co, folder) {
  modalDeleteFolder = folder || null;
  $('modal-title').textContent = title;
  $('modal-co').textContent = co || '';
  $('overlay').classList.add('show');
}
// open a modal directly from an in-memory /generate result (bulk preview)
function openModalFor(data) {
  if (!data) return;
  const t = data.target || {};
  openModalShell(t.title || 'Application', [t.company, t.location].filter(Boolean).join(' · '));
  renderApplication($('modal-body'), data, filesForRun(data));
}

/* Job detail modal: info + editable email + actions (Jobs tab) */
const SENT_KIND_LABEL = { application: '📧 Application', followup: '🔔 Follow-up', hr: '✉️ HR email' };
function sentHistoryHtml(j) {
  if (!j.sent_log || !j.sent_log.length) return '';
  const items = j.sent_log.slice().reverse().map(s => `
    <details style="border:1px solid var(--line);border-radius:10px;padding:8px 10px;background:var(--soft-bg)">
      <summary style="cursor:pointer;font-size:13px"><b>${esc(SENT_KIND_LABEL[s.kind] || s.kind)}</b> <span class="muted">· ${esc((s.at||'').replace('T',' ').slice(0,16))} · to ${esc(s.to||'')}</span></summary>
      <div style="margin-top:8px">
        <div style="font-size:11px;color:var(--faint)">SUBJECT</div>
        <div style="font-weight:600;margin-bottom:8px">${esc(s.subject||'')}</div>
        <div style="font-size:11px;color:var(--faint)">BODY</div>
        <div style="white-space:pre-wrap;font-size:13px;background:var(--input-bg);border:1px solid var(--line);border-radius:8px;padding:10px">${esc(s.body||'')}</div>
      </div>
    </details>`).join('');
  return `<label class="fld" style="display:block;margin-top:6px">Sent history (${j.sent_log.length}) — review what was emailed</label>
    <div style="display:flex;flex-direction:column;gap:8px;margin-bottom:6px">${items}</div>`;
}
function openJobDetail(j) {
  if (!j) return;
  openModalShell(j.title || 'Job', [j.company, j.location].filter(Boolean).join(' · '));
  const meta = (k, v) => `<div class="meta"><div class="meta-label" style="font-size:11px;color:var(--faint);text-transform:uppercase">${k}</div><div>${v||'—'}</div></div>`;
  $('modal-body').innerHTML = `
    <div class="meta-grid">
      ${meta('Source', esc(j.source))}${meta('Status', esc(j.status) + (j.repeat?' · 🔁 repeat':''))}
      ${meta('Date', esc(j.date))}${meta('Applied', j.applied?'Yes':'No')}
      ${meta('Last generated', j.gen ? esc(j.generated_at || '—') : 'Not generated yet')}
      ${j.sent_at ? meta('Emailed', esc(j.sent_at) + (j.sent_to ? ' → ' + esc(j.sent_to) : '')) : ''}
      ${j.hr_emailed_at ? meta('HR emailed', esc(j.hr_emailed_at)) : ''}
      ${(j.followups && j.followups.length) ? meta('Follow-ups', j.followups.length + ' (last ' + esc((j.followups[j.followups.length-1]||'').replace('T',' ').slice(0,16)) + ')') : ''}
    </div>
    <label class="fld">Contact email (HR) — edit & save to enable email apply${(!j.email && j.company_email)?' <span style="color:var(--accent)">· prefilled from saved company HR</span>':''}</label>
    <div style="display:flex;gap:8px">
      <input id="jd-email" class="jl-inp" style="flex:1" value="${esc(j.email || j.company_email || '')}" placeholder="hr@company.com" ${j.id?'':'disabled'}>
      <button class="btn primary sm" id="jd-email-save" ${j.id?'':'disabled'}>Save</button>
    </div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin:14px 0">
      ${j.apply_url?`<a class="btn subtle sm" href="${esc(j.apply_url)}" target="_blank" rel="noreferrer">Open portal ↗</a>`:''}
      ${j.gen?`<button class="btn ghost sm" id="jd-preview">Preview application</button>`:''}
      ${j.id?`<button class="btn ghost sm" id="jd-irrel">${j.irrelevant?'↩ Restore (relevant)':'🚫 Not relevant'}</button>`:''}
      ${j.id?`<button class="btn danger sm" id="jd-del">🗑 Delete job</button>`:''}
      ${j.id?`<button class="btn primary sm" id="jd-gen">${j.gen?'Regenerate':'Generate'}</button>`:''}
    </div>
    ${sentHistoryHtml(j)}
    <label class="fld">Job description</label>
    <div class="summary-box" style="max-height:42vh;overflow:auto;white-space:pre-wrap;background:var(--soft-bg);border:1px solid var(--line);border-radius:10px;padding:12px;font-size:13px">${esc(j.description) || '<span class="muted">No description.</span>'}</div>`;
  const save = $('jd-email-save');
  if (save) save.onclick = async () => {
    const email = $('jd-email').value.trim();
    save.disabled = true;
    try {
      await api(`/jobs/${j.id}/update`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ contact_email: email }) });
      j.email = email;
      const row = (jl.all || []).find(x => x.id === j.id); if (row) row.email = email;
      toast('Email updated.');
      if (!bulkRunning) renderJobs();                    // light, in place — never reload mid-generation
    } catch (e) { toast('Update failed: ' + e.message, true); } finally { save.disabled = false; }
  };
  const prev = $('jd-preview'); if (prev) prev.onclick = () => { if (j.folder) openLibrary(j.folder); };
  const gen = $('jd-gen'); if (gen) gen.onclick = () => { $('overlay').classList.remove('show'); genJob(j, gen); };
  const irr = $('jd-irrel'); if (irr) irr.onclick = async () => {
    const val = !j.irrelevant;
    irr.disabled = true;
    try {
      await api(`/jobs/${j.id}/irrelevant`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ irrelevant: val }) });
      j.irrelevant = val;
      toast(val ? 'Flagged not relevant — hidden from the active lists.' : 'Restored — no longer flagged.');
      $('overlay').classList.remove('show');
      loadJobs(); loadLibrary(); renderScrapedJobs();
    } catch (e) { toast('Update failed: ' + e.message, true); irr.disabled = false; }
  };
  const del = $('jd-del'); if (del) del.onclick = () => {
    $('overlay').classList.remove('show');
    deleteJobEntry({ id: j.id, title: j.title, company: j.company, folder: j.folder }, del);
  };
}
$('modal-x').onclick = () => $('overlay').classList.remove('show');
$('overlay').onclick = (e) => { if (e.target === $('overlay')) $('overlay').classList.remove('show'); };
document.addEventListener('keydown', e => { if (e.key === 'Escape') document.querySelectorAll('.overlay.show').forEach(o => o.classList.remove('show')); });

/* ---------- Theme toggle ---------- */
function applyTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  lsSet('theme', t);
  const dark = t === 'dark';
  $('theme-ic').textContent = dark ? '☀️' : '🌙';
  $('theme-lbl').textContent = dark ? 'Light mode' : 'Dark mode';
}
$('theme-toggle').onclick = () =>
  applyTheme(document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');

/* ---------- Boot ---------- */
applyTheme(lsGet('theme') || 'dark');
loadHealth(); loadModels(); loadPersonas();
// Persist the n8n test-mode toggle across reloads.
try { const t = $('n8n-test'); if (t) { t.checked = lsGet('n8n-test') === '1'; t.onchange = () => { try { lsSet('n8n-test', t.checked ? '1' : '0'); } catch {} }; } } catch {}
$('n8n-verify').onclick = (e) => verifyN8n(e.currentTarget);
showView(lsGet('view') || 'generate');   // stay on the last tab after refresh
setInterval(loadHealth, 15000);
