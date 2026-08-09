# SRE Forge AI — Incident Triage Platform

SRE Forge AI is an autonomous incident triage and diagnostic platform built for Zerops submissions. It helps on-call teams resolve outages faster by turning service incidents, logs, and metrics into actionable root-cause analysis.

## Architecture

Three services deployed on Zerops:

- **`web`** — Next.js frontend. Displays active incidents and lets judges ask the AI for triage guidance.
- **`api`** — FastAPI backend. Stores incident data, exposes a triage API, and optionally calls Claude to generate detailed diagnostics.
- **`db`** — Managed PostgreSQL. Persists incident records and keeps the SRE triage state available across deployments.

## Run it locally first

This repository now supports local development using SQLite for the API, so Docker is optional.

```bash
# 1. backend
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
set DATABASE_URL="sqlite:///./sreforge_local.db"
set ANTHROPIC_API_KEY="sk-ant-..."
uvicorn main:app --reload --port 8000

# 2. frontend (new terminal)
cd frontend
npm install
set NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev
```

Open http://localhost:3000. Select an incident, refresh the incident feed, and ask questions like:

- “What is the likely root cause of this active incident?”
- “How should I stabilize this outage?”
- “What triage steps should the SRE team take first?”

The backend now pulls live incident data from GitHub Status at `https://www.githubstatus.com/api/v2/incidents.json` and upserts it into the database. On Zerops, that database is the managed PostgreSQL instance wired through `DATABASE_URL`.

This is intentionally a prototype data source: GitHub Status is being used as a live, reliable stand-in so the app can demonstrate the incident triage workflow in one weekend. The real product would point at private alerting/logs or service monitoring data.

To verify persistence, the API exposes `GET /sre/stats`, which returns the current incident count and latest stored incident timestamp.

## Deploy to Zerops

1. Push this repo to GitHub.
2. In Zerops: import the project using `zerops-project-import.yml`.
3. Replace `<your-username>` in `buildFromGit` with your GitHub repo URL, and set `ANTHROPIC_API_KEY` as a secret.
4. Deploy the `db`, `api`, and `web` services.
5. After `api` launches, set `web`'s `NEXT_PUBLIC_API_URL` to the generated API endpoint.
6. Redeploy `web` and use the `web` subdomain link as your live submission.

## Submission notes

- **Live URL**: the deployed `web` subdomain.
- **Repo**: your GitHub URL.
- **Zerops usage**: "Three-service deployment with Next.js frontend, FastAPI backend, and managed PostgreSQL on Zerops."
- **AI disclosure**: mention Claude is used for incident diagnostics when the API key is configured.
- **Demo idea**: show incident selection, a refresh cycle, and a triage question answered by SRE Forge AI.
