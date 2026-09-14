/* Resume Studio v3.5 upgrade UI: batch import, tier badges, Outreach review screen,
   Ledger and dashboard. Loaded after the main page script; it adds its own nav
   buttons and sections so index.html changes stay small. Depends on the page's
   $, esc, api, toast, showView and lsGet/lsSet helpers. */
(function () {
  'use strict';

  /* ---------- helpers ---------- */
  const TIER_TXT = { A: 'Tier A', B: 'Tier B', C: 'Tier C' };
  window.tierBadge = function (j) {
    const g = j.grade || {};
    if (!g.tier) return j.lane_slug ? `<span class="lane-chip" title="Lane">${esc(j.lane_slug)}</span>` : '';
    const gaps = (g.gap_flags || []).join(' | ') || 'none';
    const title = `${TIER_TXT[g.tier]}: ${g.tier_reason || ''}\nGaps: ${gaps}\nFit: ${g.fit_sentence || '(no evidence-traced fit sentence)'}\nEvidence skills: ${(g.evidence_skill_ids || []).join(', ') || 'none'}`;
    const warn = (j.seniority && j.seniority.warning) ? `<span class="sen-warn" title="Seniority: ${esc(j.seniority.reason || '')}">⚠</span>` : '';
    return `<span class="tier tier-${g.tier}" title="${esc(title)}">${g.tier}</span><span class="lane-chip" title="Lane ${esc(g.lane || j.lane_slug || '')}">${esc(j.lane_slug || g.lane || '')}</span>${warn}`;
  };

  function fmtDate(s) { return (s || '').replace('T', ' ').slice(0, 16); }
  function words(s) { return (s || '').trim().split(/\s+/).filter(Boolean).length; }
  function post(path, body) { return api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) }); }

  /* ---------- nav + sections ---------- */
  function addNav(view, label, after) {
    const nav = document.querySelector('.nav');
    if (!nav || nav.querySelector(`button[data-view="${view}"]`)) return;
    const b = document.createElement('button');
    b.dataset.view = view; b.innerHTML = label; b.title = b.textContent.trim();
    const anchor = nav.querySelector(`button[data-view="${after}"]`);
    if (anchor && anchor.nextSibling) nav.insertBefore(b, anchor.nextSibling); else nav.appendChild(b);
    b.onclick = () => showView(view);
  }
  function addSection(id, html) {
    if ($(id)) return;
    const main = document.querySelector('main') || document.body;
    const s = document.createElement('section');
    s.className = 'view'; s.id = id; s.innerHTML = html;
    main.appendChild(s);
  }

  addNav('outreach', '<span class="ic">📤</span> Outreach', 'companies');
  addNav('ledger', '<span class="ic">📒</span> Ledger', 'outreach');

  addSection('view-outreach', `
    <h1 class="page-h">HR Outreach</h1>
    <p class="page-sub">The app drafts and you approve. <b>Nothing leaves without you seeing it.</b> Approved messages go to n8n, which sends through Gmail and reports back. Each follow-up step needs its own approval.</p>
    <div class="card up-state" id="or-state"></div>
    <div class="up-grid">
      <div class="card">
        <div class="sec-title">Draft a message</div>
        <label class="up-lbl">Job (graded)</label>
        <select id="or-job" class="jl-inp"></select>
        <label class="up-lbl">Contact</label>
        <select id="or-contact" class="jl-inp"></select>
        <label class="up-lbl">Template</label>
        <select id="or-template" class="jl-inp"></select>
        <label class="up-lbl">Applied on (for the follow-up template)</label>
        <input id="or-applied" class="jl-inp" type="date">
        <div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">
          <button class="btn primary sm" id="or-draft">✍️ Draft</button>
          <button class="btn ghost sm" id="or-draft-cold" title="Cold approach for a designated employer with no posting: pick a contact and a lane">Draft cold approach</button>
          <select id="or-lane" class="jl-inp" style="width:auto"></select>
        </div>
        <div class="sec-title" style="margin-top:18px">Add or correct a contact</div>
        <input id="or-c-company" class="jl-inp" placeholder="Company">
        <input id="or-c-email" class="jl-inp" placeholder="hr@company.com">
        <input id="or-c-name" class="jl-inp" placeholder="HR name (optional)">
        <button class="btn subtle sm" id="or-c-save" style="margin-top:8px">Save as verified</button>
        <div class="sec-title" style="margin-top:18px">Companies with no contact yet</div>
        <div id="or-missing" class="up-list muted"></div>
      </div>
      <div class="card">
        <div class="sec-title" style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">Review queue
          <select id="or-filter" class="jl-inp" style="width:auto">
            <option value="queued,approved">Awaiting approval + approved</option>
            <option value="queued">Awaiting approval</option>
            <option value="approved">Approved, not yet sent</option>
            <option value="sending,sent">Sent</option>
            <option value="replied">Replied</option>
            <option value="bounced,failed,cancelled">Bounced / failed / cancelled</option>
            <option value="">Everything</option>
          </select>
          <span class="up-actions">
            <button class="btn primary sm" id="or-approve" disabled>✅ Approve selected</button>
            <button class="btn subtle sm" id="or-cancel" disabled>Cancel selected</button>
            <button class="btn ghost sm" id="or-preview">🔍 Preview dispatch</button>
            <button class="btn ghost sm" id="or-dispatch-test" title="Posts to n8n with test:true; n8n pretends to send and calls back">Dispatch (test)</button>
            <button class="btn primary sm" id="or-dispatch">📤 Dispatch approved</button>
          </span>
        </div>
        <div id="or-preview-out"></div>
        <div id="or-list"><div class="empty">Loading…</div></div>
      </div>
    </div>
    <div class="up-grid" style="margin-top:14px">
      <div class="card"><div class="sec-title">Suppression list (permanent)</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap"><input id="or-sup-key" class="jl-inp" placeholder="email, @domain, or company" style="flex:1"><select id="or-sup-kind" class="jl-inp" style="width:auto"><option value="email">email</option><option value="domain">domain</option><option value="company">company</option></select><button class="btn subtle sm" id="or-sup-add">Add</button></div>
        <div id="or-sup" class="up-list"></div></div>
      <div class="card"><div class="sec-title">Audit log</div><div id="or-events" class="up-list up-mono"></div></div>
    </div>`);

  addSection('view-ledger', `
    <h1 class="page-h">Application Ledger</h1>
    <p class="page-sub">One row per imported role. The app fills tier, gaps, dates built and outreach status. You set <b>date sent</b> and <b>status</b>.</p>
    <div id="lg-dash" class="up-dash"></div>
    <div class="card" style="margin:12px 0;display:flex;gap:10px;flex-wrap:wrap;align-items:center">
      <input id="lg-q" class="jl-inp" placeholder="🔎 company, role, lane…" style="flex:1;min-width:180px">
      <select id="lg-tier" class="jl-inp" style="width:auto"><option value="">Any tier</option><option>A</option><option>B</option><option>C</option></select>
      <select id="lg-status" class="jl-inp" style="width:auto"><option value="">Any status</option></select>
      <label class="checks" style="margin:0"><input type="checkbox" id="lg-designated" style="width:auto"> Designated employers only</label>
      <button class="btn subtle sm" id="lg-refresh">↻ Refresh</button>
      <button class="btn ghost sm" id="lg-regrade" title="Re-run grading for every job against the current matrices">Regrade all</button>
    </div>
    <div class="card jl-tablewrap"><table class="jl-table" id="lg-table"><thead><tr>
      <th>Company</th><th>Role</th><th>Lane</th><th>NOC</th><th>Pathway</th><th>Tier</th><th>Gaps</th><th>Built</th><th>Sent</th><th>Status</th><th>Outreach</th><th>Last touch</th><th></th>
    </tr></thead><tbody id="lg-body"></tbody></table></div>`);

  /* ---------- batch import panel inside the Intake view ---------- */
  (function addImportPanel() {
    const scrape = $('view-scrape');
    if (!scrape || $('bi-panel')) return;
    const actions = scrape.querySelector('.sc-actions');
    const panel = document.createElement('div');
    panel.className = 'card'; panel.id = 'bi-panel'; panel.style.marginBottom = '16px';
    panel.innerHTML = `<div class="sec-title">Import a sourcing run (three CSVs per stream, twelve per day)</div>
      <p class="muted" style="margin:6px 0 10px;font-size:13px">Select every <code>jobs_import_*</code>, <code>hr_companies_*</code> and <code>fit_report_*</code> file for the day at once. Import is additive and re-importing the same day changes nothing. Every row is graded against its lane matrix on the way in.</p>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
        <button class="btn primary sm" id="bi-pick">⬆ Import day batch</button>
        <input type="file" id="bi-files" accept=".csv,text/csv" multiple style="display:none">
        <button class="btn subtle sm" id="bi-history">Past batches</button>
        <span id="bi-lanes" class="muted" style="font-size:12px"></span>
      </div>
      <div id="bi-report"></div>`;
    if (actions && actions.parentNode) actions.parentNode.insertBefore(panel, actions.nextSibling); else scrape.appendChild(panel);

    $('bi-pick').onclick = () => $('bi-files').click();
    $('bi-files').onchange = async (e) => {
      const files = Array.from(e.target.files || []);
      if (!files.length) return;
      const payload = { files: await Promise.all(files.map(f => f.text().then(csv => ({ name: f.name, csv })))) };
      $('bi-report').innerHTML = '<div class="empty"><span class="spinner dark"></span> importing…</div>';
      try {
        const rep = await post('/import/batch', payload);
        renderImportReport(rep);
        toast(`Imported: ${rep.jobs.new} new job(s), ${rep.jobs.already_known} already known.`);
        if (typeof loadJobs === 'function') loadJobs();
      } catch (err) { $('bi-report').innerHTML = ''; toast('Import failed: ' + err.message, true); }
      e.target.value = '';
    };
    $('bi-history').onclick = async () => {
      const r = await api('/import/batches');
      $('bi-report').innerHTML = `<div class="up-list" style="margin-top:10px">${(r.batches || []).map(b =>
        `<div><b>${esc(b.imported_at)}</b> · ${esc((b.streams || []).join(', '))} · ${esc((b.run_dates || []).join(', '))} · jobs ${b.jobs.new} new / ${b.jobs.already_known} known · companies ${b.companies.new} new / ${b.companies.known} known · tiers ${esc(JSON.stringify(b.jobs.tiers || {}))}</div>`).join('') || '<div class="muted">No batches yet.</div>'}</div>`;
    };
    api('/lanes/status').then(s => {
      const drift = (s.drift || []).filter(d => d.status !== 'ok');
      $('bi-lanes').innerHTML = `Instruction set <b>v${esc(s.instruction_set_version)}</b> · ${s.lanes} lanes` +
        (s.version_mismatch ? ' · <span style="color:var(--err)">lane files disagree on version</span>' : '') +
        (drift.length ? ` · <span style="color:var(--warn)">${drift.length} lane(s) drifted from markdown, run sync:lanes</span>` : '');
    }).catch(() => {});
  })();

  function renderImportReport(rep) {
    const j = rep.jobs, c = rep.companies, f = rep.fit;
    const fileErrs = rep.files.filter(x => x.errors && x.errors.length);
    $('bi-report').innerHTML = `<div class="up-report">
      <div><b>Batch ${esc(rep.batch_id)}</b> · streams ${esc(rep.streams.join(', ') || '—')} · run dates ${esc(rep.run_dates.join(', ') || '—')}</div>
      <div>Jobs: ${j.rows_in} in · <b>${j.new} new</b> · ${j.already_known} already known · ${j.deduped_within_stream} deduped in-stream · ${j.deduped_cross_stream} deduped cross-stream · ${j.rejected.length} rejected · ${j.lane_unresolved} without a lane · ${j.seniority_warnings} seniority warnings · tiers ${esc(JSON.stringify(j.tiers))}</div>
      <div>Companies: ${c.rows_in} rows · ${c.new} new · ${c.known} known · contacts ${c.contacts_new} new / ${c.contacts_upgraded} upgraded / ${c.contacts_unchanged} unchanged</div>
      <div>Fit report: ${f.rows_in} rows · ${f.joined} joined · ${f.unmatched.length} unmatched</div>
      ${fileErrs.length ? `<div class="up-bad"><b>File problems</b><ul>${fileErrs.map(x => `<li>${esc(x.name)}: ${esc(x.errors.join('; '))}</li>`).join('')}</ul></div>` : ''}
      ${j.rejected.length ? `<div class="up-bad"><b>Rejected rows</b><ul>${j.rejected.map(r => `<li>${esc(r.file)} line ${r.line}: ${esc(r.reason)}</li>`).join('')}</ul></div>` : ''}
      ${j.tag_violations.length ? `<div class="up-bad"><b>Tag violations</b><ul>${j.tag_violations.map(v => `<li>${esc(v.company)} · ${esc(v.title)} · <code>${esc(v.noc_teer)}</code>: ${esc(v.violations.join('; '))}</li>`).join('')}</ul></div>` : ''}
      ${f.unmatched.length ? `<div class="up-bad"><b>Fit rows with no job</b>: ${esc(f.unmatched.join(', '))}</div>` : ''}
    </div>`;
  }

  /* ---------- Outreach view ---------- */
  const or = { msgs: [], sel: new Set(), jobs: [], contacts: [], templates: [] };

  async function loadOutreach() {
    try {
      const [state, tpl, contacts, jobs, lanesR] = await Promise.all([
        api('/outreach/state'), api('/outreach/templates'), api('/outreach/contacts'), api('/jobs'), api('/lanes')]);
      or.templates = tpl.templates || []; or.contacts = contacts.contacts || [];
      or.jobs = (jobs.jobs || []).filter(j => j.grade && j.grade.tier && !j.irrelevant);
      renderOrState(state);
      $('or-template').innerHTML = or.templates.map(t => `<option value="${esc(t.id)}">${esc(t.name)}</option>`).join('');
      $('or-job').innerHTML = '<option value="">— pick a graded job —</option>' + or.jobs
        .sort((a, b) => (a.grade.tier || 'Z').localeCompare(b.grade.tier || 'Z') || a.company.localeCompare(b.company))
        .map(j => `<option value="${esc(j.key_id)}">${esc(j.grade.tier)} · ${esc(j.company)} · ${esc(j.title)}</option>`).join('');
      $('or-lane').innerHTML = '<option value="">lane for cold approach…</option>' + (lanesR.lanes || []).map(l => `<option value="${esc(l.slug)}">${l.lane}. ${esc(l.title)}</option>`).join('');
      renderContactSelect();
      $('or-job').onchange = renderContactSelect;
      await Promise.all([loadOrMessages(), loadOrMissing(), loadOrSuppression(), loadOrEvents()]);
    } catch (e) { toast('Outreach unavailable: ' + e.message, true); }
  }

  function renderContactSelect() {
    const jid = $('or-job').value;
    const job = or.jobs.find(j => j.key_id === jid);
    const co = job ? job.company.toLowerCase() : '';
    const list = or.contacts.filter(c => !co || (c.company || '').toLowerCase() === co || (c.company_norm || '') === co)
      .concat(co ? or.contacts.filter(c => (c.company || '').toLowerCase() !== co) : []);
    $('or-contact').innerHTML = list.map(c =>
      `<option value="${esc(c.id)}">${esc(c.company)} · ${esc(c.hr_name || '(no name)')} · ${esc(c.hr_email)} · ${esc(c.confidence)}${c.do_not_contact ? ' · DO NOT CONTACT' : ''}</option>`).join('') || '<option value="">— no contacts yet —</option>';
  }

  function renderOrState(s) {
    const box = $('or-state');
    const cfg = (s.webhook_configured ? '' : '<span class="up-bad-inline">OUTREACH_WEBHOOK_URL not set</span> ') + (s.secret_configured ? '' : '<span class="up-bad-inline">OUTREACH_SHARED_SECRET not set (callbacks refused)</span>');
    box.className = 'card up-state' + (s.kill_switch ? ' killed' : '');
    box.innerHTML = `<div><b>${s.kill_switch ? '⛔ KILL SWITCH ON: all dispatch frozen' : '● Dispatch enabled'}</b> · sent today ${s.sent_today} / cap ${s.daily_cap} · cooldown ${s.cooldown_days} days ${cfg}</div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
        <button class="btn ${s.kill_switch ? 'primary' : 'danger'} sm" id="or-kill">${s.kill_switch ? 'Turn kill switch OFF' : 'Kill switch ON'}</button>
        <label class="muted" style="font-size:12px">Daily cap <input id="or-cap" class="jl-inp" type="number" min="0" value="${s.daily_cap}" style="width:70px"></label>
        <label class="muted" style="font-size:12px">Cooldown days <input id="or-cool" class="jl-inp" type="number" min="0" value="${s.cooldown_days}" style="width:70px"></label>
        <button class="btn subtle sm" id="or-save-state">Save</button>
      </div>`;
    $('or-kill').onclick = async () => { const st = await post('/outreach/state/kill_switch', { value: s.kill_switch ? '0' : '1' }); renderOrState(st); toast(st.kill_switch ? 'Kill switch ON. Nothing will dispatch.' : 'Kill switch off.'); };
    $('or-save-state').onclick = async () => {
      let st = await post('/outreach/state/daily_cap', { value: $('or-cap').value });
      st = await post('/outreach/state/cooldown_days', { value: $('or-cool').value });
      renderOrState(st); toast('Saved.');
    };
  }

  async function loadOrMessages() {
    const r = await api('/outreach/messages?status=' + encodeURIComponent($('or-filter').value));
    or.msgs = r.messages || []; or.sel.clear(); syncOrBtns();
    const by = {};
    or.msgs.forEach(m => (by[m.company || ''] = by[m.company || ''] || []).push(m));
    const companies = Object.keys(by).sort((a, b) => a.localeCompare(b));
    $('or-list').innerHTML = companies.length ? companies.map(co => `<div class="or-co"><div class="or-co-h">${esc(co)} <span class="muted">(${by[co].length})</span></div>${by[co].map(renderMsg).join('')}</div>`).join('')
      : '<div class="empty">Nothing here. Draft a message on the left.</div>';
    $('or-list').querySelectorAll('.or-ck').forEach(cb => cb.onchange = () => { cb.checked ? or.sel.add(cb.dataset.id) : or.sel.delete(cb.dataset.id); syncOrBtns(); });
    $('or-list').querySelectorAll('[data-oract="edit"]').forEach(b => b.onclick = () => editMsg(b.dataset.id));
    $('or-list').querySelectorAll('[data-oract="toggle"]').forEach(b => b.onclick = () => { const d = $('or-body-' + b.dataset.id); d.hidden = !d.hidden; });
  }

  function renderMsg(m) {
    const canSel = m.status === 'queued' || m.status === 'approved';
    const gaps = (m.gap_flags || []).length ? (m.gap_flags || []).join(' | ') : 'none';
    return `<div class="or-msg st-${esc(m.status)}">
      <div class="or-row">
        ${canSel ? `<input type="checkbox" class="or-ck" data-id="${esc(m.id)}">` : '<span style="width:16px;display:inline-block"></span>'}
        <span class="jl-st ${esc(m.status)}">${esc(m.status)}</span>
        <b>${esc(m.subject)}</b>
        <span class="muted">→ ${esc(m.to_name || '')} &lt;${esc(m.to_email)}&gt;</span>
        <span class="conf conf-${esc(m.contact_confidence)}" title="Address confidence">${esc(m.contact_confidence || '?')}</span>
        ${m.tier ? `<span class="tier tier-${esc(m.tier)}" title="Gaps: ${esc(gaps)}">${esc(m.tier)}</span>` : ''}
        <span class="muted">step ${m.sequence_step} · ${esc(m.template_id)} · ${esc(fmtDate(m.scheduled_for))}</span>
        <span class="up-actions"><button class="btn subtle sm" data-oract="toggle" data-id="${esc(m.id)}">Read</button>${canSel ? `<button class="btn ghost sm" data-oract="edit" data-id="${esc(m.id)}">Edit</button>` : ''}</span>
      </div>
      ${m.job_title ? `<div class="muted" style="font-size:12px;margin-left:24px">Job: ${esc(m.job_title)} · lane ${esc(m.lane || '')}${m.pathway ? ' · ' + esc(m.pathway) : ''} · gaps: ${esc(gaps)}</div>` : ''}
      ${m.last_guardrail ? `<div class="up-bad-inline" style="margin-left:24px">Held back: ${esc(m.last_guardrail)}</div>` : ''}
      ${m.error ? `<div class="up-bad-inline" style="margin-left:24px">Error: ${esc(m.error)}</div>` : ''}
      ${m.approved_at ? `<div class="muted" style="font-size:12px;margin-left:24px">Approved by ${esc(m.approved_by)} at ${esc(fmtDate(m.approved_at))}${m.sent_at ? ' · handed to n8n ' + esc(fmtDate(m.sent_at)) : ''}${m.replied_at ? ' · replied ' + esc(fmtDate(m.replied_at)) : ''}${m.bounce_reason ? ' · bounce: ' + esc(m.bounce_reason) : ''}</div>` : ''}
      <pre id="or-body-${esc(m.id)}" class="or-body" hidden>${esc(m.body)}</pre>
    </div>`;
  }

  function syncOrBtns() { const n = or.sel.size; $('or-approve').disabled = !n; $('or-cancel').disabled = !n; $('or-approve').textContent = `✅ Approve selected (${n})`; }

  async function editMsg(id) {
    const m = or.msgs.find(x => x.id === id); if (!m) return;
    const subject = prompt('Subject (under 60 characters):', m.subject); if (subject === null) return;
    const body = prompt('Body (under 150 words, plain text, no dashes):', m.body); if (body === null) return;
    try { await post(`/outreach/messages/${enc(id)}/edit`, { subject, body }); toast('Saved.'); loadOrMessages(); }
    catch (e) { toast(e.message, true); }
  }

  async function loadOrMissing() {
    const r = await api('/outreach/contacts/missing');
    $('or-missing').innerHTML = (r.companies || []).slice(0, 60).map(c => `<div>${esc(c)}</div>`).join('') || '<div>Every imported company has a contact.</div>';
  }
  async function loadOrSuppression() {
    const r = await api('/outreach/suppression');
    $('or-sup').innerHTML = (r.suppression || []).map(s => `<div><code>${esc(s.key)}</code> <span class="muted">${esc(s.kind)} · ${esc(s.reason || '')} · ${esc(fmtDate(s.added_at))}</span> <button class="btn subtle sm" data-unsup="${esc(s.key)}">remove</button></div>`).join('') || '<div class="muted">Empty.</div>';
    $('or-sup').querySelectorAll('[data-unsup]').forEach(b => b.onclick = async () => { await api('/outreach/suppression/' + encodeURIComponent(b.dataset.unsup), { method: 'DELETE' }); loadOrSuppression(); });
  }
  async function loadOrEvents() {
    const r = await api('/outreach/events?limit=80');
    $('or-events').innerHTML = (r.events || []).map(e => `<div>${esc(fmtDate(e.at))} <b>${esc(e.kind)}</b> ${esc(e.actor)} ${e.message_id ? '· ' + esc(e.message_id.slice(0, 8)) : ''} ${esc(JSON.stringify(e.data || {}).slice(0, 140))}</div>`).join('') || '<div class="muted">No events yet.</div>';
  }

  function wireOutreach() {
    $('or-filter').onchange = loadOrMessages;
    $('or-draft').onclick = async () => {
      const job_key = $('or-job').value, contact_id = $('or-contact').value, template_id = $('or-template').value;
      if (!contact_id) return toast('Pick a contact.', true);
      if (!job_key && template_id !== 'cold-approach-pathway') return toast('Pick a graded job (or use the cold approach with a lane).', true);
      try {
        const r = await post('/outreach/draft', { job_key, contact_id, template_id, applied_on: $('or-applied').value || '' });
        toast(`Drafted ${r.messages.length} message(s). Read and approve them.`); loadOrMessages(); loadOrEvents();
      } catch (e) { toast(e.message, true); }
    };
    $('or-draft-cold').onclick = async () => {
      const contact_id = $('or-contact').value, lane = $('or-lane').value;
      if (!contact_id || !lane) return toast('Pick a contact and a lane.', true);
      try { const r = await post('/outreach/draft', { contact_id, template_id: 'cold-approach-pathway', lane }); toast(`Drafted ${r.messages.length}.`); loadOrMessages(); }
      catch (e) { toast(e.message, true); }
    };
    $('or-approve').onclick = async () => {
      const ids = Array.from(or.sel); if (!ids.length) return;
      if (!confirm(`Approve ${ids.length} message(s)? Approval is what makes a message eligible to be sent.`)) return;
      const r = await post('/outreach/approve', { ids }); toast(`Approved ${r.approved.length}.`); loadOrMessages(); loadOrEvents();
    };
    $('or-cancel').onclick = async () => { const ids = Array.from(or.sel); if (!ids.length) return; await post('/outreach/cancel', { ids }); toast('Cancelled.'); loadOrMessages(); };
    $('or-preview').onclick = async () => {
      const r = await post('/outreach/preview', {});
      $('or-preview-out').innerHTML = `<div class="up-report"><b>Dispatch preview</b>${(r.preview || []).map(p => `<div>${p.ok ? '✅' : '⛔'} ${esc(p.company)} → ${esc(p.to)} ${p.ok ? 'would send' : esc([...(p.blocked || []), ...(p.deferred || [])].join('; '))}</div>`).join('') || '<div class="muted">No approved messages.</div>'}</div>`;
    };
    const doDispatch = async (test) => {
      if (!test && !confirm('Dispatch every approved, unblocked message to n8n now?')) return;
      try {
        const r = await post('/outreach/dispatch?test=' + (test ? 'true' : 'false'), {});
        const msg = `${r.sent.length} handed to n8n · ${r.blocked.length} blocked · ${r.deferred.length} deferred` + (r.error ? ' · ' + r.error : '');
        toast(msg, !!r.error);
        $('or-preview-out').innerHTML = `<div class="up-report"><b>Dispatch result${test ? ' (test)' : ''}</b><div>${esc(msg)}</div>${r.blocked.map(b => `<div>⛔ ${esc(b.company)}: ${esc(b.reasons.join('; '))}</div>`).join('')}${r.deferred.map(b => `<div>⏳ ${esc(b.company)}: ${esc(b.reasons.join('; '))}</div>`).join('')}</div>`;
        loadOrMessages(); loadOrEvents(); api('/outreach/state').then(renderOrState);
      } catch (e) { toast(e.message, true); }
    };
    $('or-dispatch').onclick = () => doDispatch(false);
    $('or-dispatch-test').onclick = () => doDispatch(true);
    $('or-c-save').onclick = async () => {
      const company = $('or-c-company').value.trim(), hr_email = $('or-c-email').value.trim(), hr_name = $('or-c-name').value.trim();
      if (!company || !hr_email.includes('@')) return toast('Company and a valid email are required.', true);
      await post('/outreach/contacts', { company, hr_email, hr_name, confidence: 'verified' });
      toast('Contact saved as verified.'); loadOutreach();
    };
    $('or-sup-add').onclick = async () => {
      const key = $('or-sup-key').value.trim(); if (!key) return;
      await post('/outreach/suppression', { key, kind: $('or-sup-kind').value, reason: 'added in review' }); $('or-sup-key').value = ''; loadOrSuppression();
    };
  }

  /* ---------- Ledger view ---------- */
  const lg = { rows: [], statuses: [] };
  async function loadLedger() {
    try {
      const [r, d] = await Promise.all([api('/ledger'), api('/dashboard')]);
      lg.rows = r.rows || []; lg.statuses = r.statuses || [];
      $('lg-status').innerHTML = '<option value="">Any status</option>' + lg.statuses.map(s => `<option>${s}</option>`).join('');
      renderDash(d); renderLedger();
    } catch (e) { toast('Ledger unavailable: ' + e.message, true); }
  }
  function kv(obj) { return Object.entries(obj || {}).map(([k, v]) => `<span class="up-kv"><b>${esc(k)}</b> ${typeof v === 'object' ? esc(JSON.stringify(v)) : esc(String(v))}</span>`).join(' ') || '<span class="muted">none</span>'; }
  function renderDash(d) {
    const rate = (o) => Object.entries(o || {}).map(([k, v]) => `<span class="up-kv"><b>${esc(k)}</b> ${v.replied}/${v.sent} (${Math.round(v.reply_rate * 100)}%)</span>`).join(' ') || '<span class="muted">no sends yet</span>';
    $('lg-dash').innerHTML = `
      <div class="card up-tile"><div class="sec-title">This week</div><div class="up-big">${d.applications_this_week}</div><div class="muted">applications sent</div><div>by lane: ${kv(d.by_lane_this_week)}</div><div>by pathway: ${kv(d.by_pathway_this_week)}</div></div>
      <div class="card up-tile"><div class="sec-title">Tier mix</div><div>${kv(d.tier_mix)}</div><div class="muted" style="margin-top:6px">${d.totals.rows} rows · ${d.totals.graded} graded · ${d.totals.seniority_warnings} seniority warnings</div></div>
      <div class="card up-tile"><div class="sec-title">Reply rate</div><div>by template: ${rate(d.reply_rate_by_template)}</div><div style="margin-top:6px">by address confidence: ${rate(d.reply_rate_by_confidence)}</div><div class="muted" style="margin-top:6px">outreach: ${d.outreach.queued} awaiting approval · ${d.outreach.approved} approved · ${d.outreach.sent_today}/${d.outreach.daily_cap} today${d.outreach.kill_switch ? ' · <b style="color:var(--err)">KILL SWITCH ON</b>' : ''}</div></div>
      <div class="card up-tile"><div class="sec-title">Days since last touch (live applications)</div>${(d.days_since_last_touch || []).slice(0, 8).map(x => `<div>${esc(x.company)} · ${esc(x.role_title)} · ${esc(x.status)} · <b>${x.days}d</b></div>`).join('') || '<div class="muted">none live</div>'}</div>
      <div class="card up-tile up-hot"><div class="sec-title">Designated-employer rows sitting untouched</div>${(d.designated_untouched || []).slice(0, 10).map(x => `<div>${x.tier ? `<span class="tier tier-${esc(x.tier)}">${esc(x.tier)}</span>` : ''} ${esc(x.company)} · ${esc(x.role_title)} · ${esc(x.pathway)}${x.hr_email ? ' · ' + esc(x.hr_email) : ' · <i>no contact</i>'}</div>`).join('') || '<div class="muted">none, or all touched</div>'}</div>`;
  }
  function renderLedger() {
    const q = $('lg-q').value.trim().toLowerCase(), tier = $('lg-tier').value, st = $('lg-status').value, des = $('lg-designated').checked;
    const rows = lg.rows.filter(r => (!q || [r.company, r.role_title, r.lane, r.pathway_tag].join(' ').toLowerCase().includes(q)) && (!tier || r.tier === tier) && (!st || r.status === st) && (!des || ['AIP', 'RCIP'].includes(r.pathway_type)));
    $('lg-body').innerHTML = rows.map((r, i) => `<tr>
      <td><b>${esc(r.company)}</b>${r.stream ? `<div class="muted" style="font-size:11px">${esc(r.stream)} · ${esc(r.run_date)}</div>` : ''}</td>
      <td>${esc(r.role_title)}${r.seniority_warning ? ' <span class="sen-warn" title="Seniority warning">⚠</span>' : ''}</td>
      <td><span class="lane-chip">${esc(r.lane || '—')}</span></td>
      <td class="muted">${esc(r.noc_code || '')}${r.teer != null ? ` / T${r.teer}` : ''}</td>
      <td class="muted">${esc(r.pathway_tag || (r.remote_type || ''))}${r.hire_type ? ' · ' + esc(r.hire_type) : ''}</td>
      <td>${r.tier ? `<span class="tier tier-${esc(r.tier)}">${esc(r.tier)}</span>` : '<span class="muted">—</span>'}</td>
      <td class="muted" style="max-width:220px;font-size:12px">${esc(r.gap_flags || '')}</td>
      <td class="muted">${esc(r.date_built || '')}</td>
      <td><input type="date" class="jl-inp lg-sent" data-i="${i}" value="${esc(r.date_sent || '')}" style="width:140px"></td>
      <td><select class="jl-inp lg-st" data-i="${i}" style="width:auto">${lg.statuses.map(s => `<option ${s === r.status ? 'selected' : ''}>${s}</option>`).join('')}</select></td>
      <td class="muted">${esc(r.outreach_status || '—')}${r.outreach_count ? ` (${r.outreach_count})` : ''}</td>
      <td class="muted">${esc(r.last_touch || '')}${r.days_since_last_touch != null ? ` <span class="muted">(${r.days_since_last_touch}d)</span>` : ''}</td>
      <td>${r.apply_url ? `<a class="btn subtle sm" href="${esc(r.apply_url)}" target="_blank" rel="noreferrer">Open ↗</a>` : ''}</td>
    </tr>`).join('') || '<tr><td colspan="13" class="empty">No rows match. Import a batch first.</td></tr>';
    const save = async (i, patch) => { const r = rows[i]; try { await post(`/ledger/${enc(r.key_id)}`, patch); toast('Saved.'); } catch (e) { toast(e.message, true); } };
    $('lg-body').querySelectorAll('.lg-sent').forEach(el => el.onchange = () => save(+el.dataset.i, { date_sent: el.value }));
    $('lg-body').querySelectorAll('.lg-st').forEach(el => el.onchange = () => save(+el.dataset.i, { status: el.value }));
  }
  function wireLedger() {
    ['lg-q', 'lg-tier', 'lg-status', 'lg-designated'].forEach(id => { const el = $(id); el.oninput = renderLedger; el.onchange = renderLedger; });
    $('lg-refresh').onclick = loadLedger;
    $('lg-regrade').onclick = async () => { const r = await post('/jobs/regrade', {}); toast('Regraded: ' + JSON.stringify(r)); loadLedger(); if (typeof loadJobs === 'function') loadJobs(); };
  }

  /* ---------- hook into the page router ---------- */
  wireOutreach(); wireLedger();
  const _showView = window.showView;
  window.showView = function (view) {
    _showView(view);
    if (view === 'outreach') loadOutreach();
    if (view === 'ledger') loadLedger();
  };
  const remembered = (typeof lsGet === 'function' && lsGet('view')) || '';
  if (remembered === 'outreach' || remembered === 'ledger') window.showView(remembered);
})();
