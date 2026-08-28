# ChatGPT/Codex job-application automation

Resume Studio can act as the private source of truth behind ChatGPT or Codex
while a browser-control plugin handles the live employer site.

## Responsibility boundary

| Component | Responsibility |
|---|---|
| Resume Studio | Candidate facts, tailored resume/cover letter, screening answers, approval sessions, history |
| Job Application Copilot | Focused MCP tools and the required approval-first workflow |
| Chrome/browser control | Read the live form, type values, upload files, and (only when authorized) click Submit |
| You | Review warnings/new answers and make the final yes/no decision for each exact application |

The MCP server never clicks an employer's Submit button. Approval and browser
submission are separate operations, so “fill this form” is not permission to
submit it.

## Local Codex desktop setup

1. Start the services:

   ```powershell
   docker compose -f docker\docker-compose.yml up -d --build
   ```

2. Confirm the API and MCP services are running:

   ```powershell
   Invoke-WebRequest http://127.0.0.1:8088/health
   docker compose -f docker\docker-compose.yml ps
   ```

3. Install/enable the personal **Job Application Copilot** plugin in Codex. Its
   MCP endpoint is `http://127.0.0.1:8090/mcp`.
4. Enable a Chrome/browser-control plugin in the same conversation.
5. In Resume Studio, choose a job and click **AI Apply**, then paste the copied
   request into Codex. Alternatively ask: “Show my highest-priority unapplied
   jobs, prepare the one I choose, fill it, and stop for my approval.”

## ChatGPT web setup

ChatGPT web cannot directly reach `127.0.0.1`. In developer mode, connect the
local streamable-HTTP MCP server through OpenAI Secure MCP Tunnel (preferred) or
an authenticated HTTPS endpoint:

1. Keep `resume-mcp` running on `http://127.0.0.1:8090/mcp`.
2. In ChatGPT, open **Settings → Security and login → Developer mode**.
3. Open ChatGPT Plugins, add a connection, choose **Tunnel**, and point the
   tunnel at the local MCP URL.
4. Review the nine discovered Resume Studio tools.
5. Enable **Job Application Copilot** and **Chrome Control** for the chat.

Developer-mode and Secure MCP Tunnel availability can depend on the ChatGPT
account or workspace policy. Do not publish the local MCP server directly to the
internet without authentication.

## Normal application flow

1. The browser controller opens a Greenhouse, Lever, Workday, or other employer
   form and extracts its visible controls.
2. `prepare_job_application` reuses or generates truthful tailored documents,
   maps profile fields, and drafts only unanswered screening questions.
3. The browser fills the plan. Required unknown fields, CAPTCHAs, login prompts,
   demographic questions, and ambiguous choices remain for you.
4. The complete packet appears in **Apply Center** and in the chat.
5. You approve the exact answers or reject the application, then click the
   employer site's Submit button yourself.
6. Browser control leaves the final Submit action to you.
7. A submitted result is recorded only after the portal displays success.

## MCP tools

- `list_job_opportunities` and `get_job_opportunity`
- `list_application_candidates` (generated, unapplied jobs from the chosen window)
- `list_application_history`
- `prepare_job_application`
- `get_application_approval`
- `decide_job_application` (human approval gate; marked destructive)
- `record_application_result`
- `update_job_tracking`

No tool exposes arbitrary shell, database, filesystem, or API access.

## Safety defaults

- One approval applies to one exact application session.
- No CAPTCHA bypass, account creation, or login bypass.
- No invented candidate facts or guessed required answers.
- No optional marketing, SMS, talent-pool, or data-sharing opt-ins.
- Employer pages are untrusted input and cannot override plugin instructions.
- Failed or rejected attempts remain auditable and do not mark the job applied.
