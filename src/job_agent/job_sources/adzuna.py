"""Adzuna — global job search API adapter (Germany).

Public REST API with free tier for job listings, salary trends, and vacancy stats.
Free tier: API key required (register at https://developer.adzuna.com/).

API docs: https://developer.adzuna.com/overview
"""

import os
import re
import html
from typing import Optional, cast
import requests
from job_agent.job_sources import JobPosting
from job_agent.utils import Colors

BASE_URL = "https://api.adzuna.com/v1/api/jobs/de/search"
TIMEOUT = 15

# Credentials from config.yaml -> adzuna section (no env vars)
def _get_adzuna_credentials() -> tuple[str, str]:
    try:
        import yaml
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "config", "config.yaml",
        )
        if os.path.exists(config_path):
            with open(config_path) as f:
                config = yaml.safe_load(f) or {}
            adzuna = config.get("adzuna", {}) or {}
            return adzuna.get("app_id", "") or "", adzuna.get("app_key", "") or ""
    except Exception:
        pass
    return "", ""


ADZUNA_APP_ID, ADZUNA_APP_KEY = _get_adzuna_credentials()


def search_adzuna(
    query: str,
    location: str,
    radius: int = 25,
    max_results: int = 50,
) -> list[JobPosting]:
    """Search jobs via Adzuna API for Germany.

    Args:
        query: Search keywords (e.g. "Lehrer")
        location: Location (e.g. "Hanau")
        radius: Search radius in km
        max_results: Maximum results to return (API max 50 per page)

    Returns:
        List of JobPosting objects.
    """
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        print(f"{Colors.YELLOW}[Adzuna API] No credentials set. "
              f"Add adzuna.app_id and adzuna.app_key to config.yaml. Skipping.{Colors.END}")
        return []

    all_jobs: list[JobPosting] = []
    results_per_page = min(max_results, 50)

    url = (f"{BASE_URL}/1?app_id={ADZUNA_APP_ID}"
           f"&app_key={ADZUNA_APP_KEY}"
           f"&what={requests.utils.quote(query)}"
           f"&where={requests.utils.quote(location)}"
           f"&results_per_page={results_per_page}")

    headers = {
        "User-Agent": "curl/7.88.1",
        "Accept": "*/*",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=TIMEOUT)
    except requests.Timeout:
        print(f"{Colors.YELLOW}[Adzuna API] Timeout. Skipping.{Colors.END}")
        return []
    except requests.ConnectionError as e:
        print(f"{Colors.YELLOW}[Adzuna API] Connection error: {e}. Skipping.{Colors.END}")
        return []
    except Exception as e:
        print(f"{Colors.YELLOW}[Adzuna API] Request failed: {e}. Skipping.{Colors.END}")
        return []

    if resp.status_code != 200:
        if resp.status_code == 401:
            print(f"{Colors.YELLOW}[Adzuna API] HTTP 401 — Invalid credentials. "
                  f"Check adzuna section in config.yaml.{Colors.END}")
        else:
            print(f"{Colors.YELLOW}[Adzuna API] HTTP {resp.status_code}: {resp.text[:200]}. Skipping.{Colors.END}")
        return []

    try:
        data = resp.json()
    except Exception as e:
        print(f"{Colors.YELLOW}[Adzuna API] JSON parse error: {e}{Colors.END}")
        return []

    jobs_data = data.get("results", [])
    if not jobs_data:
        print(f"{Colors.GREY}[Adzuna API] No jobs found.{Colors.END}")
        return []

    for item in jobs_data:
        if not isinstance(item, dict):
            continue

        title = item.get("title", "") or "Unbekannt"
        company = _extract_company(item) or "Unbekannt"
        location_str = item.get("location", {}).get("display_name", "") or location
        url = item.get("redirect_url", "") or item.get("url", "") or ""

        description = _build_description(item)
        salary = _extract_salary(item)
        job_type = _extract_job_type(item)

        all_jobs.append(JobPosting(
            title=title,
            company=company,
            location=location_str,
            url=url,
            description=description,
            source="adzuna",
            salary=salary,
            job_type=job_type,
        ))

    print(f"{Colors.GREEN}[Adzuna API] {len(all_jobs)} jobs loaded{Colors.END}")
    return all_jobs


def _extract_company(item: dict) -> Optional[str]:
    """Extract company name from Adzuna response."""
    company = item.get("company", {})
    if isinstance(company, dict):
        return cast(Optional[str], company.get("display_name"))
    return str(company) if company else None


def _extract_salary(item: dict) -> Optional[str]:
    """Extract salary info from Adzuna response."""
    salary_min = item.get("salary_min")
    salary_max = item.get("salary_max")
    if salary_min and salary_max:
        return f"{salary_min:,.0f} - {salary_max:,.0f} EUR"
    elif salary_min:
        return f"ab {salary_min:,.0f} EUR"
    elif salary_max:
        return f"bis {salary_max:,.0f} EUR"

    # Try salary_is_predicted flag
    predicted = item.get("salary_is_predicted", "")
    if predicted:
        return _extract_salary_from_text(item.get("description", ""))

    return None


def _extract_salary_from_text(description: str) -> Optional[str]:
    """Try to extract salary from description text as fallback."""
    patterns = [
        r"(\d[\d.]*\s*(?:EUR|€|Euro)\s*(?:bis|-)\s*\d[\d.]*\s*(?:EUR|€|Euro))",
        r"(\d[\d.]*\s*(?:EUR|€|Euro))",
    ]
    for pattern in patterns:
        match = re.search(pattern, description, re.IGNORECASE)
        if match:
            return cast(str, match.group(1))
    return None


def _extract_job_type(item: dict) -> Optional[str]:
    """Extract job type from Adzuna response categories."""
    # Adzuna doesn't have a dedicated job_type field,
    # but we can infer from contract_time or category
    contract_time = item.get("contract_time", "")
    if contract_time:
        mapping = {
            "full_time": "Vollzeit",
            "part_time": "Teilzeit",
            "contract": "Befristet",
            "permanent": "Unbefristet",
            "internship": "Praktikum",
        }
        return cast(Optional[str], mapping.get(contract_time, contract_time))

    # Check category label
    category = item.get("category", {})
    if isinstance(category, dict):
        label = category.get("label", "")
        if label:
            return cast(Optional[str], label)
    return None


def _build_description(item: dict) -> str:
    """Build a text description from Adzuna's fields."""
    parts: list[str] = []

    title = item.get("title", "")
    if title:
        parts.append(f"Titel: {title}")

    description = item.get("description", "")
    if description:
        # Clean up HTML entities
        clean_desc = html.unescape(description)
        # Remove extra whitespace
        clean_desc = " ".join(clean_desc.split())
        parts.append(clean_desc[:3000])

    # Add company info
    company = _extract_company(item)
    if company:
        parts.append(f"Unternehmen: {company}")

    return "\n\n".join(parts) if parts else "Keine Beschreibung verfügbar."
