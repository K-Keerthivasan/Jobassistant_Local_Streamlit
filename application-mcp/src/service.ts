import { randomUUID, createHash } from "node:crypto";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { ApplyInput, Snapshot, type Application } from "./schema.js";
import {
  detectAts,
  isNavLabel,
  pickFinal,
  pickNav,
  plan,
  reviewProblems,
} from "./adapters.js";
import { digest, documentInfo, safeUrl, sensitive, chromeDocumentPath } from "./security.js";
import { Store } from "./store.js";
import type { Browser } from "./bridge.js";
import { Studio } from "./studio.js";
import { adviseNavigation } from "./advisor.js";
import { draftAnswer, narrativeQuestion } from './answers.js';

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const DONE = [
  "review",
  "submitting",
  "uncertain",
  "submitted",
  "failed",
  "rejected",
];
// How long a run waits for you at one barrier before giving up the wait.
const WAIT_MINUTES = 30;
const missingTab=(error:unknown)=>/^(?:No matching application tab\.|No tab with id:\s*\d+\.?$)/i.test(error instanceof Error?error.message:String(error));

export class Service {
  private fieldIssues=new Map<string,Map<string,string>>();
  private answerAttempts=new Set<string>();
  busy = false;
  stopped = false;
  /** Application id the auto-run is driving, if any. */
  running?: string;
  runCancel = false;
  waitMs = 4000;
  queueAdvancing = false;
  queueMessage = "Waiting for queue driver.";
  profileFor(a: Application, profile: Record<string, any>) {
    const scoped = profile.applicationAnswers?.[a.input.studioSessionId] || {};
    const aliases:Record<string,unknown>={};
    for(const field of a.snapshot?.fields || []){const key=this.historyMemoryKey(a,field);if(key && profile.commonAnswers?.[key])aliases[field.label]=profile.commonAnswers[key];}
    return {...profile, blankAnswers:{...profile.blankAnswers,...profile.applicationBlankAnswers?.[a.input.studioSessionId]}, commonAnswers: {...aliases,...scoped, ...Object.fromEntries(Object.entries(profile.commonAnswers || {}).filter(([key]) => !(key in scoped)))}};
  }
  private annotateHistory(snapshot:Snapshot){
    if(detectAts(snapshot.url)!=='dayforce')return snapshot;
    const keys:Record<string,string>={degreeName:'credential',majorName:'credential',schoolName:'institution',title:'role',companyName:'company',description:'bullets',effectiveStart:'startDate',effectiveEnd:'endDate'};
    for(const field of snapshot.fields){
      if(field.type==='file'){
        if(/(?:^|_)files_resume$/i.test(field.label))field.label='Resume';
        else if(/(?:^|_)files_coverLetter$/i.test(field.label))field.label='Cover Letter';
      }
      if(field.history)continue;
      const match=field.selector.match(/_(educationHistory|workHistory)_(\d+)_(\w+)$/);
      if(!match)continue;
      field.history={section:match[1]==='educationHistory'?'education':'experience',index:Number(match[2]),key:keys[match[3]] || match[3],orderedBlankRow:true};
      field.label=`${field.history.section==='education'?'Education':'Work experience'} ${field.history.index+1} · ${field.label}`;
    }
    return snapshot;
  }
  private historyMemoryKey(a:Application,field:import('./schema.js').Field){
    if(!field.history)return undefined;
    const peers=a.snapshot?.fields.filter(f=>f.history?.section===field.history!.section && f.history.index===field.history!.index) || [];
    const name=peers.find(f=>f.history?.key===(field.history!.section==='experience'?'company':'institution'))?.value;
    const role=peers.find(f=>f.history?.key===(field.history!.section==='experience'?'role':'credential'))?.value;
    return name && role?`${field.history.section==='experience'?'Employer':'Education'} ${name.trim()} / ${role.trim()} · ${field.label.split('·').pop()!.trim()}`:undefined;
  }
  private leavesBlank(field: import('./schema.js').Field, profile:Record<string,any>) {
    const names:Record<string,string>={'middle name':'middleName','home phone':'homePhone','home telephone':'homePhone','home number':'homePhone','home phone number':'homePhone'};
    const fact=names[field.label.replace(/\*/g,'').trim().toLowerCase()];
    const confirmedAbsent=fact && profile[fact]==='' && profile.factProvenance?.[fact]?.source==='user_confirmed';
    const label=field.label.split('·').pop()!.trim();
    const omit=(profile.omitGpa===true && /^(?:g\.?p\.?a\.?|grade point average)$/i.test(label)) || (profile.omitOptionalSupervisor===true && /^supervisor(?: name)?$/i.test(label));
    return !field.required && !field.invalid && !field.value && !field.files.length && (omit || profile.blankAnswers?.[field.label]===true || !!confirmedAbsent) && !sensitive(field.label) && !['checkbox','file'].includes(field.type);
  }
  async leaveBlank(id:string,selector:string,frameId:number,reuse=false){
    const a=this.store.get(id);
    if(!['working','paused','review'].includes(a.state))throw new Error('This application is not accepting changes.');
    const field=a.snapshot?.fields.find(f=>f.selector===selector && f.frameId===frameId);
    if(!field || field.required || field.invalid || field.value || field.files.length || sensitive(field.label) || ['checkbox','file','search'].includes(field.type))throw new Error('Only an empty optional field can be left blank. Required or invalid fields still need attention.');
    const result=await this.studio.request('/application-engine/blank-answer',{question:field.label,session_id:a.input.studioSessionId,confirmed:true,reuse:field.history?false:reuse});
    if(!result.saved)throw new Error('Could not save the blank choice.');
    const current=this.store.get(id);for(const watch of current.manualWatches || [])if(watch.label===field.label)watch.saved=true;
    if(!current.deferredAt && /^Fill .* in Chrome,/.test(current.reason)){current.state='working';current.reason='';}this.store.save(current);
    this.store.event(id,'optional_field_left_blank',{question:field.label,reuse});
    return {saved:true};
  }
  private async educationBatch(a:Application, profile:Record<string,any>) {
    const dates=a.snapshot?.fields.filter(f=>f.history?.section==='education' && /^(start|end)Date$/.test(f.history.key)) || [];
    if(!dates.length)return [];
    const history=await this.studio.request('/application-engine/'+encodeURIComponent(a.input.studioSessionId)+'/resume-history');
    const scoped=this.profileFor(a,profile);
    return (history.education || []).map((row:any,index:number)=>{
      const start=dates.find(f=>f.history!.index===index && f.history!.key==='startDate');
      const end=dates.find(f=>f.history!.index===index && f.history!.key==='endDate');
      const fact=profile.educationHistory?.find((r:any)=>r.institution===row.institution && r.credential===row.credential);
      return {index,institution:row.institution,credential:row.credential,year:row.year || '',startTerm:fact?.startTerm || '',
        startDate:scoped.commonAnswers?.[`Education ${index+1} · Start Date`] || start?.value || (/^\d{4}-\d{2}-\d{2}$/.test(row.start || '')?row.start:''),
        endDate:scoped.commonAnswers?.[`Education ${index+1} · End Date`] || end?.value || (/^\d{4}-\d{2}-\d{2}$/.test(row.end || '')?row.end:''),
        requiredStart:dates.some(f=>f.history!.key==='startDate' && f.required),requiredEnd:dates.some(f=>f.history!.key==='endDate' && f.required)};
    });
  }
  async confirmEducationBatch(id:string, rows:{index:number,startDate:string,endDate:string}[]) {
    const a=this.store.get(id);
    if(!['paused','working','review'].includes(a.state))throw new Error('This application is not accepting education answers.');
    const profile=JSON.parse(await readFile(path.join(this.root,'data/apply_profile.json'),'utf8'));
    const expected=await this.educationBatch(a,profile);
    if(!expected.length || rows.length!==expected.length || new Set(rows.map(r=>r.index)).size!==expected.length)throw new Error('Review every resume education entry together.');
    for(const row of rows){
      const source=expected.find((r:any)=>r.index===row.index);
      if(!source)throw new Error('Unknown education entry.');
      for(const side of ['start','end'] as const){
        const value=row[`${side}Date`];
        if(!value && source[side==='start'?'requiredStart':'requiredEnd'])throw new Error(`Education ${row.index+1}: ${side} date is required.`);
        if(value && (!/^\d{4}-\d{2}-\d{2}$/.test(value) || !Number.isFinite(Date.parse(value)) || new Date(value).toISOString().slice(0,10)!==value))throw new Error('Enter a valid exact date.');
      }
      if(row.startDate && row.endDate && row.startDate>row.endDate)throw new Error('Education end date must follow its start date.');
    }
    for(const row of rows)for(const side of ['start','end'] as const){
      const value=row[`${side}Date`];if(!value)continue;
      const saved=await this.studio.request('/application-engine/answers',{question:`Education ${row.index+1} · ${side==='start'?'Start':'End'} Date`,answer:value,confirmed:true,reuse:false,session_id:a.input.studioSessionId});
      if(!saved.saved)throw new Error('An education answer could not be saved.');
    }
    this.store.event(id,'education_batch_confirmed',{entries:rows.length});
    const current=this.store.get(id);current.educationBatchSourceHash=digest(expected.map((r:any)=>[r.institution,r.credential,r.year]));current.state='working';current.reason='Applying your confirmed education dates.';current.reviewHash=undefined;current.approvedHash=undefined;this.store.save(current);
    if(!this.running)this.startRun(id);
    return {saved:true,entries:rows.length};
  }
  async questions() {
    const profile = JSON.parse(await readFile(path.join(this.root, "data/apply_profile.json"), "utf8"));
    return Promise.all(this.store.list().filter(a => !["submitted", "failed", "rejected", "uncertain", "submitting"].includes(a.state)).map(async a => {
      const fields = a.snapshot?this.annotateHistory(a.snapshot).fields:[];
      if((this.running===a.id || this.busy && !a.deferredAt) && a.preparationStage!=='needs_user')return {applicationId:a.id,company:a.input.company,title:a.input.title,deferred:!!a.deferredAt,questions:[],mayOmitCover:false,preparingKnown:true,reason:a.preparationStage==='uploading'?'Uploading available application documents…':'Filling known answers from your profile and tailored resume…'};
      const localProfile: Record<string, any> = this.profileFor(a, profile);
      if (fields.some(f => f.history)) {
        try { localProfile.tailoredResume = await this.studio.request('/application-engine/' + encodeURIComponent(a.input.studioSessionId) + '/resume-history'); } catch { /* Missing source stays unanswered. */ }
      }
      const planned = plan(fields, localProfile, [], {title:a.input.title});
      const questions = fields.filter(f => ((!f.value && !f.files.length && (f.required || !sensitive(f.label) && f.type !== "checkbox")) ||
        (!!f.value && !sensitive(f.label) && !/^(?:link to this job|language|search)/i.test(f.label)) || f.invalid) && !["file","search"].includes(f.type) &&
        !this.leavesBlank(f,localProfile) && (!a.answerDrafts?.some(d=>d.question===f.label && d.answer===f.value) || f.invalid) && (!planned.find(p => p.field === f)?.value || f.invalid || this.fieldIssues.get(a.id)?.has(f.label))).map(f => ({selector:f.selector, frameId:f.frameId, question:f.label,
          options:f.options, observedValue:f.value, manual:sensitive(f.label) || f.type === "checkbox",
          watching:!!a.manualWatches?.some(w=>!w.saved && w.label===f.label && w.frameId===f.frameId),
          canLeaveBlank:!f.required && !f.invalid && !f.value && !sensitive(f.label) && !['checkbox','file','search'].includes(f.type),
          defaultReuse:!f.history && !sensitive(f.label) && !/\b(?:why|salary|pay|compensation|date|available|this (?:role|job|position|company))\b/i.test(f.label)}));
      let educationBatch=await this.educationBatch(a,profile).catch(()=>[]);
      if(a.educationBatchSourceHash===digest(educationBatch.map((r:any)=>[r.institution,r.credential,r.year])))educationBatch=[];
      return {applicationId:a.id, company:a.input.company, title:a.input.title, reason:a.reason, deferred:!!a.deferredAt,
        educationBatch,questions:questions.filter(q=>!educationBatch.length || !/^Education \d+ · (?:Start|End) Date$/.test(q.question)), mayOmitCover:(a.state==='review' || /cover.?letter|Document not attached|upload/i.test(a.reason)) && a.documents.some(d => d.kind === "cover_letter" && !d.attached && !d.omissionReason)};
    })).then(groups => groups.filter(a => a.questions.length || a.reason || a.mayOmitCover));
  }
  async confirmQuestion(id: string, selector: string, frameId: number, answer: string, reuse: boolean) {
    const a = this.store.get(id);
    if (!["paused", "working", "review"].includes(a.state)) throw new Error("This application is not accepting answers.");
    const field = a.snapshot?.fields.find(f => f.selector === selector && f.frameId === frameId);
    if (!field || sensitive(field.label) || ["checkbox", "file"].includes(field.type)) throw new Error("Complete this choice personally in Chrome.");
    const memoryQuestion=field.history && reuse?this.historyMemoryKey(a,field):undefined;
    if (field.history && !memoryQuestion) reuse = false;
    if(/supervisor/i.test(field.label) && !memoryQuestion)reuse=false;
    if (!answer.trim() || field.options.length && !field.options.includes(answer)) throw new Error("Choose an exact offered answer.");
    const result = await this.studio.request("/application-engine/answers", {question:memoryQuestion || field.label, answer:answer.trim(), confirmed:true,
      reuse, session_id:a.input.studioSessionId});
    if (!result.saved) throw new Error("The answer could not be saved.");
    this.fieldIssues.get(id)?.delete(field.label);
    const answered=this.store.get(id);for(const watch of answered.manualWatches || [])if(watch.label===field.label)watch.saved=true;
    answered.reviewHash=undefined;answered.approvedHash=undefined;
    if(!answered.deferredAt && answered.state==='paused' && !answered.snapshot?.blockers.some(b=>!/^CAPTCHA:/.test(b))){answered.state='working';answered.reason='';}this.store.save(answered);
    this.store.event(id, "answer_confirmed_in_extension", {question:field.label, reuse});
    if (!a.deferredAt && !this.running) {
      const current = await this.resume(id);
      if (!DONE.includes(current.state)) this.startRun(current.id);
    }
    return {saved:true};
  }
  async learnQuestion(id: string, selector: string, frameId: number, reuse: boolean) {
    const a = this.active(id, true);
    const previous = a.snapshot?.fields.find(f => f.selector === selector && f.frameId === frameId);
    if (!previous || sensitive(previous.label) || ["checkbox", "file"].includes(previous.type)) throw new Error("This choice cannot be remembered.");
    const current = await this.resume(id);
    const matches = current.snapshot!.fields.filter(f => f.label === previous.label && f.frameId === frameId);
    if (matches.length !== 1 || !matches[0].value || matches[0].invalid) throw new Error("Fill this exact field in Chrome first, then confirm it here.");
    return this.confirmQuestion(id, matches[0].selector, frameId, matches[0].value, reuse);
  }
  async watchManualAnswer(id:string,selector:string,frameId:number,reuse:boolean){
    const a=await this.exclusive(async()=>{
      const a=await this.inspectInternal(this.active(id,true));
      if(DONE.includes(a.state))throw new Error('This application no longer needs a manual answer.');
      if(!a.snapshot?.supportsFocus)throw new Error('Click Reload updated bridge in Chrome before enabling automatic manual-answer detection.');
      const f=a.snapshot?.fields.find(f=>f.selector===selector && f.frameId===frameId);
      if(!f || sensitive(f.label) || ['checkbox','file','search','password'].includes(f.type))throw new Error('This field cannot be learned automatically.');
      const contextKey=this.historyMemoryKey(a,f);
      const watches=(a.manualWatches ||= []);const watch={label:f.label,selector,frameId,reuse:reuse && (!f.history || !!contextKey) && (!/supervisor/i.test(f.label) || !!contextKey),baseline:f.value,contextKey,saved:false};
      const old=watches.findIndex(w=>w.label===f.label && w.frameId===frameId);if(old>=0)watches[old]=watch;else watches.push(watch);
      a.state='paused';a.reason=`Fill ${f.label} in Chrome, then leave the field. The app will detect and save your answer.`;
      a.preparationStage='needs_user';
      a.reviewHash=undefined;a.approvedHash=undefined;this.store.save(a);return a;
    });
    this.stopped=false;if(!this.running)this.startRun(a.id);return {watching:true};
  }
  private async consumeManualAnswers(a:Application,snapshot:Snapshot){
    let learned=false;a.snapshot=snapshot;
    for(const watch of a.manualWatches || []){
      if(watch.saved)continue;
      const matches=snapshot.fields.filter(f=>f.label===watch.label && f.frameId===watch.frameId);
      if(matches.length!==1)continue;const f=matches[0];
      if(watch.contextKey && this.historyMemoryKey(a,f)!==watch.contextKey)continue;
      if(!f.value.trim() || f.value===watch.baseline || f.invalid || f.focused || sensitive(f.label)) {watch.candidate=undefined;watch.seenAt=undefined;continue;}
      if(watch.candidate!==f.value){watch.candidate=f.value;watch.seenAt=Date.now();continue;}
      if(Date.now()-(watch.seenAt || Date.now())<2000)continue;
      const memory=watch.reuse?this.historyMemoryKey(a,f):undefined;
      const reuse=watch.reuse && (!f.history || !!memory);
      const result=await this.studio.request('/application-engine/answers',{question:memory || f.label,answer:f.value,confirmed:true,reuse,session_id:a.input.studioSessionId});
      if(!result.saved)continue;
      watch.saved=true;learned=true;a.reviewHash=undefined;a.approvedHash=undefined;
      this.fieldIssues.get(a.id)?.delete(f.label);
      this.store.event(a.id,'manual_answer_detected_and_saved',{question:f.label,reuse});
      if(this.store.notifySettings().learned)this.browser.notify?.({applicationId:a.id,barrier:'learned',title:'Answer saved',message:`${a.input.company}: ${f.label} saved${reuse?' for matching future questions':''}.`});
    }
    this.store.save(a);return learned;
  }
  async observeManualAnswers(){
    if(this.stopped || this.busy || this.running || this.queueAdvancing)return;
    const a=this.store.list().find(a=>!a.deferredAt && !DONE.includes(a.state) && a.manualWatches?.some(w=>!w.saved));if(!a)return;
    let proceed=false;
    await this.exclusive(async()=>{const snapshot=Snapshot.parse(await this.command(a,'scan'));await this.validateUrl(snapshot.url,a.input.allowedDomains);
      if(await this.consumeManualAnswers(a,snapshot) && !a.manualWatches?.some(w=>!w.saved)){a.state='working';a.reason='';this.store.save(a);proceed=true;}});
    if(proceed)this.startRun(a.id);
  }
  private queueRetry = new Map<string, number>();
  async driveQueue() {
    if (!this.store.queueEnabled() || this.stopped || this.busy || this.running || this.queueAdvancing) return;
    const active = this.store.list().find(a => !a.deferredAt && !["submitted", "failed", "rejected"].includes(a.state));
    if (active) {
      this.queueMessage = `${active.input.company}: ${active.reason || active.state}`;
      if (active.state === "paused" && (missingTab(active.reason) || /^(?:Open regular Chrome|Chrome disconnected|Auto-run stopped: Chrome disconnected|Service restarted;)/.test(active.reason))) {
        const recovered = await this.resume(active.id);
        if (!DONE.includes(recovered.state)) this.startRun(recovered.id);
        return;
      }
      if (active.state === "working" || (active.state === "paused" && /^(CAPTCHA:|Login or verification:)/.test(active.reason))) this.startRun(active.id);
      return;
    }
    const pending = this.store.list().filter(a => a.deferredAt && (this.store.queueScope()==='all' || (detectAts(a.input.jobUrl)==='indeed'?'indeed':'company')===this.store.queueScope()) && /Required blank:/.test(a.reason) && !a.snapshot?.blockers.length);
    if (pending.length) {
      const profile = JSON.parse(await readFile(path.join(this.root, "data/apply_profile.json"), "utf8"));
      for (const a of pending) {
        const blanks = a.snapshot!.fields.filter(f => f.required && !f.value && !f.files.length);
        if (!blanks.length || a.snapshot!.fields.some(f => f.invalid)) continue;
        const answers = plan(a.snapshot!.fields, this.profileFor(a, profile), this.store.mappings(new URL(a.snapshot!.url).hostname), {title:a.input.title});
        if (!blanks.every(f => answers.some(answer => answer.field === f && !!answer.value))) continue;
        const reopened = await this.reopenDeferred(a.id);
        this.queueMessage = `Revisiting ${a.input.company}: confirmed answers are now available.`;
        this.startRun(reopened.id);
        return;
      }
    }
    await this.continueQueue();
  }
  async continueQueue() {
    if (!this.store.queueEnabled() || this.stopped || this.busy || this.queueAdvancing) return;
    if (this.store.list().some(a => !a.deferredAt && !["submitted", "failed", "rejected"].includes(a.state))) return;
    this.queueAdvancing = true;
    try {
      const since = new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10);
      const response = await this.studio.request('/apply/candidates?limit=10000&since=' + since);
      const attempted = new Set(this.store.list().map(a => a.input.jobUrl));
      const candidates = (response.candidates || []).filter((job: any) => {
        try { return (this.queueRetry.get(job.key_id) || 0) < Date.now() &&
          job.key_id && (this.store.queueScope()==='all' || (detectAts(job.apply_url)==='indeed' ? 'indeed':'company')===this.store.queueScope()) && !/canada\s*life/i.test(job.company || '') && !attempted.has(job.apply_url) &&
          !/(^|\.)linkedin\.com$/.test(new URL(job.apply_url).hostname);
        } catch { return false; }
      });
      candidates.sort((a:any,b:any)=>Number(detectAts(b.apply_url)==='indeed')-Number(detectAts(a.apply_url)==='indeed'));
      for (const job of candidates) {
        if (!this.store.queueEnabled() || this.stopped) break;
        try {
          this.queueMessage = `Preparing ${job.company} · ${job.title}`;
          const packet = await this.studio.request('/application-engine/prepare', { job_key: job.key_id, run_id: job.run_id });
          if (packet.job_key !== job.key_id || packet.company !== job.company || packet.title !== job.title)
            throw new Error('Prepared job identity mismatch; employer was not opened.');
          const a = await this.apply({ jobUrl: packet.job_url, company: packet.company, title: packet.title,
            studioSessionId: packet.session_id, resumePath: packet.documents.resume.path,
            coverLetterPath: packet.documents.cover_letter?.path || null, mode: 'review' });
          this.startRun(a.id);
          this.store.event(a.id, 'queue_advanced', {});
          return;
        } catch (error) {
          this.queueRetry.set(job.key_id, Date.now() + 300000);
          this.queueMessage = `Could not prepare ${job.company}: ${(error as Error).message}`;
          this.store.event('queue', 'candidate_blocked', { jobKey: job.key_id, reason: (error as Error).message });
          // Never start another job if this attempt already opened a session.
          if (this.store.list().some(a => !a.deferredAt && !["submitted", "failed", "rejected"].includes(a.state))) return;
        }
      }
      this.queueMessage = 'No new eligible jobs. Checking automatically.';
    } finally { this.queueAdvancing = false; }
  }
  constructor(
    public store: Store,
    public browser: Browser,
    public studio: Studio,
    public root: string,
    public uploadRoots: string[],
    public validateUrl: typeof safeUrl = safeUrl,
  ) {}
  async exclusive<T>(action: () => Promise<T>) {
    if (this.busy) throw new Error("One application operation at a time.");
    this.busy = true;
    try {
      return await action();
    } finally {
      this.busy = false;
    }
  }
  active(id: string, allowPaused = false) {
    const a = this.store.get(id);
    if (
      this.stopped ||
      a.deferredAt ||
      ["submitted", "failed", "rejected", "submitting", "uncertain"].includes(
        a.state,
      ) ||
      (!allowPaused && a.state === "paused")
    )
      throw new Error(
        "Application requires resume or investigation before this operation.",
      );
    return a;
  }
  async command(
    a: Application,
    op: string,
    args: Record<string, unknown> = {},
  ) {
    if (this.stopped && op !== "finish")
      throw new Error("Application service is stopped. Resume explicitly.");
    try {
      return await this.browser.command(op, {
        ...args,
        applicationId: a.id,
        domains: a.input.allowedDomains,
      });
    } catch (e) {
      if (
        ![
          "submitting",
          "uncertain",
          "submitted",
          "rejected",
          "failed",
        ].includes(a.state)
      ) {
        a.state = "paused";
        a.reason = (e as Error).message;
        a.approvedHash = undefined;
        this.store.save(a);
        this.store.event(a.id, "human_required", { reason: a.reason });
      }
      throw e;
    }
  }
  /**
   * Drive one application on its own until it needs the user: follow the
   * posting's apply link, fill confirmed answers, attach the documents, click
   * Next/Continue, and stop at the submit decision. At a login, CAPTCHA or a
   * field only the user can answer it pauses (which sends a notification),
   * watches the page, and carries on by itself once the barrier is gone.
   * It never clicks a submit control.
   */
  startRun(id: string) {
    if (this.running && this.running !== id)
      throw new Error("Another application is already running.");
    if (this.running === id) return { running: id };
    const a = this.store.get(id);
    if (a.deferredAt) throw new Error("Reopen the deferred application before running it.");
    if (DONE.includes(a.state))
      throw new Error(`Nothing to run: the application is ${a.state}.`);
    this.stopped = false;
    this.running = id;
    this.runCancel = false;
    a.preparationStage='preparing';this.fieldIssues.delete(id);this.store.save(a);
    this.store.event(id, "auto_run_started", {});
    void this.runLoop(id)
      .catch((e) => {
        const cur = this.store.get(id);
        if (!DONE.includes(cur.state)) {
          cur.state = "paused";
          cur.preparationStage='needs_user';
          cur.reason = `Auto-run stopped: ${(e as Error).message}`;
          this.store.save(cur);
        }
        this.store.event(id, "auto_run_error", { error: (e as Error).message });
      })
      .finally(() => {
        if (this.running === id) this.running = undefined;
        this.store.event(id, "auto_run_ended", {});
      });
    return { running: id };
  }
  stopRun() {
    this.runCancel = true;
    return { stopping: this.running || null };
  }
  private async pauseFor(id: string, reason: string) {
    const a = this.store.get(id);
    a.state = "paused";
    a.preparationStage='needs_user';
    a.reason = reason;
    a.approvedHash = undefined;
    this.store.save(a);
    this.store.event(id, "human_required", { reason });
  }
  /** Watch the page while paused; true once the barrier is gone. */
  private async waitForUser(id: string) {
    const start = this.store.get(id);
    const key = (s?: Snapshot) =>
      s
        ? JSON.stringify([
            s.url,
            s.fields.map((f) => f.selector),
            s.buttons.map((b) => [b.selector, b.label]),
            reviewProblems(s).length,
          ])
        : "";
    const before = key(start.snapshot);
    const end = Date.now() + WAIT_MINUTES * 60_000;
    while (Date.now() < end) {
      await sleep(this.waitMs);
      if (this.runCancel || this.stopped) return false;
      const cur = this.store.get(id);
      if (cur.state !== "paused") return true; // resumed from the dashboard
      let snap: Snapshot;
      try {
        snap = Snapshot.parse(
          await this.browser.command("scan", {
            applicationId: id,
            domains: cur.input.allowedDomains,
          }),
        );
      } catch {
        continue; // still on a login or another domain: keep waiting
      }
      if (snap.confirmation) {
        await this.exclusive(async () => {
          const current = this.store.get(id);
          if (current.state === "submitted") return;
          current.state = "uncertain";
          await this.verifyInternal(current, snap);
        });
        return false;
      }
      if (snap.blockers.some(b=>!/^CAPTCHA:/.test(b))) continue;
      let manualLearned=false;
      if(cur.manualWatches?.some(w=>!w.saved)){
        manualLearned=await this.exclusive(()=>this.consumeManualAnswers(cur,snap));
        if(cur.manualWatches.some(w=>!w.saved))continue;
      }
      if(snap.blockers.length){
        const changed=key(snap)!==before;
        cur.snapshot=this.annotateHistory(snap);this.syncAttachmentReceipts(cur,snap);this.store.save(cur);
        if(changed && !cur.manualWatches?.some(w=>!w.saved)){
          cur.state='working';cur.reason='Continuing preparation after your form edits.';this.store.save(cur);return true;
        }
        if(manualLearned){cur.reason=snap.blockers.join('; ');this.store.save(cur);}continue;
      }
      if (/Document upload:/.test(start.reason)) {
        this.syncAttachmentReceipts(cur, snap);
        cur.snapshot = snap;
        this.store.save(cur);
        if (cur.documents.some(d => d.uploadAttemptedAt && !d.attached && !d.omissionReason)) continue;
      }
      const blanks = reviewProblems(snap).length;
      if (manualLearned || key(snap) !== before || (start.snapshot?.blockers.length && blanks === 0)) {
        cur.state = "working";
        cur.reason = "";
        this.store.save(cur);
        this.store.event(id, "barrier_cleared", { url: snap.url });
        return true;
      }
    }
    await this.pauseFor(
      id,
      `Waited ${WAIT_MINUTES} minutes at this step. Click Run when you are ready.`,
    );
    return false;
  }
  private async runLoop(id: string) {
    let lastNav = false;
    let preparedCaptcha = false;
    let missingNavigation = 0;
    for (let step = 0; step < 80; step++) {
      if (this.runCancel || this.stopped) return;
      let a = this.store.get(id);
      if (DONE.includes(a.state)) return;
      if(a.linkHealth==='unavailable'){
        await this.pauseFor(id,'Opportunity unavailable. The employer is no longer accepting this application. Saved for checking later.');
        await this.defer(id);return;
      }
      if (a.state === "paused") {
        if (!preparedCaptcha && this.mayPrepareWithPendingCaptcha(a, true)) {
          await this.preparePage(id, true);
          preparedCaptcha = true;
          a = this.store.get(id);
        }
        // Our own apply/next click led to the employer's application site:
        // approve that exact host once, as part of following the posting.
        const host = /New domain[^(]*\(([a-z0-9.-]+)\)/i.exec(a.reason)?.[1];
        if (host && lastNav && !a.input.allowedDomains.includes(host)) {
          const u = await this.validateUrl("https://" + host);
          a.input.allowedDomains.push(u.hostname);
          a.state = "working";
          a.reason = "";
          this.store.save(a);
          this.store.event(id, "domain_followed_from_apply", {
            domain: u.hostname,
          });
          lastNav = false;
          continue;
        }
        a=this.store.get(id);a.preparationStage='needs_user';this.store.save(a);
        if (!(await this.waitForUser(id))) return;
        continue;
      }
      a.preparationStage='preparing';this.store.save(a);
      a = await this.exclusive(() =>
        this.inspectInternal(this.active(id, true)),
      );
      if (DONE.includes(a.state)) return;
      if (a.state === "paused") {
        if (this.mayPrepareWithPendingCaptcha(a, true)) {
          await this.preparePage(id, true);
          preparedCaptcha = true;
        }
        continue;
      }
      lastNav = false;
      preparedCaptcha = false;

      try { a = await this.uploadResumeFirst(id); }
      catch (e) { await this.pauseFor(id, `Document upload: ${(e as Error).message}`); continue; }
      a.preparationStage='preparing';this.store.save(a);

      for (let pass = 0; pass < 20; pass++) {
        const before = JSON.stringify(a.snapshot?.fields.map(f => [f.selector, f.label, f.value]));
        a = await this.fill(id);
        if (a.state === "paused" || JSON.stringify(a.snapshot?.fields.map(f => [f.selector, f.label, f.value])) === before) break;
      }
      if (a.state === "paused") continue;

      a.preparationStage='uploading';this.store.save(a);
      for (const doc of a.documents.filter(
        (d) => !d.attached && !d.omissionReason && !d.uploadAttemptedAt,
      )) {
        const files = a.snapshot!.fields.filter((f) => f.type === "file");
        const field =
          files.find((f) =>
            doc.kind === "resume"
              ? /resume|résumé|\bcv\b/i.test(f.label)
              : /cover/i.test(f.label),
          ) ||
          (doc.kind === "resume" && files.length === 1 ? files[0] : undefined);
        if (!field || field.files.length) continue;
        try {
          a = await this.upload(id, doc.kind, field.selector, field.frameId);
        } catch (e) {
          if (/Document upload is not yet verified/.test((e as Error).message)) {
            this.store.event(id,'upload_verification_pending',{kind:doc.kind});
            continue;
          }
          a.preparationStage='needs_user';this.store.save(a);
          await this.pauseFor(id, `Document upload: ${(e as Error).message}`);
          break;
        }
      }
      a = this.store.get(id);
      a.preparationStage='needs_user';this.store.save(a);
      if (a.state === "paused") continue;
      const issues=[...(this.fieldIssues.get(id)?.values() || [])];
      if(issues.length){await this.pauseFor(id,`Fields need you: ${issues.join('; ')}`);continue;}

      const snapshot = a.snapshot!;
      if (pickFinal(snapshot)) {
        a = await this.review(id);
        if (a.state === "review") return; // the submit decision is yours
        if (!snapshot.blockers.length && reviewProblems(snapshot).some(p => /^Required blank:/.test(p))) {
          await this.defer(id);
          return;
        }
        continue; // review found problems and paused; wait for them
      }
      const blanks = reviewProblems(snapshot);
      if (blanks.length) {
        await this.pauseFor(id, `Fields need you: ${blanks.join("; ")}`);
        if (!snapshot.blockers.length && blanks.some(p => /^Required blank:/.test(p))) {
          await this.defer(id);
          return;
        }
        continue;
      }
      const nav = await adviseNavigation(snapshot, process.env.APP_HERMES_BASE_URL || "", fetch,
        `${this.store.get(id).input.company} · ${this.store.get(id).input.title}`);
      if (this.stopped || this.runCancel || this.store.get(id).state !== "working") return;
      if (!nav) {
        // Give client-rendered portals time to hydrate before deferring them.
        if (++missingNavigation < 3) { await sleep(1500); continue; }
        await this.pauseFor(
          id,
          "No Apply or Next control found on this page; move the application forward in Chrome.",
        );
        await this.defer(id);
        return;
      }
      missingNavigation = 0;
      if (nav.href) {
        const host = new URL(nav.href).hostname;
        if (!a.input.allowedDomains.includes(host)) {
          const u = await this.validateUrl(nav.href);
          a.input.allowedDomains.push(u.hostname);
          this.store.save(a);
          this.store.event(id, "domain_followed_from_apply", {
            domain: u.hostname,
          });
        }
      }
      await this.navigate(id, nav.selector, nav.frameId);
      lastNav = true;
      await sleep(1500);
    }
    await this.pauseFor(
      id,
      "Auto-run step limit reached; continue in Chrome or click Run.",
    );
  }
  async apply(raw: unknown) {
    return this.exclusive(async () => {
      if (this.stopped) throw new Error("Service stopped; resume explicitly.");
      const input = ApplyInput.parse(raw);
      if (input.mode === "automatic")
        throw new Error(
          "Standing automatic submission is disabled: project instructions require a fresh yes per application.",
        );
      if (
        this.store
          .list()
          .some((a) => !a.deferredAt && !["submitted", "failed", "rejected"].includes(a.state))
      )
        throw new Error("Finish or cancel the active application first.");
      const u = await this.validateUrl(input.jobUrl);
      if (/(^|\.)(indeed\.com|linkedin\.com)$/.test(u.hostname))
        throw new Error("Use the direct employer application URL.");
      input.jobUrl = u.href;
      input.allowedDomains = [
        ...new Set([u.hostname, ...input.allowedDomains]),
      ];
      for (const host of input.allowedDomains)
        await this.validateUrl("https://" + host);
      const studio = await this.studio.validate(input.studioSessionId);
      if (
        studio.status !== "prepared" ||
        studio.job_url !== input.jobUrl ||
        studio.company !== input.company ||
        studio.title !== input.title ||
        !studio.run_id
      )
        throw new Error(
          "A matching prepared Resume Studio session with generated documents is required.",
        );
      const documents = [];
      for (const [kind, file] of [
        ["resume", input.resumePath],
        ["cover_letter", input.coverLetterPath],
      ] as const) {
        if (!file) continue;
        const info = await documentInfo(file, this.uploadRoots);
        const known =
          studio.documents?.[kind]?.path &&
          path.resolve(studio.documents[kind].path) === info.path;
        if (!known)
          throw new Error(
            "Use the exact documents in the Resume Studio approval packet.",
          );
        documents.push({ kind, ...info, attached: false });
      }
      const now = new Date().toISOString();
      const a: Application = {
        id: randomUUID(),
        input,
        state: "opening",
        ats: detectAts(input.jobUrl),
        documents,
        filled: [],
        reason: "",
        createdAt: now,
        updatedAt: now,
      };
      this.store.save(a);
      this.store.event(a.id, "created", { url: input.jobUrl, ats: a.ats });
      await this.command(a, "open", { url: input.jobUrl });
      return this.inspectInternal(a);
    });
  }
  /** Preserve unanswered work without recording a false failed/rejected outcome. */
  syncRecordedResult(id: string) {
    return this.exclusive(async () => {
      const a = this.store.get(id);
      if (["submitting", "uncertain"].includes(a.state)) throw new Error("Investigate an uncertain submission first.");
      const recorded = await this.studio.get(a.input.studioSessionId);
      if (recorded.status !== "submitted" || recorded.verified_success !== true)
        throw new Error("Resume Studio has no verified successful result.");
      await this.command(a, "finish");
      a.state = "submitted";
      a.synced = true;
      a.deferredAt = undefined;
      a.reason = "Verified employer success already recorded in Resume Studio.";
      this.store.event(id, "studio_verified_result_imported", { sessionId: a.input.studioSessionId });
      return this.store.save(a);
    });
  }
  defer(id: string) {
    return this.exclusive(async () => {
      const a = this.active(id, true);
      if (a.state !== "paused") throw new Error("Only a blocked application can be deferred.");
      if (this.running === id) this.runCancel = true;
      // Release the managed tab before allowing another application to open.
      const reason = a.reason;
      try {
        await this.command(a, "finish");
      } catch (error) {
        // An extension reload can already have released this exact session.
        // Do not adopt or alter any unrelated tab to retire its backend work.
        if (!missingTab(error)) throw error;
        a.reason = reason;
      }
      a.deferredAt = new Date().toISOString();
      a.approvedHash = undefined;
      a.reviewHash = undefined;
      this.store.event(id, "deferred_for_answers", { reason: a.reason });
      return this.store.save(a);
    });
  }
  reopenDeferred(id: string) {
    return this.exclusive(async () => {
      const a = this.store.get(id);
      if (!a.deferredAt) throw new Error("Application is not deferred.");
      if (this.store.list().some(other => other.id !== id && !other.deferredAt && !["submitted", "failed", "rejected"].includes(other.state)))
        throw new Error("Finish or defer the current application first.");
      const url = a.snapshot?.url || a.input.jobUrl;
      await this.validateUrl(url, a.input.allowedDomains);
      try { await this.command(a, "recover", { url }); }
      catch (error) {
        if (!missingTab(error) && !/Unknown (?:bridge )?command|Unknown (?:browser |DOM )?operation/i.test((error as Error).message)) throw error;
        await this.command(a, "open", {url});
      }
      a.deferredAt = undefined;
      a.documents.forEach(doc => { doc.attached = false; });
      a.filled = [];
      a.approvedHash = undefined;
      a.reviewHash = undefined;
      this.store.event(id, "deferred_reopened", {url, source:"last_observed_step"});
      return this.inspectInternal(a);
    });
  }
  async resumeCheckpoint(id: string) {
    const target = this.store.get(id);
    if (["submitted", "failed", "rejected", "submitting", "uncertain"].includes(target.state))
      throw new Error("This application cannot be resumed automatically. Inspect its recorded outcome first.");
    if (this.queueAdvancing) throw new Error("The queue is preparing a job. Try again when that step finishes.");
    const other = this.store.list().find(a => a.id !== id && !a.deferredAt && !["submitted", "failed", "rejected"].includes(a.state));
    if (other && ["submitting", "uncertain"].includes(other.state)) throw new Error("Verify the current submission before switching applications.");
    this.queueAdvancing = true;
    try {
      this.runCancel = true;
      const until = Date.now() + 12000;
      while (this.running && Date.now() < until) await sleep(50);
      if (this.running || this.busy) throw new Error("The current operation is still finishing. Your progress is saved; try Resume again shortly.");
      this.stopped = false;
      if (other) {
        try { await this.exclusive(() => this.inspectInternal(this.active(other.id, true))); }
        catch { /* Preserve the last saved scan if the old tab is unavailable. */ }
        await this.pause(other.id, "Saved while switching to another application.");
        await this.defer(other.id);
      }
      const current = this.store.get(id);
      const resumed = current.deferredAt ? await this.reopenDeferred(id) : await this.resume(id);
      this.store.event(id, "resumed_from_checkpoint", {url:resumed.snapshot?.url});
      if (!DONE.includes(resumed.state)) this.startRun(id);
      this.queueMessage = `Resuming ${resumed.input.company} from its saved step.`;
      return resumed;
    } finally { this.queueAdvancing = false; }
  }
  async saveCheckpoint(id: string) {
    const a = this.active(id, true);
    if (this.queueAdvancing) throw new Error("Wait for the queue's current operation to finish.");
    this.queueAdvancing = true;
    try {
      this.runCancel = true;
      const until = Date.now() + 12000;
      while (this.running && Date.now() < until) await sleep(50);
      if (this.running || this.busy) throw new Error("The current operation is still finishing. Try Save for later shortly.");
      try { await this.exclusive(() => this.inspectInternal(this.active(a.id, true))); }
      catch { /* Retain the previous checkpoint if the tab is unavailable. */ }
      await this.pause(id, "Saved for later by user.");
      return await this.defer(id);
    } finally { this.queueAdvancing = false; }
  }
  async restartApplication(id:string){
    const target=this.store.get(id);
    if(['submitted','submitting','uncertain','failed','rejected'].includes(target.state))throw new Error('A completed or uncertain application cannot be restarted. Verify its outcome first.');
    const other=this.store.list().find(a=>a.id!==id && !a.deferredAt && !['submitted','failed','rejected'].includes(a.state));
    if(other)throw new Error('Save or finish the current application before restarting another.');
    if(this.queueAdvancing)throw new Error('Wait for the current queue operation to finish.');
    this.queueAdvancing=true;this.runCancel=true;
    try{
      const until=Date.now()+15000;while((this.busy || this.running) && Date.now()<until)await sleep(50);
      if(this.busy || this.running)throw new Error('The current operation is still stopping. Try Restart shortly.');
      this.stopped=false;
      await this.studio.validate(target.input.studioSessionId);
      await this.validateUrl(target.input.jobUrl,target.input.allowedDomains);
      let restarted=await this.exclusive(async()=>{
        const a=this.store.get(id);
        try{
          const observed=Snapshot.parse(await this.command(a,'scan'));
          if(observed.confirmation){a.state='uncertain';return this.verifyInternal(a,observed);}
        }catch(error){if(!missingTab(error))throw error;}
        // Keep a durable checkpoint and all previous evidence before resetting the page.
        this.store.event(id,'restart_from_original_link',{previousUrl:a.snapshot?.url,url:a.input.jobUrl});
        a.reviewHash=undefined;a.approvedHash=undefined;a.approvedAt=undefined;a.deferredAt=undefined;
        a.state='paused';a.reason='Restarting from the original job link.';this.store.save(a);
        try{await this.command(a,'restart',{url:a.input.jobUrl});}
        catch(error){
          if(!missingTab(error) && !/Unknown (?:bridge )?command|Unknown (?:browser |DOM )?operation/i.test((error as Error).message))throw error;
          try{await this.command(a,'finish',{closeCompleted:true});}catch(e){if(!missingTab(e))throw e;}
          await this.command(a,'open',{url:a.input.jobUrl});
        }
        a.documents.forEach(d=>{d.attached=false;d.uploadAttemptedAt=undefined;d.selector=undefined;d.frameId=undefined;});a.filled=[];a.manualWatches=[];
        return this.inspectInternal(a);
      });
      if(restarted.linkHealth==='unavailable')restarted=await this.defer(id);
      if(!restarted.snapshot?.blockers.length && !DONE.includes(restarted.state))this.startRun(id);
      this.queueMessage=restarted.state==='submitted'?'Submission was already confirmed; no restart was performed.':`Restarted ${restarted.input.company} from the original job link.`;
      return restarted;
    }finally{this.queueAdvancing=false;}
  }
  async inspectInternal(a: Application) {
    const snapshot = this.annotateHistory(Snapshot.parse(await this.command(a, "scan")));
    await this.validateUrl(snapshot.url, a.input.allowedDomains);
    if (snapshot.confirmation) {
      a.state = "uncertain";
      return this.verifyInternal(a, snapshot);
    }
    a.snapshot = snapshot;
    a.linkHealth=snapshot.blockers.some(b=>/Opportunity unavailable/i.test(b))?'unavailable':snapshot.blockers.some(b=>/Session expired/i.test(b))?'session_expired':'available';
    this.syncAttachmentReceipts(a, snapshot);
    a.ats = detectAts(snapshot.url);
    a.state = snapshot.blockers.length ? "paused" : "working";
    a.reason = snapshot.blockers.join("; ");
    const waiting=a.manualWatches?.find(w=>!w.saved && snapshot.fields.some(f=>f.label===w.label && f.frameId===w.frameId));
    if(waiting && !snapshot.blockers.length){a.state='paused';a.reason=`Fill ${waiting.label} in Chrome, then leave the field. The app will detect and save your answer.`;}
    a.reviewHash = undefined;
    a.approvedHash = undefined;
    a.ats = detectAts(snapshot.url);
    a.finalSubmitBy ||= 'user'; // New sessions require the user's final Submit click on every platform.
    // Structural signatures exclude answers, filenames and changing DOM IDs.
    // Keep every new layout instead of replacing the last layout for this host.
    if (snapshot.fields.length) {
      const fields = snapshot.fields.map(f => ({label:f.history ? `${f.history.section}.${f.history.key}` : f.label, type:f.type, required:f.required, options:f.options}));
      const shape = [...new Map(fields.map(f => [JSON.stringify(f), f])).values()].sort((a,b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
      a.formFormat = a.ats + '-' + digest(shape).slice(0,12);
      const fresh = this.store.rememberFormat(a.formFormat, {id:a.formFormat, category:a.ats, host:new URL(snapshot.url).hostname, fields:shape, observedAt:new Date().toISOString(), tested:false});
      if (fresh) this.store.event(a.id,'new_form_format_saved',{id:a.formFormat,category:a.ats});
    }
    this.store.template(new URL(snapshot.url).hostname, {
      ats: a.ats,
      fields: snapshot.fields.map(({ value, files, ...f }) => f),
      observedAt: new Date().toISOString(),
      tested: false,
    });
    this.store.event(a.id, "inspected", {
      url: snapshot.url,
      fieldCount: snapshot.fields.length,
      blockers: snapshot.blockers,
    });
    return this.store.save(a);
  }
  inspect(id: string) {
    return this.exclusive(() => this.inspectInternal(this.active(id)));
  }
  private syncAttachmentReceipts(a: Application, snapshot: Snapshot) {
    for (const doc of a.documents) {
      const receipt = snapshot.attachments.find(
        (r) => r.kind === doc.kind && r.name === doc.name,
      );
      if (receipt && !doc.attached) {
        doc.attached = true;
        doc.frameId = receipt.frameId;
        this.store.event(a.id, "document_receipt_verified", {
          kind: doc.kind,
          name: doc.name,
          hash: doc.hash,
          url: snapshot.url,
          source: "visible_upload_receipt",
        });
      }
    }
  }
  private async uploadResumeFirst(id: string, allowPendingCaptcha = false) {
    let a = await this.exclusive(() => this.inspectInternal(this.active(id, true)));
    if (a.state === 'paused' && !this.mayPrepareWithPendingCaptcha(a, allowPendingCaptcha)) return a;
    const doc = a.documents.find(d => d.kind === 'resume' && !d.attached && !d.omissionReason);
    const files = a.snapshot!.fields.filter(f => f.type === 'file');
    const field = files.find(f=>f.uploadRole==='resume') || files.find(f => f.uploadRole!=='resume_import' && /resume|résumé|\bcv\b/i.test(f.label)) || (files.length === 1 ? files[0] : undefined);
    if (!doc || !field || field.files.length || doc.uploadAttemptedAt) return a;
    a.preparationStage='uploading';this.store.save(a);
    try { a = await this.upload(id, 'resume', field.selector, field.frameId, allowPendingCaptcha); }
    catch (error) {
      if (!/Document upload is not yet verified/.test((error as Error).message)) throw error;
      this.store.event(id,'upload_verification_pending',{kind:'resume'});
      a=this.store.get(id);
    }
    // Resume parsers often replace the form asynchronously after accepting the file.
    // Re-observe until controls settle before planning any answers against them.
    let previous = '', stable = 0;
    for (let pass = 0; pass < 12; pass++) {
      await sleep(750);
      a = await this.exclusive(() => this.inspectInternal(this.active(id, true)));
      const signature = JSON.stringify(a.snapshot?.fields.map(f => [f.selector, f.label, f.value]));
      stable = signature === previous ? stable + 1 : 0;
      previous = signature;
      if (pass >= 3 && stable >= 3) break;
    }
    return a;
  }
  async preparePage(id: string, allowPendingCaptcha = false) {
    const initial=this.store.get(id);initial.preparationStage='preparing';this.store.save(initial);
    try {
    let a = await this.uploadResumeFirst(id, allowPendingCaptcha);
    a.preparationStage='preparing';this.store.save(a);
    a = await this.fill(id, allowPendingCaptcha);
    if (a.state === "submitted") return a;
    // React portals recreate control IDs after each answer. Replan from fresh
    // observations while progress is made, instead of handing known blanks back.
    for (let pass = 0; pass < 20; pass++) {
      if (a.state === "paused" && !this.mayPrepareWithPendingCaptcha(a, allowPendingCaptcha)) break;
      const before = JSON.stringify(a.snapshot?.fields.map(f => [f.selector, f.label, f.value]));
      a = await this.fill(id, allowPendingCaptcha);
      if (JSON.stringify(a.snapshot?.fields.map(f => [f.selector, f.label, f.value])) === before) break;
    }
    if (
      a.state === "paused" &&
      !this.mayPrepareWithPendingCaptcha(a, allowPendingCaptcha)
    )
      return a;
    a.preparationStage='uploading';this.store.save(a);
    for (const doc of a.documents.filter(
      (d) => !d.attached && !d.omissionReason && !d.uploadAttemptedAt,
    )) {
      const field = a.snapshot!.fields.find(
        (f) =>
          f.type === "file" &&
          (doc.kind === "resume"
            ? /^(resume|résumé|cv)\b/i.test(f.label)
            : /^cover letter\b/i.test(f.label)),
      );
      if (!field) continue;
      try { a = await this.upload(
        id,
        doc.kind,
        field.selector,
        field.frameId,
        allowPendingCaptcha,
      ); } catch (error) {
        if (!/Document upload is not yet verified/.test((error as Error).message)) throw error;
        this.store.event(id,'upload_verification_pending',{kind:doc.kind});
        a=this.store.get(id);
      }
    }
    a = await this.exclusive(() => this.inspectInternal(this.active(id, true)));
    const problems = reviewProblems(a.snapshot!);
    problems.push(...(this.fieldIssues.get(id)?.values() || []));
    for (const doc of a.documents)
      if (!doc.attached && !doc.omissionReason)
        problems.push(`Document not attached: ${doc.kind}`);
    if (problems.length) {
      a.state = "paused";
      a.reason = problems.join("; ");
      this.store.save(a);
    }
    await this.studio.snapshot(a.input.studioSessionId, {
      snapshot: a.snapshot,
      documents: a.documents,
      filled: a.filled,
      engine_id: a.id,
      review_hash: "",
    });
    this.store.event(id, "page_prepared", {
      filled: a.filled.length,
      attached: a.documents.filter((d) => d.attached).length,
      remaining: problems,
    });
    a.preparationStage='needs_user';this.store.save(a);
    if (!problems.length) return this.review(id);
    return this.store.save(a);
    }finally{const current=this.store.get(id);current.preparationStage='needs_user';this.store.save(current);}
  }
  private mayPrepareWithPendingCaptcha(a: Application, allowed: boolean) {
    return (
      allowed &&
      !!a.snapshot?.blockers.length &&
      a.snapshot.blockers.every((reason) => /^CAPTCHA:/.test(reason))
    );
  }
  async fill(id: string, allowPendingCaptcha = false) {
    return this.exclusive(async () => {
      const a = await this.inspectInternal(
        this.active(id, allowPendingCaptcha),
      );
      if (a.state === "submitted") return a;
      if (
        a.state === "paused" &&
        !this.mayPrepareWithPendingCaptcha(a, allowPendingCaptcha)
      )
        return a;
      if (this.mayPrepareWithPendingCaptcha(a, allowPendingCaptcha))
        this.store.event(id, "preparation_before_captcha_authorized", {
          operation: "fill",
        });
      const profile = JSON.parse(
        await readFile(path.join(this.root, "data/apply_profile.json"), "utf8"),
      );
      const educationAdd=a.snapshot!.buttons.find(b=>/^\+?\s*Add Education History$/i.test(b.label));
      if (a.snapshot!.fields.some(f => f.history) || educationAdd) {
        profile.tailoredResume = await this.studio.request('/application-engine/' + encodeURIComponent(a.input.studioSessionId) + '/resume-history');
      }
      const educationSection=a.snapshot!.educationSection;
      const educationRows=profile.tailoredResume?.education || [];
      const sectionText=educationSection?.text.normalize('NFKC').toLowerCase().replace(/\s+/g,' ') || '';
      const savedEducation=educationRows.map((row:any)=>!!row.institution && !!row.credential && [row.institution,row.credential].every((value:string)=>sectionText.includes(value.normalize('NFKC').toLowerCase().replace(/\s+/g,' '))));
      const nextEducation=savedEducation.indexOf(false);
      const knownPrefix=nextEducation>0 && savedEducation.slice(0,nextEducation).every(Boolean) && !savedEducation.slice(nextEducation).some(Boolean);
      if(educationAdd && educationSection && (!educationSection.hasRecords || knownPrefix) && nextEducation>=0 && !a.snapshot!.fields.some(f=>f.history?.section==='education') && educationRows[nextEducation]?.institution && educationRows[nextEducation]?.credential){
        // Append the next missing source entry only after recognizing the saved prefix.
        // Never modify existing records or guess how unknown records align.
        await this.command(a,'click',{selector:educationAdd.selector,frameId:educationAdd.frameId});
        this.store.event(id,'education_history_expanded',{source:'tailored_resume.education'});
        await sleep(300);
        return this.inspectInternal(a);
      }
      const planned = plan(
        a.snapshot!.fields,
        this.profileFor(a, profile),
        this.store.mappings(new URL(a.snapshot!.url).hostname),
        { title: a.input.title },
      );
      const currentProfile=this.profileFor(a,profile);
      for(const entry of planned)if(this.leavesBlank(entry.field,currentProfile)){entry.value=undefined;entry.reason='Optional field intentionally left blank by user';}
      const watched=(label:string)=>a.manualWatches?.some(w=>!w.saved && w.label===label);
      for(const entry of planned)if(watched(entry.field.label))entry.value=undefined;
      const unanswered=planned.filter(p=>!p.value && !watched(p.field.label) && !this.leavesBlank(p.field,currentProfile) && narrativeQuestion(p.field));
      if(unanswered.length){
        try {
          const context=await this.studio.request('/application-engine/'+encodeURIComponent(a.input.studioSessionId)+'/answer-context');
          const sourceHash=digest(context);
          for(const entry of unanswered){
            const repeated=a.snapshot!.fields.filter(f=>f.label===entry.field.label);
            if(repeated.length!==1)continue;
            const saved=a.answerDrafts?.find(d=>d.question===entry.field.label && d.sourceHash===sourceHash);
            let drafted=saved;
            const key=digest([a.id,sourceHash,entry.field.label]);
            if(!drafted && !this.answerAttempts.has(key)){
              this.answerAttempts.add(key);
              const result=await draftAnswer(entry.field,context,process.env.APP_HERMES_BASE_URL || '');
              if(result){drafted={question:entry.field.label,...result,sourceHash,createdAt:new Date().toISOString()};(a.answerDrafts ||= []).push(drafted);this.store.save(a);this.store.event(a.id,'ai_answer_drafted',{question:entry.field.label,sourceHash});}
              else this.store.event(a.id,'ai_answer_needs_user',{question:entry.field.label});
            }
            if(drafted){entry.value=drafted.answer;entry.source='AI draft from this application’s tailored resume — review required';}
          }
        }catch{this.store.event(a.id,'ai_answer_context_unavailable',{});}
      }
      for (const entry of planned) {
        if(entry.value===entry.field.value)this.fieldIssues.get(id)?.delete(entry.field.label);
        if(this.fieldIssues.get(id)?.has(entry.field.label))continue;
        const profileKey=entry.source?.match(/^apply_profile\.(\w+)$/)?.[1];
        const corrected=profileKey && profile.factProvenance?.[profileKey]?.source==='user_confirmed' && typeof profile.factProvenance[profileKey].previousValue==='string' && entry.field.value.trim().toLowerCase()===profile.factProvenance[profileKey].previousValue.trim().toLowerCase();
        const confirmedHere = corrected || Object.values(profile.answerProvenance || {}).some((p: any) =>
          p.sessionId === a.input.studioSessionId && p.originalQuestion === entry.field.label);
        if (!entry.value || entry.field.value === entry.value || (entry.field.value && !confirmedHere && !entry.source?.startsWith('tailored_resume.'))) continue;
        await this.command(a, "fill", {
          frameId: entry.field.frameId,
          selector: entry.field.selector,
          value: entry.value,
        });
        const observed = Snapshot.parse(await this.command(a, "scan"));
        const filled = observed.fields.find(
          (f) =>
            f.frameId === entry.field.frameId &&
            f.selector === entry.field.selector,
        );
        if (filled?.value !== entry.value) {
          if(!this.fieldIssues.has(id))this.fieldIssues.set(id,new Map());
          this.fieldIssues.get(id)!.set(entry.field.label,`Could not verify field: ${entry.field.label}`);
          if(observed.fields.map(f=>f.selector).join()!==a.snapshot!.fields.map(f=>f.selector).join())break;
          continue;
        }
        a.filled.push({
          label: entry.field.label,
          value: entry.value,
          source: entry.source!,
        });
        this.store.save(a);
        this.store.event(a.id, "field_filled", {
          label: entry.field.label,
          source: entry.source,
        });
        // Dynamic controls may change; stop this pass and require a fresh plan when they do.
        if (
          observed.fields.map((f) => f.selector).join() !==
          a.snapshot!.fields.map((f) => f.selector).join()
        )
          break;
      }
      const refreshed=await this.inspectInternal(a);
      const update=refreshed.snapshot!.buttons.find(b=>b.educationIndex!==undefined && /^Update$/i.test(b.label));
      if(update){
        const rowFields=refreshed.snapshot!.fields.filter(f=>f.history?.section==='education' && f.history.index===update.educationIndex);
        const source=profile.tailoredResume?.education?.[update.educationIndex!];
        const matched=source && ['institution','credential'].every(key=>rowFields.some(f=>f.history!.key===key && f.value===source[key]));
        if(matched && rowFields.length && rowFields.every(f=>!f.invalid && (!f.required || !!f.value)) && !refreshed.manualWatches?.some(w=>!w.saved)){
          await this.command(refreshed,'click',{selector:update.selector,frameId:update.frameId,educationUpdate:true});
          this.store.event(id,'education_record_saved',{index:update.educationIndex});
          return this.inspectInternal(refreshed);
        }
      }
      return refreshed;
    });
  }
  async requestMissingDocumentRetry(id:string, includeCoverLetter=false){
    const a=this.store.get(id);
    if(!['working','paused','review'].includes(a.state))throw new Error('This application cannot retry attachments.');
    this.runCancel=true;
    const until=Date.now()+12000;while(this.running && Date.now()<until)await sleep(50);
    if(this.running || this.busy)throw new Error('The current operation is still finishing.');
    if(includeCoverLetter){
      const cover=a.documents.find(d=>d.kind==='cover_letter');
      if(cover?.omissionReason){this.store.event(id,'cover_letter_omission_revoked_by_user',{});cover.omissionReason=undefined;}
    }
    a.retryMissingDocumentsRequested=true;a.state='paused';a.reason='Missing attachments reported. Reload updated bridge to use verified document bytes; the app will retry once automatically.';a.preparationStage='needs_user';this.store.save(a);
    this.store.event(id,'missing_documents_reported_by_user',{});
    await this.observeDocumentRetries();return this.store.get(id);
  }
  async observeDocumentRetries(){
    if(this.running || this.busy)return;
    const a=this.store.list().find(a=>a.retryMissingDocumentsRequested && ['working','paused'].includes(a.state));if(!a)return;
    let observed:Application;
    try{observed=await this.exclusive(()=>this.inspectInternal(this.active(a.id,true)));}catch{return;}
    if(!observed.snapshot?.supportsByteUploads){observed.reason='Reload updated bridge: missing documents will retry automatically with verified file contents.';this.store.save(observed);return;}
    for(const doc of observed.documents)if(!doc.attached && !doc.omissionReason){this.store.event(a.id,'document_retry_authorized',{kind:doc.kind,previousAttempt:doc.uploadAttemptedAt});doc.uploadAttemptedAt=undefined;}
    observed.retryMissingDocumentsRequested=false;this.store.save(observed);this.startRun(a.id);
  }
  async upload(
    id: string,
    kind: string,
    selector: string,
    frameId = 0,
    allowPendingCaptcha = false,
  ) {
    return this.exclusive(async () => {
      const a = await this.inspectInternal(
        this.active(id, allowPendingCaptcha),
      );
      if (
        a.state === "paused" &&
        !this.mayPrepareWithPendingCaptcha(a, allowPendingCaptcha)
      )
        return a;
      if (this.mayPrepareWithPendingCaptcha(a, allowPendingCaptcha))
        this.store.event(id, "preparation_before_captcha_authorized", {
          operation: "upload",
          kind,
        });
      const doc = a.documents.find((d) => d.kind === kind);
      if (!doc) throw new Error("No supplied document of this type.");
      if (doc.attached) return a;
      if (doc.uploadAttemptedAt)
        throw new Error("Document upload: a previous upload is unverified. The app will not upload another copy. Check the existing attachment in Chrome.");
      const info = await documentInfo(doc.path, this.uploadRoots);
      if (info.hash !== doc.hash)
        throw new Error("Document changed since preparation.");
      const field = a.snapshot!.fields.find(
        (f) =>
          f.selector === selector && f.frameId === frameId && f.type === "file",
      );
      if (!field) throw new Error("Choose an observed file input.");
      if (
        a.documents.some(
          (d) =>
            d.kind !== kind &&
            d.attached &&
            d.selector === selector &&
            d.frameId === frameId,
        )
      )
        throw new Error(
          "This input already contains a different application document. Choose its correct document type control.",
        );
      if (
        (kind === "resume" && /cover.?letter/i.test(field.label)) ||
        (kind === "cover_letter" && /resume|résumé|\bcv\b/i.test(field.label))
      )
        throw new Error("Document type does not match the upload label.");
      const ext = path.extname(doc.path).toLowerCase();
      const mime: Record<string, string> = {
        ".pdf": "application/pdf",
        ".doc": "application/msword",
        ".docx":
          "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".txt": "text/plain",
      };
      if (
        field.accept &&
        !field.accept
          .split(",")
          .some(
            (t) =>
              (t.trim().startsWith('.')?t.trim().toLowerCase():'.'+t.trim().toLowerCase()) === ext ||
              t.trim().toLowerCase() === mime[ext] ||
              t.trim() === "*/*",
          )
      )
        throw new Error("Document type does not match this upload input.");
      doc.uploadAttemptedAt = new Date().toISOString();
      this.store.save(a); // Persist before sending: a timeout/restart must not duplicate the upload.
      const bytes=await readFile(doc.path);
      if(createHash('sha256').update(bytes).digest('hex')!==doc.hash)throw new Error('Document changed before upload.');
      const bytePayload=a.snapshot!.supportsByteUploads && bytes.length<=5*1024*1024?{contentBase64:bytes.toString('base64'),name:doc.name,size:bytes.length,mime:mime[ext]}:{};
      await this.command(a, "upload", { selector, frameId, path: chromeDocumentPath(doc.path, this.root, process.env.APP_WINDOWS_WORKSPACE),...bytePayload });
      let snapshot: Snapshot | undefined;
      let verified = false;
      for (let attempt = 0; attempt < 40; attempt++) {
        snapshot = Snapshot.parse(await this.command(a, "scan"));
        verified =
          !!snapshot.fields
            .find((f) => f.selector === selector && f.frameId === frameId)
            ?.files.includes(doc.name) ||
          snapshot.attachments.some(
            (r) =>
              r.kind === kind && r.name === doc.name && r.frameId === frameId,
          );
        if (verified) break;
        await sleep(250);
      }
      if (!verified || !snapshot)
        throw new Error(
          "Document upload is not yet verified; inspect the page before retrying.",
        );
      doc.attached = true;
      doc.selector = selector;
      doc.frameId = frameId;
      this.store.event(a.id, "document_attached", {
        kind,
        path: doc.path,
        hash: doc.hash,
        url: snapshot.url,
        selector,
      });
      return this.inspectInternal(a);
    });
  }
  async navigate(id: string, selector: string, frameId = 0) {
    return this.exclusive(async () => {
      const a = await this.inspectInternal(this.active(id));
      if (a.state === "paused") return a;
      const button = a.snapshot!.buttons.find(
        (b) => b.selector === selector && b.frameId === frameId,
      );
      if (!button || !isNavLabel(button.label))
        throw new Error("Only an observed navigation control may be used.");
      if (button.href)
        await this.validateUrl(button.href, a.input.allowedDomains);
      await this.command(a, "click", { selector, frameId, submit: false });
      return this.inspectInternal(a);
    });
  }
  async review(id: string) {
    return this.exclusive(async () => {
      const a = await this.inspectInternal(this.active(id));
      if (a.state === "submitted") return a;
      const problems = reviewProblems(a.snapshot!);
      problems.push(...(this.fieldIssues.get(id)?.values() || []));
      if (!a.documents.find((d) => d.kind === "resume")?.attached)
        problems.push("Resume attachment has not been verified.");
      if (
        a.documents.some(
          (d) => d.kind === "cover_letter" && !d.attached && !d.omissionReason,
        )
      )
        problems.push(
          "Supplied cover letter has not been attached; attach it or explicitly omit it if the portal does not accept one.",
        );
      for (const doc of a.documents.filter((d) => d.attached)) {
        const field = a.snapshot!.fields.find(
          (f) => f.selector === doc.selector && f.frameId === doc.frameId,
        );
        if (
          field &&
          !field.files.includes(doc.name) &&
          !a.snapshot!.attachments.some(
            (r) => r.kind === doc.kind && r.name === doc.name,
          )
        )
          problems.push(`Attachment changed: ${doc.kind}`);
      }
      if (problems.length) {
        a.state = "paused";
        a.reason = problems.join("; ");
        return this.store.save(a);
      }
      a.state = "review";
      a.reason = a.finalSubmitBy === 'user' ? 'Ready for your final Submit click in Chrome. The app will watch for confirmation.' : "Submit this exact application: yes or no?";
      a.reviewHash = digest({ snapshot: a.snapshot, documents: a.documents });
      await this.studio.snapshot(a.input.studioSessionId, {
        snapshot: a.snapshot,
        documents: a.documents,
        filled: a.filled,
        engine_id: a.id,
        review_hash: a.reviewHash,
      });
      this.store.event(a.id, "review_ready", { hash: a.reviewHash });
      await this.captureInternal(a);
      return this.store.save(a);
    });
  }
  async submit(
    id: string,
    hash: string,
    yes: boolean,
    selector: string,
    frameId = 0,
  ) {
    return this.exclusive(async () => {
      const a = this.active(id);
      if (a.finalSubmitBy !== 'approved_agent' || a.ats === 'workday' || detectAts(a.snapshot?.url || a.input.jobUrl) === 'workday')
        throw new Error('Final submission must be clicked by you in Chrome.');
      if (
        !yes ||
        a.state !== "review" ||
        !a.reviewHash ||
        hash !== a.reviewHash
      )
        throw new Error("A fresh yes for this exact review is required.");
      const snapshot = Snapshot.parse(await this.command(a, "scan"));
      if (
        digest({ snapshot, documents: a.documents }) !== hash ||
        reviewProblems(snapshot).length
      )
        throw new Error("Form changed; review and approve again.");
      const button = snapshot.buttons.find(
        (b) => b.selector === selector && b.frameId === frameId,
      );
      if (
        !button ||
        !/^(submit application|submit|send application|apply now)$/i.test(
          button.label,
        )
      )
        throw new Error(
          "Choose the exact final submission control from the review.",
        );
      for (const d of a.documents)
        if ((await documentInfo(d.path, this.uploadRoots)).hash !== d.hash)
          throw new Error("Document changed; prepare again.");
      await this.studio.validate(a.input.studioSessionId);
      const decision = await this.studio.confirm(a.input.studioSessionId);
      if (!decision.may_submit || decision.already_decided)
        throw new Error(
          "Resume Studio did not issue a fresh submission authorization.",
        );
      a.approvedHash = hash;
      a.approvedAt = new Date().toISOString();
      a.state = "submitting";
      this.store.save(a);
      this.store.event(a.id, "submission_started", { hash, url: snapshot.url });
      try {
        await this.command(a, "click", { selector, frameId, submit: true });
      } catch {
        a.state = "uncertain";
        a.reason =
          "Submission may have occurred; inspect the site before any retry.";
        return this.store.save(a);
      }
      a.state = "uncertain";
      this.store.save(a);
      return this.verifyInternal(a);
    });
  }
  async verifyInternal(a: Application, observed?: Snapshot) {
    if (!["uncertain", "submitting"].includes(a.state))
      throw new Error("No submission attempt is awaiting verification.");
    const snapshot = observed || Snapshot.parse(await this.command(a, "scan"));
    a.snapshot = snapshot;
    if (!snapshot.confirmation) {
      a.state = "uncertain";
      a.reason =
        a.manualSubmissionReportedAt ? "Submitted by you; employer confirmation has not been captured. Do not reapply." :
        "No visible submission confirmation. Investigate in Chrome; do not resubmit.";
      return this.store.save(a);
    }
    a.state = "submitted";
    a.verificationSource = "employer_confirmation";
    a.confirmation = snapshot.confirmation;
    a.reason = "Visible employer confirmation verified.";
    a.snapshot = snapshot;
    this.store.save(a);
    this.store.event(a.id, "submission_verified", {
      url: snapshot.url,
      confirmation: snapshot.confirmation,
    });
    await this.captureInternal(a);
    try {
      await this.studio.result(
        a.input.studioSessionId,
        "submitted",
        `${snapshot.url}: ${snapshot.confirmation}`,
        true,
        a.finalSubmitBy === 'user' || a.manualSubmissionReportedAt ? 'me' : 'agent',
      );
      a.synced = true;
    } catch {
      a.synced = false;
      a.reason += " Resume Studio sync failed; use sync_application_result.";
    }
    try { await this.command(a, "finish", { closeCompleted: true }); }
    catch (error) { this.store.event(a.id, 'completed_tab_cleanup_pending', {reason:(error as Error).message}); }
    const saved = this.store.save(a);
    if (this.store.queueEnabled())
      setTimeout(() => { void this.continueQueue().catch(error => this.store.event('queue', 'advance_error', { reason: error.message })); }, 1500);
    return saved;
  }
  verify(id: string) {
    return this.exclusive(() => this.verifyInternal(this.store.get(id)));
  }
  async reportSubmitted(id: string) {
    if (this.running === id) this.runCancel = true;
    return this.exclusive(async () => {
      const a = this.store.get(id);
      if (a.state === "submitted") return a;
      a.state = "uncertain";
      a.manualSubmissionReportedAt = new Date().toISOString();
      a.reason = "Submitted by you; checking employer confirmation. Do not reapply.";
      a.approvedHash = undefined;
      a.reviewHash = undefined;
      this.store.save(a);
      this.store.event(id, "manual_submission_reported", {});
      const stopped = this.stopped;
      this.stopped = false;
      try { return await this.verifyInternal(a); }
      catch (error) {
        a.reason = `Submitted by you; verification unavailable: ${(error as Error).message}. Do not reapply.`;
        return this.store.save(a);
      } finally { this.stopped = stopped; }
    });
  }
  async confirmManualSubmission(id: string, note: string) {
    if (this.running === id) this.runCancel = true;
    return this.exclusive(async () => {
      const a = this.store.get(id);
      if (a.state === "submitted") return a;
      if (["submitting", "failed", "rejected"].includes(a.state)) throw new Error("Inspect the current outcome before confirming this application.");
      const now = new Date().toISOString();
      a.manualSubmissionReportedAt ||= now;
      a.manuallyConfirmedAt = now;
      a.verificationSource = "user_confirmation";
      a.state = "submitted";
      a.deferredAt = undefined;
      a.confirmation = "User personally confirmed completing and submitting this application; employer tab is closed.";
      a.reason = "Submitted — manually confirmed by you.";
      a.approvedHash = undefined;
      a.reviewHash = undefined;
      a.synced = false;
      this.store.save(a);
      this.store.event(id, "submission_manually_confirmed", {source:"user_confirmation", note, at:now});
      try {
        await this.studio.result(a.input.studioSessionId, "submitted", `${a.confirmation}${note ? " " + note : ""}`, false, "me");
        a.synced = true;
      } catch { a.reason += " Resume Studio sync pending; use Sync verified result."; }
      // This action deliberately makes no Chrome call: it must work after the
      // employer tab or the whole browser has been closed.
      return this.store.save(a);
    });
  }
  async observeCompletion() {
    if (this.stopped || this.busy || this.running || this.queueAdvancing) return;
    const a = this.store.list().find(item => !item.deferredAt && ["review", "paused", "working", "uncertain"].includes(item.state));
    if (!a) return;
    await this.exclusive(async () => {
      try {
        const snapshot = Snapshot.parse(await this.browser.command("scan", {applicationId:a.id, domains:a.input.allowedDomains}));
        await this.validateUrl(snapshot.url, a.input.allowedDomains);
        if (!snapshot.confirmation) return;
        a.state = "uncertain";
        await this.verifyInternal(a, snapshot);
      } catch { /* Observation must never reopen a tab or retry submission. */ }
    });
  }
  async captureInternal(a: Application) {
    try {
      const response = (await this.browser.command("screenshot", {
        applicationId: a.id,
        domains: a.input.allowedDomains,
      })) as { data: string };
      if (
        typeof response.data !== "string" ||
        response.data.length > 8 * 1024 * 1024
      )
        throw new Error("Screenshot unavailable or too large.");
      const bytes = Buffer.from(response.data, "base64");
      if (bytes.subarray(0, 8).toString("hex") !== "89504e470d0a1a0a")
        throw new Error("Invalid screenshot image.");
      const directory = path.join(
        this.root,
        "data/job-applications/engine/evidence",
        a.id,
      );
      await mkdir(directory, { recursive: true });
      const file = path.join(directory, Date.now() + ".png");
      await writeFile(file, bytes, { flag: "wx" });
      const evidence = {
        kind: a.state,
        path: file,
        url: a.snapshot?.url || a.input.jobUrl,
        at: new Date().toISOString(),
      };
      (a.evidence ||= []).push(evidence);
      this.store.event(a.id, "screenshot_saved", evidence);
      this.store.save(a);
    } catch {
      this.store.event(a.id, "screenshot_unavailable", {
        reason: "Page capture unavailable; structured observations retained.",
      });
    }
  }
  capture(id: string) {
    return this.exclusive(async () => {
      const a = this.active(id, true);
      if (a.snapshot?.blockers.length)
        throw new Error("Resolve login or verification before capture.");
      await this.captureInternal(a);
      return this.store.save(a);
    });
  }
  async sync(id: string) {
    return this.exclusive(async () => {
      const a = this.store.get(id);
      if (a.state !== "submitted" || !a.confirmation)
        throw new Error("No verified result to sync.");
      await this.studio.result(
        a.input.studioSessionId,
        "submitted",
        `${a.snapshot?.url}: ${a.confirmation}`,
        a.verificationSource !== "user_confirmation",
        a.verificationSource === "user_confirmation" ? "me" : "agent",
      );
      a.synced = true;
      return this.store.save(a);
    });
  }
  resolveUncertain(
    id: string,
    outcome: "failed" | "rejected",
    reason: string,
    confirmed: boolean,
  ) {
    return this.exclusive(async () => {
      const a = this.store.get(id);
      if (a.state !== "uncertain" || !confirmed || !reason.trim())
        throw new Error(
          "Inspect the employer site and explicitly confirm the observed failure before resolving uncertainty.",
        );
      await this.studio.result(
        a.input.studioSessionId,
        outcome,
        `User investigated uncertain submission: ${reason}`,
        false,
      );
      a.state = outcome;
      a.reason = reason;
      this.store.event(id, "uncertainty_resolved_by_user", { outcome, reason });
      this.store.save(a);
      await this.command(a, "finish");
      return a;
    });
  }
  pause(id: string, reason: string) {
    return this.exclusive(async () => {
      const a = this.active(id, true);
      a.state = "paused";
      a.reason = reason;
      a.approvedHash = undefined;
      this.store.event(id, "paused", { reason });
      return this.store.save(a);
    });
  }
  resume(id: string) {
    return this.exclusive(async () => {
      this.stopped = false;
      const a = this.active(id, true);
      try { return await this.inspectInternal(a); }
      catch (error) {
        if (!missingTab(error)) throw error;
        // Recover only an observed, approved employer URL. A lost tab must never
        // replay submission or keep an approval/attachment claim from another page.
        const url = a.snapshot?.url || a.input.jobUrl;
        await this.validateUrl(url, a.input.allowedDomains);
        try { await this.command(a, "recover", { url }); }
        catch (recoveryError) {
          // Older installed bridges can still reopen through their existing API.
          if (!missingTab(recoveryError) && !/Unknown (?:browser |DOM )?operation|Unknown command/i.test((recoveryError as Error).message)) throw recoveryError;
          await this.command(a, "open", { url });
        }
        a.approvedHash = undefined;
        a.approvedAt = undefined;
        a.reviewHash = undefined;
        a.documents.forEach(doc => { doc.attached = false; });
        a.filled = [];
        this.store.event(id, "application_tab_recovered", { url });
        return this.inspectInternal(a);
      }
    });
  }
  async cancel(id: string) {
    if (this.running === id) this.runCancel = true;
    const until=Date.now()+15000;
    while(this.busy && Date.now()<until) await sleep(50);
    return this.exclusive(async () => {
      const a = this.store.get(id);
      if (a.cancelledAt) return a;
      if (["submitted", "submitting", "uncertain", "failed", "rejected"].includes(a.state))
        throw new Error('This application has a recorded or uncertain outcome; cancellation cannot replace it.');
      const wasActive = !a.deferredAt;
      a.state = "rejected";
      a.cancelledAt = new Date().toISOString();
      a.deferredAt = undefined;
      a.reviewHash = undefined;
      a.approvedHash = undefined;
      a.reason = "Automation cancelled by you. No submission was made by this action.";
      this.store.save(a);
      this.store.event(id, 'automation_cancelled', {by:'user'});
      try { await this.studio.result(
        a.input.studioSessionId,
        "rejected",
        a.reason,
        false,
      ); a.synced = true; }
      catch { a.synced = false; a.reason += ' Tracking sync pending.'; }
      if (wasActive) {
        try { await this.command(a, "finish", {closeCompleted:true}); }
        catch (error) { this.store.event(id,'cancelled_tab_cleanup_pending',{reason:(error as Error).message}); }
      }
      // The persistent queue driver starts the next job once this runner exits.
      return this.store.save(a);
    });
  }
  async allowDomain(id: string, domain: string, confirmed: boolean) {
    return this.exclusive(async () => {
      if (!confirmed)
        throw new Error("User confirmation required for a new domain.");
      const a = this.active(id, true);
      const u = await this.validateUrl("https://" + domain);
      if (u.hostname !== domain)
        throw new Error("Enter an exact hostname only.");
      a.input.allowedDomains.push(u.hostname);
      this.store.event(id, "domain_approved", { domain: u.hostname });
      return this.store.save(a);
    });
  }
  async omitCover(id: string, reason: string, confirmed: boolean) {
    return this.exclusive(async () => {
      if (!confirmed || !reason.trim())
        throw new Error(
          "Confirm why this portal does not accept the optional cover letter.",
        );
      const a = this.active(id, true);
      const doc = a.documents.find((d) => d.kind === "cover_letter");
      if (!doc || doc.attached)
        throw new Error(
          "Only an unattached optional cover letter can be omitted.",
        );
      doc.omissionReason = reason;
      a.reviewHash = undefined;
      this.store.event(id, "cover_letter_omitted", { reason });
      return this.store.save(a);
    });
  }
  async mapping(
    id: string,
    selector: string,
    frameId: number,
    profilePath: string,
    confirmed: boolean,
  ) {
    return this.exclusive(async () => {
      if (!confirmed)
        throw new Error("Confirm the exact profile mapping first.");
      const a = this.active(id, true);
      const field = a.snapshot?.fields.find(
        (f) => f.selector === selector && f.frameId === frameId,
      );
      if (
        !field ||
        sensitive(field.label) ||
        ["checkbox", "file"].includes(field.type)
      )
        throw new Error("This control cannot be mapped.");
      if (
        a.snapshot!.fields.filter((f) => f.label === field.label).length !==
          1 ||
        sensitive(profilePath)
      )
        throw new Error(
          "Repeated labels and sensitive profile paths require manual completion.",
        );
      const profile = JSON.parse(
        await readFile(path.join(this.root, "data/apply_profile.json"), "utf8"),
      );
      const value = profilePath
        .split(".")
        .reduce((v: any, key) => v?.[key], profile);
      if (
        typeof value !== "string" ||
        !value.trim() ||
        (field.options.length && !field.options.includes(value))
      )
        throw new Error(
          "The profile path must contain a confirmed value matching this exact control.",
        );
      const host = new URL(a.snapshot!.url).hostname;
      this.store.saveMapping(host, {
        label: field.label,
        type: field.type,
        options: field.options,
        profilePath,
      });
      this.store.event(id, "site_mapping_confirmed", {
        host,
        label: field.label,
        profilePath,
      });
      return this.store.mappings(host);
    });
  }
  async answer(
    question: string,
    answer: string,
    confirmed: boolean,
    reuse: boolean,
  ) {
    if (!confirmed || sensitive(question))
      throw new Error(
        "Only user-confirmed, non-sensitive reusable answers may be saved.",
      );
    return this.studio.request("/application-engine/answers", {
      question,
      answer,
      confirmed,
      reuse,
    });
  }
}



