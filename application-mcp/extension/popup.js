async function send(op) {
  const r = await chrome.runtime.sendMessage({
    op,
    applicationId: document.getElementById("application").value.trim(),
  });
  document.getElementById("status").textContent =
    r.error ||
    `Extension ID: ${r.id}\n${r.connected ? "Connected" : "Disconnected"}\nActive: ${r.session?.applicationId || "none"}`;
}
document.getElementById("connect").onclick = () => send("connect");
document.getElementById("adopt").onclick = () => send("adopt");
document.getElementById('chrome-autofill').onclick = async () => {
  const current = await chrome.runtime.sendMessage({op:'status'});
  if (current.session?.applicationId) await api(`/applications/${encodeURIComponent(current.session.applicationId)}/stop-run`,{});
  const result = await chrome.runtime.sendMessage({op:'chrome-autofill'});
  document.getElementById('autofill-status').textContent = result.error || 'Choose your saved address in Chrome (press Down if needed). Then resume the application; the app will read the filled fields and complete the remaining ones.';
};
send("status").then(checkReview);
document.getElementById("reload").onclick = async () => {
  const current = await chrome.runtime.sendMessage({ op: "status" });
  if (current.session)
    await chrome.storage.local.set({
      applicationTab: { ...current.session, savedAt: Date.now() },
    });
  chrome.runtime.reload();
};

let packet;
document.getElementById('retry-documents').onclick=async()=>{
  if(!packet)return;
  try{await api(`/applications/${encodeURIComponent(packet.id)}/retry-documents`,{userConfirmedMissing:true,includeCoverLetter:true});el('review-status').textContent='Missing document retry queued. The app will upload each missing supplied document once.';}catch(error){el('review-status').textContent=error.message;}
};
let submitting = false;
const el = id => document.getElementById(id);
async function api(route, data) {
  const response = await fetch('http://127.0.0.1:8091' + route, {
    method: data === undefined ? 'GET' : 'POST',
    ...(data === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Application service unavailable.');
  return result;
}
function render(a) {
  packet = a;
  el('review-details').replaceChildren();
  const line = text => {
    const p = document.createElement('p'); p.textContent = text;
    el('review-details').append(p);
  };
  line(`${a.input.company} — ${a.input.title}`);
  line(a.snapshot?.url || a.input.jobUrl);
  if(a.snapshot?.reviewText)line(a.snapshot.reviewText);
  for(const draft of a.answerDrafts || []){line(`AI draft · ${draft.question}: ${draft.answer}`);line(`Resume evidence: ${draft.evidence.join('; ')}`);}
  for (const f of a.snapshot?.fields || [])
    if (f.type !== 'file') line(`${f.label}: ${f.value || (f.required ? 'REQUIRED BLANK' : '(optional, blank)')}`);
  for (const doc of a.documents) line(`${doc.kind}: ${doc.name} — ${doc.attached ? 'attached' : 'NOT ATTACHED'}`);
  el('review-status').textContent = a.reason || a.state;
  el('submit-yes').disabled = submitting || a.finalSubmitBy === 'user' || a.ats === 'workday' || a.state !== 'review' || !a.reviewHash;
  el('submit-yes').textContent = a.finalSubmitBy === 'user' || a.ats === 'workday' ? 'Click final Submit yourself in Chrome' : 'Yes — submit this exact application';
  if (a.formFormat) line(`Website format: ${a.formFormat}`);
  el('submit-no').disabled = submitting || !['review', 'paused', 'working'].includes(a.state);
  el('report-submitted').disabled = submitting || a.state === 'submitted';
  el('cancel-automation').disabled = submitting || ['submitted','submitting','uncertain','failed','rejected'].includes(a.state);
  el('manual-confirmation').hidden = a.state === 'submitted';
  el('manual-confirm-label').textContent = ` I personally submitted ${a.input.company} — ${a.input.title}, and the employer tab is closed.`;
  el('manual-confirm-check').checked=false;el('manual-confirm-save').disabled=true;
}
async function checkReview() {
  if (submitting) return;
  el('submit-yes').disabled = true;
  try {
    const current = await chrome.runtime.sendMessage({ op: 'status' });
    const id = current.session?.applicationId;
    if (!id) throw new Error('No active application. Open or adopt its tab first.');
    let a = await api('/applications/' + encodeURIComponent(id));
    const health = await api('/health');
    if (health.running === id) {
      render(a);
      el('review-status').textContent = 'The app is preparing this application. Wait for its review or action request.';
      return;
    }
    if (['working', 'paused', 'review'].includes(a.state)) {
      a = await api('/tools/resume_application', { applicationId: id });
      if (a.state === 'working' && a.snapshot?.fields.length && a.snapshot.buttons.some(b => !b.href && /^(submit application|submit|send application|apply now|apply)$/i.test(b.label.trim())))
        a = await api('/tools/review_application', { applicationId: id });
    }
    render(a);
  } catch (error) { el('review-status').textContent = error.message; }
}
el('refresh-review').onclick = checkReview;
el('cancel-automation').onclick = async () => {
  if (!packet || submitting) return;
  el('cancel-automation').disabled=true;
  try {render(await api(`/applications/${encodeURIComponent(packet.id)}/cancel`,{}));await loadQuestions();}
  catch(error){el('review-status').textContent=error.message;el('cancel-automation').disabled=false;}
};
el('report-submitted').onclick = async () => {
  if (!packet || submitting) return;
  el('report-submitted').disabled=true;
  try {render(await api(`/applications/${packet.id}/report-submitted`,{userReportedSubmitted:true}));}
  catch(error){el('review-status').textContent=error.message;el('report-submitted').disabled=false;}
};
el('submit-no').onclick = async () => {
  if (!packet || submitting) return;
  try { render(await api('/tools/pause_application', { applicationId: packet.id, reason: 'User chose No in the Chrome popup; keep pending.' })); }
  catch (error) { el('review-status').textContent = error.message; }
  el('submit-yes').disabled = true;
};
el('submit-yes').onclick = async () => {
  if (submitting || packet?.state !== 'review' || !packet.reviewHash) return;
  const button = packet.snapshot.buttons.find(b => /^(submit application|submit|send application|apply now)$/i.test(b.label.trim()));
  if (!button) { el('review-status').textContent = 'No verified submit control. Refresh the review.'; return; }
  submitting = true;
  el('submit-yes').disabled = el('submit-no').disabled = true;
  el('refresh-review').disabled = true;
  el('review-status').textContent = 'Submitting once and checking the employer confirmation…';
  try {
    render(await api(`/applications/${encodeURIComponent(packet.id)}/approval`, {
      reviewHash: packet.reviewHash, userSaidYes: true, selector: button.selector, frameId: button.frameId,
    }));
  } catch (error) {
    el('review-status').textContent = error.message + ' No automatic retry. Check the application status before continuing.';
  }
};


// Questions are owned by the app and survive closing this popup or deferring a job.
let questionsBusy = false;
let educationDrafts={};let educationDraftsLoaded=false;
async function loadQuestions() {
  try {
    if(!educationDraftsLoaded){educationDrafts=(await chrome.storage.local.get('educationDrafts')).educationDrafts || {};educationDraftsLoaded=true;}
    const groups = await api('/questions');
    const requested=(await chrome.storage.session?.get('requestedQuestionApplication'))?.requestedQuestionApplication;
    const list = el('questions-list'); list.replaceChildren();
    let count = 0;
    for (const group of groups) {
      const section = document.createElement('details');section.className='question-group';
      section.open=!group.deferred || requested===group.applicationId || groups.every(g=>g.deferred) && group===groups[0];
      const heading = document.createElement('summary');
      heading.textContent = `${group.company} · ${group.title}${group.deferred ? ' · pending' : ''}`;
      section.append(heading);
      if(group.educationBatch?.length){
        const card=document.createElement('div');card.className='question-card';
        const title=document.createElement('h4');title.textContent='Education — review all dates once';card.append(title);
        const note=document.createElement('p');note.textContent='The app fills the schools and programs from this tailored resume. Confirm dates together here; it will save each completed website row and continue. These dates are saved for this application only.';card.append(note);
        const entries=[];
        for(const row of group.educationBatch){
          const heading=document.createElement('p');heading.textContent=`${row.credential} · ${row.institution} · ${row.year}${row.startTerm?' · Confirmed term: '+row.startTerm:''}`;card.append(heading);
          const inputs={index:row.index};
          for(const side of ['start','end']){
            const label=document.createElement('label');label.textContent=`${side==='start'?'Start':'End'} date${row[side==='start'?'requiredStart':'requiredEnd']?' (required)':' (optional)'}`;
            const key=`${group.applicationId}:${row.index}:${side}`;
            const input=document.createElement('input');input.type='date';input.value=educationDrafts[key] ?? row[side+'Date'] ?? '';input.setAttribute('aria-label',`${row.credential} ${side} date`);input.oninput=()=>{educationDrafts[key]=input.value;chrome.storage.local.set({educationDrafts});};inputs[side+'Date']=input;label.append(input);card.append(label);
          }
          entries.push(inputs);
        }
        const status=document.createElement('p');status.setAttribute('role','status');
        const save=document.createElement('button');save.textContent='Confirm all education dates & continue';save.disabled=group.deferred;
        save.onclick=async()=>{questionsBusy=true;save.disabled=true;try{await api('/questions/education',{applicationId:group.applicationId,userConfirmed:true,rows:entries.map(row=>({index:row.index,startDate:row.startDate.value,endDate:row.endDate.value}))});el('questions-status').textContent='All education dates saved. The app is filling and saving the entries.';await loadQuestions();}catch(error){status.textContent=error.message;}finally{questionsBusy=false;save.disabled=group.deferred;}};
        card.append(save,status);section.append(card);count+=group.educationBatch.length;
      }
      if(group.deferred){
        const resume=document.createElement('button');resume.textContent=groups.some(g=>!g.deferred)?'Save current & resume this':'Resume saved step';
        resume.onclick=async()=>{resume.disabled=true;try{await api(`/applications/${group.applicationId}/resume-checkpoint`,{});await loadQuestions();await checkReview();}catch(error){el('questions-status').textContent=error.message;resume.disabled=false;}};
        section.append(resume);
      }
      for (const q of group.questions) {
        count++;
        const card = document.createElement('div'); card.className = 'question-card';
        const title = document.createElement('p'); title.className = 'question-title'; title.textContent = q.question; card.append(title);
        if (q.manual) {
          const note = document.createElement('p'); note.textContent = 'Complete this choice personally in the employer tab. Consent and sensitive choices are never remembered.'; card.append(note);
        } else {
          const input = document.createElement(q.options.length ? 'select' : 'textarea');
          input.setAttribute('aria-label',q.question); input.className = 'answer-select';
          if (q.options.length) {
            const placeholder = document.createElement('option'); placeholder.value=''; placeholder.textContent='Choose an answer'; input.append(placeholder);
            for (const value of q.options) { const option=document.createElement('option');option.value=value;option.textContent=value;input.append(option); }
          }
          if(q.observedValue) input.value=q.observedValue;
          const reuseLabel = document.createElement('label');reuseLabel.className='reuse';
          const reuse=document.createElement('input');reuse.type='checkbox';reuse.checked=!!q.defaultReuse;
          reuseLabel.append(reuse,' Remember this answer for the same question on future applications');
          const save=document.createElement('button');save.textContent='Confirm answer';
          const learned=document.createElement('button');learned.textContent='Use what I filled in Chrome';learned.disabled=group.deferred;
          const status=document.createElement('p');status.setAttribute('role','status');
          const submit = async (fromChrome) => {
            questionsBusy=true;
            save.disabled=learned.disabled=true;
            try {
              if (!fromChrome && !input.value.trim()) throw new Error('Enter or choose your answer first.');
              await api(fromChrome ? '/questions/learn' : '/questions/answer', {
                applicationId:group.applicationId,selector:q.selector,frameId:q.frameId,
                ...(fromChrome ? {} : {answer:input.value}),reuse:reuse.checked,userConfirmed:true
              });
              el('questions-status').textContent='Answer saved. The app will continue or revisit this pending application.';
              await loadQuestions();
            } catch(error) {status.textContent=error.message;status.className='question-error';}
            finally {questionsBusy=false;save.disabled=false;learned.disabled=group.deferred;}
          };
          save.onclick=()=>submit(false);learned.onclick=()=>submit(true);
          card.append(input,reuseLabel,save,learned,status);
          const watch=document.createElement('button');watch.textContent=q.watching?'Watching for your entry in Chrome':'I’ll fill this in Chrome';watch.disabled=group.deferred || q.watching;
          watch.onclick=async()=>{questionsBusy=true;watch.disabled=true;try{await api('/questions/watch',{applicationId:group.applicationId,selector:q.selector,frameId:q.frameId,reuse:reuse.checked,userConfirmed:true});el('questions-status').textContent='Fill the employer field, then click outside it. The app will detect the completed value, save it, and continue.';await loadQuestions();}catch(error){status.textContent=error.message;watch.disabled=false;}finally{questionsBusy=false;}};
          card.append(watch);
          if(q.canLeaveBlank){
            reuse.checked=false;
            reuseLabel.lastChild.textContent=' Remember this choice for the same optional question on future applications';
            const blank=document.createElement('button');blank.textContent='Leave blank';
            blank.onclick=async()=>{questionsBusy=true;blank.disabled=true;try{await api('/questions/blank',{applicationId:group.applicationId,selector:q.selector,frameId:q.frameId,reuse:reuse.checked,userConfirmed:true});el('questions-status').textContent='Left blank by your choice. The app will not ask for this optional field again.';await loadQuestions();}catch(error){status.textContent=error.message;blank.disabled=false;}finally{questionsBusy=false;}};
            card.append(blank);
          }
        }
        section.append(card);
      }
      if (group.mayOmitCover) {
        const omit=document.createElement('button');omit.textContent='This portal has no cover-letter upload — omit it';
        omit.disabled=group.deferred;
        omit.onclick=async()=>{
          omit.disabled=true;
          try {await api('/tools/omit_optional_cover_letter',{applicationId:group.applicationId,reason:'User confirmed in extension that this portal has no cover-letter upload.',userConfirmed:true});await loadQuestions();await checkReview();}
          catch(error){el('questions-status').textContent=error.message;omit.disabled=false;}
        };
        section.append(omit);
      }
      if (!group.questions.length && group.reason) {const note=document.createElement('p');note.className='muted';note.textContent=group.reason;section.append(note);}
      list.append(section);
    }
    el('question-count').textContent=String(count);
    if (!groups.length) list.textContent='No questions waiting.';
  } catch(error) {el('questions-status').textContent=error.message;}
}
el('refresh-questions').onclick=loadQuestions;
loadQuestions();
setInterval(()=>{if(!questionsBusy && !document.hidden && !['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName)) loadQuestions();},5000);
chrome.storage.local.get('popupTheme').then(({popupTheme})=>{
  const theme=['light','dark'].includes(popupTheme)?popupTheme:'system';
  el('theme').value=theme;
  if(theme!=='system') document.documentElement.dataset.theme=theme;
});
el('theme').onchange=async()=>{
  const theme=el('theme').value;
  if(theme==='system') delete document.documentElement.dataset.theme;else document.documentElement.dataset.theme=theme;
  await chrome.storage.local.set({popupTheme:theme});
};

el('manual-confirm-check').onchange=()=>el('manual-confirm-save').disabled=!packet || !el('manual-confirm-check').checked;
el('manual-confirm-save').onclick=async()=>{
  if(!packet || submitting || !el('manual-confirm-check').checked)return;
  submitting=true;el('manual-confirm-save').disabled=true;el('submit-yes').disabled=true;
  try {render(await api(`/applications/${packet.id}/manual-confirmation`,{userConfirmed:true,tabClosed:true,note:el('manual-confirm-note').value}));await loadQuestions();}
  catch(error){el('review-status').textContent=error.message;el('manual-confirm-save').disabled=false;}
  finally{submitting=false;}
};
