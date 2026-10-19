# Resume Studio Application Workflow

These are durable project instructions for job-application work in this repository.

## Candidate facts and memory

- Treat `data/apply_profile.json` and Resume Studio as the source of truth for candidate facts and reusable application answers.
- Save newly user-confirmed profile facts and screening answers back to `data/apply_profile.json` so future applications can reuse them.
- Never guess, inflate, or change facts to match a posting.
- For all job-application website work, use the user's **main regular Google Chrome profile** through Chrome browser control so existing logins, autofill, and the user's password manager are available.
- Do not use `resume_studio_browser`, its `.pw-profile`, temporary Chromium, the in-app test browser, or any other automation-only browser profile for job applications unless the user explicitly asks for that browser in the current conversation.
- The user authorizes saving website credentials through either the ChatGPT desktop app's built-in browser password manager or the password manager in their regular Chrome or Edge profile, when the user personally enters and approves saving them. Never store or reproduce passwords, one-time codes, recovery codes, cookies, or authentication tokens in this repository, Resume Studio data, chat, logs, or generated files.

## Job queue

- Start from Resume Studio at `http://127.0.0.1:8088`.
- Work on jobs that are generated, not applied, and found or posted within the past seven days.
- Prefer live direct employer/ATS application URLs over LinkedIn or Indeed intermediary pages.
- Skip or flag jobs whose employer page says the opportunity is unavailable.
- Drive one application at a time. If facts are missing, ask the exact questions in this chat, defer that application as pending (not failed or rejected), and continue to the next eligible job. Save replies through Resume Studio and revisit pending work without guessing. Exclude Canada Life unless the user changes that instruction.

## Application workflow

### Default assistance scope

- By default, provide targeted help only for the exact application question, technical question, or form section the user identifies. Do not inspect, prepare, fill, or manage the rest of the application unless the user explicitly asks for full-application assistance in that conversation.
- For targeted help, answer concisely using verified candidate facts, the job description, and any answer choices the user provides. Ask only for genuinely missing information and never guess candidate facts.
- Do not invoke the full Resume Studio application-preparation workflow for a targeted question unless it is necessary to retrieve an already-confirmed fact or save a user-confirmed reusable answer.

1. Confirm the company, title, URL, description, generated run, and that the job is not already applied.
2. Use Resume Studio MCP for the candidate queue, job facts, generated documents, field plans, decisions, and tracking. Use browser control only for Resume Studio and the live employer page. Do not use or propose a Rapid Apply/Tampermonkey application userscript.
3. Use the user's main regular Google Chrome profile and reuse its signed-in session or user-approved password-manager autofill. Never substitute a test, temporary, in-app, or automation-only browser profile unless the user explicitly requests it for that application. Never request that a password be pasted into chat.
4. Inspect the visible form and prepare the application through Resume Studio.
   Check custom dropdowns and radio groups as well as native inputs, including Province and Country. The engine's field list alone is not proof that every required control is complete. Finish all edits and document uploads, verify required choices and validation messages, and present the exact review before asking the user to complete CAPTCHA. Do not change completed fields after CAPTCHA unless a real correction is necessary.
5. Upload the generated resume and cover letter and assign their correct document types.
6. Fill only verified profile facts, previously confirmed answers, and truthful document-derived work or education history.
7. At login, CAPTCHA, consent, legal attestation, demographic questions, missing required facts, or ambiguous screening choices, leave the page open and ask the user to complete or confirm that blocker. Resume when the user says it is done.
8. When a field needs an unknown fact, ask its exact question and choices in this chat and continue with the next job after deferring the blocked application. Do not draft or infer the answer. Save user-confirmed reusable facts and screening answers to `data/apply_profile.json` through Resume Studio, then automatically fill them when revisiting pending work. Login and CAPTCHA must still be completed personally in Chrome; never request secrets in chat. Consent and demographic choices remain explicit and application-specific.
9. Do not opt into marketing, SMS, talent pools, or optional data sharing. Leave voluntary demographic and disability fields unanswered unless the user explicitly chooses otherwise for that application.
10. Before final submission, show the exact job, documents, answers, blanks, and warnings and ask: `Submit this exact application: yes or no?`
11. Submit only after a fresh explicit `yes` for that exact prepared session and only when Resume Studio reports `may_submit=true`.
12. Verify the employer site's visible success state before recording `submitted`. Otherwise record the observed result as failed or rejected.

## Communication

- Use a human-in-the-loop cadence: work autonomously until a genuine blocker, then give the user one concise action to perform in the open browser.
- Do not send application emails.
- For missing facts, post a concise question in chat and defer the application so the queue can continue. For login/CAPTCHA, identify the site requiring action. Never submit pending work without its own fresh exact review approval.

## Docker verification after changes

- After app edits, rebuild and recreate the affected services in the existing Docker Compose stack and check the live health and changed behavior. Preserve persistent data; do not reset volumes. Restart only affected services so unrelated resume batches can continue.

## Extension questions and learning

- For Workday, automate preparation through the final review, but leave the final Submit click to the user. Observe confirmation afterward; never submit Workday through the agent approval endpoint.
- Fill employment and education from this application's generated tailored resume, including its tailored descriptions. Do not substitute another job's resume or invent missing months. Match repeated rows to their source entries and ask unclear values in the extension.
- Classify observed ATS/form layouts and preserve each new structural format separately without storing candidate answers in the format registry. A saved layout is not proof that every control is supported.

- Route missing application questions and unfamiliar form controls to the Chrome extension's Questions & actions section instead of Codex chat. Preserve pending applications while continuing the eligible queue.
- Let the user answer there or fill the control once in Chrome and explicitly confirm the observed value. Save through Resume Studio. Remember an answer across applications only when the user opts into reuse; otherwise scope it to that application. Never learn credentials, CAPTCHA, consent or demographic choices as reusable answers.

## Manual submission after the employer tab is closed

- When the user explicitly confirms personally submitting an application and closing its tab, record it as submitted by the user with verificationSource=user_confirmation and verified_success=false. Do not require reopening the site, invent employer-visible proof, or reapply. Keep this distinct from employer-confirmed success and retain the confirmation timestamp and audit note.

## AI-written application answers

- Use the same application engine for Indeed Easy Apply and direct company sites. AI may draft narrative answers from this job’s tailored resume and job description, with supporting candidate evidence. Unknown personal facts still require the user; job requirements never establish candidate qualifications.
- Keep AI drafts scoped to the application and show their evidence at final review. Do not promote drafts into confirmed reusable facts.
- The user clicks the final Submit on all platforms. Prepare through review and observe the confirmation afterward.


## Optional fields and website queues

- Let the user intentionally leave empty optional, non-sensitive fields blank through the extension. Store blank intent separately from answers; never fill the words 'blank' or 'N/A'. Reuse only when explicitly selected, and never bypass a required field or validation error.
- Keep Indeed and direct company/ATS queues separately selectable. A posting on Indeed is not proof that Easy Apply is offered; inspect the actual application route before deciding.


## Expired links and restart

- Distinguish expired sessions/links from unavailable job postings. Flag unavailable opportunities and defer them without recording an employer rejection; leave login/session recovery for the user.
- Restart uses the original approved job URL and the same Studio record. Refuse submitted or uncertain sessions, check for a visible success page before resetting, and clear prior review approval. Preserve audit history and keep uploads guarded if restart fails.


## Current candidate and manual-entry preferences

- The confirmed street address is 1504 Howland Ave, London. Keep the real address in forms. For new resumes use London for local jobs, Ontario for other Ontario jobs, and Canada with a clearly labelled target province for other provinces; never imply residence in a different province.
- Leave optional GPA and optional supervisor fields blank. Required supervisor details are entered by the user.
- Automatic learning requires an explicit per-field choice. Wait for a valid stable value after blur, never capture partial typing, credentials, consent or demographics, and scope employment/education answers to their matching history entry. Respect the user's reuse selection and notify when the answer is saved or the completed application is ready for review.



## Prepare known information before prompting

- This is the default for every job application and supported website, not a Buckland-specific workflow: prepare all known information first, group missing facts for the whole application wherever the form permits, preserve the user's drafts, and continue through repeated sections without requiring Update/Resume clicks for every record. Extend each ATS adapter to honor this workflow; do not claim support for untested layouts.
- On each reachable application page, upload the tailored resume first when its control is available, wait for the site's parser and re-observe the form, then fill verified profile/resume answers and upload other supplied documents before showing missing-question prompts. Show preparation progress while this runs. Ask only remaining unknown facts or unresolved controls; login and genuine technical barriers may require earlier user action.
- Suppress missing-field notifications during preparation and release them after the known-fields/upload pass. Do not ask to omit a cover letter before reaching its upload/review stage.
- For repeated education rows, collect missing dates for all resume entries together in the extension. Preserve input drafts across refreshes. Save valid education rows automatically and continue to the next missing entry; do not require the user to repeat Update/Resume for every row. Never invent exact dates from a year or academic term.

