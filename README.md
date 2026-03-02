# Job Fit Assessment

Automated candidate-job fit evaluation powered by [CrewAI](https://crewai.com) agents. Provide a job posting URL and a resume PDF, and three AI agents will extract requirements, analyze the candidate, and produce a structured fit report.

## How It Works

The system runs a CrewAI Flow with three sequential agents:

1. **Skill Extraction Specialist** — Scrapes the job posting URL using Firecrawl and extracts the job title, company name, and required skills.
2. **Resume Analyzer** — Reads the candidate's resume PDF using RAG (PDFSearchTool) and scores the candidate against the extracted requirements, identifying strengths and gaps.
3. **Report Writer** — Compiles findings into a structured markdown report with fitness score, strengths, missing skills, and an overall assessment.

## Project Structure

```
template_job_fit_assessment/
├── src/template_job_fit_assessment/
│   └── main.py              # CrewAI flow with 3 agents
├── frontend/
│   ├── app.py               # Flask server (API proxy)
│   ├── templates/index.html  # Web UI
│   ├── static/style.css      # Styling
│   ├── requirements.txt      # Flask dependencies
│   ├── Procfile              # Heroku deployment
│   └── .env                  # API credentials (not committed)
├── pyproject.toml            # CrewAI project config
└── .env                      # API keys (not committed)
```

## Prerequisites

- Python >= 3.11
- [uv](https://docs.astral.sh/uv/) package manager
- API keys:
  - `OPENAI_API_KEY` — for the LLM agents
  - `FIRECRAWL_API_KEY` — for scraping job postings

## Setup

### CrewAI Flow (backend)

```bash
# Install dependencies
uv sync

# Set API keys in .env
OPENAI_API_KEY=sk-...
FIRECRAWL_API_KEY=fc-...
```

The flow is deployed to CrewAI AMP and triggered via its API. To run locally:

```bash
uv run kickoff
```

### Flask Frontend

```bash
cd frontend

# Install dependencies
pip install -r requirements.txt

# Configure .env with your AMP credentials
CREWAI_API_URL=https://your-deployment.crewai.com
CREWAI_BEARER_TOKEN=your-token

# Run the server
python app.py
```

Open `http://localhost:5001`.

## API Flow

The frontend communicates with CrewAI AMP through two proxy endpoints:

1. **`POST /api/kickoff`** — Receives the job URL and resume PDF, base64-encodes the PDF, and forwards to CrewAI AMP's `/kickoff` endpoint. Returns a `kickoff_id`.

2. **`GET /api/status/<kickoff_id>`** — Polls CrewAI AMP's `/status` endpoint until the flow completes, then returns the markdown report.

## Deployment

### CrewAI AMP (backend)

```bash
crewai deploy
```

### Heroku (frontend)

The `frontend/` directory includes a `Procfile` for Heroku. Set `CREWAI_API_URL` and `CREWAI_BEARER_TOKEN` as config vars.

## Report Output

The generated report follows this structure:

- **Position** — Company and job title
- **Candidate** — Name only (PII redacted)
- **Required Skills** — Full list from the posting
- **Fitness Score** — X/100 with interpretation
- **Strengths** — Matched skills
- **Gaps / Missing Skills** — Unmatched requirements
- **Summary** — 2-3 sentence overall assessment
