"""Job sources package — official API adapters instead of web scraping.

Provides a unified interface for searching job vacancies from official sources:
- Bundesagentur für Arbeit (official German job board, no auth needed)
- Arbeitnow (aggregates from ATS systems, no auth needed)
- Jooble (aggregator API, requires JOOBLE_API_KEY env var)
- Adzuna (global job search API, requires ADZUNA_APP_ID + ADZUNA_APP_KEY env vars)

Usage:
    from job_agent.job_sources import search_all_sources

    jobs = search_all_sources("Fachinformatiker", "Frankfurt", radius=25)
    for job in jobs:
        print(job.title, job.company, job.url)
"""

from typing import Optional
from dataclasses import dataclass
from job_agent.utils import Colors


@dataclass
class JobPosting:
    """Normalized job posting from any source."""
    title: str
    company: str
    location: str
    url: str
    description: str
    source: str  # "bundesagentur" | "arbeitnow" | etc.
    salary: Optional[str] = None
    job_type: Optional[str] = None  # "Vollzeit", "Teilzeit", etc.


def search_all_sources(
    query: str,
    location: str,
    radius: int = 25,
    sources: Optional[list[str]] = None,
    max_results: int = 25,
) -> list[JobPosting]:
    """Search all configured job sources and return merged, deduplicated results.

    Args:
        query: Job search query (e.g. "Fachinformatiker")
        location: City or PLZ (e.g. "Frankfurt am Main" or "60311")
        radius: Search radius in km
        sources: List of source names to search.
                 Default: ["bundesagentur", "arbeitnow"]
        max_results: Maximum total results across all sources

    Returns:
        List of JobPosting objects, sorted by source priority, limited to max_results.
    """
    if sources is None:
        sources = ["bundesagentur", "arbeitnow", "jooble", "adzuna"]

    # Import all source functions once
    from job_agent.job_sources.bundesagentur import search_bundesagentur
    from job_agent.job_sources.arbeitnow import search_arbeitnow
    from job_agent.job_sources.jooble import search_jooble
    from job_agent.job_sources.adzuna import search_adzuna

    source_map = {
        "bundesagentur": lambda: search_bundesagentur(query, location, radius),
        "arbeitnow": lambda: search_arbeitnow(query, location),
        "jooble": lambda: search_jooble(query, location, radius, max_results),
        "adzuna": lambda: search_adzuna(query, location, radius, max_results),
    }

    all_jobs: list[JobPosting] = []
    seen_urls: set[str] = set()

    for source_name in sources:
        try:
            search_fn = source_map.get(source_name)
            if search_fn:
                jobs = search_fn()
            else:
                print(f"{Colors.YELLOW}[JobSources] Unknown source: {source_name}. Skipping.{Colors.END}")
                continue

            for job in jobs:
                if job.url not in seen_urls:
                    seen_urls.add(job.url)
                    all_jobs.append(job)

            print(f"{Colors.GREEN}[JobSources] {source_name}: {len(jobs)} jobs found{Colors.END}")

        except Exception as e:
            print(f"{Colors.YELLOW}[JobSources] Error searching {source_name}: {e}{Colors.END}")

    print(f"{Colors.CYAN}[JobSources] Total: {len(all_jobs)} unique jobs from {len(sources)} sources{Colors.END}")

    return all_jobs[:max_results]
