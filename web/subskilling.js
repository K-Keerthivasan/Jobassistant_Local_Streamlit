/* Read-only job audit; skill confirmations are separate explicit writes. */
(()=>{
 const nav=document.querySelector('.nav'), main=document.querySelector('main');
 const button=document.createElement('button');button.dataset.view='subskilling';button.textContent='Skill subskilling';nav.append(button);
 const section=document.createElement('section');section.className='view';section.id='view-subskilling';main.append(section);
 section.innerHTML=`<h1 class="page-h">Skill subskilling</h1><p class="page-sub">Audit every saved job against your profile and existing resume. Existing resumes stay unchanged. “Not evidenced” means unconfirmed, not necessarily a skill you lack.</p><div class="card"><button id="ss-start" class="btn primary">Start / resume audit</button> <button id="ss-pause" class="btn subtle">Pause after current job</button> <button id="ss-retry" class="btn subtle">Retry unresolved</button><p id="ss-progress" role="status"></p><p id="ss-error"></p></div><div class="card"><h2>Permanent skill library</h2><p>Learning skills are excluded from resume claims. Confirm only skills you can demonstrate.</p><input id="ss-name" class="jl-inp" placeholder="Skill"><select id="ss-state" class="jl-inp"><option value="learning">Learning</option><option value="not_yet">Not yet</option><option value="confirmed">Confirmed skill</option></select><textarea id="ss-evidence" class="jl-inp" placeholder="Evidence: project, work example, or course outcome"></textarea><label><input id="ss-confirm" type="checkbox"> I confirm I can demonstrate this skill</label><button id="ss-save" class="btn primary">Save skill</button><div id="ss-library"></div></div><div class="card"><h2>Repeated gaps</h2><div id="ss-summary"></div></div><input id="ss-filter" class="jl-inp" placeholder="Filter company, role, or skill"><div id="ss-jobs"></div>`;
 let data;
 const post=(url,body)=>api(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 function render(){
  if(!data)return;
  $('ss-progress').textContent=Object.entries(data.counts).map(([k,v])=>`${v} ${k}`).join(' · ')+(data.enabled?' · Audit enabled':' · Paused');
  $('ss-library').innerHTML=data.skills.map(s=>`<p><b>${esc(s.name)}</b> · ${esc(s.status)} — ${esc(s.evidence)}</p>`).join('');
  const counts=new Map();for(const job of data.jobs)for(const g of job.data.gaps||[])if(g.category!=='matched'){const key=g.skill.toLowerCase();counts.set(key,(counts.get(key)||0)+1);}
  $('ss-summary').innerHTML=[...counts].sort((a,b)=>b[1]-a[1]).slice(0,30).map(([s,n])=>`<p>${esc(s)} · ${n} jobs</p>`).join('')||'Results will appear as jobs are audited.';
  const query=$('ss-filter').value.toLowerCase();
  $('ss-jobs').innerHTML=data.jobs.filter(j=>JSON.stringify(j).toLowerCase().includes(query)).map(j=>`<details class="card"><summary>${esc(j.company)} · ${esc(j.title)} — ${esc(j.status)}</summary><p>${esc(j.data.error||j.data.fit_explanation||'Waiting for audit')}</p>${j.data.source_url?`<p>Source: ${esc(j.data.source_url)} · ${esc(j.data.retrieval)}</p>`:''}${(j.data.gaps||[]).map(g=>`<div class="card"><b>${esc(g.skill)}</b> · ${esc(g.category)}<p>Job requirement: ${esc(g.requirement_quote)}</p><p>${esc(g.explanation)}</p><p>Candidate evidence: ${esc(g.candidate_evidence||'Not found in saved evidence')}</p><p>Next step: ${esc(g.next_step)}</p></div>`).join('')}</details>`).join('');
 }
 async function refresh(){try{data=await api('/subskilling');render();$('ss-error').textContent='';}catch(e){$('ss-error').textContent=e.message;}}
 button.onclick=()=>{showView('subskilling');refresh();};
 for(const action of ['start','pause','retry'])$('ss-'+action).onclick=async()=>{try{await post('/subskilling/control',{action});await refresh();}catch(e){$('ss-error').textContent=e.message;}};
 $('ss-filter').oninput=render;
 $('ss-save').onclick=async()=>{try{await post('/subskilling/skills',{name:$('ss-name').value,status:$('ss-state').value,evidence:$('ss-evidence').value,user_confirmed:$('ss-confirm').checked});await refresh();$('ss-name').value='';$('ss-evidence').value='';$('ss-confirm').checked=false;}catch(e){$('ss-error').textContent=e.message;}};
 setInterval(()=>{if(section.classList.contains('active')&&!section.contains(document.activeElement))refresh();},5000);
})();
