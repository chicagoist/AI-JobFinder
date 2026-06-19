"""
Unit tests for JobPipeline — all LLM calls mocked.

Run:
    python -m pytest tests/test_pipeline.py -v
or:
    python -m unittest tests.test_pipeline -v
"""

import io
import os
import sys
import json
import unittest
from unittest.mock import patch, MagicMock

# Ensure src/ is on the path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

from job_agent.pipeline import JobPipeline, ProcessResult, run_pipeline_mode
from job_agent.job_sources import JobPosting


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

SAMPLE_JOB = JobPosting(
    title="Python Developer (m/w/d)",
    company="Tech GmbH",
    location="60311 Frankfurt am Main",
    url="https://example.com/job/12345",
    description="Wir suchen einen erfahrenen Python Developer. "
    "Kenntnisse: Python, Django, PostgreSQL, Docker. "
    "Deutsch B2 erforderlich. Gehalt: 55.000-65.000 EUR.",
    source="arbeitnow",
    salary="55.000 - 65.000 EUR",
    job_type="Vollzeit",
)

DUPLICATE_JOB = JobPosting(
    title="Python Developer (m/w/d)",
    company="Tech GmbH",
    location="60311 Frankfurt",
    url="https://example.com/job/12345",
    description="Duplicate posting.",
    source="bundesagentur",
)

SENIOR_JOB = JobPosting(
    title="Senior Python Developer (m/w/d)",
    company="BigCorp AG",
    location="10115 Berlin",
    url="https://example.com/job/senior",
    description="Senior Python role. 5+ years experience required. "
    "Deutsch C1. Gehalt: 80.000 EUR.",
    source="arbeitnow",
    salary="80.000 EUR",
    job_type="Vollzeit",
)

SAMPLE_INTAKE = {
    "is_valid_job": True,
    "company_name": "Tech GmbH",
    "job_title": "Python Developer",
    "industry": "IT",
    "industry_reasoning": "IT job posting",
    "forbidden_title_detected": False,
    "is_duplicate": False,
    "ko_triggered": False,
}

SAMPLE_SCORE_HIGH = {
    "total_score": 9.0,
    "ko_criterion_triggered": False,
    "reasoning": "Excellent match: Python, Django, Docker all match profile.",
}

SAMPLE_SCORE_LOW = {
    "total_score": 3.0,
    "ko_criterion_triggered": False,
    "reasoning": "Low match: candidate lacks required experience.",
}

SAMPLE_SCORE_KO = {
    "total_score": 0.0,
    "ko_criterion_triggered": True,
    "reasoning": "KO: US citizenship required.",
}

SAMPLE_ANSCHREIBEN = {
    "subject": "Bewerbung als Python Developer",
    "salutation": "Sehr geehrte Damen und Herren,",
    "body": "Mit großem Interesse bewerbe ich mich auf die Position.\n\n"
            "Ich bringe umfassende Erfahrung in Python und Django mit.",
    "closing": "Mit freundlichen Grüßen",
}

SAMPLE_CANDIDATE_PROFILE = {
    "personal_info": {
        "first_name": "Max",
        "last_name": "Mustermann",
        "email": "max@example.com",
        "phone": "+49 123 456789",
        "address": "Hauptstr. 1",
        "city": "60311 Frankfurt am Main",
        "country": "Deutschland",
    },
    "languages": {"Deutsch": "B2", "Englisch": "B1"},
    "skills": ["Python", "Django", "PostgreSQL", "Docker", "Linux", "Git"],
    "experience_years": 3.0,
    "education": [],
    "certifications": [],
}

SAMPLE_CONFIG = {
    "defaults": {
        "salary_expectation": "60.000 €",
        "availability": "sofort",
        "work_permit": "Germany",
        "notice_period": "3 Monate",
    },
    "criteria": {"german_level": "B1"},
    "smtp": {"username": "max@example.com"},
    "llm": {"priority": "local", "local_model": "llama3.2:3b"},
    "user_profile": {"cv_path": "Lebenslauf.pdf", "chrome_data_dir": "/tmp"},
}

SAMPLE_CRITERIA = {
    "ko_filters": {
        "salary": {"min_annual_eur": 40000},
        "languages": {"min_required_german": "B1", "min_required_english": "A2"},
        "clearances": {"forbidden_keywords": ["US citizenship", "Top Secret"]},
        "certifications": {"mandatory_if_specified": []},
        "spam_providers": {"blocked_keywords": []},
        "datacenter_physical_work": {"keywords": [], "forbidden": False},
        "companies_blacklist": [],
        "forbidden_titles": ["Sales", "HR"],
        "user_rejected_reasons": [],
    },
    "cover_letter": {"career_start_year": 2020, "mandatory_skills": []},
    "scoring": {"min_score_to_apply": 8.0},
    "industries": {
        "IT": {"scoring": {"min_score_to_apply": 7.0}, "cover_letter": {"mandatory_skills": ["Python"]}}
    },
}


def _make_mock_llm(response_text: str) -> MagicMock:
    """Create a mock LLM response object with .text attribute."""
    mock = MagicMock()
    mock.text = response_text
    return mock


# ---------------------------------------------------------------------------
# Test base class — sets up pipeline with mocked dependencies
# ---------------------------------------------------------------------------


class BasePipelineTest(unittest.TestCase):
    """Base class for pipeline tests — injects all dependencies."""

    def setUp(self):
        # Mock DB connection
        self.mock_conn = MagicMock()
        self.mock_cursor = MagicMock()
        self.mock_conn.cursor.return_value = self.mock_cursor
        self.mock_cursor.fetchall.return_value = []
        self.mock_cursor.fetchone.return_value = None

        # Create pipeline and inject all dependencies directly
        self.pipeline = JobPipeline(workspace_dir="/tmp/test_workspace")
        self.pipeline._config = SAMPLE_CONFIG.copy()
        self.pipeline._criteria = SAMPLE_CRITERIA.copy()
        self.pipeline._candidate_profile = SAMPLE_CANDIDATE_PROFILE.copy()
        self.pipeline._conn = self.mock_conn
        self.pipeline._initialized = True  # skip file loading


# ---------------------------------------------------------------------------
# Test: search (job sources)
# ---------------------------------------------------------------------------


class TestSearch(BasePipelineTest):
    def test_search_returns_jobs(self):
        """Search via mocked search_all_sources returns JobPosting list."""
        with patch("job_agent.pipeline.search_all_sources") as mock_search:
            mock_search.return_value = [SAMPLE_JOB, SENIOR_JOB]

            results = self.pipeline.search("Python", "Berlin", radius=25)

            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].title, "Python Developer (m/w/d)")
            self.assertEqual(results[1].company, "BigCorp AG")
            mock_search.assert_called_once()

    def test_search_empty_results(self):
        """search_all_sources returns empty list — pipeline handles it."""
        with patch("job_agent.pipeline.search_all_sources", return_value=[]):
            results = self.pipeline.search("Nonexistent", "Nowhere")

            self.assertEqual(results, [])
            self.assertIsInstance(results, list)

    def test_search_passes_parameters(self):
        """search() passes query, location, radius, max_results to search_all_sources."""
        with patch("job_agent.pipeline.search_all_sources") as mock_search:
            mock_search.return_value = []

            self.pipeline.search("Java", "Frankfurt", radius=10, max_results=5,
                                 sources=["bundesagentur"])

            _, kwargs = mock_search.call_args
            self.assertEqual(kwargs["query"], "Java")
            self.assertEqual(kwargs["location"], "Frankfurt")
            self.assertEqual(kwargs["radius"], 10)
            self.assertEqual(kwargs["max_results"], 5)
            self.assertEqual(kwargs["sources"], ["bundesagentur"])


# ---------------------------------------------------------------------------
# Test: job_intake
# ---------------------------------------------------------------------------


class TestJobIntake(BasePipelineTest):
    def test_intake_valid_job(self):
        """LLM returns a valid intake result — verify parsed correctly."""
        with patch("job_agent.pipeline.llm_request_with_fallback") as mock_llm:
            mock_llm.return_value = _make_mock_llm(json.dumps(SAMPLE_INTAKE))

            result = self.pipeline.job_intake(SAMPLE_JOB)

            self.assertTrue(result["is_valid_job"])
            self.assertEqual(result["company_name"], "Tech GmbH")
            self.assertEqual(result["job_title"], "Python Developer")
            self.assertEqual(result["industry"], "IT")
            self.assertFalse(result["ko_triggered"])
            self.assertFalse(result["is_duplicate"])

    def test_intake_llm_returns_none(self):
        """LLM returns None — fallback to default intake (allow)."""
        with patch("job_agent.pipeline.llm_request_with_fallback", return_value=None):
            result = self.pipeline.job_intake(SAMPLE_JOB)

            self.assertTrue(result["is_valid_job"])
            self.assertEqual(result["company_name"], "Unbekannt")
            self.assertEqual(result["industry"], "Allgemein")

    def test_intake_llm_raises_exception(self):
        """LLM raises exception — fallback to default intake."""
        with patch("job_agent.pipeline.llm_request_with_fallback",
                   side_effect=RuntimeError("Connection refused")):
            result = self.pipeline.job_intake(SAMPLE_JOB)

            self.assertTrue(result["is_valid_job"])
            self.assertEqual(result["company_name"], "Unbekannt")

    def test_intake_invalid_job(self):
        """LLM detects the page is not a valid job posting."""
        invalid = {**SAMPLE_INTAKE, "is_valid_job": False,
                   "invalid_reason": "404 page"}
        with patch("job_agent.pipeline.llm_request_with_fallback") as mock_llm:
            mock_llm.return_value = _make_mock_llm(json.dumps(invalid))
            result = self.pipeline.job_intake(SAMPLE_JOB)

            self.assertFalse(result["is_valid_job"])
            self.assertEqual(result["invalid_reason"], "404 page")


# ---------------------------------------------------------------------------
# Test: score_job
# ---------------------------------------------------------------------------


class TestScoreJob(BasePipelineTest):
    def test_score_high_match(self):
        """LLM returns a high score — candidate is a good fit."""
        with patch("job_agent.pipeline.llm_request_with_fallback") as mock_llm:
            mock_llm.return_value = _make_mock_llm(json.dumps(SAMPLE_SCORE_HIGH))

            result = self.pipeline.score_job(SAMPLE_JOB, SAMPLE_INTAKE)

            self.assertAlmostEqual(result["total_score"], 9.0)
            self.assertFalse(result["ko_criterion_triggered"])
            self.assertIn("Excellent", result["reasoning"])

    def test_score_low_match(self):
        """LLM returns low score — candidate doesn't match well."""
        with patch("job_agent.pipeline.llm_request_with_fallback") as mock_llm:
            mock_llm.return_value = _make_mock_llm(json.dumps(SAMPLE_SCORE_LOW))

            result = self.pipeline.score_job(SENIOR_JOB, SAMPLE_INTAKE)

            self.assertAlmostEqual(result["total_score"], 3.0)
            self.assertFalse(result["ko_criterion_triggered"])

    def test_score_ko_triggered(self):
        """LLM detects a KO criterion."""
        with patch("job_agent.pipeline.llm_request_with_fallback") as mock_llm:
            mock_llm.return_value = _make_mock_llm(json.dumps(SAMPLE_SCORE_KO))

            result = self.pipeline.score_job(SAMPLE_JOB, SAMPLE_INTAKE)

            self.assertAlmostEqual(result["total_score"], 0.0)
            self.assertTrue(result["ko_criterion_triggered"])

    def test_score_llm_returns_none(self):
        """LLM returns None — fallback to KO/skip."""
        with patch("job_agent.pipeline.llm_request_with_fallback", return_value=None):
            result = self.pipeline.score_job(SAMPLE_JOB, SAMPLE_INTAKE)

            self.assertAlmostEqual(result["total_score"], 0.0)
            self.assertTrue(result["ko_criterion_triggered"])


# ---------------------------------------------------------------------------
# Test: generate_anschreiben
# ---------------------------------------------------------------------------


class TestGenerateAnschreiben(BasePipelineTest):
    def test_generate_valid(self):
        """LLM returns a structured cover letter JSON."""
        with patch("job_agent.pipeline.llm_request_with_fallback") as mock_llm:
            mock_llm.return_value = _make_mock_llm(json.dumps(SAMPLE_ANSCHREIBEN))

            result = self.pipeline.generate_anschreiben(
                SAMPLE_JOB, SAMPLE_INTAKE, SAMPLE_SCORE_HIGH
            )

            self.assertEqual(result["subject"], "Bewerbung als Python Developer")
            self.assertIn("Mit großem Interesse", result["body"])
            self.assertIn("Bewerbung als Python Developer", result.get("full_text", ""))
            self.assertEqual(result["closing"], "Mit freundlichen Grüßen")

    def test_generate_llm_returns_none(self):
        """LLM returns None — fallback to empty anschreiben."""
        with patch("job_agent.pipeline.llm_request_with_fallback", return_value=None):
            result = self.pipeline.generate_anschreiben(
                SAMPLE_JOB, SAMPLE_INTAKE, SAMPLE_SCORE_HIGH
            )

            self.assertEqual(result["subject"], "Bewerbung")
            self.assertIn("Leider konnte kein Anschreiben", result["body"])

    def test_generate_plain_text_fallback(self):
        """LLM returns plain text (not JSON) — falls back to empty anschreiben.

        Note: clean_and_repair_json cannot repair arbitrary plain text,
        so json.loads raises and the outer except returns _empty_anschreiben()
        with the default error message.
        """
        with patch("job_agent.pipeline.llm_request_with_fallback") as mock_llm:
            mock_llm.return_value = _make_mock_llm("Sehr geehrte Damen und Herren,\n\n"
                                                    "Hiermit bewerbe ich mich...\n\n"
                                                    "Mit freundlichen Grüßen")

            result = self.pipeline.generate_anschreiben(
                SAMPLE_JOB, SAMPLE_INTAKE, SAMPLE_SCORE_HIGH
            )

            # Falls back gracefully — not empty, has default structure
            self.assertIsNotNone(result.get("subject"))
            self.assertIsNotNone(result.get("full_text"))
            self.assertIsInstance(result, dict)


# ---------------------------------------------------------------------------
# Test: process_job (end-to-end pipeline)
# ---------------------------------------------------------------------------


class TestProcessJob(BasePipelineTest):
    def test_process_job_approved(self):
        """Full pipeline: intake → score → anschreiben → PDF → draft — all pass."""
        with patch("job_agent.pipeline.llm_request_with_fallback") as mock_llm, \
             patch("job_agent.pipeline.generate_email_draft") as mock_draft, \
             patch.object(JobPipeline, "save_pdf", return_value="/tmp/output/Anschreiben_Tech_GmbH.pdf"):

            # Mock LLM responses for intake, scoring, and anschreiben
            mock_llm.side_effect = [
                _make_mock_llm(json.dumps(SAMPLE_INTAKE)),       # intake
                _make_mock_llm(json.dumps(SAMPLE_SCORE_HIGH)),   # scoring
                _make_mock_llm(json.dumps(SAMPLE_ANSCHREIBEN)),  # anschreiben
            ]
            mock_draft.return_value = "/tmp/drafts/Bewerbung_Tech_GmbH_2026-06-19.eml"

            result = self.pipeline.process_job(SAMPLE_JOB)

            self.assertTrue(result.approved)
            self.assertAlmostEqual(result.score, 9.0)
            self.assertEqual(result.status, "Draft Generated")
            self.assertIsNotNone(result.pdf_path)
            self.assertIsNotNone(result.draft_path)
            self.assertIsNotNone(result.intake)
            self.assertEqual(result.intake["company_name"], "Tech GmbH")

    def test_process_job_intake_ko(self):
        """Intake detects KO filter — job is skipped before scoring."""
        ko_intake = {**SAMPLE_INTAKE, "ko_triggered": True,
                     "ko_reason": "Blacklisted company"}

        with patch("job_agent.pipeline.llm_request_with_fallback") as mock_llm:
            mock_llm.return_value = _make_mock_llm(json.dumps(ko_intake))

            result = self.pipeline.process_job(SAMPLE_JOB)

            self.assertFalse(result.approved)
            self.assertEqual(result.status, "Skipped (KO)")
            self.assertIsNone(result.pdf_path)
            self.assertIsNone(result.draft_path)

    def test_process_job_low_score(self):
        """Score is below threshold — job is skipped."""
        with patch("job_agent.pipeline.llm_request_with_fallback") as mock_llm:
            mock_llm.side_effect = [
                _make_mock_llm(json.dumps(SAMPLE_INTAKE)),      # intake passes
                _make_mock_llm(json.dumps(SAMPLE_SCORE_LOW)),   # score = 3.0
            ]

            result = self.pipeline.process_job(SAMPLE_JOB)

            self.assertFalse(result.approved)
            self.assertAlmostEqual(result.score, 3.0)
            self.assertEqual(result.status, "Skipped (Low Score)")
            self.assertIsNone(result.pdf_path)

    def test_process_job_force_generate(self):
        """Force-generate mode — skip scoring, generate directly."""
        with patch("job_agent.pipeline.llm_request_with_fallback") as mock_llm, \
             patch("job_agent.pipeline.generate_email_draft") as mock_draft, \
             patch.object(JobPipeline, "save_pdf", return_value="/tmp/test.pdf"):

            mock_llm.side_effect = [
                _make_mock_llm(json.dumps(SAMPLE_INTAKE)),       # intake
                _make_mock_llm(json.dumps(SAMPLE_ANSCHREIBEN)),  # anschreiben (no scoring!)
            ]
            mock_draft.return_value = "/tmp/drafts/test.eml"

            result = self.pipeline.process_job(SAMPLE_JOB, force_generate=True)

            self.assertTrue(result.approved)
            self.assertAlmostEqual(result.score, 10.0)
            self.assertTrue(result.ko_triggered == False)

    def test_process_job_intake_invalid(self):
        """Intake returns invalid job — skipped."""
        invalid = {**SAMPLE_INTAKE, "is_valid_job": False,
                   "invalid_reason": "Search results page, not a job"}

        with patch("job_agent.pipeline.llm_request_with_fallback") as mock_llm:
            mock_llm.return_value = _make_mock_llm(json.dumps(invalid))

            result = self.pipeline.process_job(SAMPLE_JOB)

            self.assertFalse(result.approved)
            self.assertIn("Search results", result.message)


# ---------------------------------------------------------------------------
# Test: process_jobs (batch)
# ---------------------------------------------------------------------------


class TestProcessJobs(BasePipelineTest):
    def test_process_multiple(self):
        """Process 2 jobs — one approved, one skipped."""
        with patch("job_agent.pipeline.llm_request_with_fallback") as mock_llm, \
             patch("job_agent.pipeline.generate_email_draft", return_value="/tmp/draft.eml"), \
             patch.object(JobPipeline, "save_pdf", return_value="/tmp/pdf.pdf"):

            # Job 1: high score (approved)
            # Job 2: low score (skipped)
            mock_llm.side_effect = [
                _make_mock_llm(json.dumps(SAMPLE_INTAKE)),       # job1 intake
                _make_mock_llm(json.dumps(SAMPLE_SCORE_HIGH)),   # job1 scoring
                _make_mock_llm(json.dumps(SAMPLE_ANSCHREIBEN)),  # job1 anschreiben
                _make_mock_llm(json.dumps(SAMPLE_INTAKE)),       # job2 intake
                _make_mock_llm(json.dumps(SAMPLE_SCORE_LOW)),    # job2 scoring
            ]

            results = self.pipeline.process_jobs([SAMPLE_JOB, SENIOR_JOB])

            self.assertEqual(len(results), 2)
            self.assertTrue(results[0].approved)
            self.assertFalse(results[1].approved)
            self.assertAlmostEqual(results[0].score, 9.0)
            self.assertAlmostEqual(results[1].score, 3.0)

    def test_process_job_exception(self):
        """Process fails with an unexpected exception — returned as failed result."""
        with patch.object(JobPipeline, "job_intake",
                          side_effect=RuntimeError("Unexpected error")):

            results = self.pipeline.process_jobs([SAMPLE_JOB])

            self.assertEqual(len(results), 1)
            self.assertFalse(results[0].approved)
            self.assertIn("Unexpected error", results[0].message)


# ---------------------------------------------------------------------------
# Test: ProcessResult dataclass
# ---------------------------------------------------------------------------


class TestProcessResult(unittest.TestCase):
    def test_defaults(self):
        """Fresh ProcessResult has correct defaults."""
        result = ProcessResult(job=SAMPLE_JOB)

        self.assertEqual(result.job, SAMPLE_JOB)
        self.assertFalse(result.approved)
        self.assertAlmostEqual(result.score, 0.0)
        self.assertEqual(result.status, "Skipped")

    def test_approved_result(self):
        """Approved result with data."""
        result = ProcessResult(
            job=SAMPLE_JOB,
            approved=True,
            score=9.0,
            status="Draft Generated",
            pdf_path="/tmp/Anschreiben_Tech.pdf",
            draft_path="/tmp/Bewerbung_Tech.eml",
        )

        self.assertTrue(result.approved)
        self.assertAlmostEqual(result.score, 9.0)
        self.assertEqual(result.pdf_path, "/tmp/Anschreiben_Tech.pdf")
        self.assertEqual(result.draft_path, "/tmp/Bewerbung_Tech.eml")


# ---------------------------------------------------------------------------
# Test: JobPosting (fixture integrity)
# ---------------------------------------------------------------------------


class TestJobPosting(unittest.TestCase):
    def test_job_posting_fields(self):
        """Verify JobPosting dataclass fields work as expected."""
        job = SAMPLE_JOB
        self.assertEqual(job.title, "Python Developer (m/w/d)")
        self.assertEqual(job.company, "Tech GmbH")
        self.assertEqual(job.source, "arbeitnow")
        self.assertEqual(job.job_type, "Vollzeit")
        self.assertIn("Python", job.description)
        self.assertIn("Django", job.description)


# ---------------------------------------------------------------------------
# Test: _normalize_profile
# ---------------------------------------------------------------------------


class TestNormalizeProfile(BasePipelineTest):
    def test_fills_missing_names(self):
        """Normalize fills first_name/last_name from 'name' field."""
        profile = {
            "personal_info": {"name": "Anna Schmidt"},
            "skills": [],
            "certifications": [],
        }
        result = self.pipeline._normalize_profile(profile)

        self.assertEqual(result["personal_info"]["first_name"], "Anna")
        self.assertEqual(result["personal_info"]["last_name"], "Schmidt")

    def test_preserves_existing_names(self):
        """Normalize doesn't overwrite if names already present."""
        profile = {
            "personal_info": {"first_name": "Max", "last_name": "Mustermann",
                              "name": "Ignored Name"},
            "skills": [],
            "certifications": [],
        }
        result = self.pipeline._normalize_profile(profile)

        self.assertEqual(result["personal_info"]["first_name"], "Max")
        self.assertEqual(result["personal_info"]["last_name"], "Mustermann")

    def test_normalizes_cert_dicts(self):
        """Certifications in dict format are converted to strings."""
        profile = {
            "personal_info": {},
            "certifications": [
                {"name": "AWS Certified", "date": "2023"},
                "Cisco CCNA",
            ],
        }
        result = self.pipeline._normalize_profile(profile)

        self.assertEqual(result["certifications"], ["AWS Certified", "Cisco CCNA"])


# ---------------------------------------------------------------------------
# Test: Ollama guard — run_pipeline_mode early exit
# ---------------------------------------------------------------------------


class TestOllamaGuard(unittest.TestCase):
    """Test early exit in run_pipeline_mode when Ollama is unavailable."""

    def _make_pipeline_mock(self):
        """Create a mock JobPipeline that doesn't touch the filesystem."""
        mock_pipeline = MagicMock()
        mock_pipeline.candidate_profile = {}
        mock_pipeline.search.return_value = []
        return mock_pipeline

    def _call_pipeline(self, **kwargs):
        """Helper: call run_pipeline_mode with defaults, override any kwarg."""
        defaults = dict(
            workspace_dir="/tmp/test_ollama",
            config={"search": {"max_results": 25}},
            criteria_path="/tmp/criteria.yaml",
            profile_path="/tmp/profile.json",
            search_jobs="Python",
            location="Berlin",
            radius=25,
        )
        defaults.update(kwargs)
        return run_pipeline_mode(**defaults)

    def test_ollama_unavailable_exits_early(self):
        """When Ollama is down + local priority + no cloud fallback,
        run_pipeline_mode returns before searching or processing any jobs."""
        with patch("job_agent.pipeline.ollama_available", return_value=False), \
             patch("job_agent.llm.PRIORITY_LLM", "local"), \
             patch("job_agent.llm.ALLOW_CLOUD_FALLBACK", False), \
             patch("job_agent.pipeline.JobPipeline") as mock_pipeline_cls, \
             patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:

            mock_pipeline_cls.return_value = self._make_pipeline_mock()
            result = self._call_pipeline()

            self.assertIsNone(result)
            mock_pipeline_cls.return_value.search.assert_not_called()
            output = mock_stdout.getvalue()
            self.assertIn("Local LLM required", output)
            self.assertIn("ollama serve", output)

    def test_ignore_ollama_bypasses_guard(self):
        """With --ignore-ollama=True, guard prints warning but PROCEEDS."""
        with patch("job_agent.pipeline.ollama_available", return_value=False), \
             patch("job_agent.llm.PRIORITY_LLM", "local"), \
             patch("job_agent.llm.ALLOW_CLOUD_FALLBACK", False), \
             patch("job_agent.pipeline.JobPipeline") as mock_pipeline_cls, \
             patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:

            mock_pipeline_cls.return_value = self._make_pipeline_mock()
            result = self._call_pipeline(ignore_ollama=True)

            self.assertIsNone(result)
            # search() WAS called — ignore-ollama bypassed the block
            mock_pipeline_cls.return_value.search.assert_called_once()
            # Warning is printed but not a red error
            output = mock_stdout.getvalue()
            self.assertIn("Proceeding", output)
            self.assertNotIn("\u274c", output)  # No ❌ emoji (only in error block)

    def test_ollama_available_proceeds(self):
        """When Ollama IS running, run_pipeline_mode proceeds past the guard."""
        with patch("job_agent.pipeline.ollama_available", return_value=True), \
             patch("job_agent.llm.PRIORITY_LLM", "local"), \
             patch("job_agent.llm.ALLOW_CLOUD_FALLBACK", False), \
             patch("job_agent.pipeline.JobPipeline") as mock_pipeline_cls, \
             patch("sys.stdout", new_callable=io.StringIO):

            mock_pipeline_cls.return_value = self._make_pipeline_mock()
            result = self._call_pipeline()

            self.assertIsNone(result)
            mock_pipeline_cls.return_value.search.assert_called_once()

    def test_cloud_fallback_allowed_skips_guard(self):
        """When ALLOW_CLOUD_FALLBACK=True, guard is skipped even if Ollama down."""
        with patch("job_agent.pipeline.ollama_available", return_value=False), \
             patch("job_agent.llm.PRIORITY_LLM", "local"), \
             patch("job_agent.llm.ALLOW_CLOUD_FALLBACK", True), \
             patch("job_agent.pipeline.JobPipeline") as mock_pipeline_cls, \
             patch("sys.stdout", new_callable=io.StringIO):

            mock_pipeline_cls.return_value = self._make_pipeline_mock()
            result = self._call_pipeline()

            self.assertIsNone(result)
            mock_pipeline_cls.return_value.search.assert_called_once()

    def test_gemini_priority_skips_guard(self):
        """When PRIORITY_LLM is not 'local', guard is skipped."""
        with patch("job_agent.pipeline.ollama_available", return_value=False), \
             patch("job_agent.llm.PRIORITY_LLM", "gemini"), \
             patch("job_agent.llm.ALLOW_CLOUD_FALLBACK", False), \
             patch("job_agent.pipeline.JobPipeline") as mock_pipeline_cls, \
             patch("sys.stdout", new_callable=io.StringIO):

            mock_pipeline_cls.return_value = self._make_pipeline_mock()
            result = self._call_pipeline()

            self.assertIsNone(result)
            mock_pipeline_cls.return_value.search.assert_called_once()


if __name__ == "__main__":
    unittest.main()
