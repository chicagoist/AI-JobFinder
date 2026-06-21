"""Direct email application — generates email drafts instead of sending via SMTP.
GDPR compliance: no automatic email sending, only .eml draft files for manual review."""

from typing import Optional

from job_agent.utils import sanitize_header
import os
import re
import json
import sqlite3
from job_agent.utils import Colors
from job_agent.config import PROMPTS
from job_agent.llm import llm_request_with_fallback, init_gemini
from job_agent.email_draft_generator import generate_email_draft

EMAIL_REGEX = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')


def _looks_like_name(text: str) -> bool:
    words = text.strip().split()
    if len(words) < 1 or len(words) > 3:
        return False
    for w in words:
        w_clean = w.strip(".,-–()\"'")
        if len(w_clean) < 2 or len(w_clean) > 30:
            return False
        if w_clean[0].islower():
            return False
    stopwords = {'Bewerbung', 'Email', 'Mail', 'Kontakt', 'Contact', 'Ansprechpartner',
                 'Recruiter', 'HR', 'Bitte', 'Per', 'Die', 'Der', 'Das', 'Mit', 'Für',
                 'Und', 'Oder', 'Bei', 'Auf', 'Ihre', 'Ihren', 'Ihrer', 'Sie', 'Wir',
                 'Tel', 'Telefon', 'Fax', 'Mobil', 'Mobiltelefon', 'Herr', 'Frau'}
    first_word = words[0].strip(".,-–()\"'")
    if first_word in stopwords:
        return False
    return True


NAME_REGEX = re.compile(
    r'(?:(?:Ansprechpartner|Ansprechpartnerin|Kontakt|contact|recruiter|HR|Ansprechpartner\s+für\s+Bewerbungen|Ihr\s+Ansprechpartner|bei\s+Rückfragen)\s*[\-–]?\s*'
    r'([A-Z][A-Za-zÀ-ÖØ-öø-ÿ]+(?:[ \t][A-Z][A-Za-zÀ-ÖØ-öø-ÿ]+){0,2}))'
)


def extract_contact_info(job_text: str) -> dict | None:
    emails = EMAIL_REGEX.findall(job_text)
    if not emails:
        return None
    email = emails[0].strip()
    recruiter_name = None
    for name_match in NAME_REGEX.finditer(job_text):
        candidate = name_match.group(1).strip()
        if not EMAIL_REGEX.match(candidate) and _looks_like_name(candidate):
            recruiter_name = candidate
            break
    if not recruiter_name:
        try:
            init_gemini()
            prompt = PROMPTS.get("extract_recruiter_prompt", "").format(
                job_text=job_text[:3000],
                email=email
            )
            if prompt:
                resp = llm_request_with_fallback(prompt)
                if resp and resp.text.strip():
                    name = resp.text.strip()
                    if name and len(name) < 100 and not name.startswith('{') and not name.startswith('['):
                        recruiter_name = name
        except Exception:
            pass
    return {"email": email, "recruiter_name": recruiter_name}


def personalize_anschreiben(text: str, recruiter_name: str) -> str:
    if not recruiter_name:
        return text
    name = recruiter_name.strip().split('\n')[0].strip()
    if not name:
        return text
    name_lower = name.lower()
    if name_lower.startswith("herr "):
        greeting = f"Sehr geehrter {name[5:]},"
    elif name_lower.startswith("frau "):
        greeting = f"Sehr geehrte {name[5:]},"
    else:
        greeting = f"Guten Tag {name},"
    text = re.sub(
        r'Sehr geehrte (?:Damen und Herren|Damen\s+und\s+Herren|Herren|Damen)\s*,',
        greeting,
        text,
        count=1,
        flags=re.IGNORECASE
    )
    return text


def _resolve_path(p: str, base_dir: Optional[str] = None) -> str:
    """Resolve a relative path using base_dir when os.getcwd() may differ."""
    if not p:
        return p
    if os.path.isabs(p):
        return p
    if base_dir:
        return os.path.normpath(os.path.join(base_dir, p))
    return os.path.normpath(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), p))


# generate_direct_email_draft and collect_relevant_attachments have been removed.
# Direct employer email is no longer supported (GDPR compliance + user request).
# Only candidate digest (.eml draft) flow remains via email_draft_generator.
