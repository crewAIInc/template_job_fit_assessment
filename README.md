# Job Fit Assessment

Automated candidate-job fit evaluation powered by [CrewAI](https://crewai.com) agents. Provide a job posting URL and a resume PDF, and three AI agents will extract requirements, analyze the candidate, and produce a structured fit report.

## How It Works

The system runs a CrewAI Flow with three sequential agents:

1. **Skill Extraction Specialist** — Scrapes the job posting URL using Firecrawl and extracts the job title, company name, and required skills.
2. **Resume Analyzer** — Reads the candidate's resume PDF using RAG (PDFSearchTool) and scores the candidate against the extracted requirements, identifying strengths and gaps.
3. **Report Writer** — Compiles findings into a structured markdown report with fitness score, strengths, missing skills, and an overall assessment.

Progress updates are delivered in real-time via webhooks and Server-Sent Events (SSE) — the flow's event listener POSTs step updates to the frontend, which pushes them to the browser as each agent starts and finishes.

## Project Structure

```
template_job_fit_assessment/
├── src/template_job_fit_assessment/
│   ├── main.py                # CrewAI flow with 3 agents
│   └── events/
│       └── listener.py        # WebhookEventListener (posts step updates)
├── frontend/
│   ├── app.py                 # Flask server (webhook receiver + SSE)
│   ├── templates/index.html   # Web UI
│   ├── static/style.css       # Styling
│   ├── requirements.txt       # Flask dependencies
│   ├── Procfile               # Heroku deployment
│   └── .env                   # API credentials (not committed)
├── pyproject.toml             # CrewAI project config
└── .env                       # API keys (not committed)
```

## Prerequisites

- Python >= 3.11
- [uv](https://docs.astral.sh/uv/) package manager
- API keys:
  - `OPENAI_API_KEY` — for the LLM agents
  - `FIRECRAWL_API_KEY` — for scraping job postings

## Local Development

### 1. CrewAI Flow (backend)

```bash
# Install dependencies
uv sync

# Set API keys in .env
cp .env.example .env
# Edit .env:
#   OPENAI_API_KEY=sk-...
#   FIRECRAWL_API_KEY=fc-...
#   WEBHOOK_URL=http://localhost:5001/webhook/messages

# Run locally
uv run kickoff
```

### 2. Flask Frontend

```bash
cd frontend

# Install dependencies
pip install -r requirements.txt

# Configure .env with your AMP credentials
cp .env.example .env
# Edit .env:
#   CREWAI_API_URL=https://your-deployment.crewai.com
#   CREWAI_BEARER_TOKEN=your-token

# Run the server
python app.py
```

Open `http://localhost:5001`.

## API Endpoints

### Browser-facing

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/warmup` | POST | Pings AMP `/inputs` to warm up the deployment |
| `/api/kickoff` | POST | Receives job URL + resume PDF, forwards to AMP, returns `session_id` and `kickoff_id` |
| `/api/stream/<session_id>` | GET | SSE stream — pushes real-time step updates and final report |
| `/api/status/<kickoff_id>` | GET | Fallback polling endpoint — proxies to AMP status API |

### Webhook (called by the flow's event listener)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/webhook/messages` | POST | Receives step updates and final report from `WebhookEventListener` |

## Deployment

### CrewAI AMP (backend)

```bash
crewai deploy create
```

Set these environment variables in AMP:
- `OPENAI_API_KEY`
- `FIRECRAWL_API_KEY`
- `WEBHOOK_URL` — your Heroku app's webhook URL (see below)

### Heroku (frontend)

```bash
# From the project root (template_job_fit_assessment/)
git subtree push --prefix frontend heroku main
```

Set these config vars on Heroku:

```bash
heroku config:set CREWAI_API_URL=https://your-deployment.crewai.com
heroku config:set CREWAI_BEARER_TOKEN=your-token
```

Your webhook URL is `https://<your-app>.herokuapp.com/webhook/messages` — set this as `WEBHOOK_URL` in AMP.

### Connecting the two

Once both are deployed:

1. Copy your Heroku app URL (e.g., `https://my-app.herokuapp.com`)
2. In AMP, set `WEBHOOK_URL=https://my-app.herokuapp.com/webhook/messages`
3. Redeploy the flow on AMP so it picks up the new env var

## Report Output

The generated report follows this structure:

- **Position** — Company and job title
- **Candidate** — Name only (PII redacted)
- **Required Skills** — Full list from the posting
- **Fitness Score** — X/100 with interpretation
- **Strengths** — Matched skills
- **Gaps / Missing Skills** — Unmatched requirements
- **Summary** — 2-3 sentence overall assessment
