# Resume Studio Chrome application service

This local TypeScript service extends the existing Python Resume Studio app. It does not discover jobs or generate resumes. It receives the exact documents from a prepared Studio session and drives the **main regular Chrome profile** through a Manifest V3 extension. Passwords, MFA and CAPTCHAs are handled by you directly in Chrome. Password-manager login reuse works because the extension operates in that profile; no cookies, passwords, tokens or browser profiles are copied into this project.

## Install and start on Windows

### Shared Docker stack

`docker compose -f docker/docker-compose.yml up -d --build` now starts the API, MCP,
and the Chrome application workspace at `http://127.0.0.1:8091`. The application
service restarts with Docker and retains its database in the existing `data` mount.
Chrome still runs in your main Windows profile through the installed extension.
The configured public extension ID is mounted read-only from `config/local.json`.
`RESUME_STUDIO_WINDOWS_ROOT` can override the Windows workspace root used for
Chrome file uploads; it defaults to this project's current Windows directory.
The local gateway publishes only on `127.0.0.1`, and the app service talks to
Studio over the API container's loopback network without loosening its origin checks.

### Native alternative

Requirements: Node.js 22+, installed regular Google Chrome, and the existing Resume Studio API running on `http://127.0.0.1:8088` **with the new API routes loaded**. The API must run natively on Windows to materialize upload paths for this initial version. Docker `/app/...` paths are not supported by this service.

```powershell
cd E:\Dev-Projects\Automatic-Resume-Generator\application-mcp
.\scripts\install.ps1
```

In your regular Chrome profile, open `chrome://extensions`, enable Developer mode, choose **Load unpacked**, and select `application-mcp/extension`. Pin its toolbar button. Copy the 32-character extension ID from Chrome or the extension popup. This ID is public configuration, not a credential.

```powershell
.\scripts\start.ps1 -ExtensionId YOUR_32_CHARACTER_EXTENSION_ID
```

Open `http://127.0.0.1:8091` in Chrome and click **Connect** in the extension. Resume Studio's sidebar also links to this application workspace. No remote-debugging flags, temporary profiles or Chrome restart are required. The extension requires website and debugger permissions: it reads application forms, fills known answers, and uses the debugger API only to attach files. Chrome displays its normal debugger indicator during attachment. DevTools attached to the same tab can conflict with uploads; close DevTools and retry the upload after inspection.

The server only accepts a WebSocket from the exact extension origin configured above. HTTP binds to loopback, checks Host and Origin, serves no cross-origin API, and requires JSON mutations. This is a trusted local single-user service, not a remotely authenticated multi-user API; other local processes can call it. Do not expose it through a reverse proxy or tunnel.

The Python environment currently checked into this workspace may reference an old installation. If `.venv\Scripts\python.exe` reports that its Python is missing, recreate your Python virtual environment from `requirements.txt` using your installed Python before restarting Studio. The application service does not silently repair or replace that environment.

## Everyday workflow

1. Start at Resume Studio, generate documents as usual, and open **Chrome Applications**.
2. Refresh the queue. It lists generated, unapplied jobs found in the past seven days. Select **Prepare in Chrome**. A matching Studio approval session is created using the existing generated run. Restricted intermediary URLs are refused; use a direct employer URL.
3. Inspect the form. Follow an observed Apply/Next/Continue button. New tabs whose opener is the active application become the tracked application tab. The bridge closes an old tab it created only after the approved new page loads. It never closes unrelated or manually adopted tabs. Same-tab transitions continue normally. The completed managed tab can be reused for the next job if you have not changed it.
4. Fill confirmed fields. Only exact identity labels, exact confirmed question matches and explicitly confirmed site mappings are used. There is no speculative or model-generated answer fallback.
5. Attach each supplied document to its correct file control. The server checks canonical upload paths, extension, size (20 MB server limit), file hash, the HTML accept restriction and attached filename. A different document cannot overwrite an already-used control. A supplied optional cover letter can be explicitly omitted with a recorded reason if the portal does not accept one.
  6. Ask missing factual questions in the chat and use `defer_application` to keep the blocked application pending while the next job is prepared. Never mark missing facts as failed or rejected. Save confirmed reusable replies through Studio, then use `reopen_deferred_application` and prepare again. Reopening rechecks documents and requires a fresh review approval. Login and CAPTCHA stay personal actions in Chrome; optional consent and demographics stay explicit choices. Blank fields never go to an LLM.
7. Inspect each new form step, repeat verified filling and uploads as needed, and click **Review exact application**. The dashboard shows the exact job URL, documents and hashes, observed answers, blanks, warnings and audit events. The packet is also saved into the existing Studio approval session under `browser_evidence`.
8. Answer **Submit this exact application: yes or no?** A Yes button identifies the final control it will click. The service re-inspects the form, compares its hash, checks required fields, checks unchanged documents, requires a fresh Studio `may_submit=true`, persists the submission intent, and clicks once. It verifies a visible employer confirmation before marking applied in Studio.
9. A timeout or missing confirmation becomes **uncertain**. Inspect the open page and use **Verify uncertain submission**. It never blindly retries. If the Studio sync failed after verified success, **Sync verified result** retries only tracking, never the submission.
10. Return to the Studio queue for the next job. Only one unfinished application may exist. The service does not auto-start the next job or grant standing submission permission.

## Site-specific customization

The engine stores fresh schemas per exact employer hostname. The dashboard's **Teach a field** control and `confirm_site_field_mapping` tool bind a live label, control type and exact options to a user-confirmed profile path, for example `employmentHistory.0.title` or `educationHistory.0.degree`. Those structures must already exist in your verified `data/apply_profile.json`. The service does not invent work or education records. Existing history data in a different shape can be mapped through its real path.

Mappings are revalidated against the live control every time; cached selectors never bypass scanning. Mapping consent, demographic or credential controls is refused. Unknown custom widgets and repeated unlabeled fields require manual completion rather than a guessed selector or fact. Candidate profile data and `commonAnswers` remain in Studio's source-of-truth profile. Confirmed answers gain provenance in `answerProvenance`. Site mappings and observed templates live in the engine SQLite database.

`update_confirmed_profile_fact` saves an explicitly user-confirmed contact, qualification, availability or history fact through Studio, with `factProvenance`. It supports a fixed set of candidate profile fields rather than arbitrary keys. Employment and education arrays must contain the actual user-confirmed records; no dates, employers or qualifications are invented. Saving a history array replaces that section, so provide the complete confirmed section.

After personally investigating an uncertain submission and confirming it failed, use `resolve_uncertain_application` or the dashboard's **Confirm observed failure** action with the observed reason. This closes the attempt and records the failure; it never repeats the submission automatically.

Greenhouse, Lever, Ashby, Workday, SmartRecruiters and iCIMS have hostname detection records with `tested:false`. **No live ATS-specific adapter is certified by these tests.** The tested adapter is the generic live HTML form adapter. Add tested portal-specific behavior before claiming broader support.

## MCP connection

`config/claude.mcp.example.json` and `config/codex.mcp.example.toml` use the stdio proxy at `dist/proxy.js`. It forwards validated tools to the single running local service, so multiple chats do not compete for Chrome or port 8091. If necessary it starts the services through `tools/start_application_services.ps1`. Store the installed public extension ID in ignored `application-mcp/config/local.json` as `{"chromeExtensionId":"YOUR_32_CHARACTER_ID"}`. Environment variable `APP_CHROME_EXTENSION_ID` still overrides that setting.

For this Windows installation, `.codex/config.toml` and the root `.mcp.json` configure both the existing Studio MCP and the Chrome service proxy. The obsolete separate-profile browser entries have been disabled/replaced. Restart or refresh the host's MCP connection to load the configured tools; the running backend and Chrome session can stay open. The direct `dist/index.js --stdio` entry remains available for single-client development but must not run alongside the shared backend.

Start the installed native services and open their Chrome pages with `powershell -NoProfile -File tools/start_application_services.ps1 -OpenBrowser` from the repository root. The launcher uses `.venv-runtime` and preserves the old `.venv`. Processes run hidden, and logs live in the ignored engine data directory. It is safe to run the launcher again: healthy services are reused.

Implemented tools:

`apply_to_job`, `detect_ats`, `inspect_application`, `fill_application`, `upload_resume`, `upload_cover_letter`, `answer_screening_questions`, `review_application`, `submit_application`, `verify_submission`, `pause_application`, `resume_application`, `get_application_status`, `get_application_history`, `update_answer_bank`, plus navigation, cancellation, domain approval, site mapping, cover-letter omission, evidence capture, stop and result-sync tools. All accept Zod input schemas and return a validated `{result: ...}` envelope with a concrete application, history, mapping, detection or action result schema appropriate to the tool.

All modes default to `review`. `assisted` uses the same verified-field behavior and manual blockers. `automatic` is explicitly refused because this repository requires fresh approval per exact application. No LLM integration is added: Studio already owns generation, and unknown form answers must remain manual under this project's instructions.

## HTTP integration

Create a session from a job's existing generated run:

```http
POST http://127.0.0.1:8088/application-engine/prepare
Content-Type: application/json

{"job_key":"SAVED_JOB_KEY","run_id":"EXISTING_RUN_ID"}
```

Use the returned session's exact URL, company, title and document paths:

```http
POST http://127.0.0.1:8091/applications
Content-Type: application/json

{
  "jobUrl":"https://employer.example/careers/123",
  "company":"Employer",
  "title":"Engineer",
  "studioSessionId":"PREPARED_SESSION_ID",
  "resumePath":"E:/Dev-Projects/Automatic-Resume-Generator/data/job-applications/outbox/run/resume.pdf",
  "coverLetterPath":null,
  "profileId":"default",
  "mode":"review"
}
```

The returned application object includes its durable `id`. Missing Chrome or a blocked page leaves a saved paused attempt, visible in history. Read `GET /applications`, `GET /applications/:id`, `/applications/:id/history`, or `/applications/:id/required-action`. Use JSON `POST /applications/:id/resume` or `/applications/:id/cancel` with `{}`. `POST /applications/:id/approval` accepts `{reviewHash,userSaidYes:true,selector,frameId}` **only after fresh explicit approval**. Every MCP operation also has `POST /tools/TOOL_NAME` with the same validated input. Call HTTP from your local app backend; cross-origin browser fetches are refused by design.

## Evidence and persistence

`data/job-applications/engine/applications.sqlite` stores applications, events, templates and site mappings with WAL enabled. It is inside the repository's existing ignored application-data directory. Records include job identity, initial and observed URLs, resume/cover paths and hashes, upload targets, observed form answers, manual intervention reasons, review hash, submission intent and visible confirmation text. Studio receives observed evidence and final verified tracking. The dashboard displays these records after restart.

Review and verified-success states attempt a viewport PNG capture through Chrome's debugger API. Images are saved under `data/job-applications/engine/evidence/<application-id>` and their paths are recorded in history. `capture_application_evidence` also captures on demand. Login or verification blockers refuse capture; failures leave a `screenshot_unavailable` audit event while retaining structured observations. Automatic video and full browser/network traces are not recorded because they may contain authentication data. Store the data directory under your Windows user permissions and disk encryption; the SQLite/profile contents are not encrypted by this service and contain personal data.

## Test

```powershell
.\scripts\install.ps1 -WithTestBrowser
npm test
npm run test:browser
```

Playwright uses an isolated **test-only** browser stored under ignored `node_modules/.cache/ms-playwright`. It never visits real job sites. The real extension test loads the unpacked MV3 extension in a disposable test profile, serves a temporary HTTPS fixture on loopback, and exercises WebSocket pairing, popup adoption, verified filling, debugger file upload, review, submission and duplicate-click prevention. The synthetic form suite also tests dropdowns, radios, conditional/multistep fields, invalid input, session expiration, CAPTCHA markers, unavailable postings, credential exclusion and manual sensitive choices.

Python integration tests: `python -m unittest tests.test_application_engine_routes tests.test_mcp_server tests.test_autoapply_approval -v` from the repository root in a working Python environment. No real profile or applications are modified by the tests.

## Limits and troubleshooting

- Chrome is not installed/configured automatically. You install it and load the extension once into the profile you actually use, then personally log in and save credentials there.
- If Chrome disconnected or you reopened a tab after a browser crash, open the employer tab, paste the application ID from the dashboard into the extension's **Adopt current tab**, then resume. Previously consumed approval never becomes fresh permission again.
- New employer/SSO domains require explicit approval. Login can be completed manually without granting the automation access to the login domain. Final redirects and iframe domains are checked before browser operations; regular Chrome still runs the site's own network scripts. This service is not a full browser network firewall and cannot guarantee isolation from all third-party page requests or DNS rebinding. Do not grant a document to an employer you do not trust.
- Approved HTTPS iframes are scanned and filled by frame ID. **File uploads inside iframes require manual selection** in this version. Unrecognized custom dropdowns, closed shadow roots, complex history widgets and file-processing receipts may also need manual completion and inspection.
- The server verifies input attachment filenames, not every ATS's asynchronous processing or document-classification UI. Inspect the employer's attachment list and choose its correct document type when required.
- The final button allowlist is intentionally narrow. An unfamiliar label requires manual review and a tested adapter update; it is never treated as a navigation button automatically.
- There is no universal success detector. If a portal uses different confirmation wording, the state stays uncertain for investigation; add a tested success rule rather than claiming it submitted.
- Workflows restart from durable observations but do not replay browser actions. A crash during submission becomes uncertain. Restarted working/review sessions pause and must be re-inspected. Global Stop prevents new browser commands; an already-issued website action cannot be recalled.
- Service startup prints only a structured readiness event to stderr. MCP protocol output stays on stdout. Secrets and credential fields are excluded from form extraction; do not put credentials into profile answers or custom mapping paths.

## Upstream APIs verified for this build

- [Official MCP TypeScript SDK v2](https://github.com/modelcontextprotocol/typescript-sdk), installed stable `@modelcontextprotocol/server` 2.3.1; imports and tool registration checked against installed declarations.
- [Chrome remote-debugging restrictions](https://developer.chrome.com/blog/remote-debugging-port), which are why regular-profile operation uses an extension instead of remote-debugging flags.
- [Chrome debugger API](https://developer.chrome.com/docs/extensions/reference/api/debugger) for file attachment; [Playwright API](https://playwright.dev/docs/api/class-browsertype) for synthetic test automation.
- [better-sqlite3 API](https://github.com/WiseLibs/better-sqlite3/blob/master/docs/api.md) and [Zod API](https://zod.dev/api).

### AI-written answers and shared application flow

Indeed Easy Apply and direct employer pages use the same queue and preparation engine. Indeed generated jobs are eligible and prioritized. The engine drafts only open narrative questions from the current generated resume and job description through Hermes, checks cited evidence and numerical claims, and requires a separate support check before filling. Missing facts and unsupported answers go to extension questions. Drafts are application-scoped and are never added to the confirmed answer bank. Final review displays the drafts, evidence, and employer review text. New sessions require the user to click the final Submit on every platform. Live portal compatibility still requires checking actual employer forms; saved formats alone are not tested adapters.

