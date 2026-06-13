# Setup

End-to-end setup for every component. Windows + Docker Desktop is the reference
environment; adjust paths for other OSes.

## 0. Prerequisites

- **Docker Desktop** (containers reach the host via `host.docker.internal`).
- **Ollama** on the host with a model pulled: `ollama pull qwen3:8b`.
- **Python 3.11** (for the CLI / local dev).
- A Chromium/Firefox browser with **Tampermonkey** (for the scraper).

## 1. Resume Studio (generator + web app)

```powershell
cd Automatic-Resume-Generator
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -e .
copy .env.example .env        # set OLLAMA_MODEL, OUTPUT_DIR, etc.

docker compose -f docker/docker-compose.yml up -d --build
```

- App: <http://localhost:8088/>  · API docs: <http://localhost:8088/docs>
- The container reaches host Ollama at `host.docker.internal:11434` (already set in
  the compose). PDF uses LibreOffice inside the container.
- `data/` and `output/` are bind-mounted, so the CLI and the container share state.

### Your profile (required, truth source)

Edit `data/profile/master_profile.yaml`:
- `contact.links` — **keep short**; every link appears on every resume.
- `skills` — grouped inventory (technical + the `marketing` / `sales_service` /
  `creative_media` / `office_admin` groups used by non-tech personas).
- `experience[].facts` — the only material bullets may be drawn from.
- Mark a role `preserve: true` to stop it being recast (e.g. a collections role
  must not become "sales").

### Personas (optional but recommended)

`data/profile/personas.yaml` maps job keywords → a role framing. See
[`personas.md`](personas.md). Nothing else to do; the app auto-detects and you can
override from the sidebar **Persona** picker.

## 2. Scraper collector (dashboard + store)

Separate app (default path `F:\AI\Resume_Scraper`):

```powershell
cd F:\AI\Resume_Scraper
docker compose up -d --build        # serves the dashboard + /api/jobs on :8765
# (or run directly:  python Scraper.py serve 0.0.0.0 8765)
```

- Dashboard: <http://localhost:8765/> (also embedded in Resume Studio's **Scraper** tab).
- Jobs are stored as CSV under `job_data/` (bind-mounted, gitignored).

## 3. Tampermonkey userscript (LinkedIn + Indeed)

1. Install **Tampermonkey** in your browser.
2. Open `tampermonkey/tampermonkey.user.js` (drag into the browser, or paste into a
   new Tampermonkey script) and install it.
3. Set your real `MY_INFO` (email/phone) at the top for auto-fill.
4. Visit a LinkedIn or Indeed job — a "Local Job Capture" panel appears; **Save Job**
   (or `Alt+Shift+S`) sends it to the collector.

The collector must be running on `:8765`. The script connects to `127.0.0.1:8765`.

## 4. Job sources / intake

Copy and edit the sources config (gitignored):

```powershell
copy data\sources.sample.yaml data\sources.yaml
```

- `type: collector` — pulls jobs you saved via the userscript.
- `type: apify` — runs a job-scraping actor (needs `APIFY_TOKEN` in `.env`).
- `type: greenhouse | lever | workday | generic` — ATS boards.
- `filters.canada_only: true` keeps Canadian postings only (see [scraper.md](scraper.md)).

Run intake from the **Scraper** tab ("🔄 Fetch new jobs") or `POST /intake/run`.

## 5. n8n (optional automation)

n8n runs in its own container. Point HTTP Request nodes at
`http://host.docker.internal:8088` (NOT `localhost` — inside a container that's the
container itself). See [`api.md`](api.md) for the endpoints to wire.

## Environment variables (`.env`)

| Var | Default | Notes |
|-----|---------|-------|
| `OLLAMA_HOST` | `http://localhost:11434` | container overrides to `host.docker.internal` |
| `OLLAMA_MODEL` | `qwen3:8b` | default generation model |
| `OLLAMA_TEMPERATURE` | `0.3` | |
| `OUTPUT_DIR` | `output` | generated application folders |
| `INTAKE_DIR` | `data/intake` | dedup store + review queue |
| `APIFY_TOKEN` | — | required only for `type: apify` sources |
| `PDF_ENGINE` | `auto` | `libreoffice` in the container |

## Verify

```powershell
curl http://localhost:8088/health     # {"ollama": true, ...}
curl http://localhost:8765/           # collector dashboard (HTTP 200)
```
