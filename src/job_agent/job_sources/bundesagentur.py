"""Bundesagentur für Arbeit — official German job board API adapter.

Uses the inofficial but well-documented REST API at rest.arbeitsagentur.de.
No authentication required. Rate limits are generous but undocumented.

API docs: https://github.com/bundesAPI/jobsuche-api
"""

import requests
from typing import Optional
from job_agent.job_sources import JobPosting
from job_agent.utils import Colors

BASE_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs"
API_KEY_HEADER = {"X-API-Key": "jobboerse-jobsuche"}
TIMEOUT = 15


def search_bundesagentur(
    query: str,
    location: str,
    radius: int = 25,
    max_pages: int = 2,
) -> list[JobPosting]:
    """Search jobs via Bundesagentur für Arbeit API.

    Args:
        query: Free-text search (e.g. "Fachinformatiker")
        location: City name or PLZ (e.g. "Frankfurt am Main")
        radius: Search radius in km
        max_pages: Number of result pages to fetch (each page ~25 results)

    Returns:
        List of JobPosting objects.
    """
    all_jobs: list[JobPosting] = []
    seen_refs: set[str] = set()

    for page in range(1, max_pages + 1):
        params = {
            "was": query,
            "wo": location,
            "umkreis": radius,
            "page": page,
            "size": 25,
            "angebotsart": 1,  # 1 = jobs (Arbeit)
        }

        try:
            resp = requests.get(
                BASE_URL,
                headers=API_KEY_HEADER,
                params=params,
                timeout=TIMEOUT,
            )
        except requests.Timeout:
            print(f"{Colors.YELLOW}[BA API] Timeout on page {page}. Stopping.{Colors.END}")
            break
        except requests.ConnectionError as e:
            print(f"{Colors.YELLOW}[BA API] Connection error: {e}. Stopping.{Colors.END}")
            break
        except Exception as e:
            print(f"{Colors.YELLOW}[BA API] Request failed: {e}. Stopping.{Colors.END}")
            break

        if resp.status_code != 200:
            print(f"{Colors.YELLOW}[BA API] HTTP {resp.status_code}: {resp.text[:200]}. Stopping.{Colors.END}")
            break

        try:
            data = resp.json()
        except Exception as e:
            print(f"{Colors.YELLOW}[BA API] JSON parse error on page {page}: {e}{Colors.END}")
            break

        # Extract jobs from response — BA API v6 uses "ergebnisliste"
        # (older v5 used "stellenangebote")
        stellenangebote = data.get("ergebnisliste", data.get("stellenangebote", []))
        if not stellenangebote:
            print(f"{Colors.GREY}[BA API] No more results on page {page}.{Colors.END}")
            break

        for item in stellenangebote:
            ref = item.get("referenznummer", "")  # v6: referenznummer (not refnr)
            if ref in seen_refs:
                continue
            seen_refs.add(ref)

            # Title: v6 uses "stellenangebotsTitel" (not "titel")
            title = item.get("stellenangebotsTitel", "") or item.get("titel", "")
            # Also try hauptberuf if title is empty
            if not title:
                hb = item.get("hauptberuf", {})
                title = hb.get("label", "") if isinstance(hb, dict) else ""
            title = title or "Unbekannt"

            company = _extract_company(item) or "Unbekannt"
            location_str = _extract_location(item) or location
            url = item.get("externeURL", "") or (f"https://www.arbeitsagentur.de/jobsuche/{ref}" if ref else "")
            description = _extract_description(item)
            salary = _extract_salary(item)
            job_type = _extract_job_type(item)

            all_jobs.append(JobPosting(
                title=title,
                company=company,
                location=location_str,
                url=url,
                description=description,
                source="bundesagentur",
                salary=salary,
                job_type=job_type,
            ))

        # Check if there are more pages
        max_ergebnisse = data.get("maxErgebnisse", 0)
        if page * 25 >= max_ergebnisse:
            break

    return all_jobs


def _extract_company(item: dict) -> Optional[str]:
    """Extract company name from a BA job item.
    v6 API uses "firma" field directly as a string.
    """
    firma: str = item.get("firma", "") or ""
    if firma:
        return firma.strip()
    # Fallback: older field names
    arbeitgeber = item.get("arbeitgeber", "") or ""
    if arbeitgeber:
        return arbeitgeber.strip()
    return None


def _extract_location(item: dict) -> Optional[str]:
    """Extract location string from a BA job item.
    v6 API uses "stellenlokationen" (list of dicts with plz, ort).
    """
    lokationen = item.get("stellenlokationen", [])
    if isinstance(lokationen, list) and lokationen:
        parts: list[str] = []
        for loc in lokationen[:2]:  # max 2 locations
            if isinstance(loc, dict):
                plz = loc.get("plz", "")
                ort = loc.get("ort", "")
                if plz and ort:
                    parts.append(f"{plz} {ort}")
                elif ort:
                    parts.append(ort)
        if parts:
            return ", ".join(parts)
    # Fallback: older "ort" field
    ort = item.get("ort", {})
    if isinstance(ort, dict):
        plz = ort.get("plz", "")
        stadt = ort.get("ort", "")
        if plz and stadt:
            return f"{plz} {stadt}"
        return stadt or plz or None
    return str(ort) if ort else None


def _extract_description(item: dict) -> str:
    """Build a text description from all available fields.
    v6 API uses "stellenangebotsTitel" and "hauptberuf" instead of "titel"/"beruf".
    """
    parts: list[str] = []
    titel = item.get("stellenangebotsTitel", "") or item.get("titel", "")
    if titel:
        parts.append(f"Titel: {titel}")
    hb = item.get("hauptberuf", {})
    if isinstance(hb, dict):
        beruf_label = hb.get("label", "")
        if beruf_label and beruf_label != titel:
            parts.append(f"Beruf: {beruf_label}")
    for key in ("kurzbeschreibung", "beschreibung", "aufgaben", "qualifikationen"):
        val = item.get(key, "")
        if val:
            parts.append(f"{key.capitalize()}: {val}")
    return "\n".join(parts) if parts else "Keine Beschreibung verfügbar."


def _extract_salary(item: dict) -> Optional[str]:
    """Extract salary info if available.
    v6 API uses "verguetungsangabe" dict.
    """
    vg = item.get("verguetungsangabe", {})
    if isinstance(vg, dict):
        von = vg.get("von", "")
        bis = vg.get("bis", "")
        if von and bis:
            return f"{von} - {bis} EUR"
        elif von:
            return f"ab {von} EUR"
    # Fallback: older "verguetung" field
    verguetung = item.get("verguetung", {})
    if isinstance(verguetung, dict):
        von = verguetung.get("von", "")
        bis = verguetung.get("bis", "")
        if von and bis:
            return f"{von} - {bis} EUR"
        elif von:
            return f"ab {von} EUR"
    return None


def _extract_job_type(item: dict) -> Optional[str]:
    """Extract job type (Vollzeit/Teilzeit).
    v6 API uses boolean flags like "arbeitszeitVollzeit", "arbeitszeitTeilzeit*".
    """
    types: list[str] = []
    if item.get("arbeitszeitVollzeit"):
        types.append("Vollzeit")
    teilzeit_keys = ["arbeitszeitTeilzeitVormittag", "arbeitszeitTeilzeitNachmittag",
                     "arbeitszeitTeilzeitAbend", "arbeitszeitTeilzeitFlexibel"]
    if any(item.get(k) for k in teilzeit_keys):
        types.append("Teilzeit")
    if item.get("arbeitszeitSchichtNachtWochenende"):
        types.append("Schicht/Nacht/Wochenende")
    if types:
        return ", ".join(types)
    # Fallback: older "arbeitszeit" field
    az = item.get("arbeitszeit", "")
    if isinstance(az, str) and az:
        return az
    if isinstance(az, list) and az:
        return ", ".join(az)
    return None
