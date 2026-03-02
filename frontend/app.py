import base64
import os

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

load_dotenv()

app = Flask(__name__)

CREWAI_API_URL = os.getenv("CREWAI_API_URL", "").rstrip("/")
CREWAI_BEARER_TOKEN = os.getenv("CREWAI_BEARER_TOKEN", "")


def _amp_headers():
    return {
        "Authorization": f"Bearer {CREWAI_BEARER_TOKEN}",
        "Content-Type": "application/json",
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/kickoff", methods=["POST"])
def api_kickoff():
    job_url = request.form.get("job_posting_url", "")
    resume_file = request.files.get("resume")

    if not job_url or not resume_file:
        return jsonify(
            {"error": "Both job posting URL and resume PDF are required."}
        ), 400

    resume_b64 = base64.b64encode(resume_file.read()).decode("utf-8")

    resp = requests.post(
        f"{CREWAI_API_URL}/kickoff",
        headers=_amp_headers(),
        json={
            "inputs": {
                "job_posting_url": job_url,
                "resume_base64": resume_b64,
            }
        },
        timeout=30,
    )

    return jsonify(resp.json()), resp.status_code


@app.route("/api/status/<kickoff_id>")
def api_status(kickoff_id):
    resp = requests.get(
        f"{CREWAI_API_URL}/status/{kickoff_id}",
        headers=_amp_headers(),
        timeout=15,
    )

    return jsonify(resp.json()), resp.status_code


if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True, port=5001)
