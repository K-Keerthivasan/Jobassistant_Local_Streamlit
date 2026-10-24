import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile, rm } from "node:fs/promises";
import os from "node:os";
import { request } from "node:http";
import path from "node:path";
import { Store } from "../src/store.js";
import { Service } from "../src/service.js";
import { Studio } from "../src/studio.js";
import { Snapshot, ApplyInput, type Application } from "../src/schema.js";
import { plan, detectAts } from "../src/adapters.js";
import { publicAddress, documentInfo, digest, chromeDocumentPath, containerDocumentPath } from "../src/security.js";
import { httpServer } from "../src/http.js";
import { ChromeBridge } from "../src/bridge.js";
import { toolset } from "../src/tools.js";

const input = ApplyInput.parse({
  jobUrl: "https://careers.example.com/job/1",
  company: "Example",
  title: "Engineer",
  resumePath: "resume.pdf",
  studioSessionId: "s1",
  allowedDomains: ["careers.example.com"],
});
const snapshot = () =>
  Snapshot.parse({
    url: input.jobUrl,
    title: "Apply",
    fields: [
      {
        selector: "#name",
        label: "First name",
        type: "text",
        required: true,
        value: "Jordan",
      },
    ],
    buttons: [{ selector: "#submit", label: "Submit application", frameId: 0 }],
    blockers: [],
  });
function app(): Application {
  return {
    id: "app1",
    input: structuredClone(input),
    state: "working",
    ats: "generic",
    finalSubmitBy: 'approved_agent',
    documents: [
      {
        kind: "resume",
        path: "resume.pdf",
        hash: "hash",
        name: "resume.pdf",
        attached: true,
      },
    ],
    filled: [],
    reason: "",
    createdAt: "now",
    updatedAt: "now",
  };
}
class FakeStudio extends Studio {
  confirmations = 0;
  results = 0;
  snapshots = 0;
  failSync = false;
  override async snapshot() {
    this.snapshots++;
    return {};
  }
  override async confirm() {
    this.confirmations++;
    return { may_submit: true };
  }
  override async result() {
    if (this.failSync) throw new Error("Studio unavailable");
    this.results++;
    return {};
  }
}
function setup(state = app()) {
  const store = new Store(":memory:");
  store.save(state);
  let observed = snapshot();
  const calls: string[] = [];
  const browser = {
    command: async (op: string, args: Record<string, unknown>) => {
      calls.push(op);
      if (op === "scan") return structuredClone(observed);
      if (op === "fill") {
        observed.fields[0].value = String(args.value);
      }
      return {};
    },
  };
  const studio = new FakeStudio();
  const service = new Service(
    store,
    browser,
    studio,
    ".",
    [],
    async (value, domains) => {
      const u = new URL(value);
      if (domains && !domains.includes(u.hostname))
        throw new Error("New domain");
      return u;
    },
  );
  return {
    store,
    studio,
    service,
    calls,
    setSnapshot: (s: Snapshot) => {
      observed = s;
    },
  };
}
test("pending answers release the queue without recording a failed outcome, and reopen requires a new scan", async () => {
  const a = app();
  a.state = "paused";
  a.reason = "Required blank: salary";
  a.reviewHash = "old";
  const { service, store, calls, studio } = setup(a);
  const pending = await service.defer(a.id);
  assert.equal(pending.state, "paused");
  assert.ok(pending.deferredAt);
  assert.equal(pending.reviewHash, undefined);
  assert.equal(studio.results, 0);
  assert.deepEqual(calls, ["finish"]);
  assert.throws(() => service.active(a.id, true));
  const other = app(); other.id = "other"; other.input.jobUrl += "2";
  store.save(other);
  await assert.rejects(service.reopenDeferred(a.id), /current application/);
  other.state = "submitted"; store.save(other);
  const resumed = await service.reopenDeferred(a.id);
  assert.equal(resumed.deferredAt, undefined);
  assert.equal(resumed.documents[0].attached, false);
  assert.deepEqual(calls, ["finish", "recover", "scan"]);
});
test("background queue persists its setting, excludes Canada Life and intermediary URLs, and waits for active work", async () => {
  const {service, store, calls, studio} = setup();
  let fetched = 0;
  studio.request = async () => { fetched++; return { candidates: [
    { company: 'Canada Life', apply_url: 'https://jobs.canadalife.com/job/1' },
    { company: 'Other', apply_url: 'https://ca.indeed.com/viewjob?jk=1' },
  ] }; };
  assert.equal(store.queueEnabled(), false);
  store.queueEnabled(true);
  await service.continueQueue();
  assert.equal(fetched, 0); // current application must finish first
  const a = store.get('app1'); a.state = 'submitted'; store.save(a);
  await service.continueQueue();
  assert.equal(fetched, 1);
  assert.deepEqual(calls, []);
  store.queueEnabled(false);
  await service.continueQueue();
  assert.equal(fetched, 1);
});
test("Docker artifact paths translate to regular Windows Chrome only inside the approved shared directory", () => {
  const root = path.resolve('shared-workspace');
  const windowsRoot = 'E:\\Projects\\ResumeStudio';
  const file = path.join(root, 'data/job-applications/outbox/run/resume.pdf');
  const windowsFile = chromeDocumentPath(file, root, windowsRoot);
  assert.equal(windowsFile, 'E:\\Projects\\ResumeStudio\\data\\job-applications\\outbox\\run\\resume.pdf');
  assert.equal(containerDocumentPath(windowsFile, root, windowsRoot), file);
  assert.throws(() => chromeDocumentPath(path.join(root, 'private.pdf'), root, windowsRoot), /outside/);
  assert.throws(() => containerDocumentPath('E:\\Projects\\ResumeStudio\\private.pdf', root, windowsRoot), /outside/);
  assert.equal(chromeDocumentPath(file, root), file);
});
test("relative availability uses the application date and relevant websites stay within confirmed links", () => {
  const fields = Snapshot.parse({ ...snapshot(), fields: [
    { selector: "#date", label: "Date Available", type: "date", required: false },
    { selector: "#web", label: "Website, Blog or Portfolio", type: "text", required: false },
  ] }).fields;
  const profile = { availableStartDate: "Two weeks from application date", portfolio: "https://portfolio.example", github: "https://github.com/example" };
  const context = { title: "Software Developer", now: new Date("2026-12-25T02:00:00Z") };
  const result = plan(fields, profile, [], context);
  assert.equal(result[0].value, "2027-01-07"); // Dec 24 in New York + 14 days
  for(const [dateFormat,expected] of [['YYYY-MM-DD','2027-01-07'],['DD/MM/YYYY','07/01/2027'],['MM/DD/YYYY','01/07/2027']] as const){
    assert.equal(plan([{...fields[0],type:'text',dateFormat}],profile,[],context)[0].value,expected);
  }
  assert.equal(result[1].value, profile.github);
  assert.equal(plan(fields, profile, [], { ...context, title: "Graphic Designer" })[1].value, profile.portfolio);
});
test("verified exact answers only; sensitive and semantically different eligibility questions remain manual", () => {
  const fields = Snapshot.parse({
    ...snapshot(),
    fields: [
      { selector: "#a", label: "First name", type: "text", required: true },
      {
        selector: "#b",
        label: "Will you now or in the future need sponsorship?",
        type: "text",
        required: true,
      },
      {
        selector: "#c",
        label: "I agree to receive marketing",
        type: "checkbox",
        required: false,
      },
      {
        selector: "#d",
        label: "Gender",
        type: "select",
        required: false,
        options: ["Male", "Female"],
      },
    ],
  }).fields;
  const p = plan(fields, {
    firstName: "Jordan",
    commonAnswers: {
      "Do you currently need sponsorship?": "No",
      Gender: "Male",
    },
  });
  assert.equal(p[0].value, "Jordan");
  for (const entry of p.slice(1)) assert.equal(entry.value, undefined);
});
test("ATS hostname detection resists lookalike suffixes", () => {
  assert.equal(detectAts("https://boards.greenhouse.io/acme"), "greenhouse");
  assert.equal(
    detectAts("https://greenhouse.io.attacker.example/acme"),
    "generic",
  );
});
test("known LinkedIn alias and current Canadian work eligibility reuse only explicit confirmed facts", () => {
  const fields = Snapshot.parse({
    ...snapshot(),
    fields: [
      {
        selector: "#linkedin",
        label: "LinkedIn URL",
        type: "text",
        required: false,
      },
      {
        selector: "#auth",
        label: "Are you currently eligible to work in Canada? *",
        type: "textarea",
        required: true,
      },
      {
        selector: "#us",
        label:
          "Are you able to travel to the United States for work purposes? *",
        type: "text",
        required: true,
      },
    ],
  }).fields;
  const planned = plan(fields, {
    linkedin: "https://linkedin.com/in/confirmed",
    commonAnswers: { "Are you legally authorized to work in Canada?": "Yes" },
  });
  assert.equal(planned[0].value, "https://linkedin.com/in/confirmed");
  assert.equal(planned[1].value, "Yes");
  assert.equal(planned[2].value, undefined);
});
test("explicit permission allows preparation before CAPTCHA but never skips login or final verification", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "apply-pending-captcha-"));
  const { service, store, setSnapshot, calls } = setup();
  service.root = root;
  try {
    await mkdir(path.join(root, "data"));
    await writeFile(
      path.join(root, "data/apply_profile.json"),
      JSON.stringify({ firstName: "Jordan" }),
    );
    const s = snapshot();
    s.fields[0].value = "";
    s.blockers = ["CAPTCHA: complete it in Chrome."];
    setSnapshot(s);
    assert.equal((await service.fill("app1")).state, "paused");
    assert.equal(calls.includes("fill"), false);
    const prepared = await service.fill("app1", true);
    assert.equal(prepared.snapshot?.fields[0].value, "Jordan");
    assert.equal(prepared.state, "paused");
    assert.equal(calls.includes("click"), false);
    assert.equal(
      (await service.review("app1").catch(() => store.get("app1"))).state,
      "paused",
    );
    const login = snapshot();
    login.fields[0].value = "";
    login.blockers = ["Login or verification: complete it in Chrome."];
    setSnapshot(login);
    const previousFills = calls.filter((c) => c === "fill").length;
    await service.fill("app1", true);
    assert.equal(calls.filter((c) => c === "fill").length, previousFills);
  } finally {
    store.db.close();
    await rm(root, { recursive: true, force: true });
  }
});
test("site mappings require exact live structure; repeated labels never receive guessed values", () => {
  const field = Snapshot.parse({
    ...snapshot(),
    fields: [
      {
        selector: "#employer",
        label: "Employer",
        type: "text",
        required: true,
      },
    ],
  }).fields[0];
  const mappings = [
    {
      label: "Employer",
      type: "text",
      options: [],
      profilePath: "employmentHistory.0.company",
    },
  ];
  const profile = { employmentHistory: [{ company: "Confirmed employer" }] };
  assert.equal(plan([field], profile, mappings)[0].value, "Confirmed employer");
  assert.equal(
    plan(
      [{ ...field, type: "select", options: ["Other"] }],
      profile,
      mappings,
    )[0].value,
    undefined,
  );
  assert.equal(
    plan([field, { ...field, selector: "#second" }], profile, mappings)[0]
      .value,
    undefined,
  );
});
test("private IPv4, mapped IPv6 and localhost are refused", () => {
  for (const ip of [
    "127.0.0.1",
    "10.1.1.1",
    "169.254.169.254",
    "172.16.0.1",
    "192.168.1.1",
    "100.64.0.1",
    "::1",
    "::ffff:127.0.0.1",
    "fe80::1",
    "fc00::1",
  ])
    assert.equal(publicAddress(ip), false, ip);
  assert.equal(publicAddress("8.8.8.8"), true);
  assert.equal(publicAddress("2606:4700:4700::1111"), true);
});
test("document allowlist enforces canonical paths and hashes", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "apply-test-"));
  try {
    await mkdir(path.join(root, "approved"));
    await writeFile(path.join(root, "approved", "r.pdf"), "resume");
    await writeFile(path.join(root, "other.pdf"), "other");
    const d = await documentInfo(path.join(root, "approved", "r.pdf"), [
      path.join(root, "approved"),
    ]);
    assert.equal(d.name, "r.pdf");
    assert.equal(d.hash.length, 64);
    await assert.rejects(
      () =>
        documentInfo(path.join(root, "other.pdf"), [
          path.join(root, "approved"),
        ]),
      /outside/,
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
test("duplicate application URL is prevented durably", () => {
  const { store } = setup();
  assert.throws(() => store.save({ ...app(), id: "duplicate" }), /UNIQUE/);
  store.db.close();
});
test("review requires required fields, valid values and verified attachments", async () => {
  const { service, setSnapshot, store } = setup();
  const s = snapshot();
  s.fields[0].value = "";
  setSnapshot(s);
  const r = await service.review("app1");
  assert.equal(r.state, "paused");
  assert.match(r.reason, /Required blank/);
  assert.equal(r.reviewHash, undefined);
  store.db.close();
});
test("review syncs exact observed form to Studio and binds hash", async () => {
  const { service, store, studio } = setup();
  const r = await service.review("app1");
  assert.equal(r.state, "review");
  assert.equal(studio.snapshots, 1);
  assert.equal(
    r.reviewHash,
    digest({ snapshot: r.snapshot, documents: r.documents }),
  );
  store.db.close();
});
test("changed form cannot reuse review approval", async () => {
  const { service, store, studio, setSnapshot, calls } = setup();
  const r = await service.review("app1");
  const s = snapshot();
  s.fields[0].value = "Changed";
  setSnapshot(s);
  await assert.rejects(
    () => service.submit("app1", r.reviewHash!, true, "#submit"),
    /changed/,
  );
  assert.equal(studio.confirmations, 0);
  assert.equal(calls.filter((c) => c === "click").length, 0);
  store.db.close();
});
test("unapproved and uncertain submissions never click", async () => {
  const { service, store, calls } = setup();
  await assert.rejects(
    () => service.submit("app1", "invalid", true, "#submit"),
    /fresh yes/,
  );
  store.save({ ...store.get("app1"), state: "uncertain" });
  await assert.rejects(() =>
    service.submit("app1", "invalid", true, "#submit"),
  );
  assert.equal(calls.includes("click"), false);
  store.db.close();
});
test("uncertain verification stays uncertain without confirmation", async () => {
  const { service, store, studio } = setup({ ...app(), state: "uncertain" });
  assert.equal((await service.verify("app1")).state, "uncertain");
  assert.equal(studio.results, 0);
  store.db.close();
});
test("visible success is saved before sync, and sync retries never resubmit", async () => {
  const { service, store, studio, setSnapshot, calls } = setup({
    ...app(),
    state: "uncertain",
  });
  const s = snapshot();
  s.confirmation = "Your application has been received.";
  setSnapshot(s);
  studio.failSync = true;
  const result = await service.verify("app1");
  assert.equal(result.state, "submitted");
  assert.equal(result.synced, false);
  studio.failSync = false;
  assert.equal((await service.sync("app1")).synced, true);
  assert.equal(calls.includes("click"), false);
  store.db.close();
});
test("restart during submission becomes uncertain and cannot replay", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "apply-state-"));
  const file = path.join(root, "test.sqlite");
  try {
    let store = new Store(file);
    store.save({ ...app(), state: "submitting" });
    store.db.close();
    store = new Store(file);
    assert.equal(store.get("app1").state, "uncertain");
    store.db.close();
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
test("HTTP rejects cross-origin requests, wrong hosts and non-JSON mutations", async () => {
  const { service, store } = setup();
  const server = httpServer(service, new ChromeBridge(), "");
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const addr = server.address() as { port: number };
  const url = `http://127.0.0.1:${addr.port}`;
  try {
    const post = (headers: Record<string, string>) =>
      new Promise<number>((resolve, reject) => {
        const req = request(
          url + "/applications",
          { method: "POST", headers },
          (res) => {
            res.resume();
            res.on("end", () => resolve(res.statusCode!));
          },
        );
        req.on("error", reject);
        req.end("{}");
      });
    // Configured Host remains 8091; a rebound Host is refused even on loopback.
    assert.equal((await fetch(url + "/health")).status, 403);
    assert.equal(
      await post({
        Host: "127.0.0.1:8091",
        Origin: "https://attacker.example",
        "Content-Type": "application/json",
      }),
      403,
    );
    assert.equal(
      await post({ Host: "127.0.0.1:8091", "Content-Type": "text/plain" }),
      400,
    );
  } finally {
    await new Promise<void>((r) => server.close(() => r()));
    store.db.close();
  }
});
test("all requested MCP tools have Zod input schemas", () => {
  const { service, store } = setup();
  const tools = toolset(service);
  for (const name of [
    "apply_to_job",
    "detect_ats",
    "inspect_application",
    "fill_application",
    "upload_resume",
    "upload_cover_letter",
    "answer_screening_questions",
    "review_application",
    "submit_application",
    "verify_submission",
    "pause_application",
    "resume_application",
    "get_application_status",
    "get_application_history",
    "update_answer_bank",
  ])
    assert.ok(tools[name as keyof typeof tools].schema);
  store.db.close();
});


test("queue driver recovers saved work, respects a manual pause and never races an active run", async () => {
  const {service, store} = setup();
  store.queueEnabled(true);
  const started: string[] = [];
  service.startRun = (id: string) => { started.push(id); service.running = id; return {running: id}; };
  await service.driveQueue();
  await service.driveQueue();
  assert.deepEqual(started, ['app1']);
  service.running = undefined;
  const a = store.get('app1'); a.state = 'paused'; a.reason = 'User said no'; store.save(a);
  await service.driveQueue();
  assert.deepEqual(started, ['app1']);
  a.state = 'review'; store.save(a);
  await service.driveQueue();
  assert.deepEqual(started, ['app1']);
  store.db.close();
});

test("queue ignores malformed links and backs off preparation errors", async () => {
  const {service, store, studio} = setup();
  const a = store.get('app1'); a.state = 'submitted'; store.save(a);
  store.queueEnabled(true);
  let preparations = 0;
  studio.request = async (url: string) => {
    if (url.startsWith('/apply/candidates')) return { candidates: [
      {key_id:'broken', company:'Bad URL', apply_url:'invalid'},
      {key_id:'valid', company:'Employer', title:'Engineer', apply_url:'https://employer.example/job'}
    ] };
    preparations++;
    throw new Error('Resume temporarily unavailable');
  };
  await service.driveQueue();
  await service.driveQueue();
  assert.equal(preparations, 1);
  store.db.close();
});


test("resume recovers a lost Chrome tab without replaying approval or submission", async () => {
  const a = app(); a.state = 'paused'; a.approvedHash = 'stale'; a.reviewHash = 'stale';
  const {service, store, calls} = setup(a);
  let lost = true;
  service.browser.command = async (op, args) => {
    calls.push(op);
    if (op === 'scan' && lost) throw new Error('No matching application tab. Use Adopt current tab in the extension.');
    if (op === 'recover') throw new Error('No matching application tab. Use Adopt current tab in the extension.');
    if (op === 'open') { lost = false; assert.equal(args.url, a.input.jobUrl); }
    if (op === 'scan') return snapshot();
    return {};
  };
  const resumed = await service.resume(a.id);
  assert.equal(resumed.state, 'working');
  assert.equal(resumed.approvedHash, undefined);
  assert.equal(resumed.reviewHash, undefined);
  assert.equal(resumed.documents[0].attached, false);
  assert.deepEqual(calls, ['scan','recover','open','scan']);
  assert.ok(!calls.includes('click'));
  store.db.close();
});


test("confirmed Indeed source selects an exact relevant option without guessing other questions", () => {
  const profile = {firstName:'Confirmed', commonAnswers:{'How Did You Hear About Us?':'Indeed'}};
  const fields = Snapshot.parse({...snapshot(),fields:[
    {selector:'#first',label:'*\nFirst name',type:'text',required:true},
    {selector:'#source',label:'Where did you hear about us?*',type:'select',required:true,options:['Employee Referral','Indeed.com','LinkedIn']},
    {selector:'#other',label:'Why are you looking for a new role?',type:'text',required:true}
  ]}).fields;
  const planned = plan(fields,profile);
  assert.equal(planned[0].value,'Confirmed');
  assert.equal(planned[1].value,'Indeed.com');
  assert.equal(planned[2].value,undefined);
  fields[1].options=['Employee Referral','Online Job Board'];
  assert.equal(plan(fields,profile)[1].value,'Online Job Board');
  fields[1].options=['Employee Referral','Other'];
  assert.equal(plan(fields,profile)[1].value,undefined);
});

test("queue revisits deferred work once all required answers are confirmed", async () => {
  const {service,store} = setup();
  const root = await mkdtemp(path.join(os.tmpdir(),'pending-ready-'));
  try {
    await mkdir(path.join(root,'data'));
    await writeFile(path.join(root,'data/apply_profile.json'),JSON.stringify({firstName:'Jordan'}));
    service.root=root;
    const a=store.get('app1');a.state='paused';a.reason='Required blank: First name';a.deferredAt='now';a.snapshot=snapshot();a.snapshot.fields[0].value='';store.save(a);
    store.queueEnabled(true);
    let reopened=0;
    service.reopenDeferred=async(id)=>{reopened++;const b=store.get(id);b.deferredAt=undefined;b.state='working';return store.save(b);};
    service.startRun=(id)=>{service.running=id;return {running:id};};
    await service.driveQueue();
    assert.equal(reopened,1);
    assert.equal(service.running,'app1');
  } finally {store.db.close();await rm(root,{recursive:true,force:true});}
});


test("extension questions validate choices and save only the requested answer scope", async () => {
  const a=app();a.state='paused';a.deferredAt='now';a.snapshot=snapshot();
  a.snapshot.fields=[{...a.snapshot.fields[0],label:'Expected pay?',value:'',options:['80000','90000']}];
  const {service,store,studio}=setup(a);
  let saved:any;
  studio.request=async (_route,body)=>{saved=body;return {saved:true};};
  await assert.rejects(service.confirmQuestion(a.id,'#name',0,'99999',true),/exact/);
  assert.equal(saved,undefined);
  await service.confirmQuestion(a.id,'#name',0,'80000',false);
  assert.deepEqual(saved,{question:'Expected pay?',answer:'80000',confirmed:true,reuse:false,session_id:'s1'});
  assert.equal(service.running,undefined);
  assert.equal(service.profileFor(a,{commonAnswers:{Other:'global'},applicationAnswers:{s1:{'Expected pay?':'80000'},s2:{Other:'different'}}}).commonAnswers.Other,'global');
  const b=store.get(a.id);b.snapshot!.fields[0].label='I agree to terms';store.save(b);
  await assert.rejects(service.confirmQuestion(a.id,'#name',0,'80000',true),/personally/);
  store.db.close();
});


test("resume saved step reuses the last approved application page and invalidates old approval", async () => {
  const a=app();a.state='paused';a.deferredAt='now';a.snapshot=snapshot();a.snapshot.url='https://careers.example.com/application/step3';a.approvedHash='old';
  const {service,store,calls}=setup(a);
  const seen: any[]=[];
  service.browser.command=async(op,args)=>{seen.push({op,args});return op==='scan'?{...snapshot(),url:a.snapshot!.url}:{};};
  service.startRun=(id)=>({running:id});
  const resumed=await service.resumeCheckpoint(a.id);
  assert.equal(seen[0].op,'recover');
  assert.equal(seen[0].args.url,a.snapshot.url);
  assert.equal(resumed.approvedHash,undefined);
  assert.equal(resumed.deferredAt,undefined);
  assert.equal(resumed.documents[0].attached,false);
  store.db.close();
});

test("switching applications saves the active job before recovering a pending checkpoint", async () => {
  const {service,store,calls}=setup();
  const pending=app();pending.id='pending';pending.input.jobUrl+='2';pending.state='paused';pending.deferredAt='now';pending.snapshot=snapshot();pending.snapshot.url='https://careers.example.com/application/step2';store.save(pending);
  service.startRun=(id)=>({running:id});
  await service.resumeCheckpoint(pending.id);
  assert.ok(store.get('app1').deferredAt);
  assert.equal(store.get('pending').deferredAt,undefined);
  assert.ok(calls.indexOf('finish')<calls.indexOf('recover'));
  store.db.close();
});


test("Bamboo custom address labels containing their displayed value remain verified profile fields", () => {
  const fields=Snapshot.parse({...snapshot(),fields:[
    {selector:'#province',label:'Province –Select–',type:'custom-select',required:false,value:''},
    {selector:'#country',label:'Country Canada',type:'custom-select',required:false,value:'Canada'},
    {selector:'#birth',label:'Country of birth',type:'custom-select',required:true,value:''}
  ]}).fields;
  const planned=plan(fields,{province:'ON',country:'Canada'});
  assert.equal(planned[0].value,'Ontario');assert.equal(planned[1].value,'Canada');assert.equal(planned[2].value,undefined);
});


test("manual submissions are recorded only after observed confirmation, without clicking or reopening", async () => {
  const {service,store,studio,calls,setSnapshot}=setup();
  const success=snapshot();success.confirmation='Your application has been received.';setSnapshot(success);
  const result=await service.reportSubmitted('app1');
  assert.equal(result.state,'submitted');assert.ok(result.manualSubmissionReportedAt);
  assert.equal(studio.results,1);
  assert.ok(!calls.some(op=>['open','recover','fill','click'].includes(op)));
  store.db.close();
});

test("a user-reported submission without visible proof blocks reapplication and cannot run", async () => {
  const {service,store,studio,calls}=setup();
  const result=await service.reportSubmitted('app1');
  assert.equal(result.state,'uncertain');assert.ok(result.manualSubmissionReportedAt);
  assert.match(result.reason,/Submitted by you/);
  assert.equal(studio.results,0);assert.throws(()=>service.startRun('app1'),/uncertain/);
  assert.deepEqual(calls,['scan']);store.db.close();
});

test("background observation detects a manual submit after the approval runner has ended", async () => {
  const a=app();a.state='review';
  const {service,store,studio,calls,setSnapshot}=setup(a);
  const success=snapshot();success.confirmation='Thank you for applying';setSnapshot(success);
  await service.observeCompletion();
  assert.equal(store.get(a.id).state,'submitted');assert.equal(studio.results,1);
  await service.observeCompletion();assert.equal(studio.results,1);
  assert.ok(!calls.some(op=>['open','fill','click'].includes(op)));store.db.close();
});


test("closed-tab manual confirmation logs the user as submitter without any browser operation", async () => {
  const {service,store,studio,calls}=setup({...app(),state:'uncertain'});
  const logged:any[]=[];
  studio.result=async(...args:any[])=>{logged.push(args);return {};};
  service.browser.command=async()=>{throw new Error('Chrome is closed and must not be opened');};
  const result=await service.confirmManualSubmission('app1','User confirmed after closing tab');
  assert.equal(result.state,'submitted');assert.equal(result.verificationSource,'user_confirmation');
  assert.ok(result.manuallyConfirmedAt);assert.equal(result.synced,true);
  assert.equal(logged[0][3],false);assert.equal(logged[0][4],'me');
  assert.deepEqual(calls,[]);
  await service.confirmManualSubmission('app1','Repeated click');
  assert.equal(logged.length,1);
  store.db.close();
});

test("retrying a manually confirmed result sync preserves its source instead of inventing employer proof", async () => {
  const {service,store,studio}=setup({...app(),state:'uncertain'});
  let offline=true;const logged:any[]=[];
  studio.result=async(...args:any[])=>{if(offline)throw new Error('offline');logged.push(args);return {};};
  const result=await service.confirmManualSubmission('app1','Closed tab');
  assert.equal(result.state,'submitted');assert.equal(result.synced,false);
  offline=false;
  await service.sync('app1');assert.equal(logged[0][3],false);assert.equal(logged[0][4],'me');
  store.db.close();
});

test('history fields use matched tailored resume rows, without inventing months', () => {
  const fields = Snapshot.parse({url:'https://example.ca',title:'Apply',buttons:[],blockers:[],fields:[
    {selector:'#company',label:'experience 1 · company',type:'text',required:true,value:'Example',history:{section:'experience',index:0,key:'company'}},
    {selector:'#role',label:'experience 1 · role',type:'text',required:true,history:{section:'experience',index:0,key:'role'}},
    {selector:'#month',label:'experience 1 · startMonth',type:'text',required:true,history:{section:'experience',index:0,key:'startMonth'}},
    {selector:'#year',label:'experience 1 · startYear',type:'text',required:true,history:{section:'experience',index:0,key:'startYear'}}]}).fields;
  const result = plan(fields,{tailoredResume:{experience:[{company:'Other',role:'Wrong'},{company:'Example',role:'Tailored Developer',start:'2023'}]}});
  assert.equal(result[1].value,'Tailored Developer');
  assert.equal(result[2].value,undefined);
  assert.equal(result[3].value,'2023');
  const absent = plan(fields,{tailoredResume:{experience:[{company:'Different',role:'Wrong'}]}});
  assert.equal(absent[1].value,undefined);
});

test('an unverified upload is never sent a second time, even after service restart', async () => {
  const state = app(); state.documents[0].attached = false;
  state.documents[0].uploadAttemptedAt = new Date().toISOString();
  const {service,calls,store} = setup(state);
  await assert.rejects(service.upload(state.id,'resume','#upload'),/will not upload another copy/);
  assert.equal(calls.filter(op => op === 'upload').length,0);
  assert.ok(store.get(state.id).documents[0].uploadAttemptedAt);
});

test('Workday final submission is user-only, and distinct structural formats persist', async () => {
  const a=app();a.ats='workday';a.finalSubmitBy='user';a.state='review';a.reviewHash='review';
  const {service,calls,store}=setup(a);
  await assert.rejects(service.submit(a.id,'review',true,'#submit'),/clicked by you/);
  assert.equal(calls.length,0);
  assert.equal(store.rememberFormat('workday-one',{id:'workday-one',fields:['name']}),true);
  assert.equal(store.rememberFormat('workday-one',{id:'workday-one',fields:['name']}),false);
  assert.equal(store.rememberFormat('workday-two',{id:'workday-two',fields:['history']}),true);
  assert.equal(store.formats().length,2);
});

test('cancelling active automation closes its tab, preserves the queue and cannot replay', async () => {
  const {service,store,calls,studio}=setup();
  store.queueEnabled(true);service.running='app1';
  const cancelled=await service.cancel('app1');
  assert.ok(cancelled.cancelledAt);assert.equal(cancelled.state,'rejected');
  assert.equal(service.runCancel,true);assert.equal(store.queueEnabled(),true);
  assert.deepEqual(calls,['finish']);assert.equal(studio.results,1);
  await service.cancel('app1');assert.equal(studio.results,1);
});

test('cancel saved application works while paused and never closes the active job', async () => {
  const a=app();a.deferredAt='now';const {service,calls}=setup(a);service.stopped=true;
  assert.ok((await service.cancel(a.id)).cancelledAt);assert.deepEqual(calls,[]);
});

test('cancellation never overrides a submitted or uncertain application', async () => {
  for(const state of ['submitted','uncertain','submitting'] as const){const a=app();a.state=state;const {service,calls}=setup(a);await assert.rejects(service.cancel(a.id),/cancellation cannot replace/);assert.deepEqual(calls,[]);}
});

test('sequential queue waits for completion, then advances after user cancellation', async () => {
  const {service,store,studio}=setup();store.queueEnabled(true);
  let fetches=0;studio.request=async()=>{fetches++;return {candidates:[]};};
  await service.driveQueue();assert.equal(fetches,0);
  await service.cancel('app1');
  await service.driveQueue();assert.equal(fetches,1);
});

test('the app fills and persists an evidence-checked AI draft without teaching the answer bank',async(t)=>{
  const root=await mkdtemp(path.join(os.tmpdir(),'ai-answers-'));await mkdir(path.join(root,'data'));await writeFile(path.join(root,'data/apply_profile.json'),'{}');
  const {service,studio,store,setSnapshot,calls}=setup();service.root=root;
  const observed=snapshot();observed.fields=[{...observed.fields[0],label:'Describe your relevant experience',value:'',type:'textarea'}];setSnapshot(observed);
  studio.request=async()=>({company:'Example',title:'Engineer',description:'SQL reports',resume:{experience:[{bullets:['Built SQL reports for operations teams.']}]}});
  let requests=0;
  t.mock.method(globalThis,'fetch',async()=>Response.json({choices:[{message:{content:JSON.stringify(++requests===1?{needsUser:false,sentences:[{text:'I built SQL reports for operations teams.',evidence:[0]}]}:{supported:true})}}]}));
  const old=process.env.APP_HERMES_BASE_URL;process.env.APP_HERMES_BASE_URL='http://hermes.test/v1';
  try {
    const result=await service.fill('app1');assert.equal(result.snapshot?.fields[0].value,'I built SQL reports for operations teams.');assert.equal(result.answerDrafts?.length,1);
    assert.equal(calls.filter(c=>c==='fill').length,1);await service.fill('app1');assert.equal(requests,2);
    assert.equal(await (await import('node:fs/promises')).readFile(path.join(root,'data/apply_profile.json'),'utf8'),'{}');
    assert.equal((await service.questions())[0]?.questions.length || 0,0);
  } finally {if(old===undefined)delete process.env.APP_HERMES_BASE_URL;else process.env.APP_HERMES_BASE_URL=old;await rm(root,{recursive:true,force:true});store.db.close();}
});

test('optional blank choices are scoped and never bypass required or invalid fields',async()=>{
 const root=await mkdtemp(path.join(os.tmpdir(),'blank-choice-'));await mkdir(path.join(root,'data'));
 await writeFile(path.join(root,'data/apply_profile.json'),JSON.stringify({applicationBlankAnswers:{s1:{'Middle Name':true}}}));
 const {service,store,setSnapshot,studio}=setup();service.root=root;
 const form=snapshot();form.fields=[{...form.fields[0],label:'Middle Name',value:'',required:false}];setSnapshot(form);await service.inspect('app1');
 assert.equal((await service.questions())[0]?.questions.length || 0,0);
 let saved:any;studio.request=async(_route,body)=>{saved=body;return {saved:true};};
 await service.leaveBlank('app1','#name',0);assert.equal(saved.reuse,false);
 form.fields[0].required=true;setSnapshot(form);await service.inspect('app1');
 assert.equal((await service.questions())[0].questions[0].canLeaveBlank,false);
 await assert.rejects(service.leaveBlank('app1','#name',0),/empty optional/);
 form.fields[0].required=false;form.fields[0].invalid=true;setSnapshot(form);await service.inspect('app1');
 await assert.rejects(service.leaveBlank('app1','#name',0),/empty optional/);
 await rm(root,{recursive:true,force:true});store.db.close();
});

test('Indeed and company queue scopes persist and filter the backend candidate selection',async()=>{
 const {service,store,studio}=setup();const a=store.get('app1');a.state='submitted';store.save(a);store.queueEnabled(true);
 const prepared:string[]=[];
 studio.request=async(route,body:any)=>{if(route.startsWith('/apply/candidates'))return {candidates:[
 {key_id:'indeed',run_id:'r',company:'Indeed job',apply_url:'https://ca.indeed.com/viewjob?jk=1'},
 {key_id:'company',run_id:'r',company:'Direct job',apply_url:'https://employer.example/job/1'}]};prepared.push(body.job_key);throw new Error('fixture stops before opening');};
 store.queueScope('indeed');await service.continueQueue();assert.deepEqual(prepared,['indeed']);
 store.queueScope('company');await service.continueQueue();assert.deepEqual(prepared,['indeed','company']);
 assert.equal(store.queueScope(),'company');store.db.close();
});

test('Resume handles Chrome missing numeric tab IDs and never substitutes an unapproved URL',async()=>{
 const a=app();a.state='paused';a.snapshot=snapshot();a.snapshot.url='https://careers.example.com/application/saved-step';
 const {service,calls}=setup(a);let closed=true;
 service.browser.command=async(op,args)=>{calls.push(op);if(op==='scan' && closed)throw new Error('No tab with id: 2122844803.');if(op==='recover'){assert.equal(args.url,a.snapshot!.url);closed=false;}return op==='scan'?{...snapshot(),url:a.snapshot!.url}:{};};
 const result=await service.resume(a.id);assert.equal(result.state,'working');assert.deepEqual(calls,['scan','recover','scan']);
});

test('restart uses the original approved URL, clears stale approval after navigation, and retains the record',async()=>{
 const a=app();a.state='paused';a.snapshot=snapshot();a.snapshot.url='https://careers.example.com/expired-session';a.reviewHash='stale';a.approvedHash='stale';a.documents[0].uploadAttemptedAt='old';
 const {service,studio,store,calls}=setup(a);studio.validate=async()=>({});let destination='';
 service.browser.command=async(op,args)=>{calls.push(op);if(op==='restart')destination=String(args.url);return op==='scan'?{...snapshot(),blockers:['Session expired: sign in in Chrome.']}:{};};
 const result=await service.restartApplication(a.id);assert.equal(destination,a.input.jobUrl);assert.equal(store.list().length,1);assert.equal(result.approvedHash,undefined);assert.equal(result.documents[0].uploadAttemptedAt,undefined);assert.equal(result.linkHealth,'session_expired');assert.ok(!calls.includes('click'));
});

test('failed restart preserves document upload guards, and completed/uncertain records never restart',async()=>{
 const a=app();a.documents[0].uploadAttemptedAt='old';const {service,studio,store}=setup(a);studio.validate=async()=>({});service.browser.command=async()=>{throw new Error('Chrome disconnected');};
 await assert.rejects(service.restartApplication(a.id),/Chrome disconnected/);assert.equal(store.get(a.id).documents[0].uploadAttemptedAt,'old');
 for(const state of ['submitted','uncertain','submitting'] as const){const current=store.get(a.id);current.state=state;store.save(current);await assert.rejects(service.restartApplication(a.id),/cannot be restarted/);}
});

test('restart observes an existing success page instead of reopening or submitting again',async()=>{
 const {service,studio,calls}=setup();studio.validate=async()=>({});
 service.browser.command=async(op)=>{calls.push(op);return op==='scan'?{...snapshot(),confirmation:'Your application has been received'}:{};};
 const result=await service.restartApplication('app1');assert.equal(result.state,'submitted');assert.ok(!calls.includes('restart'));assert.ok(!calls.includes('open'));assert.ok(!calls.includes('click'));
});

test('unavailable jobs are deferred without reporting rejection or blocking the next queue job',async()=>{
 const a=app();a.state='paused';a.linkHealth='unavailable';const {service,store,studio}=setup(a);
 await (service as any).runLoop(a.id);
 assert.ok(store.get(a.id).deferredAt);assert.equal(store.get(a.id).state,'paused');assert.equal(studio.results,0);
});

test('Dayforce history rows use their tailored education and employment without invented full dates',()=>{
 const fields=Snapshot.parse({...snapshot(),fields:[
 {selector:'#degree',label:'Education 1 · Degree',type:'text',required:true,history:{section:'education',index:0,key:'credential',orderedBlankRow:true}},
 {selector:'#school',label:'Education 1 · School',type:'text',required:true,history:{section:'education',index:0,key:'institution',orderedBlankRow:true}},
 {selector:'#start',label:'Education 1 · Start Date',type:'date',required:true,history:{section:'education',index:0,key:'startDate',orderedBlankRow:true}},
 {selector:'#mobile',label:'Mobile Phone Number',type:'text',required:true}]}).fields;
 const result=plan(fields,{phone:'2260000000',tailoredResume:{education:[{institution:'Fanshawe College',credential:'Game Development: Advanced Programming',year:'2023 to 2024'}]}});
 assert.equal(result[0].value,'Game Development: Advanced Programming');assert.equal(result[1].value,'Fanshawe College');assert.equal(result[2].value,undefined);assert.equal(result[3].value,'2260000000');
});

test('manual capture waits for blur and stability, then saves employer-scoped answers once',async()=>{
 const a=app();a.state='paused';a.snapshot=Snapshot.parse({...snapshot(),fields:[
 {selector:'#company',label:'Work experience 1 · Employer Name',type:'text',required:true,value:'Example Ltd',history:{section:'experience',index:0,key:'company'}},
 {selector:'#role',label:'Work experience 1 · Position Title',type:'text',required:true,value:'Developer',history:{section:'experience',index:0,key:'role'}},
 {selector:'#supervisor',label:'Work experience 1 · Supervisor',type:'text',required:true,value:'',history:{section:'experience',index:0,key:'supervisorName'}}]});
 const {service,store,studio}=setup(a);let saved:any;let count=0;studio.request=async(_route,body)=>{count++;saved=body;return {saved:true};};
 const current=store.get(a.id);current.manualWatches=[{label:current.snapshot!.fields[2].label,selector:'#supervisor',frameId:0,reuse:true,baseline:'',saved:false}];
 const scan=structuredClone(current.snapshot!);scan.fields[2].value='Confirmed Supervisor';scan.fields[2].focused=true;
 assert.equal(await (service as any).consumeManualAnswers(current,scan),false);assert.equal(count,0);
 scan.fields[2].focused=false;assert.equal(await (service as any).consumeManualAnswers(current,scan),false);
 current.manualWatches[0].seenAt=Date.now()-3000;
 assert.equal(await (service as any).consumeManualAnswers(current,scan),true);assert.equal(saved.question,'Employer Example Ltd / Developer · Supervisor');assert.equal(saved.reuse,true);
 await (service as any).consumeManualAnswers(current,scan);assert.equal(count,1);
 const profile=service.profileFor(current,{commonAnswers:{[saved.question]:'Confirmed Supervisor'}});assert.equal(profile.commonAnswers[current.snapshot!.fields[2].label],'Confirmed Supervisor');
});

test('known answers and available uploads complete before the remaining-question list is exposed',async()=>{
 const root=await mkdtemp(path.join(os.tmpdir(),'known-first-'));await mkdir(path.join(root,'data'));await writeFile(path.join(root,'data/apply_profile.json'),JSON.stringify({firstName:'Jordan'}));
 const a=app();a.documents[0].attached=false;a.preparationStage='preparing';
 const {service,store}=setup(a);service.root=root;service.running=a.id;
 let observed=Snapshot.parse({...snapshot(),fields:[
 {selector:'#first',label:'First name',type:'text',required:true,value:''},
 {selector:'#unknown',label:'An unknown factual question',type:'text',required:true,value:''},
 {selector:'#resume',label:'Resume',type:'file',required:true,value:''}]});
 const order:string[]=[];
 service.browser.command=async(op,args)=>{if(op==='scan')return structuredClone(observed);if(op==='fill'){order.push('fill');observed.fields[0].value=String(args.value);const groups=await service.questions();assert.equal(groups[0].questions.length,0);}return {};};
 service.upload=async()=>{order.push('upload');assert.equal(observed.fields[0].value,'');assert.equal((await service.questions())[0].questions.length,0);observed.fields[0].selector='#parsed-first';observed.fields[2].files=['resume.pdf'];const current=store.get(a.id);current.documents[0].attached=true;current.snapshot=structuredClone(observed);store.save(current);return current;};
 await (service as any).runLoop(a.id);
 assert.deepEqual(order,['upload','fill']);assert.equal(store.get(a.id).preparationStage,'needs_user');
 assert.deepEqual((await service.questions())[0].questions.map(q=>q.question),['An unknown factual question']);
 service.running=undefined;await rm(root,{recursive:true,force:true});store.db.close();
});

test('an unverified prior upload does not block known fields or upload another copy',async()=>{
 const root=await mkdtemp(path.join(os.tmpdir(),'pending-upload-'));await mkdir(path.join(root,'data'));await writeFile(path.join(root,'data/apply_profile.json'),JSON.stringify({firstName:'Jordan'}));
 const a=app();a.documents[0].attached=false;a.documents[0].uploadAttemptedAt=new Date().toISOString();
 const {service,store}=setup(a);service.root=root;service.running=a.id;
 const observed=Snapshot.parse({...snapshot(),fields:[{selector:'#first',label:'First name',type:'text',required:true,value:''},{selector:'#unknown',label:'Unknown factual question',type:'text',required:true,value:''},{selector:'#resume',label:'Resume',type:'file',required:true,value:''}]});
 let uploads=0;service.upload=async()=>{uploads++;throw new Error('Must not duplicate');};
 service.browser.command=async(op,args)=>{if(op==='scan')return structuredClone(observed);if(op==='fill')observed.fields[0].value=String(args.value);return {};};
 await (service as any).runLoop(a.id);assert.equal(observed.fields[0].value,'Jordan');assert.equal(uploads,0);assert.equal(store.get(a.id).documents[0].attached,false);
 service.running=undefined;await rm(root,{recursive:true,force:true});store.db.close();
});

test('education batch exposes future rows together and validates all dates before saving',async()=>{
 const root=await mkdtemp(path.join(os.tmpdir(),'education-batch-'));await mkdir(path.join(root,'data'));await writeFile(path.join(root,'data/apply_profile.json'),'{}');
 const a=app();a.snapshot=Snapshot.parse({...snapshot(),fields:[{selector:'#start',label:'Education 1 · Start Date',type:'date',required:true,value:'2024-09-01',history:{section:'education',index:0,key:'startDate'}}]});
 const {service,store}=setup(a);service.root=root;
 const saved:any[]=[];service.studio.request=async(route,body)=>{if(route.endsWith('/resume-history'))return {education:[{institution:'College A',credential:'Program A',year:'2024 to 2025'},{institution:'College B',credential:'Program B',year:'2020 to 2022'}]};saved.push(body);return {saved:true};};
 const batch=await (service as any).educationBatch(a,{});assert.equal(batch.length,2);assert.equal(batch[0].startDate,'2024-09-01');assert.equal(batch[1].startDate,'');assert.equal(batch[1].requiredStart,true);
 await assert.rejects(()=>service.confirmEducationBatch(a.id,[{index:0,startDate:'2024-09-01',endDate:''},{index:1,startDate:'2020-02-31',endDate:''}]),/valid exact date/);assert.equal(saved.length,0);
 let starts=0;service.startRun=()=>{starts++;return {running:a.id};};
 await service.confirmEducationBatch(a.id,[{index:0,startDate:'2024-09-01',endDate:''},{index:1,startDate:'2020-09-01',endDate:'2022-06-01'}]);
 assert.equal(saved.length,3);assert.equal(starts,1);assert(saved.every(answer=>answer.reuse===false && answer.session_id===a.input.studioSessionId));
 await rm(root,{recursive:true,force:true});store.db.close();
});

test('Indeed final review rejects a different visible resume even after an earlier verified upload',async()=>{
 const a=app();a.input.jobUrl='https://smartapply.indeed.com/beta/indeedapply/form/review-module';a.input.allowedDomains=['smartapply.indeed.com'];a.documents[0].attached=true;
 const {service,store}=setup(a);
 service.browser.command=async op=>op==='scan'?{...snapshot(),url:a.input.jobUrl,attachments:[{kind:'resume',name:'old-other-job.pdf',frameId:35,shownByIndeed:true}]}:{};
 const result=await service.review(a.id);assert.equal(result.state,'paused');assert.equal(result.documents[0].attached,false);assert.match(result.reason,/Indeed final document check: expected resume.pdf; shown: old-other-job.pdf/);
 store.db.close();
});

test('missing-field notifications wait for the preparation stage to finish',async()=>{
 const {shouldNotify,defaultSettings}=await import('../src/notify.js');
 const a=app();a.state='paused';a.reason='Required blank: missing fact';a.preparationStage='uploading';
 assert.equal(shouldNotify(undefined,a,defaultSettings()),null);
 const previous={state:a.state,reason:a.reason,preparationStage:a.preparationStage};a.preparationStage='needs_user';
 assert.equal(shouldNotify(previous,a,defaultSettings()),'fields');
});

test('Dayforce internal resume controls accept bare pdf extensions and upload once',async()=>{
 const root=await mkdtemp(path.join(os.tmpdir(),'dayforce-upload-'));const file=path.join(root,'resume.pdf');await writeFile(file,'%PDF-1.4 fixture');const doc=await documentInfo(file,[root]);
 const a=app();a.input.jobUrl='https://jobs.dayforcehcm.com/job/1';a.input.allowedDomains=['jobs.dayforcehcm.com'];a.documents=[{kind:'resume',...doc,attached:false}];
 const {service,calls}=setup(a);service.root=root;service.uploadRoots=[root];let uploaded=false;
 service.browser.command=async(op)=>{calls.push(op);if(op==='upload')uploaded=true;return op==='scan'?{...snapshot(),url:a.input.jobUrl,fields:[{selector:'#upload',label:'jobPostingApplication_files_resume',type:'file',required:true,accept:'doc,docx,pdf,rtf',files:uploaded?['resume.pdf']:[]}]}:{};};
 const result=await service.upload(a.id,'resume','#upload');assert.equal(result.documents[0].attached,true);assert.equal(calls.filter(c=>c==='upload').length,1);await rm(root,{recursive:true,force:true});
});
