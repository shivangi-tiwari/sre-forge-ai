import os
import uuid
from datetime import datetime
from typing import List, Optional

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, String, Text, DateTime, case
from sqlalchemy.orm import sessionmaker, declarative_base
import anthropic

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./sreforge_local.db")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
WATCHED_REPOS = [repo.strip() for repo in os.environ.get("WATCHED_REPOS", "").split(",") if repo.strip()]

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class Incident(Base):
    __tablename__ = "incidents"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    incident_key = Column(String, unique=True, nullable=False)
    title = Column(String, nullable=False)
    service = Column(String, nullable=False)
    severity = Column(String, nullable=False)
    status = Column(String, nullable=False)
    started_at = Column(DateTime, nullable=False)
    summary = Column(Text, nullable=True)
    logs = Column(Text, nullable=True)
    metrics = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


Base.metadata.create_all(bind=engine)

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class IncidentOut(BaseModel):
    id: str
    incident_key: str
    title: str
    service: str
    severity: str
    status: str
    started_at: datetime
    summary: Optional[str] = None
    logs: Optional[str] = None
    metrics: Optional[str] = None

    class Config:
        orm_mode = True


class DiagnoseRequest(BaseModel):
    incident_id: Optional[str] = None
    question: str


class DiagnoseResponse(BaseModel):
    answer: str
    used_incidents: List[str]


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------
SAMPLE_INCIDENTS = [
    {
        "incident_key": "db-connection-exhaustion",
        "title": "Database connection exhaustion on payments-api",
        "service": "payments-api",
        "severity": "critical",
        "status": "open",
        "started_at": datetime.utcnow(),
        "summary": "Payments API is failing with database connection errors and slow checkout responses.",
        "logs": "2026-08-09T08:14:22Z ERROR payments-api: FATAL: remaining connection slots are reserved for non-replication superuser connections\n2026-08-09T08:14:22Z ERROR payments-api: connection pool acquire timed out after 10000ms\n2026-08-09T08:14:23Z WARN payments-api: retrying query for order 2948",
        "metrics": "db.connections=98/100\ndb.waiting_connections=23\nrequest.latency=1.9s\nerror_rate=12%",
    },
    {
        "incident_key": "ingest-api-timeout",
        "title": "Telemetry ingest API experiencing high latency",
        "service": "ingest-api",
        "severity": "high",
        "status": "open",
        "started_at": datetime.utcnow(),
        "summary": "The ingest API is returning timeouts as backend queue workers fall behind.",
        "logs": "2026-08-09T08:11:05Z ERROR ingest-api: timeout awaiting response from metrics-store\n2026-08-09T08:11:06Z WARN ingest-api: queue depth increased to 720\n2026-08-09T08:11:07Z INFO ingest-api: retrying batch upload after backoff",
        "metrics": "queue.depth=720\nworker.utilization=89%\napi.latency.p95=2.4s\nerror_rate=8%",
    },
    {
        "incident_key": "auth-service-cpu-spike",
        "title": "Auth service CPU spike causing login failures",
        "service": "auth-service",
        "severity": "medium",
        "status": "investigating",
        "started_at": datetime.utcnow(),
        "summary": "Auth service CPU usage climbed above 92%, causing slow session validation and failed login attempts.",
        "logs": "2026-08-09T08:09:58Z WARN auth-service: request processing delayed by 850ms\n2026-08-09T08:10:02Z ERROR auth-service: login failed for user id 8422 due to timeout\n2026-08-09T08:10:05Z INFO auth-service: scaling check in progress",
        "metrics": "cpu.usage=93%\nrequest.latency.p95=1.8s\nthread.count=260\nerror_rate=6%",
    },
]


def _upsert_incident(db, item: dict):
    existing = db.query(Incident).filter(Incident.incident_key == item["incident_key"]).first()
    if existing:
        for key, value in item.items():
            setattr(existing, key, value)
        return existing

    incident = Incident(**item)
    db.add(incident)
    return incident


def fetch_live_incidents(github_token: Optional[str] = None) -> List[dict]:
    token = github_token.strip() if github_token else GITHUB_TOKEN
    if not WATCHED_REPOS:
        raise HTTPException(500, "WATCHED_REPOS is not configured")
    if not token:
        raise HTTPException(500, "GITHUB_TOKEN is not configured")

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "SRE Forge AI",
    }
    incidents = []

    for repo in WATCHED_REPOS:
        url = f"https://api.github.com/repos/{repo}/actions/runs?status=failure&per_page=5"
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        payload = response.json()
        runs = payload.get("workflow_runs", []) or []

        for index, run in enumerate(runs):
            incidents.append(_normalize_incident(repo, run, index == 0))

    return incidents


def _normalize_incident(repo: str, run: dict, is_most_recent: bool) -> dict:
    created_at = run.get("created_at")
    if created_at:
        started_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    else:
        started_at = datetime.utcnow()

    conclusion = run.get("conclusion") or "failure"
    workflow_name = run.get("name") or str(run.get("workflow_id"))
    html_url = run.get("html_url") or ""
    summary = f"{workflow_name} failed on {repo}."

    return {
        "incident_key": str(run.get("id") or f"{repo}-{started_at.timestamp()}"),
        "title": f"{workflow_name} failure — {repo}",
        "service": repo,
        "severity": "critical" if is_most_recent else "medium",
        "status": "open",
        "started_at": started_at,
        "summary": summary,
        "logs": f"{conclusion} — {html_url}",
        "metrics": f"run_id={run.get('id')}\nworkflow={workflow_name}\nrepo={repo}",
    }


def seed_incidents(db):
    if db.query(Incident).count() > 0:
        return

    try:
        live_items = fetch_live_incidents()
        if live_items:
            for item in live_items:
                _upsert_incident(db, item)
            db.commit()
            return
    except requests.RequestException:
        pass

    for item in SAMPLE_INCIDENTS:
        _upsert_incident(db, item)
    db.commit()


SEVERITY_ORDER = case(
    (Incident.severity == "critical", 0),
    (Incident.severity == "high", 1),
    (Incident.severity == "medium", 2),
    else_=3,
)


def build_incident_context(incident: Incident) -> str:
    return (
        f"Incident: {incident.title}\n"
        f"Service: {incident.service}\n"
        f"Severity: {incident.severity}\n"
        f"Status: {incident.status}\n"
        f"Summary: {incident.summary or 'No summary available.'}\n\n"
        f"Logs:\n{incident.logs or 'No logs available.'}\n\n"
        f"Metrics:\n{incident.metrics or 'No metrics available.'}"
    )


def local_triage(incident: Incident, question: str) -> str:
    logs = (incident.logs or "").lower()
    metrics = (incident.metrics or "").lower()

    if "connection" in logs or "connection slots" in logs:
        root = (
            "This looks like a database connection exhaustion issue. The payments API is hitting the PostgreSQL max connections limit, "
            "which causes delays and retries when new requests attempt to open sessions."
        )
        fix = (
            "Check the database connection pool configuration, close idle client connections, and increase max_connections if needed. "
            "Also investigate whether the service is leaking connections or retrying too aggressively."
        )
    elif "timeout" in logs or "timeout awaiting response" in logs:
        root = (
            "The ingest API is timing out while waiting for downstream storage, and queue depth is rising. "
            "This suggests backend saturation or insufficient write throughput in the telemetry pipeline."
        )
        fix = (
            "Throttle incoming batches, add worker capacity, and inspect the metrics-store backend for slow commits. "
            "A temporary backpressure mechanism can prevent the queue from growing further."
        )
    elif "cpu" in metrics or "cpu.usage" in metrics:
        root = (
            "Auth service CPU is saturated at over 90%, which is causing request processing delays and login timeouts. "
            "This is a resource contention issue rather than a functional bug."
        )
        fix = (
            "Scale the auth-service horizontally, optimize hot request paths, and verify if a garbage collection storm or thread exhaustion is contributing to the spike."
        )
    else:
        root = (
            "The incident appears to be caused by a service-side performance regression or resource bottleneck. "
            "Review the service logs and metrics around the highest-error and highest-latency operations."
        )
        fix = "Collect additional traces, narrow the problem to the service/component emitting the most errors, and redeploy a patched release once the root cause is confirmed."

    return f"{root} {fix}"


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="SRE Forge AI API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    db = SessionLocal()
    try:
        seed_incidents(db)
    finally:
        db.close()


@app.get("/health")
def health():
    return {"status": "ok", "anthropic_configured": client is not None}


@app.get("/sre/incidents", response_model=List[IncidentOut])
def list_incidents():
    db = SessionLocal()
    try:
        return db.query(Incident).order_by(SEVERITY_ORDER, Incident.started_at).all()
    finally:
        db.close()


@app.get("/sre/stats")
def incident_stats():
    db = SessionLocal()
    try:
        count = db.query(Incident).count()
        latest = db.query(Incident).order_by(Incident.updated_at.desc()).first()
        return {
            "incident_count": count,
            "latest_incident": latest.title if latest else None,
            "latest_update": latest.updated_at.isoformat() if latest else None,
        }
    finally:
        db.close()


@app.post("/sre/refresh", response_model=List[IncidentOut])
def refresh_incidents(request: Request):
    db = SessionLocal()
    try:
        github_token = request.headers.get("x-github-token", "").strip()
        try:
            live_items = fetch_live_incidents(github_token=github_token)
        except requests.RequestException as exc:
            raise HTTPException(502, f"Failed to fetch live incident data: {exc}")

        incidents = [_upsert_incident(db, item) for item in live_items]
        db.commit()
        return db.query(Incident).order_by(SEVERITY_ORDER, Incident.started_at).all()
    finally:
        db.close()


@app.post("/sre/diagnose", response_model=DiagnoseResponse)
def diagnose(payload: DiagnoseRequest, request: Request):
    db = SessionLocal()
    try:
        incident = None
        if payload.incident_id:
            incident = db.query(Incident).filter(Incident.id == payload.incident_id).first()

        if not incident:
            incident = db.query(Incident).order_by(SEVERITY_ORDER, Incident.started_at).first()
        if not incident:
            raise HTTPException(404, "No incidents are available to diagnose.")

        prompt_context = build_incident_context(incident)
        user_prompt = (
            f"You are an SRE incident triage assistant. Use the incident context below to answer the user's question. "
            f"Be concise, provide root-cause reasoning, and suggest practical remediation steps.\n\n"
            f"Incident context:\n{prompt_context}\n\nQuestion: {payload.question}\n"
        )

        header_key = request.headers.get("x-anthropic-key", "").strip()
        current_client = None
        if header_key:
            current_client = anthropic.Anthropic(api_key=header_key)
        elif client is not None:
            current_client = client

        if current_client is not None:
            response = current_client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=800,
                system="You are SRE Forge AI, an autonomous incident triage assistant.",
                messages=[{"role": "user", "content": user_prompt}],
            )
            answer = "".join(
                block.text for block in response.content if getattr(block, "type", "") == "text"
            ).strip()
        else:
            answer = (
                "No Anthropic API key is configured, so using local SRE logic. "
                f"Incident summary: {incident.summary or 'No summary available.'} "
                f"Root cause and remediation: {local_triage(incident, payload.question)}"
            )

        return DiagnoseResponse(answer=answer, used_incidents=[incident.title])
    finally:
        db.close()
