"""Jooble — free job board REST API adapter.

Public REST API for job search across Germany and other countries.
Free tier: API key required (register at https://jooble.org/api).

API docs: https://help.jooble.org/en/support/solutions/articles/60001448238-rest-api-documentation
"""

import os
import requests
from typing import Optional
from job_agent.job_sources import JobPosting
from job_agent.utils import Colors

BASE_URL = "https://jooble.org/api"
TIMEOUT = 15

# Credentials from config.yaml -> jooble section (no env vars)
def _get_jooble_key() -> str:
    try:
        import yaml
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "config", "config.yaml",
        )
        if os.path.exists(config_path):
            with open(config_path, encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            jooble = config.get("jooble", {}) or {}
            return jooble.get("api_key", "") or ""
    except Exception:
        pass
    return ""


API_KEY = _get_jooble_key()


def search_jooble(
    query: str,
    location: str,
    radius: int = 25,
    max_results: int = 50,
) -> list[JobPosting]:
    """Search jobs via Jooble public REST API.

    Args:
        query: Search keywords (e.g. "Lehrer")
        location: Location (e.g. "Hanau, Germany")
        radius: Search radius in km (valid: 0, 4, 8, 16, 26, 40, 80)
        max_results: Maximum results to return (API default ~20 per page)

    Returns:
        List of JobPosting objects.
    """
    if not API_KEY:
        print(f"{Colors.YELLOW}[Jooble API] No API key set. "
              f"Add jooble.api_key to config.yaml. Skipping.{Colors.END}")
        return []

    # Clamp radius to Jooble's allowed values (0, 4, 8, 16, 26, 40, 80)
    allowed = [0, 4, 8, 16, 26, 40, 80]
    jooble_radius = min(allowed, key=lambda r: abs(r - radius))

    url = f"{BASE_URL}/{API_KEY}"

    payload = {
        "keywords": query,
        "location": f"{location}, Germany",
        "radius": jooble_radius,
    }

    if max_results:
        payload["ResultOnPage"] = min(max_results, 50)

    all_jobs: list[JobPosting] = []

    try:
        resp = requests.post(url, json=payload, timeout=TIMEOUT)
    except requests.Timeout:
        print(f"{Colors.YELLOW}[Jooble API] Timeout. Skipping.{Colors.END}")
        return []
    except requests.ConnectionError as e:
        print(f"{Colors.YELLOW}[Jooble API] Connection error: {e}. Skipping.{Colors.END}")
        return []
    except Exception as e:
        print(f"{Colors.YELLOW}[Jooble API] Request failed: {e}. Skipping.{Colors.END}")
        return []

    if resp.status_code != 200:
        # 403 often means invalid API key
        if resp.status_code == 403:
            print(f"{Colors.YELLOW}[Jooble API] HTTP 403 — Invalid API key. Check jooble section in config.yaml.{Colors.END}")
        else:
            print(f"{Colors.YELLOW}[Jooble API] HTTP {resp.status_code}: {resp.text[:200]}. Skipping.{Colors.END}")
        return []

    try:
        data = resp.json()
    except Exception as e:
        print(f"{Colors.YELLOW}[Jooble API] JSON parse error: {e}{Colors.END}")
        return []

    jobs_data = data.get("jobs", [])
    if not jobs_data:
        print(f"{Colors.GREY}[Jooble API] No jobs found.{Colors.END}")
        return []

    for item in jobs_data[:max_results]:
        if not isinstance(item, dict):
            continue

        title = item.get("title", "") or "Unbekannt"
        company = item.get("company", "") or "Unbekannt"
        location_str = item.get("location", "") or location

        # Jooble provides a direct apply URL
        url = item.get("link", "") or item.get("url", "") or ""

        # Build description from available fields
        description = _build_description(item)

        # Salary is often a string like "50,000€ - 70,000€"
        salary = item.get("salary", None)
        # If salary is a full object, try to get a string representation
        if isinstance(salary, dict):
            salary = salary.get("text") or str(salary.get("min", "")) + " - " + str(salary.get("max", ""))

        job_type = None
        full_text = (title + " " + (item.get("snippet", "") or "")).lower()
        if "teilzeit" in full_text:
            job_type = "Teilzeit"
        elif "vollzeit" in full_text:
            job_type = "Vollzeit"

        all_jobs.append(JobPosting(
            title=title,
            company=company,
            location=location_str,
            url=url,
            description=description,
            source="jooble",
            salary=salary,
            job_type=job_type,
        ))

    print(f"{Colors.GREEN}[Jooble API] {len(all_jobs)} jobs loaded{Colors.END}")
    return all_jobs


def _build_description(item: dict) -> str:
    """Build a text description from Jooble's fields."""
    parts: list[str] = []

    # Jooble returns 'snippet' as a short description
    snippet = item.get("snippet", "")
    if snippet:
        parts.append(snippet)

    # Full description might be available
    desc = item.get("description", "")
    if desc and desc != snippet:
        parts.append(desc[:2000])

    return "\n\n".join(parts) if parts else "Keine Beschreibung verfügbar."
