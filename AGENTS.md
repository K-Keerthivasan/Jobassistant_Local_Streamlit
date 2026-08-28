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
- Complete one application workflow at a time. After its final outcome is recorded, return to the Resume Studio main page and continue with the next eligible unfinished job.

## Application workflow

### Default assistance scope

- By default, provide targeted help only for the exact application question, technical question, or form section the user identifies. Do not inspect, prepare, fill, or manage the rest of the application unless the user explicitly asks for full-application assistance in that conversation.
- For targeted help, answer concisely using verified candidate facts, the job description, and any answer choices the user provides. Ask only for genuinely missing information and never guess candidate facts.
- Do not invoke the full Resume Studio application-preparation workflow for a targeted question unless it is necessary to retrieve an already-confirmed fact or save a user-confirmed reusable answer.

1. Confirm the company, title, URL, description, generated run, and that the job is not already applied.
2. Use Resume Studio MCP for the candidate queue, job facts, generated documents, field plans, decisions, and tracking. Use browser control only for Resume Studio and the live employer page. Do not use or propose a Rapid Apply/Tampermonkey application userscript.
3. Use the user's main regular Google Chrome profile and reuse its signed-in session or user-approved password-manager autofill. Never substitute a test, temporary, in-app, or automation-only browser profile unless the user explicitly requests it for that application. Never request that a password be pasted into chat.
4. Inspect the visible form and prepare the application through Resume Studio.
5. Upload the generated resume and cover letter and assign their correct document types.
6. Fill only verified profile facts, previously confirmed answers, and truthful document-derived work or education history.
7. At login, CAPTCHA, consent, legal attestation, demographic questions, missing required facts, or ambiguous screening choices, leave the page open and ask the user to complete or confirm that blocker. Resume when the user says it is done.
8. When a form field is blank, missing from the confirmed profile, ambiguous, consent-related, or demographic, do not ask Resume Studio or another model to draft or infer an answer. Leave it for the user to fill in the open browser. After the user confirms the entry, save reusable facts and screening answers to `data/apply_profile.json` through Resume Studio so future applications can reuse them.
9. Do not opt into marketing, SMS, talent pools, or optional data sharing. Leave voluntary demographic and disability fields unanswered unless the user explicitly chooses otherwise for that application.
10. Before final submission, show the exact job, documents, answers, blanks, and warnings and ask: `Submit this exact application: yes or no?`
11. Submit only after a fresh explicit `yes` for that exact prepared session and only when Resume Studio reports `may_submit=true`.
12. Verify the employer site's visible success state before recording `submitted`. Otherwise record the observed result as failed or rejected.

## Communication

- Use a human-in-the-loop cadence: work autonomously until a genuine blocker, then give the user one concise action to perform in the open browser.
- Do not send application emails.
- Keep the browser on the current blocker or review screen until the user responds.
