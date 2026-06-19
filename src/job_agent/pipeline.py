"""
JobPipeline — clean orchestrator for the AI-JobFinder application.

Integrates three compliance features:
1. Official Job APIs (Bundesagentur, Arbeitnow) — no web scraping
2. Local LLM (Ollama) with cloud fallback — no data leaves the machine by default
3. Email drafts (.eml) instead of SMTP auto-send — manual review required

Usage:
    pipeline = JobPipeline()
    jobs = pipeline.search("Fachinformatiker", "Frankfurt", radius=25)
    for job in jobs[:5]:
        result = pipeline.process_job(job)
        if result["approved"]:
            print(f"✅ {job.title} at {job.company} — Score {result['score']}/10")
            print(f"   PDF: {result['pdf_path']}")
            print(f"   Draft: {result['draft_path']}")

Principles: SOLID, KISS, Clean Code, Single Responsibility.
"""

import os
import json
import datetime
import sqlite3
from typing import Optional, cast
from dataclasses import dataclass

from job_agent.utils import Colors, clean_and_repair_json, TeeStdout
from job_agent.config import load_config, load_criteria, PROMPTS
from job_agent.db import init_db, log_application, get_past_rejections
from job_agent import llm as _llm
from job_agent.llm import init_gemini, llm_request_with_fallback
from job_agent.ollama_llm import ollama_available
from job_agent.job_sources import search_all_sources, JobPosting
from job_agent.email_draft_generator import generate_email_draft
from job_agent.direct_email_applier import extract_contact_info, \
    personalize_anschreiben


# ---------------------------------------------------------------------------
# Pipeline result container
# ---------------------------------------------------------------------------

@dataclass
class ProcessResult:
    """Result of processing a single job through the pipeline."""
    job: JobPosting
    approved: bool = False
    score: float = 0.0
    ko_triggered: bool = False
    intake: Optional[dict] = None
    score_data: Optional[dict] = None
    anschreiben_data: Optional[dict] = None
    pdf_path: Optional[str] = None
    draft_path: Optional[str] = None
    status: str = "Skipped"
    message: str = ""
    reasoning: str = ""


# ---------------------------------------------------------------------------
# Pipeline orchestrator
# ---------------------------------------------------------------------------

class JobPipeline:
    """Clean orchestrator for the job application workflow.

    Single Responsibility: coordinate the pipeline stages.
    Each stage delegates to a specialized module.
    """

    def __init__(
        self,
        workspace_dir: Optional[str] = None,
        config_path: Optional[str] = None,
        criteria_path: Optional[str] = None,
        profile_path: Optional[str] = None,
    ):
        if workspace_dir is None:
            workspace_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.workspace_dir = workspace_dir

        # Config paths — try src/config/ first, then workspace root
        self.config_dir = os.path.join(workspace_dir, "config")
        self.config_path = config_path or os.path.join(self.config_dir, "config.yaml")
        self.criteria_path = criteria_path or os.path.join(self.config_dir, "job_criteria.yaml")
        self.profile_path = profile_path or os.path.join(self.config_dir, "candidate_profile.json")

        # Lazy-loaded state — type-annotated for mypy
        self._config: Optional[dict] = None
        self._criteria: Optional[dict] = None
        self._candidate_profile: Optional[dict] = None
        self._conn: Optional[sqlite3.Connection] = None
        self._initialized = False

    # -----------------------------------------------------------------------
    # Initialization
    # -----------------------------------------------------------------------

    def initialize(self) -> None:
        """Load configs, init DB, init LLM. Safe to call multiple times."""
        if self._initialized:
            return
        self._config = load_config(self.config_path)  # type: ignore[assignment]
        self._criteria = load_criteria(self.criteria_path)  # type: ignore[assignment]
        self._candidate_profile = self._load_profile()  # type: ignore[assignment]
        self._conn = init_db()
        init_gemini()
        self._initialized = True

    def _load_profile(self) -> dict:
        """Load candidate profile from JSON file."""
        if os.path.exists(self.profile_path):
            with open(self.profile_path, "r", encoding="utf-8") as f:
                return cast(dict, json.load(f))
        print(f"{Colors.YELLOW}Warning: Candidate profile '{self.profile_path}' not found.{Colors.END}")
        return {}

    @property
    def config(self) -> dict:
        """Lazy-load config."""
        if self._config is None:
            self._config = load_config(self.config_path)
        return self._config

    @property
    def criteria(self) -> dict:
        """Lazy-load criteria."""
        if self._criteria is None:
            self._criteria = load_criteria(self.criteria_path)
        return self._criteria

    @property
    def candidate_profile(self) -> dict:
        """Lazy-load candidate profile."""
        if self._candidate_profile is None:
            self._candidate_profile = self._load_profile()
        return self._candidate_profile

    @property
    def conn(self) -> sqlite3.Connection:
        """Lazy-init DB connection."""
        if self._conn is None:
            self._conn = init_db()
        return self._conn

    # -----------------------------------------------------------------------
    # Stage 1: Search jobs via official APIs
    # -----------------------------------------------------------------------

    def search(
        self,
        query: str,
        location: str,
        radius: int = 25,
        max_results: int = 25,
        sources: Optional[list[str]] = None,
    ) -> list[JobPosting]:
        """Search job listings via official APIs (no web scraping).

        Args:
            query: Job search query (e.g. "Fachinformatiker").
            location: City or PLZ (e.g. "Frankfurt am Main" or "60311").
            radius: Search radius in km.
            max_results: Maximum total results across all sources.
            sources: List of source names. Default: ["bundesagentur", "arbeitnow"].

        Returns:
            List of JobPosting objects, deduplicated and sorted by source priority.
        """
        self.initialize()
        print(f"\n{Colors.CYAN}{Colors.BOLD}--- Job Search: {query} in {location} ---{Colors.END}")
        return search_all_sources(
            query=query,
            location=location,
            radius=radius,
            sources=sources,
            max_results=max_results,
        )

    # -----------------------------------------------------------------------
    # Stage 2: Intake check (LLM-based validation + metadata extraction)
    # -----------------------------------------------------------------------

    def job_intake(self, job: JobPosting) -> dict:
        """Validate and extract metadata from a job posting using LLM.

        Returns a dict with: is_valid_job, company_name, job_title, industry,
        forbidden_title_detected, is_duplicate, ko_triggered, etc.
        """
        self.initialize()
        print(f"  {Colors.GREY}Running job intake (LLM) for: {job.title} @ {job.company}{Colors.END}")

        ko = self.criteria.get("ko_filters", {})
        previous_apps = ""
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT company_name, job_title FROM applied_jobs ORDER BY id DESC LIMIT 30")
            rows = cursor.fetchall()
            if rows:
                previous_apps = "\n".join([f"- {r[0]} | {r[1]}" for r in rows])
        except Exception:
            pass
        if not previous_apps:
            previous_apps = "Keine bisherigen Bewerbungen"

        prompt = PROMPTS.get("job_intake_prompt").format(
            page_title=f"{job.title} — {job.company}",
            page_text=job.description[:3000] if job.description else "",
            url=job.url,
            candidate_profile=json.dumps(self.candidate_profile, ensure_ascii=False, indent=2),
            excluded_companies=", ".join(ko.get("companies_blacklist", [])) or "Keine",
            forbidden_titles=", ".join(ko.get("forbidden_titles", [])) or "Keine",
            clearance_keywords=", ".join(ko.get("clearances", {}).get("forbidden_keywords", [])) or "Keine",
            mandatory_certifications=", ".join(ko.get("certifications", {}).get("mandatory_if_specified", [])) or "Keine",
            spam_keywords=", ".join(ko.get("spam_providers", {}).get("blocked_keywords", [])) or "Keine",
            datacenter_keywords=", ".join(ko.get("datacenter_physical_work", {}).get("keywords", [])) or "Keine",
            min_salary=ko.get("salary", {}).get("min_annual_eur", 36000),
            candidate_german=ko.get("languages", {}).get("min_required_german", "B1"),
            candidate_english=ko.get("languages", {}).get("min_required_english", "A2"),
            previous_applications=previous_apps,
        )

        try:
            response = llm_request_with_fallback(prompt)
            if response is None:
                return self._default_intake()
            text = clean_and_repair_json(response.text)
            result: dict = json.loads(text)  # type: ignore[assignment]
            return result
        except Exception as e:
            print(f"{Colors.YELLOW}Warning: job_intake LLM call failed: {e}. Falling back to allow.{Colors.END}")
            return self._default_intake()

    def _default_intake(self) -> dict:
        return {
            "is_valid_job": True,
            "company_name": "Unbekannt",
            "job_title": "Unbekannt",
            "industry": "Allgemein",
            "forbidden_title_detected": False,
            "is_duplicate": False,
            "ko_triggered": False,
        }

    # -----------------------------------------------------------------------
    # Stage 3: Score job against candidate profile
    # -----------------------------------------------------------------------

    def score_job(self, job: JobPosting, intake: dict) -> dict:
        """Score a job posting against the candidate profile.

        Returns dict with: total_score, ko_criterion_triggered, reasoning.
        Score is a recommendation — not an automatic decision.
        """
        self.initialize()
        industry = intake.get("industry", "Allgemein")
        industry_cfg = self.criteria.get("industries", {}).get(industry, {})
        mandatory_skills = industry_cfg.get("cover_letter", {}).get("mandatory_skills", [])

        print(f"  {Colors.GREY}Scoring job against profile (industry: {industry})...{Colors.END}")

        ko = self.criteria.get("ko_filters", {})
        past_rejections = get_past_rejections(self.conn)
        yaml_rejections = ko.get("user_rejected_reasons", [])
        if yaml_rejections:
            past_rejections = list(set(past_rejections + yaml_rejections))

        rejections_str = ""
        if past_rejections:
            rejections_str = "\\nBisherige Ablehnungsgründe des Kandidaten (vermeide Stellen mit ähnlichen Kriterien/Ausschlusskriterien):\\n"
            for r in set(past_rejections):
                rejections_str += f"- {r}\\n"

        prompt_key = f"scoring_prompt_{industry}"
        if prompt_key not in PROMPTS:
            prompt_key = "scoring_prompt"

        prompt = PROMPTS.get(prompt_key).format(
            candidate_profile=json.dumps(self.candidate_profile, ensure_ascii=False, indent=2),
            job_description=job.description,
            rejections_str=rejections_str,
            career_start_year=self.criteria.get("cover_letter", {}).get("career_start_year", 2010),
            candidate_german=ko.get("languages", {}).get("min_required_german", "B1"),
            candidate_english=ko.get("languages", {}).get("min_required_english", "A2"),
            clearance_keywords=", ".join(ko.get("clearances", {}).get("forbidden_keywords", [])),
            certifications=", ".join(ko.get("certifications", {}).get("mandatory_if_specified", [])),
            min_salary=ko.get("salary", {}).get("min_annual_eur", 36000),
            spam_keywords=", ".join(ko.get("spam_providers", {}).get("blocked_keywords", [])),
            datacenter_keywords=", ".join(ko.get("datacenter_physical_work", {}).get("keywords", [])),
            mandatory_skills=", ".join(mandatory_skills),
        )

        try:
            response = llm_request_with_fallback(prompt)
            if response is None:
                return {"total_score": 0.0, "ko_criterion_triggered": True, "reasoning": "LLM returned None"}
            text = clean_and_repair_json(response.text)
            result: dict = json.loads(text)  # type: ignore[assignment]
            return result
        except Exception as e:
            print(f"{Colors.YELLOW}Warning: score_job failed: {e}. Skipping job.{Colors.END}")
            return {"total_score": 0.0, "ko_criterion_triggered": True, "reasoning": f"LLM error: {e}"}

    # -----------------------------------------------------------------------
    # Stage 4: Generate cover letter
    # -----------------------------------------------------------------------

    def generate_anschreiben(self, job: JobPosting, intake: dict, score_data: dict) -> dict:
        """Generate a cover letter (Anschreiben) using LLM.

        Returns dict with: subject, salutation, body, closing, full_text.
        """
        self.initialize()
        industry = intake.get("industry", "Allgemein")
        cv_text = self._read_cv_text()

        print(f"  {Colors.GREY}Generating Anschreiben (industry: {industry})...{Colors.END}")

        prompt_key = f"cover_letter_prompt_{industry}"
        if prompt_key not in PROMPTS:
            prompt_key = "cover_letter_prompt"

        industry_cfg = self.criteria.get("industries", {}).get(industry, {})
        mandatory_skills = industry_cfg.get("cover_letter", {}).get("mandatory_skills", [])

        prompt = PROMPTS.get(prompt_key).format(
            candidate_profile=json.dumps(self.candidate_profile, ensure_ascii=False, indent=2),
            job_description=job.description,
            cv_text=cv_text or "Nicht verfügbar",
            salary_exp=self.config.get("defaults", {}).get("salary_expectation", "nach Vereinbarung"),
            availability=self.config.get("defaults", {}).get("availability", "sofort"),
            candidate_german=self.config.get("criteria", {}).get("german_level", "B1"),
            career_start_year=self.criteria.get("cover_letter", {}).get("career_start_year", 2010),
            mandatory_skills=", ".join(mandatory_skills),
        )

        try:
            response = llm_request_with_fallback(prompt)
            if response is None:
                return self._empty_anschreiben()
            raw = response.text.strip()
            data = json.loads(clean_and_repair_json(raw))
            if isinstance(data, dict) and "body" in data:
                full_text = (
                    f"{data.get('subject', 'Bewerbung')}\n\n"
                    f"{data.get('salutation', 'Sehr geehrte Damen und Herren,')}\n\n"
                    f"{data.get('body', '')}\n\n"
                    f"{data.get('closing', 'Mit freundlichen Grüßen')}"
                )
                data["full_text"] = full_text
                return data
            return self._empty_anschreiben(raw)
        except Exception:
            return self._empty_anschreiben()

    def _read_cv_text(self) -> Optional[str]:
        """Read CV PDF text for use in Anschreiben context."""
        try:
            cv_name = self.config.get("user_profile", {}).get("cv_path", "Lebenslauf_UserName.pdf")
            if not cv_name:
                return None
            cv_path = cv_name
            if not os.path.isabs(cv_path):
                cv_path = os.path.join(self.workspace_dir, cv_path)
            if not os.path.exists(cv_path):
                cv_path = os.path.join(os.path.dirname(self.workspace_dir), "documents", os.path.basename(cv_name))
            if os.path.exists(cv_path):
                import fitz
                doc = fitz.open(cv_path)
                text = "".join(page.get_text() for page in doc)
                doc.close()
                return text.strip() or None
        except Exception:
            pass
        return None

    def _empty_anschreiben(self, full_text: Optional[str] = None) -> dict:
        return {
            "subject": "Bewerbung",
            "salutation": "Sehr geehrte Damen und Herren,",
            "body": full_text or "Leider konnte kein Anschreiben generiert werden.",
            "closing": "Mit freundlichen Grüßen",
            "full_text": full_text or "Leider konnte kein Anschreiben generiert werden.",
        }

    # -----------------------------------------------------------------------
    # Stage 5: Render PDF
    # -----------------------------------------------------------------------

    def save_pdf(self, anschreiben_data: dict, company_name: str) -> Optional[str]:
        """Render cover letter as a DIN 5008 PDF using Playwright.

        Returns path to generated PDF, or None on failure.
        """
        self.initialize()
        output_dir = os.path.join(self.workspace_dir, "output")
        os.makedirs(output_dir, exist_ok=True)

        safe_name = "".join(c for c in company_name if c.isalnum() or c in (" ", "_")).strip().replace(" ", "_")
        pdf_path = os.path.join(output_dir, f"Anschreiben_{safe_name}.pdf")

        # Build sender info from profile
        pi = self.candidate_profile.get("personal_info", {})
        raw_name = pi.get("name", f"{pi.get('first_name', '')} {pi.get('last_name', '')}").strip()
        sender_name = raw_name if raw_name else "Bewerber"
        raw_loc = pi.get("location", "")
        if raw_loc and "," in raw_loc:
            parts = [p.strip() for p in raw_loc.split(",")]
            sender_address = parts[0]
            city = parts[-1]
        else:
            sender_address = pi.get("address", "")
            city = pi.get("city", raw_loc or "Berlin")
        sender_email = pi.get("email", "")
        sender_phone = pi.get("phone", "")
        date_str = datetime.date.today().strftime("%d.%m.%Y")

        if isinstance(anschreiben_data, dict):
            subject = anschreiben_data.get("subject", "Bewerbung")
            salutation = anschreiben_data.get("salutation", "Sehr geehrte Damen und Herren,")
            raw_body = anschreiben_data.get("body", "")
            body_html = "".join(f"<p>{p.strip()}</p>" for p in raw_body.split("\n") if p.strip())
            if not body_html:
                body_html = "<p>" + anschreiben_data.get("full_text", "").replace("\n", "</p><p>") + "</p>"
        else:
            subject = "Bewerbung"
            salutation = "Sehr geehrte Damen und Herren,"
            body_html = f"<p>{str(anschreiben_data).replace(chr(10), '</p><p>')}</p>"

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
  @page {{ size: A4; margin: 25mm 20mm 20mm 20mm; }}
  body {{ font-family: Arial, sans-serif; font-size: 11pt; line-height: 1.5; color: #333; }}
  .sender {{ text-align: right; margin-bottom: 10mm; font-size: 9.5pt; color: #666; }}
  .recipient {{ margin-bottom: 15mm; font-size: 10.5pt; }}
  .date {{ text-align: right; margin-bottom: 10mm; }}
  .subject {{ font-weight: bold; font-size: 12pt; margin-bottom: 8mm; }}
  .salutation {{ margin-bottom: 6mm; }}
  .content {{ text-align: justify; }}
  .content p {{ margin-bottom: 4mm; }}
  .closing {{ margin-top: 8mm; }}
</style></head><body>
  <div class="sender"><strong>{sender_name}</strong><br>{sender_address}<br>{sender_email} | {sender_phone}</div>
  <div class="recipient"><strong>{company_name} GmbH</strong><br>Ansprechpartner für Bewerbungen<br>Deutschland</div>
  <div class="date">{city}, {date_str}</div>
  <div class="subject">{subject}</div>
  <div class="salutation">{salutation}</div>
  <div class="content">{body_html}</div>
  <div class="closing">Mit freundlichen Grüßen<br><br><br><strong>{sender_name}</strong></div>
</body></html>"""

        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page()
                page.set_content(html)
                page.pdf(path=pdf_path, format="A4")
                browser.close()
            print(f"{Colors.GREEN}✅ PDF erstellt: {pdf_path}{Colors.END}")
            return pdf_path
        except Exception as e:
            print(f"{Colors.YELLOW}Warning: PDF generation failed: {e}{Colors.END}")
            return None

    # -----------------------------------------------------------------------
    # Stage 6: Create email draft (.eml, no SMTP)
    # -----------------------------------------------------------------------

    def create_draft(
        self,
        job: JobPosting,
        anschreiben_data: dict,
        pdf_path: Optional[str] = None,
        terminal_output: Optional[str] = None,
    ) -> Optional[str]:
        """Generate .eml draft file for manual review and sending.

        No SMTP involved — GDPR compliance. Returns path to .eml file.
        """
        self.initialize()

        # Try to extract recruiter contact from job description
        contact = extract_contact_info(job.description)
        if not contact:
            print(f"{Colors.YELLOW}No contact email found in job description. Draft will be for candidate reference.{Colors.END}")
            # Generate draft for candidate's own email
            candidate_email = self.candidate_profile.get("personal_info", {}).get("email")
            if not candidate_email:
                print(f"{Colors.RED}No candidate email configured. Cannot generate draft.{Colors.END}")
                return None
            contact = {"email": candidate_email, "recruiter_name": None}

        # Personalize anschreiben if recruiter name is known
        full_text = anschreiben_data.get("full_text", "")
        if contact.get("recruiter_name"):
            full_text = personalize_anschreiben(full_text, contact["recruiter_name"])

        # Collect attachments
        attachments = []
        if pdf_path and os.path.exists(pdf_path):
            attachments.append(pdf_path)
        attachments.extend(self._collect_candidate_docs())

        draft_path = generate_email_draft(
            smtp_config=self.config.get("smtp", {}),
            candidate_profile=self.candidate_profile,
            contact=contact,
            anschreiben_text=full_text,
            attachment_paths=attachments,
            job_title=job.title,
            company_name=job.company,
            url=job.url,
            terminal_output=terminal_output,
            is_candidate_copy=False,
        )

        # Also generate CC copy for candidate
        candidate_email = self.candidate_profile.get("personal_info", {}).get("email")
        if candidate_email and contact["email"] != candidate_email:
            cc_contact = {"email": candidate_email, "recruiter_name": contact.get("recruiter_name")}
            generate_email_draft(
                smtp_config=self.config.get("smtp", {}),
                candidate_profile=self.candidate_profile,
                contact=cc_contact,
                anschreiben_text=full_text,
                attachment_paths=attachments,
                job_title=job.title,
                company_name=job.company,
                url=job.url,
                terminal_output=terminal_output,
                is_candidate_copy=True,
            )

        return draft_path

    def _collect_candidate_docs(self) -> list[str]:
        """Collect CV and certificate paths for draft attachments."""
        paths = []
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT file_path FROM candidate_files WHERE classification = 'Lebenslauf' ORDER BY mtime DESC LIMIT 1"
            )
            row = cursor.fetchone()
            if row:
                f = row[0]
                if not os.path.isabs(f):
                    f = os.path.normpath(os.path.join(self.workspace_dir, f))
                if os.path.exists(f):
                    paths.append(f)

            cursor.execute(
                "SELECT file_path FROM candidate_files WHERE classification IN ('Zertifikat', 'Diplom', 'Zeugnis', 'Arbeitszeugnis')"
            )
            for (doc_path,) in cursor.fetchall():
                f = doc_path
                if not os.path.isabs(f):
                    f = os.path.normpath(os.path.join(self.workspace_dir, f))
                if os.path.exists(f) and f not in paths:
                    _, ext = os.path.splitext(f)
                    if ext.lower() in (".pdf", ".png", ".jpg", ".jpeg"):
                        paths.append(f)
        except Exception:
            pass
        return paths

    # -----------------------------------------------------------------------
    # Full pipeline: process one job end-to-end
    # -----------------------------------------------------------------------

    def process_job(
        self,
        job: JobPosting,
        auto_approve: bool = False,
        force_generate: bool = False,
        tee: Optional["TeeStdout"] = None,
    ) -> ProcessResult:
        """Run the full pipeline on a single job posting.

        Stages:
        1. Intake check (validation + metadata extraction)
        2. Scoring against candidate profile
        3. Cover letter generation
        4. PDF rendering
        5. Email draft generation

        Args:
            job: JobPosting from search_all_sources().
            auto_approve: If True, log as "Applied" after processing.
            force_generate: If True, skip scoring and generate directly.
            tee: Optional TeeStdout for capturing terminal output.

        Returns:
            ProcessResult with all pipeline stage outputs.
        """
        self.initialize()
        result = ProcessResult(job=job)

        print(f"\n{Colors.GREY}{'='*80}{Colors.END}")
        print(f"{Colors.CYAN}{Colors.BOLD}Processing: {Colors.END}{Colors.BLUE}{job.title} @ {job.company}{Colors.END}")
        print(f"{Colors.GREY}  Source: {job.source}  |  Location: {job.location}{Colors.END}")
        if job.salary:
            print(f"{Colors.GREY}  Salary: {job.salary}{Colors.END}")
        print(f"{Colors.GREY}{'-'*80}{Colors.END}")

        # --- Stage 1: Intake ---
        print(f"  {Colors.GREY}Stage 1: Intake check...{Colors.END}")
        intake = self.job_intake(job)
        result.intake = intake

        if not intake.get("is_valid_job", True):
            result.message = intake.get("invalid_reason", "Invalid job page")
            print(f"{Colors.YELLOW}  Skipping: {result.message}{Colors.END}")
            print(f"{Colors.GREY}{'='*80}{Colors.END}\n")
            return result

        if intake.get("is_duplicate", False):
            result.message = f"Duplicate: {intake.get('duplicate_of', 'unknown')}"
            print(f"{Colors.YELLOW}  Skipping: {result.message}{Colors.END}")
            print(f"{Colors.GREY}{'='*80}{Colors.END}\n")
            return result

        if intake.get("ko_triggered", False):
            result.message = intake.get("ko_reason", "KO filter triggered")
            print(f"{Colors.YELLOW}  Skipping: {result.message}{Colors.END}")
            result.status = "Skipped (KO)"
            log_application(self.conn, intake.get("company_name", "Unbekannt"),
                            intake.get("job_title", "Unbekannt"), job.url, 0.0, result.status)
            print(f"{Colors.GREY}{'='*80}{Colors.END}\n")
            return result

        company_name = intake.get("company_name", job.company)
        job_title = intake.get("job_title", job.title)
        industry = intake.get("industry", "Allgemein")
        print(f"  {Colors.GREY}Company:{Colors.END} {Colors.CYAN}{company_name}{Colors.END}")
        print(f"  {Colors.GREY}Title:{Colors.END} {Colors.CYAN}{job_title}{Colors.END}")
        print(f"  {Colors.GREY}Industry:{Colors.END} {Colors.CYAN}{industry}{Colors.END}")

        # --- Stage 2: Scoring ---
        print(f"  {Colors.GREY}Stage 2: Scoring...{Colors.END}")
        if force_generate:
            result.score = 10.0
            result.ko_triggered = False
            result.score_data = {"total_score": 10.0, "ko_criterion_triggered": False, "reasoning": "Force-generate mode"}
            print(f"{Colors.YELLOW}  [FORCE] Skipping scoring, generating directly.{Colors.END}")
        else:
            score_data = self.score_job(job, intake)
            result.score_data = score_data
            result.score = score_data.get("total_score", 0.0)
            result.ko_triggered = score_data.get("ko_criterion_triggered", False)
            result.reasoning = score_data.get("reasoning", "")

        min_score = self.criteria.get("industries", {}).get(industry, {}).get("scoring", {}).get("min_score_to_apply", 8.0)
        if force_generate:
            min_score = 0.0

        if result.score >= min_score and not result.ko_triggered:
            print(f"  {Colors.GREY}Score:{Colors.END} {Colors.GREEN}{Colors.BOLD}{result.score}/10 ✅{Colors.END}")
        else:
            print(f"  {Colors.GREY}Score:{Colors.END} {Colors.RED}{Colors.BOLD}{result.score}/10 ❌{Colors.END}")
            if not force_generate and result.score < min_score:
                result.message = result.reasoning or "Below minimum score threshold"
                print(f"{Colors.RED}  Skipping: {result.message}{Colors.END}")
                result.status = "Skipped (Low Score)"
                log_application(self.conn, company_name, job_title, job.url, result.score, result.status)
                print(f"{Colors.GREY}{'='*80}{Colors.END}\n")
                return result

        # --- Stage 3: Cover letter ---
        print(f"  {Colors.GREY}Stage 3: Generating Anschreiben...{Colors.END}")
        anschreiben_data = self.generate_anschreiben(job, intake, result.score_data or {})
        result.anschreiben_data = anschreiben_data

        # --- Stage 4: PDF ---
        print(f"  {Colors.GREY}Stage 4: Rendering PDF...{Colors.END}")
        pdf_path = self.save_pdf(anschreiben_data, company_name)
        result.pdf_path = pdf_path

        # --- Stage 5: Email draft ---
        print(f"  {Colors.GREY}Stage 5: Creating email draft...{Colors.END}")
        terminal_out = tee.getvalue() if tee else None
        draft_path = self.create_draft(job, anschreiben_data, pdf_path, terminal_out)
        result.draft_path = draft_path

        # --- Approval ---
        result.approved = True
        result.status = "Draft Generated" if draft_path else "Processed (No Draft)"
        log_application(
            self.conn, company_name, job_title, job.url, result.score, result.status,
            terminal_output=terminal_out, pdf_path=pdf_path,
        )

        if draft_path:
            print(f"{Colors.GREEN}✅ {result.status}: {draft_path}{Colors.END}")
        print(f"{Colors.GREEN}  Job processing completed.{Colors.END}")
        print(f"{Colors.GREY}{'='*80}{Colors.END}\n")

        return result

    # -----------------------------------------------------------------------
    # Process multiple jobs
    # -----------------------------------------------------------------------

    def process_jobs(
        self,
        jobs: list[JobPosting],
        auto_approve: bool = False,
        force_generate: bool = False,
    ) -> list[ProcessResult]:
        """Process a list of job postings through the full pipeline."""
        results: list[ProcessResult] = []
        for job in jobs:
            tee = TeeStdout()
            try:
                result = self.process_job(job, auto_approve=auto_approve, force_generate=force_generate, tee=tee)
                results.append(result)
            except Exception as e:
                print(f"{Colors.RED}Error processing {job.title} @ {job.company}: {e}{Colors.END}")
                results.append(ProcessResult(job=job, message=str(e)))
        return results

    # -----------------------------------------------------------------------
    # Document indexing
    # -----------------------------------------------------------------------

    def index_documents(self) -> None:
        """Scan documents/ and output/ directories and index PDFs into the DB."""
        import glob
        import fitz

        self.initialize()
        print(f"\n{Colors.MAGENTA}{Colors.BOLD}--- Indexing candidate PDF files ---{Colors.END}")

        project_root = os.path.dirname(self.workspace_dir)
        doc_pattern = os.path.join(project_root, "documents", "*.pdf")
        out_pattern = os.path.join(self.workspace_dir, "output", "*.pdf")
        pdf_files = set(glob.glob(doc_pattern) + glob.glob(out_pattern))

        cursor = self.conn.cursor()
        cursor.execute("SELECT file_path, file_size, mtime, classification FROM candidate_files")
        db_rows = cursor.fetchall()

        def to_rel(p: str) -> str:
            return os.path.relpath(p, self.workspace_dir) if os.path.isabs(p) else p

        def to_abs(p: str) -> str:
            return os.path.normpath(os.path.join(self.workspace_dir, p)) if not os.path.isabs(p) else p

        # Build DB index from existing records
        db_records: dict[str, dict] = {}
        for row in db_rows:
            rel = to_rel(row[0])
            if rel != row[0]:
                cursor.execute("UPDATE candidate_files SET file_path = ? WHERE file_path = ?", (rel, row[0]))
            db_records[rel] = {"size": row[1], "mtime": row[2], "classification": row[3]}
        self.conn.commit()

        detected_rel = {to_rel(f) for f in pdf_files}
        db_rel = set(db_records.keys())

        added = detected_rel - db_rel
        deleted = db_rel - detected_rel

        # Detect modifications
        modified: set[str] = set()
        for f_rel in detected_rel & db_rel:
            f_abs = to_abs(f_rel)
            try:
                st = os.stat(f_abs)
                if st.st_size != db_records[f_rel]["size"] or abs(st.st_mtime - db_records[f_rel]["mtime"]) > 1e-3:
                    modified.add(f_abs)
            except Exception:
                pass

        # Process deletions
        for f in deleted:
            print(f" {Colors.RED}- Deleted: {f}{Colors.END}")
            cursor.execute("DELETE FROM candidate_files WHERE file_path = ?", (f,))

        # Process additions and modifications
        to_process = {to_abs(f) for f in added} | modified
        for f in to_process:
            f_rel = to_rel(f)
            print(f" {Colors.CYAN}- New/modified: {f_rel}{Colors.END}")

            # Extract text from first page
            doc_text = ""
            try:
                doc = fitz.open(f)
                if len(doc) > 0:
                    doc_text = doc[0].get_text()[:1000]
                doc.close()
            except Exception as e:
                print(f"   Warning: could not read text: {e}")

            # Classify by filename (fast path)
            classification = "Sonstiges"
            fname_lower = os.path.basename(f).lower()
            if "lebenslauf" in fname_lower or "cv" in fname_lower:
                classification = "Lebenslauf"
            elif "anschreiben" in fname_lower or "cover_letter" in fname_lower:
                classification = "Anschreiben"
            elif "zertifikat" in fname_lower or "certificate" in fname_lower:
                classification = "Zertifikat"
            elif "zeugnis" in fname_lower or "diplom" in fname_lower or "degree" in fname_lower:
                classification = "Diplom"

            # LLM classification for ambiguous names
            if classification == "Sonstiges" and doc_text:
                prompt = PROMPTS.get("classify_document_prompt", "").format(
                    filename=os.path.basename(f), doc_text=doc_text[:1500]
                )
                if prompt:
                    try:
                        resp = llm_request_with_fallback(prompt)
                        if resp:
                            text = resp.text.strip()
                            for prefix in ("```json", "```"):
                                if text.startswith(prefix):
                                    text = text[len(prefix):]
                            if text.endswith("```"):
                                text = text[:-3]
                            result = json.loads(clean_and_repair_json(text.strip()))
                            classification = result.get("classification", "Sonstiges")
                            conf = result.get("confidence", 0)
                            reason = result.get("reasoning", "")
                            print(f"   {Colors.GREY}LLM classified:{Colors.END} {classification} (conf: {conf:.0%}) — {reason}")
                    except Exception as e:
                        print(f"   {Colors.YELLOW}LLM classification failed: {e}{Colors.END}")

            print(f"   Classified as: {Colors.YELLOW}{Colors.BOLD}{classification}{Colors.END}")

            # Parse based on classification
            parsed = {}
            try:
                if classification == "Lebenslauf":
                    profile_path = os.path.join(self.workspace_dir, "config", "candidate_profile.json")
                    parsed = self.parse_cv(f, profile_path)
                elif classification == "Anschreiben":
                    parsed = self._parse_pdf_generic(f, "anschreiben")
                elif classification == "Zertifikat":
                    parsed = self._parse_pdf_generic(f, "zertifikat")
                elif classification == "Diplom":
                    parsed = self._parse_pdf_generic(f, "diplom")
                else:
                    parsed = self._parse_pdf_generic(f, "sonstiges")
            except Exception as e:
                print(f"   Error parsing: {e}")
                parsed = {"error": str(e)}

            # Store in DB
            try:
                st = os.stat(f)
                cursor.execute(
                    "INSERT OR REPLACE INTO candidate_files (file_path, file_size, mtime, classification, parsed_json) VALUES (?, ?, ?, ?, ?)",
                    (f_rel, st.st_size, st.st_mtime, classification, json.dumps(parsed, ensure_ascii=False)),
                )
                self.conn.commit()
            except Exception as e:
                print(f"   Error saving to DB: {e}")

        print(f"{Colors.GREEN}Candidate file index is up to date.{Colors.END}\n")

    # -----------------------------------------------------------------------
    # CV/document parsing
    # -----------------------------------------------------------------------

    def parse_cv(self, cv_path: str, output_path: str) -> dict:
        """Parse a CV PDF into structured candidate profile using LLM."""
        import fitz
        init_gemini()

        if not os.path.exists(cv_path):
            print(f"{Colors.RED}Error: CV file '{cv_path}' not found.{Colors.END}")
            return {"error": "File not found"}

        print(f"Extracting text from '{cv_path}'...")
        try:
            doc = fitz.open(cv_path)
            cv_text = "".join(page.get_text() for page in doc)
            doc.close()
        except Exception as e:
            print(f"Error reading PDF: {e}")
            return {"error": str(e)}

        prompt = (
            "Du bist ein erfahrener Senior HR-Spezialist in Deutschland. Analysiere diesen Lebenslauf (CV) "
            "und erstelle ein konsolidiertes Profil.\n\n"
            "WICHTIG: Extrahiere zu jedem Ausbildungseintrag (education) ein 'curriculum'-Feld mit den "
            "detaillierten Kursinhalten/Modulen, falls im Dokument beschrieben.\n\n"
            "WICHTIG: STRENGE TRENNUNG VON EDUCATION UND EXPERIENCE. Extrahiere NUR explizite "
            "Arbeitsverhältnisse mit Firmenname als 'experience'.\n\n"
            f"Hier ist der extrahierte Text des Lebenslaufs:\n--- START LEBENSLAUF ---\n{cv_text}\n--- ENDE LEBENSLAUF ---\n\n"
            "Struktur des erwarteten JSON:\n"
            '{"personal_info": {"first_name": "...", "last_name": "...", "email": "...", '
            '"phone": "...", "address": "...", "city": "...", "country": "Deutschland", '
            '"location": "Stadt, Land, Straße", "availability": "Datum oder \'sofort\'"}, '
            '"languages": {"deutsch": "B2", "englisch": "A2"}, '
            '"skills": [...], "experience_years": 0.0, "seniority_level": "...", '
            '"hr_assessment": {"job_search_directions": [...], "target_vacancies": [...], '
            '"apply_to_learning_roles": true, "strategic_advice": "..."}, '
            '"experience": [{"title": "...", "company": "...", "years": "..."}], '
            '"education": [...], "certifications": [...]}'
        )

        response = llm_request_with_fallback(prompt)
        if response is None:
            print(f"{Colors.RED}Warning: LLM returned None for CV parsing.{Colors.END}")
            return {"error": "LLM returned None"}

        try:
            text = clean_and_repair_json(response.text)
            profile_data: dict = json.loads(text)
            profile_data = self._normalize_profile(profile_data)
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(profile_data, f, ensure_ascii=False, indent=2)
            print(f"{Colors.GREEN}Profile created at '{output_path}'{Colors.END}")
            self._candidate_profile = profile_data  # Update cached profile
            return profile_data
        except Exception as e:
            print(f"{Colors.RED}Failed to parse CV JSON: {e}{Colors.END}")
            return {"error": str(e)}

    def _normalize_profile(self, profile: dict) -> dict:
        """Fill in missing fields from name/location."""
        pi = profile.get("personal_info", {})
        if not pi.get("first_name") and not pi.get("last_name") and pi.get("name"):
            parts = pi["name"].strip().rsplit(" ", 1)
            if len(parts) == 2:
                pi["first_name"] = pi.get("first_name") or parts[0]
                pi["last_name"] = pi.get("last_name") or parts[1]
            else:
                pi["first_name"] = pi.get("first_name") or pi["name"]
                pi["last_name"] = pi.get("last_name") or pi["name"]

        loc = pi.get("location", "")
        if not pi.get("address") and not pi.get("city"):
            if loc and "," in loc:
                parts = [p.strip() for p in loc.split(",")]
                pi["address"] = parts[0]
                pi["city"] = parts[1] if len(parts) > 1 else loc
            else:
                pi["address"] = pi.get("address") or loc
                pi["city"] = pi.get("city") or loc
        elif not pi.get("city") and pi.get("address"):
            pi["city"] = pi["address"].rsplit(" ", 1)[-1] if " " in pi["address"] else pi["address"]

        pi["country"] = pi.get("country") or "Deutschland"
        for key in ("first_name", "last_name", "address", "city"):
            pi[key] = pi.get(key) or ""

        certs = profile.get("certifications", [])
        if certs and isinstance(certs, list):
            profile["certifications"] = [
                c["name"] if isinstance(c, dict) and "name" in c else str(c) for c in certs
            ]
        return profile

    def _parse_pdf_generic(self, file_path: str, doc_type: str) -> dict:
        """Parse any PDF document using LLM."""
        import fitz
        init_gemini()

        doc = fitz.open(file_path)
        text = "".join(page.get_text() for page in doc)
        doc.close()

        prompts_by_type = {
            "anschreiben": (
                'Analysiere dieses Anschreiben (Cover Letter) und extrahiere die folgenden Informationen im JSON-Format.\n'
                'Gib NUR das reine JSON-Dokument zurück, ohne zusätzliche Erklärung.\n\n'
                'Struktur des erwarteten JSON:\n'
                '{"company_name": "Name des Zielunternehmens (falls vorhanden)", '
                '"job_title": "Bewerbungs-Position/Rolle", '
                '"salary_expectation": "Gehaltsvorstellung (falls erwähnt)", '
                '"availability": "Verfügbarkeit / Eintrittstermin (falls erwähnt)", '
                '"content": "Vollständiger Text des Anschreibens"}\n\n'
                f'Text des Dokuments:\n{text[:5000]}'
            ),
            "zertifikat": (
                'Analysiere dieses Zertifikat (Certificate) und extrahiere die folgenden Informationen im JSON-Format.\n'
                'Gib NUR das reine JSON-Dokument zurück.\n\n'
                'Struktur des erwarteten JSON:\n'
                '{"title": "Name/Bezeichnung des Zertifikats", '
                '"issuer": "Ausstellende Organisation", '
                '"issue_date": "Ausstellungsdatum (falls vorhanden)", '
                '"skills": ["Zertifizierte Fähigkeit 1", "Zertifizierte Fähigkeit 2"]}\n\n'
                f'Text des Dokuments:\n{text[:5000]}'
            ),
            "diplom": (
                'Analysiere dieses Diplom/Zeugnis (Degree/Diploma/Transcript) und extrahiere die folgenden Informationen im JSON-Format.\n'
                'Gib NUR das reine JSON-Dokument zurück.\n\n'
                'Struktur des erwarteten JSON:\n'
                '{"degree": "Art des Abschlusses", '
                '"field": "Fachrichtung / Spezialisierung", '
                '"institution": "Name der Schule/Hochschule", '
                '"year": "Abschlussjahr (falls vorhanden)", '
                '"grade": "Abschlussnote / Score (falls vorhanden)"}\n\n'
                f'Text des Dokuments:\n{text[:5000]}'
            ),
            "sonstiges": (
                'Analysiere dieses Dokument und extrahiere die folgenden Informationen im JSON-Format.\n'
                'Gib NUR das reine JSON-Dokument zurück.\n\n'
                'Struktur des erwarteten JSON:\n'
                '{"title": "Kompakter Titel / Beschreibung des Dokuments", '
                '"topic": "Hauptthema / Kategorie des Dokuments", '
                '"content_summary": "Kurze Zusammenfassung des Inhalts", '
                '"extracted_text": "Gesamter extrahierter Text (gekürzt)"}\n\n'
                f'Text des Dokuments:\n{text[:5000]}'
            ),
        }

        prompt = prompts_by_type.get(doc_type, prompts_by_type["sonstiges"])
        response = llm_request_with_fallback(prompt)
        if response is None:
            return {"title": os.path.basename(file_path), "error": "LLM returned None"}
        try:
            return cast(dict, json.loads(clean_and_repair_json(response.text)))
        except Exception as e:
            return {"title": os.path.basename(file_path), "error": str(e)}

    # -----------------------------------------------------------------------
    # Batch digest draft
    # -----------------------------------------------------------------------

    def generate_pending_digest(self) -> Optional[str]:
        """Generate a digest .eml with all pending applications."""
        from job_agent.email_draft_generator import generate_candidate_digest_draft
        self.initialize()

        cursor = self.conn.cursor()
        try:
            cursor.execute(
                "SELECT id, company_name, job_title, url, score, applied_date, terminal_output, pdf_path "
                "FROM applied_jobs "
                "WHERE (status LIKE 'Applied%' OR status LIKE 'Draft%') AND email_sent = 0"
            )
            rows = cursor.fetchall()
        except sqlite3.OperationalError as e:
            print(f"{Colors.RED}DB error: {e}{Colors.END}")
            return None

        if not rows:
            print(f"{Colors.GREEN}No pending applications to digest.{Colors.END}")
            return None

        candidate_email = self.candidate_profile.get("personal_info", {}).get("email")
        if not candidate_email:
            print(f"{Colors.RED}No candidate email configured.{Colors.END}")
            return None

        print(f"Generating digest draft for {len(rows)} pending applications...")
        return generate_candidate_digest_draft(
            smtp_config=self.config.get("smtp", {}),
            candidate_profile=self.candidate_profile,
            candidate_email=candidate_email,
            rows=rows,
            conn=self.conn,
        )

    # -----------------------------------------------------------------------
    # Utilities
    # -----------------------------------------------------------------------

    def create_git_restore(self) -> None:
        """Create a git RESTORE backup commit."""
        import subprocess
        git_dir = os.path.dirname(self.workspace_dir) if os.path.basename(self.workspace_dir) == "src" else self.workspace_dir
        print(f" {Colors.BLUE}- Creating git RESTORE backup...{Colors.END}")
        try:
            if not os.path.exists(os.path.join(git_dir, ".git")):
                print(f"   {Colors.YELLOW}No .git found. Skipping.{Colors.END}")
                return
            subprocess.run(["git", "add", "."], cwd=git_dir, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            status = subprocess.run(["git", "status", "--porcelain"], cwd=git_dir, capture_output=True, text=True, check=True)
            if status.stdout.strip():
                subprocess.run(["git", "commit", "-m", "RESTORE"], cwd=git_dir, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print(f" {Colors.GREEN}- RESTORE commit created.{Colors.END}")
            else:
                print(f" {Colors.GREEN}- Working tree clean.{Colors.END}")
        except Exception as e:
            print(f"   {Colors.RED}Backup commit failed: {e}{Colors.END}")

    def reset_workspace(self) -> None:
        """Delete all generated files and restore configs from samples."""
        import glob
        self.create_git_restore()

        patterns = [
            os.path.join(self.workspace_dir, "*.pdf"),
            os.path.join(self.workspace_dir, "output", "*.pdf"),
            os.path.join(os.path.dirname(self.workspace_dir), "documents", "*.pdf"),
            os.path.join(self.workspace_dir, "*.html"),
            os.path.join(self.workspace_dir, "output", "*.html"),
            os.path.join(self.workspace_dir, "*.png"),
            os.path.join(self.workspace_dir, "output", "*.png"),
            os.path.join(self.workspace_dir, "output", "*.db"),
            os.path.join(self.workspace_dir, "output", "*.sqlite"),
        ]
        for pattern in patterns:
            for f in glob.glob(pattern):
                if f.endswith(".sample"):
                    continue
                try:
                    os.remove(f)
                    print(f" {Colors.RED}- Deleted: {f}{Colors.END}")
                except Exception as e:
                    print(f"   {Colors.RED}Error deleting {f}: {e}{Colors.END}")

        print(f"{Colors.GREEN}Workspace reset completed.{Colors.END}")


# ---------------------------------------------------------------------------
# CLI-accessible entry point for the pipeline mode
# ---------------------------------------------------------------------------

def run_pipeline_mode(
    workspace_dir: str,
    config: dict,
    criteria_path: str,
    profile_path: str,
    search_jobs: Optional[str],
    location: str,
    radius: int,
    force_generate: bool = False,
    auto_approve: bool = False,
    ignore_ollama: bool = False,
) -> None:
    """Run the GDPR-compliant pipeline from the CLI.

    Called by agent.py when --pipeline is specified.
    Uses official Job APIs instead of web scraping, local LLM by default,
    and email drafts instead of SMTP.
    """
    print(f"\n{Colors.MAGENTA}{Colors.BOLD}{'='*80}{Colors.END}")
    print(f"{Colors.MAGENTA}{Colors.BOLD}  GDPR-Compliant Pipeline Mode{Colors.END}")
    print(f"{Colors.MAGENTA}{Colors.BOLD}{'='*80}{Colors.END}")
    print(f"  {Colors.GREY}Sources:{Colors.END} Bundesagentur für Arbeit API + Arbeitnow API")
    print(f"  {Colors.GREY}LLM:{Colors.END} Local (Ollama) → OpenRouter → Gemini fallback")
    print(f"  {Colors.GREY}Output:{Colors.END} .eml drafts in drafts/ (no automatic SMTP)")
    print(f"{Colors.MAGENTA}{Colors.BOLD}{'='*80}{Colors.END}\n")

    # Initialize pipeline
    pipeline = JobPipeline(
        workspace_dir=workspace_dir,
        criteria_path=criteria_path,
        profile_path=profile_path,
    )
    pipeline.initialize()

    # --- Early exit: Local LLM required but Ollama is not running ---
    if _llm.PRIORITY_LLM == "local" and not _llm.ALLOW_CLOUD_FALLBACK:
        if not ollama_available(_llm.LOCAL_MODEL):
            if ignore_ollama:
                print(f"\n{Colors.YELLOW}{Colors.BOLD}{'='*60}{Colors.END}")
                print(f"{Colors.YELLOW}{Colors.BOLD}  Warning: Local LLM required but Ollama is not running.{Colors.END}")
                print(f"{Colors.YELLOW}  Proceeding due to --ignore-ollama flag. Jobs will score 0/10.{Colors.END}")
                print(f"{Colors.YELLOW}  Start Ollama for real results: ollama serve{Colors.END}")
                print(f"{Colors.YELLOW}{Colors.BOLD}{'='*60}{Colors.END}\n")
            else:
                print(f"\n{Colors.RED}{Colors.BOLD}{'='*60}{Colors.END}")
                print(f"{Colors.RED}{Colors.BOLD}  ❌ Local LLM required. Start Ollama:{Colors.END}")
                print(f"{Colors.CYAN}     ollama serve{Colors.END}")
                print(f"{Colors.GREY}     Or if already installed: ollama run {_llm.LOCAL_MODEL}{Colors.END}")
                print(f"{Colors.GREY}     Model needed: {_llm.LOCAL_MODEL}{Colors.END}")
                print(f"{Colors.RED}{Colors.BOLD}{'='*60}{Colors.END}\n")
                return

    # Index candidate documents
    pipeline.index_documents()

    # Check if we have a valid candidate profile
    if not pipeline.candidate_profile or not pipeline.candidate_profile.get("personal_info"):
        print(f"{Colors.YELLOW}No valid candidate profile loaded. Run --parse-cv first, or parse via --url.{Colors.END}")
        print(f"{Colors.YELLOW}Continuing with default profile...{Colors.END}")

    # Search via official APIs
    if search_jobs is None:
        print(f"{Colors.CYAN}No search query specified. Showing all available vacancies...{Colors.END}")
        search_jobs = ""

    jobs = pipeline.search(
        query=search_jobs,
        location=location or "Frankfurt am Main",
        radius=radius,
        max_results=config.get("search", {}).get("max_results", 25),
    )

    if not jobs:
        print(f"{Colors.YELLOW}No jobs found for '{search_jobs}' in {location}.{Colors.END}")
        return

    print(f"\n{Colors.CYAN}Found {len(jobs)} unique jobs. Processing...{Colors.END}\n")

    # Process each job through the pipeline
    approved_count = 0
    skipped_count = 0
    for idx, job in enumerate(jobs, 1):
        print(f"\n{Colors.CYAN}[{idx}/{len(jobs)}]{Colors.END}")
        result = pipeline.process_job(
            job,
            auto_approve=auto_approve,
            force_generate=force_generate,
        )
        if result.approved:
            approved_count += 1
            print(f"{Colors.GREEN}  ✅ {job.title} at {job.company} — Score {result.score}/10{Colors.END}")
            if result.pdf_path:
                print(f"     {Colors.GREY}PDF: {result.pdf_path}{Colors.END}")
            if result.draft_path:
                print(f"     {Colors.GREY}Draft: {result.draft_path}{Colors.END}")
        else:
            skipped_count += 1
            print(f"  {Colors.YELLOW}⏭️  {job.title} at {job.company} — {result.message}{Colors.END}")

    # Generate digest draft for all processed jobs
    print(f"\n{Colors.BLUE}{Colors.BOLD}--- Generating batch digest ---{Colors.END}")
    digest_path = pipeline.generate_pending_digest()

    if digest_path:
        print(f"{Colors.GREEN}✅ Batch digest saved at: {digest_path}{Colors.END}")

    # Summary
    print(f"\n{Colors.MAGENTA}{Colors.BOLD}{'='*80}{Colors.END}")
    print(f"{Colors.MAGENTA}{Colors.BOLD}  Pipeline Summary{Colors.END}")
    print(f"{Colors.MAGENTA}{Colors.BOLD}{'='*80}{Colors.END}")
    print(f"  {Colors.GREEN}Approved: {approved_count}{Colors.END}")
    print(f"  {Colors.YELLOW}Skipped: {skipped_count}{Colors.END}")
    print(f"  {Colors.GREY}Total jobs processed: {len(jobs)}{Colors.END}")
    print(f"\n  {Colors.GREY}Drafts saved in:{Colors.END} drafts/")
    print(f"  {Colors.GREY}PDFs saved in:{Colors.END} src/output/")
    print(f"{Colors.MAGENTA}{Colors.BOLD}{'='*80}{Colors.END}")
    print(f"{Colors.YELLOW}⚠️  Please open .eml files manually to send (GDPR compliance).{Colors.END}\n")
