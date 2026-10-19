import { test, expect } from "@playwright/test";
// The extension's actual DOM code is executed on local fixtures only.
// @ts-expect-error Browser module is plain JavaScript for Chrome MV3.
import { domTask } from "../../extension/dom.js";
// @ts-expect-error Plain browser module shared with the installed extension.
import { readRecaptchaIndicator } from "../../extension/verification.js";
import { reviewProblems } from '../../src/adapters.js';
import { Snapshot } from '../../src/schema.js';
import { pickFinal, pickNav } from '../../src/adapters.js';

test('document byte upload sends the full file and change event to the designated attachment input',async({page})=>{
  await page.setContent('<input type="file" id="import" aria-label="Attachment:"><input type="file" id="jobPostingApplication_files_resume"><div id="receipt"></div>');
  await page.evaluate(()=>document.querySelector('#jobPostingApplication_files_resume')!.addEventListener('change',event=>{const file=(event.target as HTMLInputElement).files![0];document.querySelector('#receipt')!.textContent=`${file.name}:${file.size}`;}));
  const bytes=Buffer.from('%PDF-1.4 verified fixture');
  const task={op:'attach',selector:'#jobPostingApplication_files_resume',contentBase64:bytes.toString('base64'),name:'tailored.pdf',mime:'application/pdf',size:bytes.length};
  await expect(page.evaluate(domTask,{...task,size:bytes.length+1})).rejects.toThrow('byte count');
  await page.evaluate(domTask,task);
  await expect(page.locator('#receipt')).toHaveText(`tailored.pdf:${bytes.length}`);
  const scanned=await page.evaluate(domTask,{op:'scan'});
  expect(scanned.supportsByteUploads).toBe(true);
  expect(scanned.fields.find(f=>f.selector==='#import')?.uploadRole).toBe('resume_import');
  expect(scanned.fields.find(f=>f.selector==='#jobPostingApplication_files_resume')?.files).toEqual(['tailored.pdf']);
});

test('education Update is scoped to its row and refuses incomplete required controls',async({page})=>{
  await page.setContent('<form><input id="job_educationHistory_1_degreeName" required value="Program"><input id="start" type="date" required><button type="button" id="update">Update</button></form><button id="other">Update</button>');
  await page.evaluate(()=>{document.querySelector('#update')!.addEventListener('click',()=>{document.querySelector('#update')!.textContent='Saved';});});
  expect((await page.evaluate(domTask,{op:'scan'})).buttons.find(b=>b.selector==='#update')?.educationIndex).toBe(1);
  await expect(page.evaluate(domTask,{op:'click',selector:'#update',educationUpdate:true,domains:[]})).rejects.toThrow();
  await page.locator('#start').fill('2023-09-01');
  await expect(page.evaluate(domTask,{op:'click',selector:'#other',educationUpdate:true,domains:[]})).rejects.toThrow();
  await page.evaluate(domTask,{op:'click',selector:'#update',educationUpdate:true,domains:[]});
  await expect(page.locator('#update')).toHaveText('Saved');
});

test('education expansion distinguishes empty history from already saved records',async({page})=>{
  await page.setContent('<section><h2>Education History</h2><div><button id="add">+ Add Education History</button></div></section>');
  expect((await page.evaluate(domTask,{op:'scan'})).educationSection?.hasRecords).toBe(false);
  await page.evaluate(()=>{document.querySelector('section')!.insertAdjacentHTML('beforeend','<div>Existing College<button>Edit Record</button></div>');});
  expect((await page.evaluate(domTask,{op:'scan'})).educationSection?.hasRecords).toBe(true);
});

test('Dayforce replacement control verifies the exact filename after upload clears its input', async ({page}) => {
  await page.setContent('<section><h2>Resume</h2><span>tailored.pdf</span><button>Replace Resume</button><input type="file" aria-label="Resume"></section>');
  const scanned=await page.evaluate(domTask,{op:'scan'});
  expect(scanned.attachments).toContainEqual({kind:'resume',name:'tailored.pdf',frameId:0});
});

test('searchable combobox selects only its associated exact normalized option', async ({page}) => {
  await page.setContent('<label for="province">Province</label><input id="province" role="combobox" aria-controls="provinces"><ul id="provinces" role="listbox"></ul><div role="option">Ontario</div>');
  await page.evaluate(() => {
    document.querySelector('#province')!.addEventListener('input', () => {
      const option=document.createElement('li');option.setAttribute('role','option');option.textContent='  ONTARIO  ';
      option.onclick=()=>{(document.querySelector('#province') as HTMLInputElement).value='Ontario';};
      document.querySelector('#provinces')!.replaceChildren(option);
    });
  });
  await page.evaluate(domTask,{op:'fill',selector:'#province',value:'Ontario'});
  await expect(page.locator('#province')).toHaveValue('Ontario');
});

test('Indeed-style narrative form continues to a visible final review without submitting',async({page})=>{
  await page.setContent('<main><label for="answer">Describe your relevant experience</label><textarea id="answer" required></textarea><button id="review">Review your application</button></main>');
  const scanned=Snapshot.parse(await page.evaluate(domTask,{op:'scan'}));
  expect(pickNav(scanned)?.label).toBe('Review your application');
  await page.evaluate(domTask,{op:'fill',selector:'#answer',value:'I built SQL reports for operations teams.'});
  await page.evaluate(()=>document.querySelector('main')!.innerHTML='<h1>Review your application</h1><p>Describe your relevant experience: I built SQL reports for operations teams.</p><button id="submit">Submit your application</button>');
  const final=Snapshot.parse(await page.evaluate(domTask,{op:'scan'}));
  expect(pickFinal(final)?.selector).toBe('#submit');expect(pickNav(final)).toBeUndefined();
  expect(final.reviewText).toContain('I built SQL reports for operations teams.');
});

test("BambooHR required labels and asynchronous attachment receipts survive input removal", async ({
  page,
}) => {
  await page.setContent(
    '<label for="first">First Name *</label><input id="first"><div><p>Cover Letter</p><input id="cover" type="file" aria-label="file-input"></div><div><p>Resume</p><input id="resume" type="file" aria-label="file-input" required></div>',
  );
  let scanned = await page.evaluate(domTask, { op: "scan" });
  expect(scanned.fields[0].required).toBe(true);
  expect(scanned.fields.find((f) => f.selector === "#cover").label).toBe(
    "Cover Letter",
  );
  expect(scanned.fields.find((f) => f.selector === "#resume").label).toBe(
    "Resume",
  );
  await page.evaluate(() => {
    document.querySelector("#resume")!.outerHTML =
      '<span>tailored.pdf</span><button aria-label="remove file">Remove</button>';
  });
  scanned = await page.evaluate(domTask, { op: "scan" });
  expect(scanned.attachments).toEqual([
    { kind: "resume", name: "tailored.pdf", frameId: 0 },
  ]);
  expect(scanned.fields.find((f) => f.selector === "#resume")).toBeUndefined();
});
test("verification inspection reads checked and expired indicators without touching response tokens", async ({
  page,
}) => {
  await page.setContent(
    '<div id="recaptcha-anchor" role="checkbox" aria-checked="true" style="width:28px;height:28px"></div><textarea id="g-recaptcha-response">must-not-be-read</textarea>',
  );
  expect(await page.evaluate(readRecaptchaIndicator)).toEqual({
    checked: true,
    error: false,
  });
  await page.evaluate(() =>
    document.body.insertAdjacentHTML(
      "beforeend",
      '<div class="rc-anchor-error-msg">Verification expired</div>',
    ),
  );
  expect(await page.evaluate(readRecaptchaIndicator)).toEqual({
    checked: true,
    error: true,
  });
  await page.evaluate(() =>
    document
      .querySelector("#recaptcha-anchor")!
      .setAttribute("aria-checked", "false"),
  );
  expect((await page.evaluate(readRecaptchaIndicator)).checked).toBe(false);
});

test("single-page required controls, dropdowns, radio groups, upload and verified success", async ({
  page,
}) => {
  await page.setContent(`<form onsubmit="event.preventDefault();document.body.innerHTML='<h1>Your application has been received</h1>'">
  <label for="first">First name</label><input id="first" required>
  <label for="country">Country</label><select id="country" required><option value="">Choose</option><option value="ca">Canada</option></select>
  <fieldset><legend>Work arrangement</legend><label><input type="radio" name="work" value="remote" required>Remote</label><label><input type="radio" name="work" value="onsite">Onsite</label></fieldset>
  <label for="resume">Resume</label><input id="resume" type="file" accept=".pdf" required>
  <button id="submit">Submit application</button></form>`);
  let s = await page.evaluate(domTask, { op: "scan" });
  expect(s.fields.length).toBe(4);
  expect(s.fields[0].required).toBe(true);
  await page.evaluate(domTask, {
    op: "fill",
    selector: "#first",
    value: "Jordan",
  });
  await page.evaluate(domTask, {
    op: "fill",
    selector: "#country",
    value: "Canada",
  });
  await page.evaluate(domTask, {
    op: "fill",
    selector: s.fields.find((f) => f.type === "radio").selector,
    value: "Remote",
  });
  await page.locator("#resume").setInputFiles({
    name: "tailored.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.4 test"),
  });
  s = await page.evaluate(domTask, { op: "scan" });
  expect(s.fields.find((f) => f.type === "file").files).toEqual([
    "tailored.pdf",
  ]);
  expect(s.fields.find((f) => f.type === "radio").value).toBe("Remote");
  // Fixture URL has an empty hostname; only the local test permits this destination.
  await page.evaluate(domTask, {
    op: "click",
    selector: "#submit",
    submit: true,
    domains: [""],
  });
  expect((await page.evaluate(domTask, { op: "scan" })).confirmation).toContain(
    "received",
  );
});
test("conditional multistep form requires a fresh scan", async ({ page }) => {
  await page.setContent(
    `<label for="experience">Experience</label><select id="experience" onchange="document.getElementById('extra').innerHTML='<label for=years>Years</label><input id=years required>'"><option value="">Choose</option><option>Yes</option></select><div id="extra"></div><button id="next" type="button" onclick="document.body.innerHTML='<label for=email>Email</label><input id=email type=email required>'">Next</button>`,
  );
  await page.evaluate(domTask, {
    op: "fill",
    selector: "#experience",
    value: "Yes",
  });
  expect(
    (await page.evaluate(domTask, { op: "scan" })).fields.map((f) => f.label),
  ).toContain("Years");
  await page.evaluate(domTask, {
    op: "click",
    selector: "#next",
    submit: false,
    domains: [],
  });
  expect((await page.evaluate(domTask, { op: "scan" })).fields[0].label).toBe(
    "Email",
  );
});
test("credentials and one-time codes are never extracted or filled", async ({
  page,
}) => {
  await page.setContent(
    '<label for="password">Password</label><input id="password" type="password" value="secret"><label for="otp">Verification code</label><input id="otp" autocomplete="one-time-code" value="123456">',
  );
  const s = await page.evaluate(domTask, { op: "scan" });
  expect(s.fields).toEqual([]);
  expect(s.blockers).toHaveLength(1);
  expect(JSON.stringify(s)).not.toContain("secret");
  expect(JSON.stringify(s)).not.toContain("123456");
  await expect(
    page.evaluate(domTask, {
      op: "fill",
      selector: "#password",
      value: "anything",
    }),
  ).rejects.toThrow(/manual/);
});
test("consent and demographic fields stay manual", async ({ page }) => {
  await page.setContent(
    '<label for="consent">I agree to the terms</label><input id="consent" type="checkbox"><label for="gender">Gender</label><input id="gender">',
  );
  await expect(
    page.evaluate(domTask, { op: "fill", selector: "#consent", value: "true" }),
  ).rejects.toThrow(/manual/);
  await expect(
    page.evaluate(domTask, { op: "fill", selector: "#gender", value: "Male" }),
  ).rejects.toThrow(/manual/);
});
test("HTML validation failure blocks final submission", async ({ page }) => {
  await page.setContent(
    '<form><label for="email">Email</label><input id="email" type="email" required><button id="submit">Submit application</button></form>',
  );
  await page.evaluate(domTask, {
    op: "fill",
    selector: "#email",
    value: "invalid",
  });
  expect((await page.evaluate(domTask, { op: "scan" })).fields[0].invalid).toBe(
    true,
  );
  await expect(
    page.evaluate(domTask, {
      op: "click",
      selector: "#submit",
      submit: true,
      domains: [""],
    }),
  ).rejects.toThrow(/validation/);
});
test("session expiration, CAPTCHA and unavailable jobs pause", async ({
  page,
}) => {
  await page.setContent(
    '<p>Your session has expired</p><iframe title="CAPTCHA" src="about:blank"></iframe><p>This position has been filled</p>',
  );
  const s = await page.evaluate(domTask, { op: "scan" });
  expect(s.blockers).toHaveLength(3);
});
test("invisible verification frames (Indeed) are not a CAPTCHA to solve", async ({
  page,
}) => {
  await page.setContent(
    '<iframe title="reCAPTCHA" src="about:blank#size=invisible" width="256" height="60"></iframe>' +
      '<div style="visibility:hidden"><iframe title="hCaptcha challenge" src="about:blank" width="400" height="580"></iframe></div>' +
      '<iframe title="CAPTCHA" src="about:blank" width="1" height="1"></iframe>' +
      '<iframe title="CAPTCHA" src="about:blank" style="position:absolute;top:-10000px" width="300" height="150"></iframe>',
  );
  const s = await page.evaluate(domTask, { op: "scan" });
  expect(s.blockers).toEqual([]);
});
test("Indeed review page reports the resume it would send and finds its Edit control", async ({
  page,
}) => {
  // domTask only treats smartapply.indeed.com as Indeed; serve the fixture there.
  await page.route("https://smartapply.indeed.com/**", (route) =>
    route.fulfill({
      contentType: "text/html",
      body:
        '<main><h1>Review your application</h1>' +
        '<section><div><h2>Contact information</h2><a href="#c">Edit</a></div><p>Keerthivasan Kalaivanan</p></section>' +
        '<section><div><h2>Resume</h2><a href="#d">Download</a><button id="edit-resume" onclick="this.dataset.clicked=1">Edit</button></div>' +
        '<div><span>kk_DWS_StructuredCablingTechnician.pdf</span></div></section>' +
        '<section><div><h2>Supporting documents</h2><button id="add-docs" onclick="this.dataset.clicked=1">Add</button></div>' +
        '<p>No cover letter or additional documents added. This is optional to add.</p></section>' +
        '<button>Submit your application</button></main>',
    }),
  );
  await page.goto("https://smartapply.indeed.com/beta/indeedapply/form/review-module");
  const s = await page.evaluate(domTask, { op: "scan" });
  expect(s.attachments).toEqual([
    { kind: "resume", name: "kk_DWS_StructuredCablingTechnician.pdf", frameId: 0, shownByIndeed: true },
  ]);
  await page.evaluate(domTask, { op: "indeedPart", part: "Resume", action: "Edit" });
  expect(await page.getAttribute("#edit-resume", "data-clicked")).toBe("1");
  expect(await page.getAttribute("#add-docs", "data-clicked")).toBeNull();
  await page.evaluate(domTask, { op: "indeedPart", part: "Supporting documents", action: "Add" });
  expect(await page.getAttribute("#add-docs", "data-clicked")).toBe("1");
});
test("Indeed review sections inside nested shadow roots are still read and clicked", async ({
  page,
}) => {
  await page.route("https://smartapply.indeed.com/**", (route) =>
    route.fulfill({
      contentType: "text/html",
      body:
        '<main><h1>Review your application</h1><review-sections id="host"></review-sections>' +
        '<button>Submit your application</button></main><script>' +
        'const host=document.getElementById("host").attachShadow({mode:"open"});' +
        'host.innerHTML=`<section><div><h2>Contact information</h2><button>Edit</button></div></section>' +
        '<section id="resume"><div><h2>Resume</h2><button id="edit">Edit</button></div><file-card id="card"></file-card></section>' +
        '<section><div><h2>Supporting documents</h2><button id="add">Add</button></div></section>`;' +
        'host.getElementById("card").attachShadow({mode:"open"}).innerHTML="<span>kk_DWS_StructuredCablingTechnician.pdf</span>";' +
        'host.getElementById("edit").onclick=()=>document.body.dataset.edit=1;' +
        '</script>',
    }),
  );
  await page.goto("https://smartapply.indeed.com/beta/indeedapply/form/review-module");
  const s = await page.evaluate(domTask, { op: "scan" });
  expect(s.attachments.map((a: any) => [a.kind, a.name])).toEqual([["resume", "kk_DWS_StructuredCablingTechnician.pdf"]]);
  expect(s.diagnostics.shadowRoots).toBe(2);
  await page.evaluate(domTask, { op: "indeedPart", part: "Resume", action: "Edit" });
  expect(await page.getAttribute("body", "data-edit")).toBe("1");
});
test("Apply in same tab and popup both navigate with observable application forms", async ({
  page,
  context,
}) => {
  await context.route("https://fixture.example/**", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: '<label for="name">Full name</label><input id="name">',
    }),
  );
  await page.setContent(
    '<a id="apply" href="https://fixture.example/form" target="_blank">Apply</a>',
  );
  const popupPromise = context.waitForEvent("page");
  await page.evaluate(domTask, {
    op: "click",
    selector: "#apply",
    submit: false,
    domains: ["fixture.example"],
  });
  const popup = await popupPromise;
  await popup.waitForLoadState();
  expect((await popup.evaluate(domTask, { op: "scan" })).fields[0].label).toBe(
    "Full name",
  );
  await page.setContent(
    '<a id="apply" href="https://fixture.example/form">Apply</a>',
  );
  await page.evaluate(domTask, {
    op: "click",
    selector: "#apply",
    submit: false,
    domains: ["fixture.example"],
  });
  await page.waitForURL("https://fixture.example/form");
  expect((await page.evaluate(domTask, { op: "scan" })).fields[0].label).toBe(
    "Full name",
  );
});
test("unknown submit controls are not treated as navigation", async ({
  page,
}) => {
  await page.setContent('<form><button id="apply">Apply now</button></form>');
  await expect(
    page.evaluate(domTask, {
      op: "click",
      selector: "#apply",
      submit: false,
      domains: [""],
    }),
  ).rejects.toThrow(/review/);
});


test("nested UKG shadow controls can be scanned and clicked by the app", async ({page}) => {
  await page.setContent('<ukg-shell id="shell"></ukg-shell>');
  await page.evaluate(() => {
    const outer = document.querySelector('#shell')!.attachShadow({mode:'open'});
    outer.innerHTML = '<ukg-apply id="component"></ukg-apply>';
    const inner = outer.querySelector('#component')!.attachShadow({mode:'open'});
    inner.innerHTML = '<button id="apply" type="button">Apply now</button>';
    inner.querySelector('button')!.addEventListener('click', () => document.body.setAttribute('data-applied', 'yes'));
  });
  const snapshot = await page.evaluate(domTask, {op:'scan'});
  const apply = snapshot.buttons.find(b => b.label === 'Apply now');
  expect(apply.selector).toBe('#shell >>> #component >>> #apply');
  await page.evaluate(domTask, {op:'click', selector:apply.selector, submit:false});
  await expect(page.locator('body')).toHaveAttribute('data-applied','yes');
});


test("custom Province dropdown is required, fills from an exact observed option and is verified", async ({page}) => {
  await page.setContent('<div><label>Province*</label><button id="province" type="button" aria-haspopup="listbox">–Select–</button></div>');
  await page.evaluate(() => {
    const button=document.querySelector('#province')!;
    button.addEventListener('click',()=>{
      if(document.querySelector('[role=listbox]')) return;
      const options=document.createElement('div');options.setAttribute('role','listbox');
      options.innerHTML='<button type="button" role="option">Ontario</button><button type="button" role="option">Alberta</button>';
      options.addEventListener('click',event=>{button.textContent=(event.target as HTMLElement).textContent;options.remove();});
      document.body.append(options);
    });
  });
  let snapshot=await page.evaluate(domTask,{op:'scan'});
  expect(snapshot.fields[0]).toMatchObject({label:'Province*',type:'custom-select',required:true,value:''});
  await page.evaluate(domTask,{op:'fill',selector:'#province',value:'Ontario'});
  snapshot=await page.evaluate(domTask,{op:'scan'});
  expect(snapshot.fields[0].value).toBe('Ontario');
  await expect(page.evaluate(domTask,{op:'fill',selector:'#province',value:'Unknown'})).rejects.toThrow(/exact/);
});

test("Workday upload receipts and repeated history controls have stable source context", async ({page}) => {
  await page.setContent(`<section><h2>Resume/CV</h2><input type="file"><div><span>tailored.pdf</span><p>Successfully Uploaded!</p><button aria-label="Delete">trash</button></div></section>
  <div data-automation-id="workExperience-1"><label for="workExperience-1--company">Company*</label><input id="workExperience-1--company" value="Example"><div data-automation-id="startDate"><label for="workExperience-1--startDate-month">Month</label><input id="workExperience-1--startDate-month"></div></div>`);
  const snap = await page.evaluate(domTask, {op:'scan'});
  expect(snap.attachments).toEqual([{kind:'resume',name:'tailored.pdf',frameId:0}]);
  expect(reviewProblems(Snapshot.parse({...snap,fields:snap.fields.filter(f => f.type === 'file').map(f => ({...f,required:true}))}))).toEqual([]);
  expect(snap.fields.find(f => f.selector === '#workExperience-1--company').history).toEqual({section:'experience',index:0,key:'company'});
  expect(snap.fields.find(f => f.selector === '#workExperience-1--startDate-month').history.key).toBe('startMonth');
});

test('closed postings and expired session links are classified separately',async({page})=>{
 for(const message of ['This job has expired','We are no longer accepting applications','404 Page not found']){
  await page.setContent(`<main><h1>${message}</h1></main>`);
  expect((await page.evaluate(domTask,{op:'scan'})).blockers).toContain('Opportunity unavailable.');
 }
 for(const message of ['Your session has expired','This link is no longer active','Page not found']){
  await page.setContent(`<main><h1>${message}</h1></main>`);
  const result=await page.evaluate(domTask,{op:'scan'});
  expect(result.blockers).toContain('Session expired: sign in in Chrome.');
  expect(result.blockers).not.toContain('Opportunity unavailable.');
 }
});

test('Dayforce education, dates and work rows retain separate context',async({page})=>{
 await page.setContent('<label for="jobPostingApplication_educationHistory_0_degreeName">Degree</label><input id="jobPostingApplication_educationHistory_0_degreeName" required><label for="jobPostingApplication_educationHistory_0_majorName">Major</label><input id="jobPostingApplication_educationHistory_0_majorName"><label for="jobPostingApplication_workHistory_0_title">Position Title</label><input id="jobPostingApplication_workHistory_0_title">');
 const result=await page.evaluate(domTask,{op:'scan'});
 expect(result.fields[0].history).toEqual({section:'education',index:0,key:'credential',orderedBlankRow:true});
 expect(result.fields[0].label).toBe('Education 1 · Degree');expect(result.fields[1].label).toBe('Education 1 · Major');expect(result.fields[2].history.section).toBe('experience');
});
