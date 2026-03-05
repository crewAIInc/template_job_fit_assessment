import base64
import json
import logging
import os
import uuid
from queue import Empty, Queue
from threading import Lock

import requests as http_requests
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request

load_dotenv()

app = Flask(__name__)
app.logger.setLevel(logging.INFO)

CREWAI_API_URL = os.getenv("CREWAI_API_URL", "").rstrip("/")
CREWAI_BEARER_TOKEN = os.getenv("CREWAI_BEARER_TOKEN", "")

# In-memory session state — keyed by session_id
sessions: dict[str, dict] = {}
sessions_lock = Lock()

# SSE notification queues — keyed by session_id
sse_queues: dict[str, list[Queue]] = {}
sse_queues_lock = Lock()


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


def _amp_headers():
    return {
        "Authorization": f"Bearer {CREWAI_BEARER_TOKEN}",
        "Content-Type": "application/json",
    }


def _get_or_create_session(session_id: str) -> dict:
    with sessions_lock:
        if session_id not in sessions:
            sessions[session_id] = {
                "steps": {},
                "report": None,
                "error": None,
            }
        return sessions[session_id]


def _notify_sse(session_id: str):
    with sse_queues_lock:
        for q in sse_queues.get(session_id, []):
            q.put(True)


def _sse_snapshot(session_id: str) -> str:
    with sessions_lock:
        session = sessions.get(session_id, {
            "steps": {},
            "report": None,
            "error": None,
        })
        return f"data: {json.dumps(session)}\n\n"


# ──────────────────────────────────────────────
# Pages
# ──────────────────────────────────────────────


@app.route("/")
def index():
    return render_template("index.html")


# ──────────────────────────────────────────────
# API routes (called by the browser)
# ──────────────────────────────────────────────


@app.route("/api/warmup", methods=["POST"])
def api_warmup():
    try:
        resp = http_requests.get(
            f"{CREWAI_API_URL}/inputs",
            headers=_amp_headers(),
            timeout=45,
        )
        resp.raise_for_status()
        return jsonify(resp.json())
    except http_requests.RequestException as exc:
        app.logger.warning("Warmup request failed: %s", exc)
        return jsonify({"error": "warmup failed"}), 502


@app.route("/api/kickoff", methods=["POST"])
def api_kickoff():
    job_url = request.form.get("job_posting_url", "")
    resume_file = request.files.get("resume")

    if not job_url or not resume_file:
        return jsonify(
            {"error": "Both job posting URL and resume PDF are required."}
        ), 400

    resume_b64 = base64.b64encode(resume_file.read()).decode("utf-8")
    session_id = uuid.uuid4().hex

    # Pre-create the session so SSE can connect immediately
    _get_or_create_session(session_id)

    try:
        resp = http_requests.post(
            f"{CREWAI_API_URL}/kickoff",
            headers=_amp_headers(),
            json={
                "inputs": {
                    "session_id": session_id,
                    "job_posting_url": job_url,
                    "resume_base64": resume_b64,
                }
            },
            timeout=30,
        )
        resp.raise_for_status()
    except http_requests.RequestException as exc:
        app.logger.error("Kickoff request failed: %s", exc)
        return jsonify({"error": "Failed to start the assessment."}), 502

    data = resp.json()
    kickoff_id = data.get("kickoff_id", "")

    return jsonify({"session_id": session_id, "kickoff_id": kickoff_id})


@app.route("/api/status/<kickoff_id>")
def api_status(kickoff_id):
    """Fallback polling endpoint — proxies to AMP status API."""
    try:
        resp = http_requests.get(
            f"{CREWAI_API_URL}/status/{kickoff_id}",
            headers=_amp_headers(),
            timeout=15,
        )
        return jsonify(resp.json()), resp.status_code
    except http_requests.RequestException as exc:
        app.logger.error("Status request failed: %s", exc)
        return jsonify({"error": "Status check failed"}), 502


@app.route("/api/stream/<session_id>")
def api_stream(session_id: str):
    """SSE stream that pushes session state whenever a webhook updates it."""

    def generate():
        q: Queue = Queue()
        with sse_queues_lock:
            sse_queues.setdefault(session_id, []).append(q)
        try:
            # Send initial snapshot immediately
            yield _sse_snapshot(session_id)

            while True:
                try:
                    q.get(timeout=30)
                except Empty:
                    yield ": keepalive\n\n"
                    continue

                yield _sse_snapshot(session_id)

                # Close stream after report or error is delivered
                with sessions_lock:
                    session = sessions.get(session_id, {})
                    if session.get("report") or session.get("error"):
                        break
        finally:
            with sse_queues_lock:
                clients = sse_queues.get(session_id, [])
                if q in clients:
                    clients.remove(q)
                if not clients and session_id in sse_queues:
                    del sse_queues[session_id]

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ──────────────────────────────────────────────
# Webhook route (called by CrewAI flow event listener)
# ──────────────────────────────────────────────


@app.route("/webhook/messages", methods=["POST"])
def webhook_messages():
    payload = request.get_json(force=True)
    app.logger.info("Webhook received: %s", json.dumps(payload, default=str)[:500])

    session_id = payload.get("session_id", "")
    msg_type = payload.get("type", "")

    if not session_id:
        app.logger.warning("Webhook missing session_id: %s", payload)
        return jsonify({"ok": True, "skipped": True})

    session = _get_or_create_session(session_id)

    with sessions_lock:
        if msg_type == "step_update":
            session["steps"][payload["step"]] = {
                "status": payload["status"],
                "label": payload["label"],
            }
        elif msg_type == "final_report":
            session["report"] = payload.get("report", "")

    _notify_sse(session_id)

    return jsonify({"ok": True})


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
