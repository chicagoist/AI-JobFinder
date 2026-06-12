# -*- coding: utf-8 -*-
import os
import sys
import yaml
import json
import shutil
from job_agent.utils import Colors

# Default Prompt Templates used by the agent
DEFAULT_PROMPTS = {
    "scoring_prompt": """Du bist ein erfahrener IT-Recruiter in Deutschland. Vergleiche das Kandidatenprofil mit der Stellenbeschreibung (Job Description).
Bewerte das Match auf einer Skala von 0 bis 10.

Ein Score von 10 bedeutet perfekte Übereinstimmung. Ein Score von 0 bedeutet, dass K.O.-Kriterien greifen oder die Rolle absolut unpassend ist (z.B. Full Stack Entwickler).

Du MUSST die folgenden Regeln strikt anwenden:
1. Mindestgehalt: Wenn das in der Anzeige erwähnte Jahresgehalt unter {min_salary} € liegt, setze den Score auf 0 und ko_criterion_triggered auf true.
2. Sprachen:
    - Der Kandidat besitzt Deutschkenntnisse auf dem Niveau {candidate_german} (B2). Wenn die Stelle Deutsch C1, C2 oder "verhandlungssicher" voraussetzt (auch ohne explizite "Muss"-Formulierung), setze den Score SOFORT auf 0 und ko_criterion_triggered auf true.
   - Der Kandidat besitzt Englischkenntnisse auf dem Niveau {candidate_english} (A2). ACHTUNG — NUR "verhandlungssicher Englisch", "fließend Englisch", "fluent English", "excellent English", "English C1", "business fluent" lösen ein K.O. aus. "Gute Englischkenntnisse" / "good English" ist KEIN K.O. — nur Abzug in der Teilbewertung.
3. K.O.-Kriterien / Ausschlüsse:
   - U.S. Staatsbürgerschaft (U.S. citizenship), Sicherheitsfreigabe (Secret/Top Secret clearance) oder TESA-Status: Wenn eines davon erforderlich ist (z.B. {clearance_keywords}), setze den Score auf 0 und ko_criterion_triggered auf true.
   - Pflichtzertifikate: Wenn die Stelle Zertifizierungen wie Red Hat ({certifications}) zwingend voraussetzt und der Kandidat diese nicht hat, setze den Score auf 0.
   - Bildungsanbieter / Weiterbildungsangebote: Wenn es sich bei dem Angebot um eine reine Umschulung, Ausbildung oder Weiterbildung von einem Bildungsanbieter (z.B. {spam_keywords}) handelt, die eine Schulung/Werbung statt einer regulären Arbeitsstelle ist, setze den Score auf 0 und ko_criterion_triggered auf true.
    - Full Stack Rollen: Wenn der Titel "Full Stack Developer", "Fullstack Developer" oder ähnlich lautet, setze den Score auf 0 (Kandidat sucht Systemadministration oder reines Backend).
   - Consultant oder Support Rollen: Wenn der Titel "Consultant" oder "Support" enthält (z.B. IT Consultant, Support Engineer), setze den Score SOFORT auf 0 und ko_criterion_triggered auf true.
4. Akademischer Grad (Computer Science / Software Engineering Degree):
   - Wenn ein akademisches IT-Studium zwingend und ohne Ausweichklausel ("oder vergleichbare Berufserfahrung") gefordert wird, setze den Score auf 0.
5. Berufserfahrung (IT-Erfahrung seit {career_start_year}):
   - Der Kandidat ist auf Junior-Ebene (Einstiegslevel). Wenn die Stelle mehr als 3 Jahre relevante Berufserfahrung verlangt, bewerte den Score niedrig oder setze ihn auf 0.
6. Regionale Einschränkung (Format der Arbeit):
   - Stellen vor Ort (On-site) in Frankfurt am Main, Hanau, Offenbach, Hessen (Umkreis bis 35 km) werden positiv bewertet.
   - Stellen vor Ort (On-site) in anderen Regionen (z.B. Berlin, München, Hamburg) sind K.O. (Score 0).

{rejections_str}

Stellenbeschreibung:
{job_description}

Gib das Ergebnis ausschließlich als valides JSON-Objekt im folgenden Format zurück (ohne Markdown-Formatierung wie ```json):
{{
  "total_score": 8.5,
  "ko_criterion_triggered": false,
  "reasoning": "Detaillierte Begründung auf Deutsch, warum dieser Score vergeben wurde..."
}}""",
    "cover_letter_prompt": """Erstelle ein professionelles Anschreiben auf Deutsch für eine Bewerbung als Systemadministrator / DevOps / Cloud Engineer (Junior-Level) basierend auf dem Kandidatenprofil und der Stellenbeschreibung.
Das Anschreiben MUSS den Standard DIN 5008 (Layout für Geschäftsbriefe) einhalten.

Kandidatenprofil:
{candidate_profile}

Stellenbeschreibung:
{job_description}

Zusätzliche Vorgaben für das Anschreiben:
- Gehaltsvorstellung: {salary_exp} € brutto pro Jahr (nicht verhandelbar).
- Verfügbarkeit / Eintrittstermin: {availability}.
- Berufserfahrung in der IT: Seit {career_start_year} (bitte organisch einbinden).
- Sprachniveau Deutsch: Der Kandidat spricht Deutsch auf dem Niveau {candidate_german} (bitte das Anschreiben sprachlich auf diesem Niveau halten, fehlerfrei, aber nicht übertrieben akademisch geschwollen).
- Pflichtkompetenzen: Binde die folgenden Pflichtkompetenzen organisch in den Text ein (sie müssen im Anschreiben erwähnt werden): {mandatory_skills}.
- Übersetzungs-Regel (Übersetzung von Fachbegriffen in geschäftliche HR-Mehrwerte):
  Übersetze technische Begriffe oder rohe Skills aus dem Lebenslauf in konkrete geschäftliche Vorteile für den Personaler. Zum Beispiel:
  * Statt nur "Docker, K8s" -> "modernisierte die Systemarchitektur für maximale Ausfallsicherheit und beschleunigte Deployment-Zyklen"
  * Statt "Python Scripting" -> "automatisierte zeitintensive Routineaufgaben, was die Fehlerquote und Betriebskosten signifikant senkte"
  * Statt "Azure Cloud" -> "optimierte Cloud-Ressourcen für kosteneffizienten Betrieb und hohe Verfügbarkeit"

Format des Geschäftsbriefs (DIN 5008):
1. Absender (Kandidat: Name, E-Mail, Telefon, Anschrift).
2. Empfänger (Unternehmen aus der Stellenbeschreibung, falls ermittelbar, sonst allgemein).
3. Datum (rechtsbündig).
4. Betreffzeile: Fett gedruckt (z.B. **Bewerbung als Junior Systemadministrator** - Referenz falls vorhanden).
5. Anrede (z.B. 'Sehr geehrte Damen und Herren' oder Name des Ansprechpartners falls bekannt).
6. Brieftext (Einleitung, Bezug zur Stelle, Motivation, Kompetenzen & Mehrwert mit Übersetzungs-Regel, Gehalt & Eintritt, Schlusssatz).
7. Grußformel (Mit freundlichen Grüßen).
8. Unterschrift (gedruckter Name des Kandidaten).

Gib NUR den reinen Text des Anschreibens aus. Keine Erklärungen, kein Markdown-Wrapper.""",
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

Gib NUR den Namen zurück (z.B. "Max Mustermann"). Wenn kein Name gefunden wird, gib eine leere Zeile zurück."""
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
        config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")
    if not os.path.exists(config_path):
        print(f"Error: Configuration file {config_path} not found.")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_criteria(criteria_path=None):
    if criteria_path is None:
        criteria_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "job_criteria.yaml")
    if not os.path.exists(criteria_path):
        print(f"Error: Criteria file {criteria_path} not found.")
        sys.exit(1)
    with open(criteria_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_prompts(prompts_path=None):
    if prompts_path is None:
        prompts_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts.yaml")
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
