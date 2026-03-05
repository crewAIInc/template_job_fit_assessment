#!/usr/bin/env python
import base64
import os
import tempfile
from typing import List

from crewai import Agent
from crewai.flow import Flow, listen, start
from crewai_tools import FirecrawlScrapeWebsiteTool, PDFSearchTool
from pydantic import BaseModel

from template_job_fit_assessment.events.listener import WebhookEventListener

# Register event listener — auto-hooks into flow events and POSTs to WEBHOOK_URL
_webhook_listener = WebhookEventListener()

# ---------------------------------------------------------------------------
# Pydantic models for structured agent outputs
# ---------------------------------------------------------------------------


class JobPostingData(BaseModel):
    job_title: str
    company_name: str
    required_skills: List[str]


class ResumeAnalysisData(BaseModel):
    candidate_name: str
    fitness_score: int  # 0–100
    strengths: List[str]
    missing_skills: List[str]


# ---------------------------------------------------------------------------
# Flow state
# ---------------------------------------------------------------------------


class JobFitState(BaseModel):
    session_id: str = ""
    job_posting_url: str = ""
    resume_base64: str = ""


# ---------------------------------------------------------------------------
# Flow
# ---------------------------------------------------------------------------


class JobFitAssessmentFlow(Flow[JobFitState]):
    @start()
    def extract_job_details(self, crewai_trigger_payload: dict = None):
        """Step 1: Scrape the job posting URL and extract structured details."""
        if crewai_trigger_payload:
            self.state.session_id = crewai_trigger_payload.get("session_id", "")
            self.state.job_posting_url = crewai_trigger_payload.get(
                "job_posting_url", ""
            )
            self.state.resume_base64 = crewai_trigger_payload.get("resume_base64", "")

        agent = Agent(
            role="Skill Extraction Specialist",
            goal=(
                "Extract the job title, company name, and a complete list of required "
                "skills from any job posting URL with precision."
            ),
            backstory=(
                "You are a senior talent acquisition analyst with years of experience "
                "parsing job descriptions across all industries. You have a sharp eye "
                "for distinguishing required skills from preferred ones, and you never "
                "miss a key requirement. You are methodical and thorough."
            ),
            tools=[FirecrawlScrapeWebsiteTool()],
            llm="openai/gpt-5-nano",
            verbose=True,
        )

        result = agent.kickoff(
            f"Scrape the job posting at this URL: {self.state.job_posting_url}\n\n"
            "Extract and return:\n"
            "1. The exact job title as stated in the posting\n"
            "2. The company name\n"
            "3. A complete list of required skills (technical and soft skills, tools, "
            "frameworks, languages, certifications, and experience requirements)\n\n"
            "Include all skills explicitly listed as required or necessary. "
            "Do not include preferred/nice-to-have skills unless treated as requirements.",
            response_format=JobPostingData,
        )

        return result.pydantic

    @listen(extract_job_details)
    def analyze_resume(self, job_data: JobPostingData):
        """Step 2: Decode resume, read it, and score against job requirements."""
        pdf_bytes = base64.b64decode(self.state.resume_base64)
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp.write(pdf_bytes)
        tmp.close()

        agent = Agent(
            role="Resume Analyzer",
            goal=(
                "Thoroughly evaluate a candidate's resume against a set of job requirements "
                "and produce an objective fitness score with clear strengths and skill gaps."
            ),
            backstory=(
                "You are a seasoned HR professional and technical recruiter with over a decade "
                "of experience evaluating candidates. You approach every resume with objectivity "
                "and rigor, matching skills precisely against requirements. You never fabricate "
                "information — if a skill is not explicitly present in the resume, it is absent."
            ),
            tools=[PDFSearchTool()],
            llm="openai/gpt-5-mini",
            verbose=True,
        )

        skills_list = "\n".join(f"- {skill}" for skill in job_data.required_skills)

        result = agent.kickoff(
            f"Read the candidate's resume at: {tmp.name}\n\n"
            f"You are evaluating them for the role of {job_data.job_title} at {job_data.company_name}.\n\n"
            f"Required skills for this role:\n{skills_list}\n\n"
            "IMPORTANT: When using the PDF search tool, you MUST provide a non-empty query string. "
            "Start by searching for the candidate's name and summary (e.g. query='experience skills summary'), "
            "then search for specific required skills.\n\n"
            "Perform the following analysis:\n"
            "1. Extract the candidate's full name\n"
            "2. Identify which required skills the candidate clearly demonstrates (strengths)\n"
            "3. Identify which required skills the candidate does not demonstrate (missing skills)\n"
            "4. Calculate a fitness score from 0 to 100 based on the proportion of required "
            "skills the candidate meets, weighted by apparent importance. "
            "Use (matched_skills / total_required_skills) * 100 as a guide.\n\n"
            "Only report what is explicitly evidenced in the resume. "
            "Redact all sensitive personal information other than the candidate's name "
            "(no addresses, phone numbers, email addresses, or ID numbers).",
            response_format=ResumeAnalysisData,
        )

        os.unlink(tmp.name)

        return {
            "job_data": job_data,
            "analysis": result.pydantic,
        }

    @listen(analyze_resume)
    def write_report(self, data: dict):
        """Step 3: Compile the findings into a structured markdown report."""
        job_data: JobPostingData = data["job_data"]
        analysis: ResumeAnalysisData = data["analysis"]

        agent = Agent(
            role="Report Writer",
            goal=(
                "Compile job assessment findings into a clear, structured markdown report "
                "that gives hiring managers an immediate picture of candidate fit."
            ),
            backstory=(
                "You are a technical writer specializing in HR and talent acquisition "
                "documentation. Your reports are concise and actionable. You present facts "
                "without editorializing and always redact sensitive personal information."
            ),
            llm="openai/gpt-5.2",
            verbose=True,
        )

        strengths_list = "\n".join(f"- {s}" for s in analysis.strengths)
        missing_list = "\n".join(f"- {s}" for s in analysis.missing_skills)
        required_list = "\n".join(f"- {s}" for s in job_data.required_skills)

        result = agent.kickoff(
            "Write a professional job fit assessment report in markdown using the data below.\n\n"
            f"Position: {job_data.job_title} at {job_data.company_name}\n"
            f"Candidate: {analysis.candidate_name}\n"
            f"Fitness Score: {analysis.fitness_score}/100\n\n"
            f"Required Skills:\n{required_list}\n\n"
            f"Strengths (matched skills):\n{strengths_list}\n\n"
            f"Missing Skills (gaps):\n{missing_list}\n\n"
            "The report must follow this exact structure:\n\n"
            "# Job Fit Assessment Report\n\n"
            "## Position\n"
            "[Company name and job title]\n\n"
            "## Candidate\n"
            "[Candidate name only — redact all other personal information]\n\n"
            "## Required Skills\n"
            "[Bullet point list]\n\n"
            "## Fitness Score\n"
            "[Score as X/100 with a one-sentence interpretation]\n\n"
            "## Strengths\n"
            "[Bullet point list of matched skills]\n\n"
            "## Gaps / Missing Skills\n"
            "[Bullet point list of missing required skills]\n\n"
            "## Summary\n"
            "[2-3 sentence overall assessment of the candidate's fit for this role]"
        )

        return result.raw


# ---------------------------------------------------------------------------
# Entry points (keep signatures matching pyproject.toml scripts)
# ---------------------------------------------------------------------------


def kickoff():
    flow = JobFitAssessmentFlow()
    flow.kickoff(
        inputs={
            "session_id": "",
            "job_posting_url": "",
            "resume_base64": "",
        }
    )


def plot():
    flow = JobFitAssessmentFlow()
    flow.plot()
