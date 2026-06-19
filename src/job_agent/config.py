# -*- coding: utf-8 -*-
import os
import sys
import yaml
import json
import shutil
from job_agent.utils import Colors

# Default Prompt Templates used by the agent
DEFAULT_PROMPTS = {
    "scoring_prompt_IT": """Du bist ein erfahrener IT-Recruiter in Deutschland. Vergleiche das Kandidatenprofil mit der Stellenbeschreibung (Job Description).

Kandidatenprofil (JSON):
{candidate_profile}

Bewerte das Match auf einer Skala von 0 bis 10.

Ein Score von 10 bedeutet perfekte Übereinstimmung. Ein Score von 0 bedeutet, dass K.O.-Kriterien greifen oder die Rolle absolut unpassend ist.

Du MUSST die folgenden Regeln strikt anwenden:
1. Mindestgehalt: Wenn das in der Anzeige erwähnte Jahresgehalt unter {min_salary} € liegt, setze den Score auf 0 und ko_criterion_triggered auf true.
2. Sprachen:
    - Der Kandidat besitzt Deutschkenntnisse auf dem Niveau {candidate_german}. Wenn die Stelle Deutsch C1, C2 oder "verhandlungssicher" voraussetzt (auch ohne explizite "Muss"-Formulierung), setze den Score SOFORT auf 0 und ko_criterion_triggered auf true.
   - Der Kandidat besitzt Englischkenntnisse auf dem Niveau {candidate_english}. ACHTUNG — NUR "verhandlungssicher Englisch", "fließend Englisch", "fluent English", "excellent English", "English C1", "business fluent" lösen ein K.O. aus.
3. K.O.-Kriterien / Ausschlüsse:
   - U.S. Staatsbürgerschaft (U.S. citizenship), Sicherheitsfreigabe (Secret/Top Secret clearance) oder TESA-Status: Wenn eines davon erforderlich ist (z.B. {clearance_keywords}), setze den Score auf 0 und ko_criterion_triggered auf true.
   - Pflichtzertifikate: Wenn die Stelle Zertifizierungen wie Red Hat ({certifications}) zwingend voraussetzt und der Kandidat diese nicht hat, setze den Score auf 0.
   - Bildungsanbieter / Weiterbildungsangebote: Wenn es sich bei dem Angebot um eine reine Umschulung, Ausbildung oder Weiterbildung von einem Bildungsanbieter (z.B. {spam_keywords}) handelt, setze den Score auf 0 und ko_criterion_triggered auf true.
   - Reine Rechenzentrums-/körperliche Arbeit: Falls die Stelle rein körperliche Rechenzentrumsarbeit wie Verkabelung, Server-Einbau betrifft (z.B. {datacenter_keywords}), setze den Score auf 0 und ko_criterion_triggered auf true.
   - Full Stack Developer: Wenn der Titel "Full Stack Developer", "Fullstack Developer" oder ähnlich lautet, setze den Score auf 0.
   - Consultant oder Support Rollen: Wenn der Titel "Consultant" oder "Support" enthält, setze den Score SOFORT auf 0 und ko_criterion_triggered auf true.
4. Akademischer Grad: Wenn ein akademisches IT-Studium zwingend und ohne Ausweichklausel ("oder vergleichbare Berufserfahrung") gefordert wird, setze den Score auf 0.
5. Berufserfahrung (IT-Erfahrung seit {career_start_year}): Der Kandidat ist auf Junior-Ebene. Wenn die Stelle mehr als 3 Jahre relevante Berufserfahrung verlangt, bewerte niedrig oder setze auf 0.
6. Regionale Einschränkung:
   - Stellen vor Ort (On-site) in Frankfurt am Main, Hanau, Offenbach, Hessen (Umkreis bis 35 km) werden positiv bewertet.
   - Stellen vor Ort in anderen Regionen (z.B. Berlin, München, Hamburg) sind K.O. (Score 0).

{rejections_str}

Stellenbeschreibung:
{job_description}

Gib das Ergebnis ausschließlich als valides JSON-Objekt im folgenden Format zurück (ohne Markdown-Formatierung wie ```json):
{{
  "total_score": 8.5,
  "ko_criterion_triggered": false,
  "reasoning": "Detaillierte Begründung auf Deutsch, warum dieser Score vergeben wurde..."
}}""",
    "scoring_prompt": """Vergleiche das Kandidatenprofil mit der Stellenbeschreibung (Job Description).

Kandidatenprofil (JSON):
{candidate_profile}

Bewerte das Match auf einer Skala von 0 bis 10.

Ein Score von 10 bedeutet perfekte Übereinstimmung. Ein Score von 0 bedeutet, dass K.O.-Kriterien greifen oder die Rolle absolut unpassend ist.

Regeln:
1. Mindestgehalt: Wenn das erwähnte Jahresgehalt unter {min_salary} € liegt, setze den Score auf 0 und ko_criterion_triggered auf true.
2. Sprachen: Der Kandidat spricht Deutsch {candidate_german}, Englisch {candidate_english}. Passe die Bewertung an.
3. K.O.-Kriterien: Prüfe Sicherheitsfreigaben ({clearance_keywords}), Zertifikate ({certifications}), Bildungsanbieter ({spam_keywords}).
4. Berufserfahrung seit {career_start_year}. Bewerte entsprechend der Anforderungen.

{rejections_str}

Stellenbeschreibung:
{job_description}

Gib das Ergebnis als JSON zurück:
{{
  "total_score": 0.0,
  "ko_criterion_triggered": false,
  "reasoning": "Begründung"
}}""",
    "cover_letter_prompt": """Erstelle ein professionelles Anschreiben auf Deutsch basierend auf dem Kandidatenprofil und der Stellenbeschreibung.

Kandidatenprofil:
{candidate_profile}

Stellenbeschreibung:
{job_description}

Zusätzliche Vorgaben:
- Gehaltsvorstellung: {salary_exp} € brutto pro Jahr.
- Verfügbarkeit / Eintrittstermin: {availability}.
- Sprachniveau Deutsch: {candidate_german}.
- Pflichtkompetenzen: {mandatory_skills}.

Format (DIN 5008):
1. Betreffzeile (fett): "Bewerbung als [Position]" — mit konkreter Position aus der Stellenbeschreibung.
2. Anrede: "Sehr geehrte Damen und Herren," oder personalisiert falls Ansprechpartner bekannt.
3. Brieftext (body): Einleitung, Motivation, Kompetenzen, Gehaltsvorstellung, Verfügbarkeit, Schlusssatz.
4. Grußformel (closing): "Mit freundlichen Grüßen".

Antworte NUR mit folgendem JSON-Objekt (kein Markdown, kein ```json):
{{
  "subject": "Bewerbung als Cloud Engineer",
  "salutation": "Sehr geehrte Damen und Herren,",
  "body": "Der vollständige Haupttext des Anschreibens (ohne Betreff, ohne Anrede, ohne Grußformel).\n\nMehrere Absätze durch Leerzeile getrennt.",
  "closing": "Mit freundlichen Grüßen"
}}""",
    "form_filler_prompt": """Du bist ein Assistent, der ein Webformular für eine Bewerbung ausfüllt. Analysiere die Liste der interaktiven Elemente (Inputs, Buttons, Uploads) und entscheide für jedes Element, welche Aktion auszuführen ist.
Kandidatenprofil:
{candidate_profile}

Zusätzliche Angaben:
- Gehaltsvorstellung: {salary_expectation}
- Frühestmöglicher Eintrittstermin: {availability}
- Arbeitserlaubnis für Deutschland vorhanden: {work_permit}

Verfügbare Elemente auf der Seite:
{elements}

Gib die Liste der auszuführenden Aktionen als JSON-Array von Objekten zurück (ohne Markdown-Wrapper):
[
  {{
    "element_id": "input-1",
    "action": "fill",
    "value": "Max"
  }},
  {{
    "element_id": "upload-cv",
    "action": "upload_cv"
  }},
  {{
    "element_id": "upload-cover",
    "action": "upload_cover_letter"
  }},
  {{
    "element_id": "submit-btn",
    "action": "click"
  }}
]""",
    "classification_prompt": """Klassifiziere das folgende Dokument basierend auf den ersten 1000 Zeichen seines Inhalts in eine der folgenden Kategorien:
- Lebenslauf
- Anschreiben
- Zertifikat
- Diplom
- Sonstiges

Textauszug des Dokuments:
{doc_text}

Antworte ausschließlich mit dem Namen der Kategorie (z.B. Lebenslauf).""",
    "extract_recruiter_prompt": """Extrahiere den vollständigen Namen des Recruiters/Ansprechpartners aus der folgenden Stellenbeschreibung.

Der E-Mail-Kontakt für Bewerbungen ist: {email}

Stellenbeschreibung:
{job_text}

Gib NUR den Namen zurück (z.B. "Max Mustermann"). Wenn kein Name gefunden wird, gib eine leere Zeile zurück.""",
    "job_intake_prompt": """Du bist ein Job-Intake-Analyst. Analysiere eine Stellenanzeige VOLLSTÄNDIG und extrahiere alle Metadaten, prüfe Ausschlusskriterien und erkenne die Branche.

== SEITENTITEL ==
{page_title}

== SEITENINHALT (Anfang) ==
{page_text}

== URL ==
{url}

== KANDIDATENPROFIL ==
{candidate_profile}

== AUSSCHLUSSKRITERIEN (KO-Filter) ==
- Gesperrte Unternehmen: {excluded_companies}
- Verbotene Jobtitel (statisch): {forbidden_titles}
- Verbotene Keywords (Sicherheitsfreigaben): {clearance_keywords}
- Pflichtzertifikate: {mandatory_certifications}
- Spam-Bildungsanbieter: {spam_keywords}
- Datacenter-Keywords: {datacenter_keywords}
- Min. Gehalt: {min_salary} EUR
- Sprachniveau Deutsch: {candidate_german}, Englisch: {candidate_english}

== BEREITS BEWORBEN (zur Duplikaterkennung) ==
{previous_applications}

AUFGABEN:
1. Prüfe, ob es sich um eine gültige Stellenanzeige handelt (kein Dead-Link, keine Suchseite, keine 404-Seite).
2. Extrahiere Firmenname und Jobtitel aus Titel + Text. Bereinige den Firmennamen (entferne GmbH, AG, SE, KG, e.V. etc.).
3. Bestimme die Branche (IT, Handwerk, Allgemein) anhand des Textes UND des Kandidatenprofils.
4. Prüfe, ob der Jobtitel gegen die forbidden_titles-Regeln oder das Senioritätslevel des Kandidaten verstösst:
   - Kandidat mit IT-Junior-Level (0-3 Jahre): Blockiere Senior, Middle, Lead, Architect, Principal, Head of, Full Stack Developer, Consultant, Helpdesk.
   - Kandidat mit Handwerk-Expert-Level: Erlaube alle Handwerk-Titel.
   - Global blockieren: Projektmanager, Sales, Marketing Manager, HR.
5. Prüfe auf Duplikate mit bereits beworbenen Stellen.
6. Prüfe KO-Filter: Unternehmen auf Blacklist, Sicherheitsfreigaben, Spam-Bildungsanbieter.

Antworte NUR mit diesem JSON-Objekt (kein Markdown):
{{
  "is_valid_job": true,
  "invalid_reason": null,
  "company_name": "Bereinigter Firmenname (ohne GmbH, AG, etc.)",
  "job_title": "Berufsbezeichnung",
  "industry": "IT",
  "industry_reasoning": "Kurze Begründung für Branchenwahl",
  "forbidden_title_detected": false,
  "forbidden_title_reason": null,
  "is_duplicate": false,
  "duplicate_of": null,
  "ko_triggered": false,
  "ko_reason": null
}}""",

    "classify_document_prompt": """Klassifiziere das folgende Dokument anhand von Dateiname und Textinhalt.

Dateiname: {filename}
Erste 1500 Zeichen des Textes:
{doc_text}

Kategorien:
- "Lebenslauf": CV, Curriculum Vitae, Werdegang, mit persönlichen Daten und Berufserfahrung
- "Anschreiben": Bewerbungsschreiben, Motivationsschreiben, Cover Letter
- "Arbeitszeugnis": Arbeitsbescheinigung, Beurteilung vom Arbeitgeber
- "Zertifikat": Fortbildungsnachweis, Teilnahmebestätigung, Certificate
- "Diplom": Abschlusszeugnis, Universitätsdiplom, Bachelor/Master-Urkunde, Schulzeugnis, Transcript
- "Sonstiges": Dokumente, die in keine andere Kategorie passen

Antworte NUR mit einem JSON-Objekt (kein Markdown):
{{
  "classification": "Lebenslauf",
  "confidence": 0.95,
  "reasoning": "Kurze Begründung"
}}""",
}

# Recreate missing active config files from their .sample templates
def restore_active_configs_from_samples(workspace_dir, config_path, criteria_path, profile_path, prompts_path):
    print(f"\n{Colors.BLUE}--- Checking and Restoring Configuration Files ---{Colors.END}")
    
    pairs = [
        (config_path, config_path + ".sample", "config.yaml"),
        (criteria_path, criteria_path + ".sample", "job_criteria.yaml"),
        (profile_path, profile_path + ".sample", "candidate_profile.json"),
        (prompts_path, prompts_path + ".sample", "prompts.yaml")
    ]
    for active, sample, name in pairs:
        if not os.path.exists(active):
            if os.path.exists(sample):
                try:
                    shutil.copy2(sample, active)
                    print(f" {Colors.GREEN}- Restored missing active config '{name}' from template sample.{Colors.END}")
                except Exception as e:
                    print(f"   {Colors.RED}Error restoring '{name}' from sample: {e}{Colors.END}")
            else:
                # If sample itself is missing, we write a basic fallback directly
                print(f"   {Colors.YELLOW}Warning: Sample file '{sample}' not found. Re-generating fallback '{name}'.{Colors.END}")
                try:
                    if name == "config.yaml":
                        default_content = """user_profile:
  chrome_data_dir: "C:\\\\Users\\\\<Username>\\\\AppData\\\\Local\\\\Google\\\\Chrome\\\\User Data"
  chrome_profile: "Default"
  cv_path: "../documents/Lebenslauf.pdf"
  documents_dir: "../documents"
defaults:
  salary_expectation: "nach Vereinbarung"
  availability: "sofort"
  work_permit: "Germany"
  notice_period: "3 Monate"
criteria:
  min_score: 8.0
  min_salary_eur: 40000
  remote_allowed: true
  german_level: "B1"
  excluded_companies: []
gemini:
  model: "gemini-2.5-flash"
  api_keys:
    - "<YOUR_GEMINI_API_KEY_1>"
    - "<YOUR_GEMINI_API_KEY_2>"
    - "<YOUR_GEMINI_API_KEY_3>"
    - "<YOUR_GEMINI_API_KEY_4>"
smtp:
  host: "smtp.gmail.com"
  port: 587
  username: "<YOUR_EMAIL>@gmail.com"
  password: "<YOUR_SMTP_PASSWORD_OR_APP_PASSWORD>"
"""
                    elif name == "job_criteria.yaml":
                        default_content = """scoring:
  min_score_to_apply: 8.0
ko_filters:
  salary:
    min_annual_eur: 40000
  clearances:
    forbidden_keywords: []
  certifications:
    mandatory_if_specified: []
  education:
    require_it_degree_strictly: false
    block_degree_only_roles: false
  languages:
    min_required_english: "A2"
    min_required_german: "B1"
  spam_providers:
    blocked_keywords: []
    allow_internship: true
  companies_blacklist: []
  forbidden_titles: []
  user_rejected_reasons: []
cover_letter:
  mandatory_skills: []
  career_start_year: 2020
"""
                    elif name == "candidate_profile.json":
                        default_content = json.dumps({
                            "personal_info": {
                                "first_name": "<Vorname>",
                                "last_name": "<Nachname>",
                                "email": "candidate.email@example.com",
                                "phone": "01521 1234567",
                                "address": "Hauptstr. 1",
                                "city": "60311 Frankfurt am Main",
                                "country": "Deutschland"
                            },
                            "languages": {"Deutsch": "B2", "Englisch": "A2"},
                            "skills": ["Linux", "Python", "Bash", "Java", "Docker"],
                            "experience_years": 10.0,
                            "education": [],
                            "certifications": []
                        }, ensure_ascii=False, indent=2)
                    else: # prompts.yaml
                        default_content = yaml.safe_dump(DEFAULT_PROMPTS, allow_unicode=True)
                        
                    with open(active, "w", encoding="utf-8") as f:
                        f.write(default_content)
                    # Also write it to the sample file to keep it next time
                    with open(sample, "w", encoding="utf-8") as f:
                        f.write(default_content)
                    print(f" {Colors.GREEN}- Successfully re-generated default config and sample for '{name}'.{Colors.END}")
                except Exception as ex:
                    print(f"   {Colors.RED}Failed to write default for '{name}': {ex}{Colors.END}")

def load_config(config_path=None):
    if config_path is None:
        config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "config.yaml")
    if not os.path.exists(config_path):
        print(f"Error: Configuration file {config_path} not found.")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_criteria(criteria_path=None):
    if criteria_path is None:
        criteria_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "job_criteria.yaml")
    if not os.path.exists(criteria_path):
        print(f"Error: Criteria file {criteria_path} not found.")
        sys.exit(1)
    with open(criteria_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_prompts(prompts_path=None):
    if prompts_path is None:
        prompts_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "prompts.yaml")
    sample_path = prompts_path + ".sample"
    if not os.path.exists(prompts_path):
        if os.path.exists(sample_path):
            try:
                shutil.copy2(sample_path, prompts_path)
                print(f" {Colors.GREEN}- Restored prompts.yaml from prompts.yaml.sample.{Colors.END}")
            except Exception as e:
                print(f"Warning: Could not copy prompts.yaml.sample: {e}")
        if not os.path.exists(prompts_path):
            try:
                with open(prompts_path, "w", encoding="utf-8") as f:
                    yaml.safe_dump(DEFAULT_PROMPTS, f, allow_unicode=True)
            except Exception as e:
                print(f"Warning: Could not create default prompts.yaml: {e}")
            return DEFAULT_PROMPTS
    try:
        with open(prompts_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            merged = DEFAULT_PROMPTS.copy()
            if isinstance(data, dict):
                merged.update(data)
            return merged
    except Exception as e:
        print(f"Warning: Could not load prompts from {prompts_path}: {e}. Using defaults.")
        return DEFAULT_PROMPTS

PROMPTS = load_prompts()
