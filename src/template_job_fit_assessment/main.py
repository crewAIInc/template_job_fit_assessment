#!/usr/bin/env python
import base64
import json
import os
import sys
import tempfile
from typing import List

from crewai import Agent
from crewai.flow import Flow, listen, start
from crewai_tools import FirecrawlScrapeWebsiteTool, PDFSearchTool
from pydantic import BaseModel, PrivateAttr

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
    # User inputs — the only fields exposed to CrewAI AMP
    job_posting_url: str = ""
    resume_base64: str = ""

    # Internal state — populated during flow execution, not exposed as inputs
    _resume_temp_path: str = PrivateAttr(default="")
    _job_title: str = PrivateAttr(default="")
    _company_name: str = PrivateAttr(default="")
    _required_skills: List[str] = PrivateAttr(default_factory=list)
    _candidate_name: str = PrivateAttr(default="")
    _fitness_score: int = PrivateAttr(default=0)
    _strengths: List[str] = PrivateAttr(default_factory=list)
    _missing_skills: List[str] = PrivateAttr(default_factory=list)
    _report: str = PrivateAttr(default="")


# ---------------------------------------------------------------------------
# Flow
# ---------------------------------------------------------------------------


class JobFitAssessmentFlow(Flow[JobFitState]):
    @start()
    def extract_job_details(self, crewai_trigger_payload: dict = None):
        """Step 1: Scrape the job posting URL and extract structured details."""
        if crewai_trigger_payload:
            self.state.job_posting_url = crewai_trigger_payload.get(
                "job_posting_url", ""
            )
            self.state.resume_path = crewai_trigger_payload.get("resume_path", "")

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

        job_data: JobPostingData = result.pydantic
        self.state._job_title = job_data.job_title
        self.state._company_name = job_data.company_name
        self.state._required_skills = job_data.required_skills

    @listen(extract_job_details)
    def prepare_resume(self):
        """Step 2: Decode the base64 resume and write it to a local temp file."""
        pdf_bytes = base64.b64decode(self.state.resume_base64)

        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp.write(pdf_bytes)
        tmp.close()
        self.state._resume_temp_path = tmp.name

    @listen(prepare_resume)
    def analyze_resume(self):
        """Step 2: Read the resume PDF and score the candidate against job requirements."""
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
            llm="openai/gpt-5-nano",
            verbose=True,
        )

        skills_list = "\n".join(f"- {skill}" for skill in self.state._required_skills)

        result = agent.kickoff(
            f"Read the candidate's resume at: {self.state._resume_temp_path}\n\n"
            f"You are evaluating them for the role of {self.state._job_title} at {self.state._company_name}.\n\n"
            f"Required skills for this role:\n{skills_list}\n\n"
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

        analysis: ResumeAnalysisData = result.pydantic
        self.state._candidate_name = analysis.candidate_name
        self.state._fitness_score = analysis.fitness_score
        self.state._strengths = analysis.strengths
        self.state._missing_skills = analysis.missing_skills

    @listen(analyze_resume)
    def write_report(self):
        """Step 3: Compile the findings into a structured markdown report."""
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
            llm="openai/gpt-5-nano",
            verbose=True,
        )

        strengths_list = "\n".join(f"- {s}" for s in self.state._strengths)
        missing_list = "\n".join(f"- {s}" for s in self.state._missing_skills)
        required_list = "\n".join(f"- {s}" for s in self.state._required_skills)

        result = agent.kickoff(
            "Write a professional job fit assessment report in markdown using the data below.\n\n"
            f"Position: {self.state._job_title} at {self.state._company_name}\n"
            f"Candidate: {self.state._candidate_name}\n"
            f"Fitness Score: {self.state._fitness_score}/100\n\n"
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

        self.state._report = result.raw

    @listen(write_report)
    def save_report(self):
        """Step 4: Return the markdown report to the caller."""
        if self.state._resume_temp_path:
            os.unlink(self.state._resume_temp_path)

        return self.state._report


# ---------------------------------------------------------------------------
# Entry points (keep signatures matching pyproject.toml scripts)
# ---------------------------------------------------------------------------


def kickoff():
    flow = JobFitAssessmentFlow()
    flow.kickoff(
        inputs={
            "job_posting_url": "",
            "resume_base64": "",
        }
    )


def plot():
    flow = JobFitAssessmentFlow()
    flow.plot()


def run_with_trigger():
    """Run the flow with a JSON trigger payload from the command line."""
    if len(sys.argv) < 2:
        raise Exception(
            "No trigger payload provided. Please provide JSON payload as argument."
        )

    try:
        trigger_payload = json.loads(sys.argv[1])
    except json.JSONDecodeError:
        raise Exception("Invalid JSON payload provided as argument")

    flow = JobFitAssessmentFlow()
    try:
        result = flow.kickoff({"crewai_trigger_payload": trigger_payload})
        return result
    except Exception as e:
        raise Exception(f"An error occurred while running the flow with trigger: {e}")


if __name__ == "__main__":
    kickoff()
