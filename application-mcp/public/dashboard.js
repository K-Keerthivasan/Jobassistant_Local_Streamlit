let applications = [];
let selected;
let queue = [];
let manualOpen = false;
let liveHealth = {};
let acting = 0;
let queueScope='all';let scopeLoaded=false;
const websiteKind=url=>{try{return /(^|\.)indeed\.com$/.test(new URL(url).hostname)?'indeed':'company';}catch{return 'company';}};
const inScope=url=>queueScope==='all' || websiteKind(url)===queueScope;
function renderScope(){
  for(const value of ['indeed','company','all']){
    const label=value==='indeed'?'Indeed':value==='company'?'Company websites':'All jobs';
    const count=queue.filter(j=>!/canada\s*life/i.test(j.company || '') && (value==='all' || websiteKind(j.apply_url)===value)).length;
    $(`scope-${value}`).textContent=`${label} (${count})`;$(`scope-${value}`).setAttribute('aria-pressed',String(value===queueScope));
  }
  $('scope-description').textContent=queueScope==='indeed'?'Indeed postings only. Easy Apply availability is checked when each posting opens.':queueScope==='company'?'Direct company and ATS application pages only.':'Indeed and company websites in one sequential queue.';
  $('start-queue').textContent=queueScope==='indeed'?'Run Indeed queue':queueScope==='company'?'Run company queue':'Run all jobs';
}
const terminal = a => ["submitted", "failed", "rejected"].includes(a.state);
const currentActive = () => applications.find(a => !a.deferredAt && !terminal(a));
const node = (tag, text, className) => { const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(className)e.className=className;return e; };
const statusText = a => a.cancelledAt ? "Cancelled by you" : a.manualSubmissionReportedAt && a.state!=="submitted" ? "Submitted by you · confirmation pending" : a.deferredAt ? "Saved for later" : a.state === "review" ? "Ready for approval" : a.state === "submitted" ? a.verificationSource === "user_confirmation" ? "Submitted · manually confirmed" : "Submitted · employer verified" : a.state === "paused" ? /CAPTCHA/i.test(a.reason) ? "Needs CAPTCHA" : /login|sign.in|verification/i.test(a.reason) ? "Needs sign-in" : "Needs attention" : a.state === "working" || a.state === "opening" ? "Preparing" : a.state;
const $ = (id) => document.getElementById(id);
async function api(url, body) {
  const r = await fetch(
    url,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  const v = await r.json();
  if (!r.ok) throw new Error(v.error || "Request failed");
  return v;
}
async function act(fn) {
  acting++;
  $("error").textContent = "";
  try {
    await fn();
  } catch (e) {
    $("error").textContent = e.message;
  } finally { acting--; }
}
function button(text, fn) {
  const b = document.createElement("button");
  b.textContent = text;
  b.onclick = () => act(async () => {
    b.disabled = true;
    try { await fn(); } finally { b.disabled = false; }
  });
  return b;
}
function pre(value) {
  const p = document.createElement("pre");
  p.textContent =
    typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return p;
}
async function tool(name, args = {}) {
  const r = await api("/tools/" + name, { applicationId: selected, ...args });
  await refresh();
  return r;
}
async function refresh() {
  const h = await api("/health");
  liveHealth = h;
  $("ai-answer-status").textContent=h.aiAnswersConfigured ? "Hermes configured · evidence-based written answers" : "AI unavailable · confirmed answers still fill; missing questions go to you";
  const q = await api("/queue");
  if(!scopeLoaded){queueScope=q.scope || 'all';scopeLoaded=true;}renderScope();
  $("queue-status").textContent = (q.enabled ? "Queue enabled · " : "Queue stopped · ") + q.message;
  $("auto-queue").checked = q.enabled;
  $("health").textContent = h.chromeConnected
    ? "Chrome connected" + (h.running ? " · running an application" : "")
    : h.extensionConfigured
      ? "Waiting for the Chrome extension. Open Chrome and click Connect."
      : "Load the extension in regular Chrome, copy its ID, and start the service with APP_CHROME_EXTENSION_ID.";
  applications = await api("/applications");
  const active = currentActive();
  $("queue-status").textContent = (q.enabled ? "Queue enabled" : "Queue paused") + " · " + (active ? `${active.input.company}: ${active.reason || statusText(active)}` : q.message);
  $("count-active").textContent = applications.filter(a => !a.deferredAt && !terminal(a)).length;
  $("count-pending").textContent = applications.filter(a => a.deferredAt).length;
  $("count-review").textContent = applications.filter(a => a.state === 'review').length;
  $("count-submitted").textContent = applications.filter(a => a.state === 'submitted').length;
  const pending = $("pending-questions"); pending.replaceChildren();
  const saved = applications.filter(a => a.deferredAt && inScope(a.input.jobUrl));
  $("pending-count").textContent = `${saved.length} pending`;
  for (const a of saved) {
    const card=node('article',undefined,'saved-card');card.dataset.applicationId=a.id;
    card.append(node('h3',a.input.company),node('p',a.input.title,'role'),node('span','Saved for later','badge'),node('p',a.reason || 'Ready to resume'));
    const when = new Date(a.deferredAt || a.updatedAt);
    card.append(node('p',`Saved ${when.toLocaleString()} · ${a.snapshot?.url || a.input.jobUrl}`,'checkpoint'));
    const resume=button(active && active.id!==a.id ? 'Save current & resume this' : 'Resume saved step',()=>resumeSaved(a.id));
    resume.className='primary';card.append(resume);
    const view=button('View details',async()=>{selected=a.id;await refresh();$('current').scrollIntoView({behavior:'smooth',block:'start'});});card.append(view);
    pending.append(card);
  }
  if(!saved.length) pending.append(node('p','No saved applications waiting.','empty'));
  renderApplicationList();
  const dropdown = $("applications");
  dropdown.replaceChildren();
  for (const a of applications) {
    const o = document.createElement("option");
    o.value = a.id;
    o.textContent = `${a.input.company} · ${a.input.title} · ${statusText(a)}`;
    dropdown.append(o);
  }
  if (!applications.some((a) => a.id === selected))
    selected = active?.id || applications[0]?.id;
  dropdown.value = selected || "";
  await render();
  if(queue.length) renderCandidates();
}
async function resumeSaved(id) {
  const a=applications.find(a=>a.id===id);
  if(a) $('queue-status').textContent=`Saving current progress and resuming ${a.input.company}…`;
  await api(`/applications/${id}/resume-checkpoint`,{});
  selected=id;await refresh();
}
async function cancelApplication(id) {
  await api(`/applications/${encodeURIComponent(id)}/cancel`,{});
  await refresh();
}
async function restartApplication(id){await api(`/applications/${encodeURIComponent(id)}/restart`,{userConfirmed:true});selected=id;await refresh();}
function renderApplicationList() {
  const box=$('application-list');box.replaceChildren();
  const filter=$('application-filter').value;
  const rows=applications.filter(a=>inScope(a.input.jobUrl)).filter(a => filter==='all' || filter==='active' && !terminal(a) && !a.deferredAt || filter==='pending' && !terminal(a) && a.deferredAt || filter==='submitted' && a.state==='submitted' || filter==='cancelled' && a.cancelledAt);
  const table=node('table',undefined,'application-table');
  const head=node('tr');for(const text of ['Company / job','Status','Website format','Actions'])head.append(node('th',text));
  const thead=node('thead');thead.append(head);table.append(thead);const body=node('tbody');
  for(const a of rows) {
    const row=node('tr');row.dataset.applicationId=a.id;
    const job=node('td');job.append(node('strong',a.input.company),node('p',a.input.title,'muted'));
    const actions=node('td');actions.className='row-actions';
    actions.append(button('View',async()=>{selected=a.id;await refresh();$('current').scrollIntoView({behavior:'smooth',block:'start'});}));
    if(!terminal(a) && !['submitting','uncertain'].includes(a.state)) {
      actions.append(button('Test this job only',async()=>{await api('/queue',{enabled:false});await resumeSaved(a.id);}));
      actions.append(button('Resume',()=>resumeSaved(a.id)));
      actions.append(button('Restart from original link',()=>restartApplication(a.id)));
      actions.append(button('Cancel automation',()=>cancelApplication(a.id)));
    }
    row.append(job,node('td',statusText(a)),node('td',a.formFormat || a.ats || 'Not inspected'),actions);body.append(row);
  }
  table.append(body);box.append(table);
  if(!rows.length)box.append(node('p','No applications match this status.','empty'));
}
$('application-filter').onchange=renderApplicationList;
async function render() {
  const box=$("current");box.replaceChildren();
  const a=applications.find(a=>a.id===selected);
  if(!a){box.append(node('p','Start the queue or choose a generated job below.','empty'));return;}
  const top=node('div',undefined,'card-top');top.append(node('h3',a.input.company),node('span',statusText(a),'badge'+(a.state==='submitted'?' success':'')));
  box.append(top,node('p',a.input.title,'muted'),node('p',a.reason || (liveHealth.running===a.id?'The app is preparing this application in Chrome.':'Ready to continue.'),'status-message'));
  if(a.snapshot?.url) box.append(node('p','Last observed step: '+a.snapshot.url,'checkpoint'));
  if(a.formFormat) box.append(node('p','Website format: '+a.formFormat,'checkpoint'));
  const actions=node('div',undefined,'actions');
  if(!terminal(a) && !['submitting','uncertain'].includes(a.state)){
    if(a.linkHealth==='session_expired')box.append(node('p','The saved session or link expired. Sign in in Chrome, or restart from the original job link.','status-message'));
    if(a.linkHealth==='unavailable')box.append(node('p','This opportunity is unavailable. Restart checks the original job page again; the app will not apply to a closed posting.','status-message'));
    actions.append(button('Restart from original link',()=>restartApplication(a.id)));
    box.append(node('p','Restart keeps your app record and documents, but unsaved entries on the employer site may be lost.','hint'));
  }
  if(!terminal(a) && !['submitting','uncertain'].includes(a.state)) actions.append(button('Cancel automation',()=>cancelApplication(a.id)));
  if(!terminal(a) && !['submitting','uncertain','review'].includes(a.state)) {
    const other=currentActive();
    const resume=button(a.deferredAt && other && other.id!==a.id ? 'Save current & resume this' : 'Resume saved step',()=>resumeSaved(a.id));resume.className='primary';
    resume.disabled=liveHealth.running===a.id;
    actions.append(resume);
  }
  if(liveHealth.running===a.id) actions.append(node('span','Automation running · waiting when your action is needed','muted'));
  if(!terminal(a) && !a.deferredAt) actions.append(button('Pause automation',()=>tool('stop_applications')));
  if(!terminal(a)) actions.append(button('I already submitted — verify',()=>api(`/applications/${a.id}/report-submitted`,{userReportedSubmitted:true}).then(refresh)));
  box.append(actions);
  if(!terminal(a)) {
    const manual=node('details',undefined,'manual-confirmation');
    manual.append(node('summary','Confirm submitted manually — tab closed'));
    manual.append(node('p','This records your confirmation. It does not reopen the employer site or claim the app observed a success page.','hint'));
    const label=node('label');const checked=node('input');checked.type='checkbox';
    label.append(checked,` I personally submitted ${a.input.company} — ${a.input.title}, and the employer tab is closed.`);
    const note=node('input');note.placeholder='Optional confirmation note';note.setAttribute('aria-label','Manual confirmation note');
    const confirm=button('Confirm manual submission',async()=>{
      if(!checked.checked)throw new Error('Confirm that you personally submitted this exact application.');
      await api(`/applications/${a.id}/manual-confirmation`,{userConfirmed:true,tabClosed:true,note:note.value});await refresh();
    });confirm.className='primary';confirm.disabled=true;checked.onchange=()=>confirm.disabled=!checked.checked;
    manual.append(label,note,confirm);box.append(manual);
  }
  if(!terminal(a)) box.append(node('p','Answer missing questions in the Chrome extension. CAPTCHA and login stay in the employer tab.','hint'));
  box.append(node('h4','Application documents'));
  for(const d of a.documents){const row=node('div',undefined,'document');row.append(node('strong',d.kind==='resume'?'Tailored resume':'Cover letter'),node('span',`${d.name} · ${d.attached?'Attachment verified':d.omissionReason?'Omitted by your choice':'Not attached yet'}`));box.append(row);}
  if(a.state==='submitted')box.append(node('p',a.confirmation || 'Employer confirmation verified.','status-message'));
  if(a.state==='review') {
    const review=node('div',undefined,'review-panel');review.append(node('h4','Review this exact application'));
    const table=node('table',undefined,'answer-table');
    if(a.snapshot.reviewText)review.append(node('pre',a.snapshot.reviewText,'employer-review'));
    if(a.answerDrafts?.length){
      const drafts=node('div',undefined,'ai-answers');drafts.append(node('h4','AI-written answers — check before submitting'),node('p','Drafted for this job from your tailored resume. These are not saved as confirmed reusable facts.','muted'));
      for(const d of a.answerDrafts){drafts.append(node('strong',d.question),node('p',d.answer));const evidence=node('details');evidence.append(node('summary','Resume evidence'),node('p',d.evidence.join('\n')));drafts.append(evidence);}
      review.append(drafts);
    }
    for(const f of a.snapshot?.fields || []){if(f.type==='file')continue;const row=node('tr');row.append(node('th',f.label),node('td',f.value || (f.required?'REQUIRED BLANK':'Optional · blank')));table.append(row);}
    const manualFinal=a.finalSubmitBy==='user' || a.ats==='workday';
    review.append(table,node('p',manualFinal?'Ready for your final Submit click in Chrome. Confirmation will be checked automatically.':'Submit this exact application: yes or no?','status-message'));
    const buttons=node('div',undefined,'actions');
    for(const b of a.snapshot.buttons.filter(b=>!manualFinal && !b.href && /^(submit application|submit|send application|apply now|apply)$/i.test(b.label.trim()))){
      const yes=button('Yes — submit this exact application',()=>api(`/applications/${a.id}/approval`,{reviewHash:a.reviewHash,userSaidYes:true,selector:b.selector,frameId:b.frameId}).then(refresh));yes.className='primary';buttons.append(yes);
    }
    buttons.append(button('No — keep pending',()=>tool('pause_application',{reason:'User chose No; keep pending.'})));review.append(buttons);box.append(review);
  }
  const advanced=node('details',undefined,'advanced');advanced.open=manualOpen;advanced.ontoggle=()=>manualOpen=advanced.open;advanced.append(node('summary','Details, recovery tools & history'));
  advanced.append(pre({applicationId:a.id,state:a.state,verificationSource:a.verificationSource,manuallyConfirmedAt:a.manuallyConfirmedAt,lastObservedUrl:a.snapshot?.url,updatedAt:a.updatedAt}));
  if(a.state==='submitted' && !a.synced)advanced.append(button('Sync submitted result',()=>tool('sync_application_result')));
  if(!terminal(a)){
    for(const [label,name] of [['Inspect current tab','resume_application'],['Prepare all fields and documents','prepare_application_page'],['Check exact review','review_application'],['Verify uncertain submission','verify_submission'],['Sync verified result','sync_application_result']]) advanced.append(button(label,()=>tool(name,name==='prepare_application_page'?{allowPendingCaptcha:true}:{})));
    if(!a.deferredAt) advanced.append(button('Save for later',async()=>{await api(`/applications/${a.id}/save-checkpoint`,{});await refresh();}));
    const domain=node('input');domain.placeholder='Exact employer domain';domain.setAttribute('aria-label','Exact employer domain');advanced.append(domain,button('Approve employer domain',()=>tool('approve_application_domain',{domain:domain.value,userConfirmed:true})));
    if(a.documents.some(d=>d.kind==='cover_letter'&&!d.attached&&!d.omissionReason))advanced.append(button('This portal has no cover-letter upload — omit it',()=>tool('omit_optional_cover_letter',{reason:'User confirmed this portal has no cover-letter upload.',userConfirmed:true})));
    if(a.state==='uncertain'){const reason=node('input');reason.placeholder='Observed result after checking employer';advanced.append(reason,button('Record observed failure',()=>tool('resolve_uncertain_application',{outcome:'failed',observedReason:reason.value,userConfirmed:true})));}
  }
  advanced.append(node('h4','Observed fields'),pre(a.snapshot?.fields || []));
  const history=await api(`/applications/${a.id}/history`);advanced.append(node('h4','Audit trail'),pre(history.events));
  for(const [i,e] of (a.evidence || []).entries()){const link=node('a',`View ${e.kind} screenshot · ${e.at}`);link.href=`/applications/${encodeURIComponent(a.id)}/evidence/${i}`;link.target='_blank';link.rel='noopener';const line=node('p');line.append(link);advanced.append(line);}
  box.append(advanced);
}
function renderCandidates(){
  const list=$('candidates');list.replaceChildren();
  const filter=$('job-filter').value.trim().toLowerCase();
  const eligible=queue.filter(job=>inScope(job.apply_url) && !/canada\s*life/i.test(job.company || '') && `${job.company} ${job.title}`.toLowerCase().includes(filter));
  for(const job of eligible){
    const row=node('div',undefined,'job-row');const info=node('div');info.append(node('h3',job.company),node('p',job.title));row.append(info);
    const existing=applications.find(a=>a.input.jobUrl===job.apply_url || a.input.company===job.company && a.input.title===job.title);
    if(existing){
      const btn=button(terminal(existing)?statusText(existing):existing.deferredAt?'Resume saved step':'View current application',async()=>{if(existing.deferredAt)await resumeSaved(existing.id);else{selected=existing.id;await refresh();$('current').scrollIntoView({behavior:'smooth'});}});btn.disabled=terminal(existing);row.append(btn);
    } else {
      const start=button('Start in Chrome',async()=>{
        const packet=await api('/prepare',{job_key:job.key_id,run_id:job.run_id});
        const a=await api('/applications',{jobUrl:packet.job_url,company:packet.company,title:packet.title,studioSessionId:packet.session_id,resumePath:packet.documents.resume.path,coverLetterPath:packet.documents.cover_letter?.path || null,mode:'review'});
        selected=a.id;await api(`/applications/${a.id}/run`,{});await refresh();
      });
      start.disabled=!!currentActive();if(start.disabled)start.title='Finish or save the current application before starting another.';row.append(start);
    }
    list.append(row);
  }
  if(!eligible.length)list.append(node('p',filter?'No jobs match this filter.':'No eligible generated jobs right now. Refresh after generating resumes.','empty'));
}
async function loadQueue(){const result=await api('/candidates');queue=result.candidates || [];renderScope();renderCandidates();}
$("applications").onchange = () =>
  act(async () => {
    selected = $("applications").value;
    await render();
  });
$("refresh").onclick = () => act(refresh);
$("stop").onclick = () => act(() => tool("stop_applications"));
$("queue").onclick = () => act(loadQueue);
$("job-filter").oninput = renderCandidates;
$("save-answer").onclick = () =>
  act(() =>
    tool("update_answer_bank", {
      question: $("question").value,
      answer: $("answer").value,
      userConfirmed: true,
      reuseAllowed: true,
    }),
  );
async function loadNotifications() {
  const { barriers, settings } = await api("/notifications");
  $("notify").replaceChildren();
  for (const b of barriers) {
    const label = document.createElement("label");
    label.style.display = "block";
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = !!settings[b.id];
    box.onchange = () =>
      act(async () => {
        await api("/notifications", { [b.id]: box.checked });
      });
    label.append(box, " " + b.label);
    $("notify").append(label);
  }
}
$("notify-test").onclick = () =>
  act(async () => {
    const r = await fetch("/notifications/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    if (!r.ok)
      throw new Error(
        "Chrome is not connected. Open the extension and click Connect, then try again.",
      );
  });
// Keep the view current while a run works in the background, and, when the
// queue option is on, prepare the next job once the current one is finished.
$("start-queue").onclick = () => act(async () => {
  await api("/queue", { enabled: true, resumeActive: true,scope:queueScope });
  await refresh();
});
$("auto-queue").onchange = () => act(async () => {
  await api("/queue", { enabled: $("auto-queue").checked,scope:queueScope });
});
for(const scope of ['indeed','company','all'])$(`scope-${scope}`).onclick=()=>act(async()=>{queueScope=scope;renderScope();await refresh();renderCandidates();});
act(async () => { $("auto-queue").checked = (await api("/queue")).enabled; });
setInterval(async () => {
  if (acting || document.hidden || ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) return;
  try { await refresh(); } catch (error) { $("error").textContent = error.message; }
}, 4000);
act(refresh);
act(loadNotifications);

const savedTheme=localStorage.getItem('resumeStudioApplicationTheme') || 'system';
$('theme').value=['light','dark'].includes(savedTheme)?savedTheme:'system';
if(savedTheme!=='system')document.documentElement.dataset.theme=savedTheme;
$('theme').onchange=()=>{const theme=$('theme').value;if(theme==='system')delete document.documentElement.dataset.theme;else document.documentElement.dataset.theme=theme;localStorage.setItem('resumeStudioApplicationTheme',theme);};
act(loadQueue);


