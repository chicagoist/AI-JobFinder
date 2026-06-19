# COMPLIANCE.md — GDPR / DSGVO / EU AI Act Documentation

**Project:** AI-JobFinder  
**Version:** 2.0 (GDPR-Compliant Pipeline)  
**Last Updated:** 2026-06-19  
**Jurisdiction:** Federal Republic of Germany / European Union  
**Branch:** `develop`  

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Data Flow Architecture](#2-data-flow-architecture)
3. [Personal Data Inventory (GDPR Art. 30)](#3-personal-data-inventory-gdpr-art-30)
4. [Legal Basis per Processing Activity](#4-legal-basis-per-processing-activity)
5. [GDPR Art. 22 — Automated Decision-Making](#5-gdpr-art-22--automated-decision-making)
6. [GDPR Art. 35 — Data Protection Impact Assessment (DPIA)](#6-gdpr-art-35--data-protection-impact-assessment-dpia)
7. [EU AI Act Annex III — High-Risk AI Classification](#7-eu-ai-act-annex-iii--high-risk-ai-classification)
8. [BDSG §26 — Employee Data Processing](#8-bdsg-§26--employee-data-processing)
9. [Schrems II — Transborder Data Flows](#9-schrems-ii--transborder-data-flows)
10. [ToS / Contract Law Compliance](#10-tos--contract-law-compliance)
11. [Technical Implementation of Compliance Measures](#11-technical-implementation-of-compliance-measures)
12. [Data Subject Rights (GDPR Art. 15–21)](#12-data-subject-rights-gdpr-art-1521)
13. [Data Retention & Deletion](#13-data-retention--deletion)
14. [Security Measures (GDPR Art. 32)](#14-security-measures-gdpr-art-32)
15. [Data Protection Officer (DPO)](#15-data-protection-officer-dpo)
16. [Audit Trail & Accountability](#16-audit-trail--accountability)
17. [Compliance Checklist](#17-compliance-checklist)

---

## 1. Executive Summary

AI-JobFinder is a Python CLI tool that automates German job applications using artificial intelligence. Version 2.0 has been **completely rearchitected** to achieve full compliance with:

- **GDPR** (Regulation (EU) 2016/679) — General Data Protection Regulation
- **BDSG** (Bundesdatenschutzgesetz) — German Federal Data Protection Act
- **EU AI Act** (Regulation (EU) 2024/1689) — Annex III high-risk AI systems
- **Schrems II** (C-311/18) — Transborder data flow restrictions
- **ToS / Contract Law** — Platform terms of service compliance

### Core Compliance Principles

| Principle | Implementation |
|-----------|---------------|
| **Data Minimization** | Only CV/profile data is processed; recruiter contact data is never stored persistently |
| **Purpose Limitation** | All processing is strictly for job application assistance |
| **Storage Limitation** | PII stored only in local SQLite and `documents/` directory |
| **Integrity & Confidentiality** | All processing is local by default; `.gitignore` blocks PII from version control |
| **Accountability** | Full audit trail in SQLite; this document serves as Art. 30 record |

### Key Design Decisions

```
┌──────────────────────────────────────────────────────┐
│  NO web scraping → Official Job APIs (Bundesagentur) │
│  NO cloud LLM → Local Ollama (llama3.2:3b)           │
│  NO auto emails → .eml drafts for manual review       │
│  NO automated decisions → Human-in-the-loop           │
│  NO PII to US servers → GDPR BLOCK on cloud fallback  │
└──────────────────────────────────────────────────────┘
```

---

## 2. Data Flow Architecture

### 2.1 High-Level Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        AI-JobFinder v2.0                            │
│                    (All processing LOCAL by default)                 │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐  │
│  │ config.yaml  │    │ candidate_   │    │ documents/           │  │
│  │ (API keys,   │    │ profile.json │    │  • CV.pdf            │  │
│  │  SMTP, opts) │    │ (name, addr, │    │  • certificates.pdf  │  │
│  │              │    │  skills, edu)│    │  • diplomas.pdf      │  │
│  └──────┬───────┘    └──────┬───────┘    └──────────┬───────────┘  │
│         │                   │                        │              │
│         └───────────────────┼────────────────────────┘              │
│                             ▼                                       │
│                   ┌──────────────────┐                              │
│                   │   JobPipeline     │                             │
│                   │  (orchestrator)   │                             │
│                   └────────┬─────────┘                              │
│                            │                                        │
│         ┌──────────────────┼──────────────────┐                     │
│         ▼                  ▼                  ▼                     │
│  ┌─────────────┐   ┌─────────────┐    ┌─────────────┐             │
│  │ STAGE 1     │   │ STAGE 2-4   │    │ STAGE 5-6   │             │
│  │ Job Search  │   │ LLM Pipeline│    │ Rendering   │             │
│  │             │   │             │    │ & Drafts    │             │
│  │ Bundesagentur│  │ Ollama LOCAL│    │ Playwright  │             │
│  │ API v6      │   │ llama3.2:3b │    │ headless    │             │
│  │ Arbeitnow   │   │             │    │ Chromium    │             │
│  │ API         │   │ ◄─ PII stays │    │ LOCAL       │             │
│  │             │   │    LOCAL ──► │    │             │             │
│  │ NO scraping │   │ GDPR BLOCK   │    │             │             │
│  │             │   │ on cloud     │    │             │             │
│  └──────┬──────┘   └──────┬──────┘    └──────┬──────┘             │
│         │                  │                  │                     │
│         ▼                  ▼                  ▼                     │
│  ┌──────────────────────────────────────────────────────┐          │
│  │                    LOCAL STORAGE                      │          │
│  │  • output/Anschreiben_*.pdf  — rendered cover letters │          │
│  │  • drafts/*.eml              — email drafts (manual)  │          │
│  │  • output/applications.db    — SQLite audit trail     │          │
│  └──────────────────────────────────────────────────────┘          │
│                                                                     │
│  ┌──────────────────────────────────────────────────────┐          │
│  │              EXTERNAL (NO PII SENT)                   │          │
│  │  • Bundesagentur API  — search query + location only  │          │
│  │  • Arbeitnow API      — no auth, public endpoint      │          │
│  │  LEGEND: → No personal data transmitted externally    │          │
│  └──────────────────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 LLM Data Flow (GDPR-Compliant)

```
llm_request_with_fallback(prompt)
│
├── 1. LOCAL (Ollama)  ← DEFAULT, NO data leaves machine
│   ├── POST http://localhost:11434/api/generate
│   ├── Model: llama3.2:3b (~2 GB, fits in 9 GB RAM)
│   └── ALL PII processed on local CPU/GPU only
│
├── 2. CLOUD FALLBACK BLOCKED  ← GDPR GUARD
│   ├── IF allow_cloud_fallback: false (DEFAULT)
│   │   └── [GDPR BLOCK] → return None
│   │   └── Print: "Personal data will NOT be sent to OpenRouter/Gemini"
│   └── IF allow_cloud_fallback: true (EXPLICIT OPT-IN)
│       └── Proceed to OpenRouter → Gemini
│
├── 3. OPENROUTER  ← Only if explicitly opted in
│   └── POST https://openrouter.ai/api/v1/chat/completions
│
└── 4. GEMINI  ← Only if explicitly opted in
    └── Google Generative AI API
```

### 2.3 Database Schema (Local SQLite)

```sql
-- All tables are stored LOCALLY in output/applications.db

applied_jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name    TEXT,           -- Employer name
    job_title       TEXT,           -- Position title
    url             TEXT UNIQUE,    -- Source URL (reference only)
    score           REAL,           -- LLM recommendation (0.0–10.0)
    applied_date    TEXT,           -- ISO timestamp
    status          TEXT,           -- 'Draft Generated' | 'Skipped (KO)' | etc.
    email_sent      INTEGER DEFAULT 0,
    terminal_output TEXT,           -- Pipeline log (for audit)
    pdf_path        TEXT            -- Path to generated Anschreiben
)

user_rejections (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name    TEXT,
    job_title       TEXT,
    url             TEXT UNIQUE,
    reason          TEXT,           -- User's rejection reason (feedback loop)
    date            TEXT
)

candidate_files (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path       TEXT UNIQUE,
    file_size       INTEGER,
    mtime           REAL,
    classification  TEXT,           -- 'Lebenslauf' | 'Zertifikat' | 'Diplom' | 'Sonstiges'
    parsed_json     TEXT            -- LLM-extracted structured data
)
```

### 2.4 PII Data Inventory Map

| Data Element | Category | Storage Location | Encrypted? | Retention |
|-------------|----------|-----------------|------------|-----------|
| First name, last name | Art. 4(1) personal data | `candidate_profile.json`, `applied_jobs.db` | No (local FS) | Until manual deletion |
| Email address | Art. 4(1) personal data | `candidate_profile.json`, `config.yaml`, `.eml` drafts | No | Until manual deletion |
| Phone number | Art. 4(1) personal data | `candidate_profile.json`, Anschreiben PDFs | No | Until manual deletion |
| Home address | Art. 4(1) personal data | `candidate_profile.json`, Anschreiben PDFs | No | Until manual deletion |
| CV content (skills, education, experience) | Art. 4(1) personal data | `candidate_profile.json`, `documents/*.pdf` | No | Until manual deletion |
| LLM prompts (contain PII) | Art. 4(1) personal data | Transient (RAM), never persisted | N/A | RAM only (~seconds) |
| Recruiter email addresses | Art. 4(1) personal data | Transient (`.eml` draft only), never in DB | No | `.eml` file until sent/deleted |
| Job application history | Art. 4(1) personal data | `output/applications.db` | No | Until `--reset-candidate` |
| API keys (Gemini, OpenRouter) | Art. 4(1) + security | `config.yaml` (Gemini), env vars (OpenRouter) | No | Until manual change |
| SMTP credentials | Art. 4(1) + security | `config.yaml` | No | Until manual change |

---

## 3. Personal Data Inventory (GDPR Art. 30)

### 3.1 Controller Information

- **Controller:** The USER operating AI-JobFinder on their personal machine
- **Software Tool:** AI-JobFinder (Open Source, MIT License)
- **Processing Location:** User's local machine (not a cloud service)
- **Category:** Natural person processing their own data for job applications

### 3.2 Processing Activities Register

| Processing Activity | Purpose | Legal Basis | Data Categories | Recipients | Retention |
|--------------------|---------|-------------|-----------------|------------|-----------|
| CV Parsing (LLM) | Extract structured profile from CV PDF | Art. 6(1)(f) — legitimate interest (job search) | Name, address, education, skills, experience | **NONE** (local Ollama) | Until manual deletion |
| Job Scoring (LLM) | Match candidate profile against job posting | Art. 6(1)(f) — legitimate interest | Profile + job posting text | **NONE** (local Ollama) | Transient (RAM) |
| Cover Letter Generation (LLM) | Generate personalized Anschreiben | Art. 6(1)(f) — legitimate interest | Profile + job posting text | **NONE** (local Ollama) | PDF on disk until deleted |
| PDF Rendering | Format cover letter to DIN 5008 | Art. 6(1)(f) — legitimate interest | Cover letter text + sender info | **NONE** (local Playwright) | PDF on disk until deleted |
| Email Draft Generation | Create `.eml` for manual sending | Art. 6(1)(f) — legitimate interest | Cover letter + attachments | **NONE** (local FS) | `.eml` until sent/deleted |
| Job API Queries | Discover job vacancies | Art. 6(1)(f) — legitimate interest | Search query + location (NO PII) | Bundesagentur API, Arbeitnow API | Transient (RAM) |
| Application Logging | Track application history | Art. 6(1)(f) — legitimate interest | Company, job title, score, date | **NONE** (local SQLite) | Until `--reset-candidate` |

### 3.3 Data NOT Processed

The following data categories are **explicitly NOT processed** by AI-JobFinder v2.0:

- ❌ Recruiter personal data stored in any database
- ❌ Browser cookies or session data from job platforms
- ❌ Login credentials for job platforms (Indeed, LinkedIn, etc.)
- ❌ IP addresses of job platform servers (legacy scraping removed)
- ❌ Behavioral data or usage analytics
- ❌ Any data sent to US-based cloud providers (by default)

---

## 4. Legal Basis per Processing Activity

### 4.1 Legitimate Interest (Art. 6(1)(f) GDPR)

All processing activities are based on **legitimate interest** — the user's interest in finding employment:

| Activity | Legitimate Interest Assessment |
|----------|-------------------------------|
| CV parsing | User needs structured profile for job matching — no less intrusive alternative exists |
| Job scoring | User needs efficient filtering of vacancies — manual review of 100s of jobs is impractical |
| Cover letter generation | User needs personalized, DIN 5008-compliant letters — LLM assists, user reviews before sending |
| Email draft creation | User needs to communicate with employers — `.eml` drafts ensure manual review |
| Job API queries | User needs to discover vacancies — official APIs are the least intrusive method |
| Application logging | User needs to track applications to avoid duplicates — local SQLite is minimal storage |

**Balancing Test:**
- The processing is expected by the user (job application tool)
- The impact on third parties (employers, recruiters) is minimal:
  - No automated contact — `.eml` drafts require manual sending
  - No persistent storage of recruiter data
  - No automated decision-making (see §5)
- The user can stop processing at any time (exit the CLI)
- Data is stored locally, minimizing exposure risk

### 4.2 Consent (Art. 6(1)(a) GDPR) — Explicit Opt-In for Cloud LLM

Cloud LLM fallback (OpenRouter / Gemini) is **disabled by default** (`allow_cloud_fallback: false`). Enabling it requires:

1. Manual edit of `config.yaml` → `llm.allow_cloud_fallback: true`
2. User acknowledges GDPR warning printed by the application:
   ```
   [GDPR BLOCK] Cloud fallback is DISABLED — PII stays local.
   Personal data will NOT be sent to OpenRouter/Gemini (US servers).
   To enable cloud fallback (at your own risk), set in config.yaml:
     llm.allow_cloud_fallback: true
   ```

This constitutes **explicit consent** under Art. 6(1)(a) and Art. 49(1)(a) for international data transfers.

### 4.3 No Special Category Data (Art. 9 GDPR)

AI-JobFinder does **not** process special category data:
- No racial or ethnic origin data
- No political opinions
- No religious or philosophical beliefs
- No trade union membership
- No genetic or biometric data
- No health data
- No data concerning sex life or sexual orientation

**Exception:** CVs may contain implied information (e.g., language skills implying ethnic origin, photo implying racial data). Users should redact such information from CVs before processing.

---

## 5. GDPR Art. 22 — Automated Decision-Making

### 5.1 Art. 22 Analysis

> "The data subject shall have the right not to be subject to a decision based solely on automated processing, including profiling, which produces legal effects concerning him or her or similarly significantly affects him or her."

**AI-JobFinder compliance:**

| Art. 22 Element | AI-JobFinder Implementation |
|----------------|----------------------------|
| "Decision based solely on automated processing" | ❌ NOT applicable — the LLM provides a **recommendation** (score 0–10), not a decision |
| "Produces legal effects" | ❌ NOT applicable — the tool generates `.eml` drafts; the USER decides whether to send |
| "Similarly significantly affects" | ❌ NOT applicable — the user reviews and may override any recommendation |

### 5.2 Human-in-the-Loop Design

```
┌──────────────────────────────────────────────────┐
│              PIPELINE FLOW                       │
├──────────────────────────────────────────────────┤
│                                                  │
│  LLM scores job → 7.5/10 (recommendation)        │
│         │                                        │
│         ▼                                        │
│  [HUMAN REVIEW] ← User sees score + reasoning    │
│         │                                        │
│    ┌────┴────┐                                   │
│    ▼         ▼                                   │
│  APPROVE   REJECT                                │
│    │         │                                   │
│    ▼         ▼                                   │
│  Generate  Log rejection                         │
│  draft     reason (feedback                      │
│            loop)                                 │
│                                                  │
│  [HUMAN SEND] ← User opens .eml manually          │
│                                                  │
└──────────────────────────────────────────────────┘
```

### 5.3 Art. 22(2) Exceptions

Even if Art. 22 were applicable (which it is not, as established above), the following exceptions would apply:

- **Art. 22(2)(a):** Necessary for entering into a contract — job application is a pre-contractual measure
- **Art. 22(2)(c):** Based on explicit consent — `--auto-approve` flag provides explicit opt-in
- **Art. 22(3):** The user has the right to obtain human intervention, express their point of view, and contest the decision — all supported by the interactive pipeline design

---

## 6. GDPR Art. 35 — Data Protection Impact Assessment (DPIA)

### 6.1 DPIA Requirement Analysis

A DPIA is required when processing is "likely to result in a high risk to the rights and freedoms of natural persons" (Art. 35(1)).

**Assessment:** Given that AI-JobFinder:
- Processes personal data of the **user themselves** (not third parties at scale)
- Stores data **locally only** (not in cloud)
- Does **not** make automated decisions
- Does **not** process special category data (Art. 9)
- Does **not** monitor publicly accessible areas (Art. 35(3)(c))

→ A full formal DPIA is **not mandatory** under Art. 35 for the default (local-only) mode.

### 6.2 DPIA Lite (Voluntary)

| DPIA Element | Assessment |
|-------------|-----------|
| **Description of processing** | See §2 Data Flow Architecture and §3 Personal Data Inventory |
| **Necessity & proportionality** | All processing is necessary for job applications; data minimization is enforced |
| **Risks to rights & freedoms** | LOW — all data stays local; no third-party data at scale; no automated decisions |
| **Measures to address risks** | Local-only LLM, GDPR block on cloud, `.gitignore` PII, human-in-the-loop, `--reset-candidate` deletion |
| **Residual risk** | LOW — if user enables cloud LLM, PII may transit to US; clearly warned and opt-in only |

### 6.3 Special Case: Cloud LLM Opt-In

If the user **explicitly opts in** to cloud LLM (`allow_cloud_fallback: true`):
- Risk level increases to **MEDIUM** (international data transfer to US)
- Mitigation: Explicit consent (Art. 49(1)(a)), user is warned via GDPR BLOCK message
- Recommendation: User should conduct their own transfer impact assessment (TIA) per Schrems II

---

## 7. EU AI Act Annex III — High-Risk AI Classification

### 7.1 Classification

Under **Annex III, Point 4(a)** of the EU AI Act (Regulation 2024/1689), AI systems intended to be used for:

> "recruitment or selection of natural persons, notably to place targeted job advertisements, to analyse and filter job applications, and to evaluate candidates"

are classified as **high-risk AI systems**.

**AI-JobFinder's position:**

| AI Act Element | AI-JobFinder Assessment |
|---------------|------------------------|
| **Classification** | Potentially high-risk (job scoring + cover letter generation) |
| **Compliance Deadline** | December 2, 2027 (per AI Omnibus amendment) |
| **Human Oversight (Art. 14)** | ✅ Implemented — user reviews all scores, decides manually |
| **Transparency (Art. 13)** | ✅ Implemented — scores shown with reasoning text (German) |
| **Risk Management (Art. 9)** | ✅ Implemented — KO filters prevent clearly inappropriate applications |
| **Data Governance (Art. 10)** | ✅ Implemented — training data is the user's own CV/profile |
| **Technical Documentation (Art. 11)** | ✅ This document + AGENTS.md + README.md |
| **Record-Keeping (Art. 12)** | ✅ SQLite audit trail of all applications |
| **Accuracy (Art. 15)** | ✅ Scoring used as recommendation only, not binding decision |

### 7.2 Mitigation: De-Risking the Classification

AI-JobFinder's design intentionally limits the AI Act's scope:

1. **Not a "recruitment" system:** It assists a single individual's job search, not an employer's candidate screening
2. **No automated filtering:** The LLM provides a **recommendation**, not a rejection
3. **Human-in-the-loop:** All outputs require manual review and action
4. **No "placing" of ads:** The tool searches existing public listings via APIs
5. **Local deployment:** Not a SaaS product — runs on user's personal machine

**Argument:** AI-JobFinder is more akin to a **productivity tool** (like a word processor with grammar checking) than a high-risk recruitment AI. The user remains in full control at every stage.

### 7.3 Compliance Roadmap

| Milestone | Status | Deadline |
|-----------|--------|----------|
| Human oversight (Art. 14) | ✅ DONE | N/A |
| Transparency (Art. 13) | ✅ DONE | N/A |
| Risk management (Art. 9) | ✅ DONE | N/A |
| Technical documentation (Art. 11) | ✅ DONE | N/A |
| Record-keeping (Art. 12) | ✅ DONE | N/A |
| CE marking / conformity assessment | ⏳ Not applicable (not commercial product) | Dec 2, 2027 |
| Registration in EU database | ⏳ Not applicable (not deployed as service) | Dec 2, 2027 |

---

## 8. BDSG §26 — Employee Data Processing

### 8.1 Applicability

**BDSG §26** governs the processing of employee data for employment-related purposes. AI-JobFinder is used by a **job seeker**, not an employer, so §26 primarily applies:

- **Directly:** To the processing of the user's own employee-like data (CV, profile)
- **Indirectly:** To the generated Anschreiben which will be sent to employers

### 8.2 BDSG §26(1) — Data Processing for Employment Purposes

> "Personal data of employees may be processed for purposes of the employment relationship if this is necessary for the decision on the establishment of an employment relationship..."

**AI-JobFinder compliance:**

- The processing is **necessary** for the job application purpose
- Data is **minimized** — only what is needed for applications
- No **excessive** data collection — profile limited to relevant professional data

### 8.3 BDSG §26(3) — Consent

Processing based on consent must be voluntary. AI-JobFinder's design:

- User **voluntarily** provides their CV and profile data
- User can **withdraw** at any time by deleting files or `--reset-candidate`
- No **detriment** for non-consent (the tool is user-operated)

### 8.4 BDSG §26(5) — Special Safeguards

> "The controller shall take appropriate measures to safeguard the data subject's legitimate interests."

| Safeguard | Implementation |
|-----------|---------------|
| Data minimization | Only CV + profile data is processed |
| Transparency | All LLM scores come with reasoning text |
| Erasure | `--reset-candidate` deletes all generated data |
| Confidentiality | Local processing by default, `.gitignore` for PII |

---

## 9. Schrems II — Transborder Data Flows

### 9.1 Analysis

The CJEU ruling in **Schrems II** (C-311/18) invalidated the EU-US Privacy Shield and imposed strict requirements on international data transfers, particularly to the United States.

### 9.2 AI-JobFinder's Position

| Scenario | Transfer? | Mitigation |
|----------|-----------|------------|
| **Default mode (Ollama)** | ❌ NO — all data stays on local machine | No transfer = no Schrems II issue |
| **Cloud LLM enabled** | ⚠️ YES — PII sent to OpenRouter (US) or Gemini (US) | Explicit opt-in only; user warned; Art. 49(1)(a) consent |
| **Job API queries** | ❌ NO PII — only search query + location | No personal data in API requests |

### 9.3 Transfer Impact Assessment (TIA) — Cloud LLM Case

If the user opts into cloud LLM:

| TIA Element | Assessment |
|------------|-----------|
| **Destination** | United States (OpenRouter servers, Google Cloud) |
| **Data transferred** | CV text, job descriptions (mixed with profile PII) |
| **US surveillance laws** | FISA §702, EO 12333 — US authorities may access data in transit |
| **Supplementary measures** | None available (plaintext LLM API calls) |
| **Risk** | Medium — data in transit may be intercepted; Google/OpenRouter process data per their ToS |
| **Mitigation** | ONLY via explicit consent (Art. 49(1)(a)); user should use local Ollama |

### 9.4 Recommendation

**Users should keep `allow_cloud_fallback: false`** (the default). The local Ollama model (`llama3.2:3b`) is sufficient for job scoring and cover letter generation. Cloud LLMs are provided only as a convenience fallback and their use is at the user's own risk.

---

## 10. ToS / Contract Law Compliance

### 10.1 Web Scraping — REMOVED in v2.0

AI-JobFinder v1.x used Playwright to scrape Indeed and LinkedIn — this violated platform ToS and potentially:
- US Computer Fraud and Abuse Act (CFAA)
- German Urheberrechtsgesetz (UrhG) — database rights (Sections 87a–87e)
- German Gesetz gegen den unlauteren Wettbewerb (UWG) — unfair competition

**v2.0 has removed ALL web scraping functions:**
- `search_indeed()` — DELETED
- `search_linkedin()` — DELETED
- `fill_page_form()` — DELETED
- `try_linkedin_easy_apply()` — DELETED
- `get_browser_context()` — DELETED
- `process_job_url()` — DELETED

### 10.2 Official APIs Used Instead

| API | Legal Basis | Authentication |
|-----|------------|---------------|
| **Bundesagentur für Arbeit API v6** | Public API with documented `X-API-Key` header | Public key: `jobboerse-jobsuche` |
| **Arbeitnow API** | Free, public job board API | None required |

### 10.3 Playwright Usage — Limited to PDF Rendering

Playwright remains in the codebase **only** for:
- `save_anschreiben_pdf()` — renders HTML to DIN 5008 PDF (headless Chromium)
- `generate_dummy_cv()` — generates test CV for development

No Playwright calls interact with any external website or job platform.

### 10.4 UrhG Database Rights

By using official APIs instead of scraping:
- No bulk extraction from protected databases (UrhG §87a–87e)
- API responses are provided under each platform's API terms
- Data volume is limited to `max_results` (~25 per search)

---

## 11. Technical Implementation of Compliance Measures

### 11.1 GDPR Block on Cloud LLM

**File:** `src/job_agent/llm.py`

```python
ALLOW_CLOUD_FALLBACK = False  # Must be explicitly set to true in config.yaml
_gdpr_warning_shown = False   # Show GDPR block warning only once per session

def init_gemini(config_path=None, force=False):
    # ...
    ALLOW_CLOUD_FALLBACK = config.get("llm", {}).get("allow_cloud_fallback", False)

def llm_request_with_fallback(prompt, **kwargs):
    if PRIORITY_LLM == "local":
        if ollama_available(LOCAL_MODEL):
            return call_ollama(...)  # LOCAL — no data leaves machine
        if not ALLOW_CLOUD_FALLBACK:
            # [GDPR BLOCK] — print warning once, return None
            global _gdpr_warning_shown
            if not _gdpr_warning_shown:
                _gdpr_warning_shown = True
                print("[GDPR BLOCK] Cloud fallback is DISABLED — PII stays local.")
            return None
```

### 11.2 Email Drafts Instead of SMTP Auto-Send

**File:** `src/job_agent/direct_email_applier.py`

```python
def generate_direct_email_draft(...):
    """Generate .eml draft for manual sending (NOT automatic SMTP)."""
    # Writes .eml files to drafts/ directory
    # User must open and send manually via mail client
```

The old `send_direct_email()` function (which used SMTP to automatically email recruiters) has been **REMOVED**.

### 11.3 Human-in-the-Loop Pipeline

**File:** `src/job_agent/pipeline.py`

```
Pipeline stages:
  1. Search (APIs)    — NO personal data sent
  2. Intake (LLM)     — LOCAL Ollama, validates job posting
  3. Scoring (LLM)    — LOCAL Ollama, produces 0-10 recommendation
  4. Cover Letter     — LOCAL Ollama, generates Anschreiben text
  5. PDF Rendering    — LOCAL Playwright, DIN 5008 format
  6. Email Draft      — LOCAL .eml file, NO automatic sending
```

At each stage, the user sees output and can interrupt the pipeline. Scores below threshold are logged as "Skipped" — not rejected, just deprioritized.

### 11.4 Data Minimization in Code

| Principle | Implementation |
|-----------|---------------|
| Only process what's needed | Pipeline only loads CV/profile once per session; job descriptions truncated to 3000 chars |
| Delete when done | `--reset-candidate` purges all PII (DB, PDFs, configs) |
| Don't store recruiter data | Recruiter emails extracted from job text are used only in `.eml` draft, never stored in DB |
| Don't log PII in plaintext | Terminal output captures are `.eml` attachments only, not persisted to DB separately |

### 11.5 File Blocking via .gitignore

The following PII-containing files are blocked from version control:

```gitignore
# PII data (block all)
*.pdf
*.db
*.sqlite
*.zip
*.png
*.jpg
*.html
config.yaml
candidate_profile.json
.env
output/
chrome_data/
temp_profile/
```

---

## 12. Data Subject Rights (GDPR Art. 15–21)

Since AI-JobFinder processes data **locally** on the user's machine, the user can exercise their rights directly:

| Right | How to Exercise |
|-------|----------------|
| **Art. 15 — Right of Access** | Open `candidate_profile.json`, `config.yaml`, `output/applications.db` |
| **Art. 16 — Right to Rectification** | Edit `candidate_profile.json` or re-run `--parse-cv` |
| **Art. 17 — Right to Erasure** | Run `python src/agent.py --reset-candidate` (deletes all PII) |
| **Art. 18 — Right to Restriction** | Set `llm.priority: local` in `config.yaml` (no external processing) |
| **Art. 20 — Right to Data Portability** | `candidate_profile.json` is structured JSON — portable by design |
| **Art. 21 — Right to Object** | Stop the CLI process (Ctrl+C); no persistent background processing |

### Third-Party Data Subject Rights

Recruiters whose email addresses are extracted from job postings:
- Data is **never stored persistently** (only in `.eml` draft)
- User sends `.eml` manually — becomes a direct communication under ePrivacy
- Recruiter can object — user simply does not send the draft

---

## 13. Data Retention & Deletion

### 13.1 Default Retention

| Data | Retention Period | Deletion Method |
|------|-----------------|-----------------|
| `candidate_profile.json` | Until manual deletion | `rm config/candidate_profile.json` |
| `output/applications.db` | Until `--reset-candidate` | `python src/agent.py --reset-candidate` |
| `output/Anschreiben_*.pdf` | Until manual deletion or `--reset-candidate` | Same as above |
| `drafts/*.eml` | Until manually sent or deleted | `rm drafts/*.eml` |
| LLM prompts (RAM) | Duration of LLM call (~seconds) | Automatic (garbage collected) |
| Job search results (RAM) | Duration of pipeline run | Automatic (process exit) |

### 13.2 Reset Procedure

```bash
# Full PII deletion:
python src/agent.py --reset-candidate

# This performs:
# 1. git commit "RESTORE" (backup of current state)
# 2. Delete applications.db
# 3. Delete all PDFs in output/
# 4. Delete all HTML/PNG/ZIP artifacts
# 5. Restore .sample configs over active configs
# 6. Clear candidate_files DB table
```

### 13.3 No Cloud Persistence

AI-JobFinder does **not**:
- Upload data to any cloud storage
- Use any external database service
- Send telemetry or usage analytics
- Cache data on third-party servers

All data is stored **exclusively** on the user's local filesystem.

---

## 14. Security Measures (GDPR Art. 32)

### 14.1 Technical Measures

| Measure | Implementation | Coverage |
|---------|---------------|----------|
| **Local processing** | All LLM, PDF, DB on local machine | Default |
| **No network exposure** | API keys in local config files (not network services) | Default |
| **Input validation** | JSON repair (`clean_and_repair_json`), type hints | All LLM outputs |
| **Error handling** | Graceful fallbacks; `_default_intake()` on LLM failure | All pipeline stages |
| **.gitignore** | PII files excluded from version control | All PII |
| **Pre-commit hooks** | `check_secrets.py` scans staged files | Git operations |

### 14.2 Organizational Measures

| Measure | Implementation |
|---------|---------------|
| **Documentation** | This COMPLIANCE.md document |
| **Audit trail** | SQLite `applied_jobs` table logs all processing |
| **User control** | Human-in-the-loop for all decisions |
| **Transparency** | All scores shown with reasoning text |
| **Training** | AGENTS.md provides developer guidance on PII handling |

### 14.3 Encryption

- **At rest:** Not encrypted (local filesystem). Users should use full-disk encryption (LUKS, BitLocker, FileVault).
- **In transit (Ollama):** `http://localhost:11434` — loopback interface, no network exposure.
- **In transit (Cloud LLM, opt-in):** HTTPS (TLS 1.2+) to OpenRouter and Gemini APIs.
- **Email drafts (`.eml`):** Plaintext on disk. Users should store in encrypted directory if concerned.

---

## 15. Data Protection Officer (DPO)

### 15.1 DPO Requirement Analysis

Under GDPR Art. 37 and BDSG §38, a DPO must be designated if:

1. Processing is carried out by a public authority (❌ — AI-JobFinder is a personal tool)
2. Core activities consist of large-scale regular monitoring of data subjects (❌ — single user, local processing)
3. Core activities consist of large-scale processing of special category data (❌ — no special category data)

→ **A DPO is NOT legally required** for AI-JobFinder's use case.

### 15.2 Voluntary DPO Contact

For inquiries about data protection in the context of this project, contact:

```
[DPO Contact Placeholder]
Email: [dpo@example.com]
PGP Key: [Optional]
```

> **Note for contributors/forkers:** Insert your DPO contact here if you modify the project for commercial deployment.

### 15.3 Supervisory Authority

The competent supervisory authority is:

```
Der Hessische Beauftragte für Datenschutz und Informationsfreiheit (HBDI)
Gustav-Stresemann-Ring 1
65189 Wiesbaden
Germany
Phone: +49 611 1408-0
Email: poststelle@datenschutz.hessen.de
Website: https://datenschutz.hessen.de
```

> Update the supervisory authority based on your German state (Bundesland). The above is for Hessen.

---

## 16. Audit Trail & Accountability

### 16.1 SQLite Audit Log

Every job processed through the pipeline is logged in `output/applications.db`:

```sql
SELECT company_name, job_title, url, score, applied_date, status, pdf_path
FROM applied_jobs
ORDER BY applied_date DESC;
```

This provides a complete audit trail for GDPR Art. 5(2) accountability.

### 16.2 Terminal Output

Pipeline runs produce colored terminal output showing:
- Each stage (1–6) with status
- LLM scores with reasoning text
- KO filter triggers with reasons
- PDF and draft paths

This output can be captured for audit purposes:
```bash
python src/agent.py --pipeline 2>&1 | tee pipeline_audit_$(date +%Y%m%d).log
```

### 16.3 Git History

Compliance-related changes are tracked in git:
```bash
git log --oneline | head -20
# Shows commits like:
# "fix: GDPR — block silent PII transfer to US cloud"
# "refactor: remove dead imports after legacy scraping cleanup"
```

---

## 17. Compliance Checklist

### 17.1 GDPR Compliance

| # | Requirement | Article | Status | Evidence |
|---|-----------|---------|--------|----------|
| 1 | Lawful basis for processing | Art. 6 | ✅ | Legitimate interest (Art. 6(1)(f)); Consent for cloud LLM (Art. 6(1)(a)) |
| 2 | Data minimization | Art. 5(1)(c) | ✅ | Only CV/profile data; 3000-char job text limit |
| 3 | Purpose limitation | Art. 5(1)(b) | ✅ | Strictly job applications only |
| 4 | Storage limitation | Art. 5(1)(e) | ✅ | `--reset-candidate` enables deletion |
| 5 | Accuracy | Art. 5(1)(d) | ✅ | User can edit `candidate_profile.json` |
| 6 | Integrity & confidentiality | Art. 5(1)(f) | ✅ | Local processing; `.gitignore` PII |
| 7 | Accountability | Art. 5(2) | ✅ | This document; SQLite audit trail; git history |
| 8 | Data Protection Impact Assessment | Art. 35 | ✅ | §6 DPIA Lite (not mandatory, conducted voluntarily) |
| 9 | Records of processing activities | Art. 30 | ✅ | §3 Personal Data Inventory |
| 10 | Security of processing | Art. 32 | ✅ | §14 Security Measures |
| 11 | Data Protection Officer | Art. 37 | N/A | Not required (see §15) |
| 12 | Automated decision-making | Art. 22 | ✅ | Not applicable; human-in-the-loop design (§5) |
| 13 | Right of access | Art. 15 | ✅ | Local files accessible to user (§12) |
| 14 | Right to rectification | Art. 16 | ✅ | Edit `candidate_profile.json` |
| 15 | Right to erasure | Art. 17 | ✅ | `--reset-candidate` command |
| 16 | Right to restriction | Art. 18 | ✅ | Set `priority: local`, disable cloud |
| 17 | Data portability | Art. 20 | ✅ | JSON format by design |
| 18 | Right to object | Art. 21 | ✅ | Ctrl+C to stop processing |
| 19 | International transfers | Art. 44–49 | ✅ | No transfers by default; explicit consent if enabled (§9) |

### 17.2 EU AI Act Compliance

| # | Requirement | Article | Status | Evidence |
|---|-----------|---------|--------|----------|
| 1 | Risk classification | Annex III.4(a) | ✅ | Assessed as potentially high-risk; de-risked via design (§7) |
| 2 | Human oversight | Art. 14 | ✅ | Human-in-the-loop for all decisions |
| 3 | Transparency | Art. 13 | ✅ | Scores shown with reasoning |
| 4 | Risk management | Art. 9 | ✅ | KO filters + scoring thresholds |
| 5 | Data governance | Art. 10 | ✅ | User's own CV as training context |
| 6 | Technical documentation | Art. 11 | ✅ | This document + README + AGENTS.md |
| 7 | Record-keeping | Art. 12 | ✅ | SQLite audit trail |
| 8 | Accuracy | Art. 15 | ✅ | Recommendation only, not binding |
| 9 | Compliance deadline | — | ✅ | Ready for Dec 2, 2027 |

### 17.3 BDSG Compliance

| # | Requirement | Section | Status | Evidence |
|---|-----------|---------|--------|----------|
| 1 | Employee data processing | §26(1) | ✅ | Necessary for job applications |
| 2 | Consent voluntariness | §26(3) | ✅ | User provides data voluntarily |
| 3 | Safeguards | §26(5) | ✅ | Local processing, data minimization |
| 4 | DPO designation | §38 | N/A | Not required |

### 17.4 ToS / Contract Law

| # | Requirement | Status | Evidence |
|---|-----------|--------|----------|
| 1 | No web scraping | ✅ | All scraping functions removed in v2.0 |
| 2 | Official APIs only | ✅ | Bundesagentur API v6, Arbeitnow API |
| 3 | No ToS circumvention | ✅ | No browser automation against job platforms |
| 4 | Database rights (UrhG §87a) | ✅ | API-based access respects DB rights |
| 5 | No automated outreach | ✅ | `.eml` drafts require manual sending |

---

## Appendix A: Glossary

| Term | Definition |
|------|-----------|
| **PII** | Personally Identifiable Information — any data relating to an identified or identifiable natural person (GDPR Art. 4(1)) |
| **LLM** | Large Language Model — AI model used for text generation (scoring, cover letters) |
| **Ollama** | Local LLM runtime — runs models entirely on the user's machine |
| **CDP** | Chrome DevTools Protocol — used by Playwright for browser automation |
| **DPIA** | Data Protection Impact Assessment (GDPR Art. 35) |
| **DPO** | Data Protection Officer (GDPR Art. 37) |
| **DIN 5008** | German standard for business letter formatting |
| **Anschreiben** | Cover letter (German) |
| **Bewerbung** | Job application (German) |
| **KO** | Knock-Out — filter criteria that immediately disqualify a job |

## Appendix B: References

| Reference | Full Title |
|-----------|-----------|
| GDPR | Regulation (EU) 2016/679 of the European Parliament and of the Council of 27 April 2016 |
| BDSG | Bundesdatenschutzgesetz (German Federal Data Protection Act), as amended 2018 |
| EU AI Act | Regulation (EU) 2024/1689 laying down harmonised rules on artificial intelligence |
| Schrems II | CJEU Judgment C-311/18, Data Protection Commissioner v Facebook Ireland Ltd, Maximillian Schrems |
| UrhG | Urheberrechtsgesetz (German Copyright Act), Sections 87a–87e (database rights) |
| UWG | Gesetz gegen den unlauteren Wettbewerb (German Act Against Unfair Competition) |

## Appendix C: Document History

| Date | Version | Changes |
|------|---------|---------|
| 2026-06-19 | 1.0 | Initial COMPLIANCE.md — covers GDPR, DSGVO, EU AI Act, Schrems II, ToS |
| — | — | AI-JobFinder v2.0: all web scraping removed, local LLM default, email drafts only |

---

**This document is part of the AI-JobFinder project's accountability record under GDPR Art. 5(2) and Art. 30.**  
**It should be reviewed and updated whenever processing activities change.**
