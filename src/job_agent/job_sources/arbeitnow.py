"""Arbeitnow — free job board API adapter.

Aggregates jobs from ATS systems (Greenhouse, SmartRecruiters, etc.).
Free tier: no API key required, rate limited but undocumented.

API docs: https://www.arbeitnow.com/blog/job-board-api
"""

import re
import requests
from typing import Optional
from job_agent.job_sources import JobPosting
from job_agent.utils import Colors

BASE_URL = "https://www.arbeitnow.com/api/job-board-api"
TIMEOUT = 15


def search_arbeitnow(
    query: str,
    location: str,
    max_results: int = 50,
) -> list[JobPosting]:
    """Search jobs via Arbeitnow free API.

    Args:
        query: Search keywords (e.g. "Fachinformatiker")
        location: Location filter (e.g. "Frankfurt")
        max_results: Maximum results to return (API returns up to ~100)

    Returns:
        List of JobPosting objects.
    """
    all_jobs: list[JobPosting] = []

    params: dict = {
        "search": query,
        "location": location,
    }

    try:
        resp = requests.get(
            BASE_URL,
            params=params,
            timeout=TIMEOUT,
        )
    except requests.Timeout:
        print(f"{Colors.YELLOW}[Arbeitnow API] Timeout. Skipping.{Colors.END}")
        return []
    except requests.ConnectionError as e:
        print(f"{Colors.YELLOW}[Arbeitnow API] Connection error: {e}. Skipping.{Colors.END}")
        return []
    except Exception as e:
        print(f"{Colors.YELLOW}[Arbeitnow API] Request failed: {e}. Skipping.{Colors.END}")
        return []

    if resp.status_code != 200:
        print(f"{Colors.YELLOW}[Arbeitnow API] HTTP {resp.status_code}: {resp.text[:200]}. Skipping.{Colors.END}")
        return []

    try:
        data = resp.json()
    except Exception as e:
        print(f"{Colors.YELLOW}[Arbeitnow API] JSON parse error: {e}{Colors.END}")
        return []

    jobs_data = data.get("data", [])
    if not jobs_data:
        print(f"{Colors.GREY}[Arbeitnow API] No jobs found.{Colors.END}")
        return []

    for item in jobs_data[:max_results]:
        if not isinstance(item, dict):
            continue

        title = item.get("title", "") or "Unbekannt"
        company = item.get("company_name", "") or "Unbekannt"
        location_str = item.get("location", "") or location
        url = item.get("url", "") or ""
        description = _build_description(item)
        salary = item.get("salary", None)
        job_type = item.get("job_types", None)
        if isinstance(job_type, list):
            job_type = ", ".join(job_type)

        all_jobs.append(JobPosting(
            title=title,
            company=company,
            location=location_str,
            url=url,
            description=description,
            source="arbeitnow",
            salary=salary,
            job_type=job_type,
        ))

    print(f"{Colors.GREEN}[Arbeitnow API] {len(all_jobs)} jobs loaded{Colors.END}")
    return all_jobs


def _build_description(item: dict) -> str:
    """Build a text description from Arbeitnow's fields."""
    parts: list[str] = []

    for key in ("description", "tags", "remote"):
        val = item.get(key, "")
        if val:
            if key == "tags" and isinstance(val, list):
                parts.append(f"Tags: {', '.join(val)}")
            elif key == "remote":
                parts.append(f"Remote: {'Ja' if val else 'Nein'}")
            else:
                # Strip HTML tags from description
                clean = re.sub(r"<[^>]+>", "", str(val))
                parts.append(clean[:2000])

    return "\n".join(parts) if parts else "Keine Beschreibung verfügbar."
