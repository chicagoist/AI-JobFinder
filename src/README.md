<!-- PROJECT LOGO / TITLE -->
<div align="center">
  <h1>🤖 Gemini JobAgent</h1>
  <p><strong>Automatisierte Bewerbungen auf dem deutschen Arbeitsmarkt — KI-gestützt, mehrsprachig, erweiterbar.</strong></p>
  <br>
</div>

---

## 🔑 API-Schlüssel — Übersicht

| Dienst | Bezugsquelle | Verwendung |
|--------|-------------|------------|
| **Gemini** (primär) | [🔗 aistudio.google.com/apikey](https://aistudio.google.com/apikey) | Job-Scoring, Anschreiben, CV-Parsing, Recruiter-Extraktion |
| **OpenRouter** (Fallback) | [🔗 openrouter.ai/keys](https://openrouter.ai/keys) | Automatischer Fallback wenn alle Gemini-Keys erschöpft sind |

> **EN:** Gemini is the primary LLM for scoring, cover letters and CV parsing.  
> OpenRouter serves as free fallback when all Gemini keys are exhausted.  
> Both are configured in `src/config/config.yaml`.

---

## 📢 Einladung an die Community

**Dieses Projekt lebt von der Gemeinschaft!**  
Egal, ob du ein erfahrener Python-Entwickler, ein KI-Enthusiast oder jemand bist, der einfach nur den Bewerbungsprozess automatisieren möchte — **du bist herzlich eingeladen, dieses Repository zu forken, zu verbessern oder zu erweitern**.

In meiner Roadmap stehen bereits:
- ➕ **Neue Job-Plattformen** (StepStone, Monster, Glassdoor, XING)
- ➕ **Neue LLM-Provider** (Claude, lokal laufende Modelle via Ollama)
- ➕ **Headless-Betrieb für CI/CD-Integration**
- ➕ **Docker-Containerisierung**
- ➕ **Web-UI / Dashboard**

→ **Forke das Repository**, erstelle einen Pull Request oder reiche ein Issue ein.  
→ **Jeder Beitrag zählt**, sei es ein neues Modul, ein Bugfix oder eine bessere Dokumentation.

---

## 📋 Inhaltsverzeichnis

- [Über das Projekt](#-über-das-projekt)
- [Für wen ist dieses Tool?](#-für-wen-ist-dieses-tool)
- [Wie funktioniert es?](#-wie-funktioniert-es)
- [Architektur-Übersicht](#-architektur-übersicht)
- [Modulübersicht (UML-Tabelle)](#-modulübersicht-uml-tabelle)
- [Abhängigkeiten](#-abhängigkeiten)
- [Konfigurationsdateien](#-konfigurationsdateien)
- [CLI-Argumente](#-cli-argumente)
- [Argument-Kompatibilitätsmatrix](#-argument-kompatibilitätsmatrix)
- [Erste Schritte](#-erste-schritte)
- [Anwendungsbeispiele](#-anwendungsbeispiele)
- [Fehlerbehebung & Bekannte Probleme](#-fehlerbehebung--bekannte-probleme)
- [Lizenz](#-lizenz)

---

## 📖 Über das Projekt

**Gemini JobAgent** ist ein Python-basiertes CLI-Tool, das den Bewerbungsprozess auf dem **deutschen Arbeitsmarkt** automatisiert. Es kombiniert:

- **Playwright** (Browser-Automation) zum Scrapen von Stellenanzeigen und Ausfüllen von Webformularen
- **Google Gemini API** (mit automatischer Key-Rotation und Modell-Fallback) zur:
  - Bewertung von Stellenanzeigen anhand eines Kandidatenprofils (0–10 Score)
  - Generierung von DIN-5008-konformen Anschreiben (PDF) auf Deutsch
  - intelligenten Ausfüllen von Bewerbungsformularen
- **SMTP-Versand** für Direktbewerbungen per E-Mail
- **SQLite-Datenbank** zur Nachverfolgung aller Bewerbungen

Das Tool unterstützt derzeit **Indeed** und **LinkedIn** als Quellen für Stellenanzeigen und kann sowohl im manuellen Modus (Human-in-the-Loop) als auch vollautomatisch arbeiten.

---

## 🎯 Für wen ist dieses Tool?

| Zielgruppe | Nutzen |
|---|---|
| **Arbeitssuchende in Deutschland** | Automatisierte Bewertung und Bewerbung auf massenhaft passende Stellen |
| **Berufseinsteiger / Quereinsteiger** | KI generiert professionelle Anschreiben mit individueller Anpassung |
| **Entwickler & KI-Enthusiasten** | Erweiterbare Codebasis, eigene LLM-Provider einbindbar |
| **Recruiter (als Experiment)** | Analyse der eigenen Stellenausschreibungen aus Kandidatensicht |

---

## ⚙️ Wie funktioniert es?

```
   ┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
   │ Konfiguration│────▶│  Browser starten  │────▶│ Stellensuche auf │
   │  (YAML/JSON) │     │  (Chrome/CDP)    │     │ Indeed/LinkedIn  │
   └─────────────┘     └──────────────────┘     └────────┬────────┘
                                                         │
                                                         ▼
   ┌──────────────────────────────────────────────────────────────┐
   │                     BEWERTUNGSPIPELINE                        │
   │                                                              │
   │  ┌─────────────┐   ┌───────────────┐   ┌──────────────────┐  │
   │  │ Lokaler K.O. │──▶│ KI-Scoring     │──▶│ K.O.-Prüfung     │  │
   │  │ Regex-Filter │   │ (Gemini/OR)   │   │ (Score ≥ 5.0?)   │  │
   │  └─────────────┘   └───────┬───────┘   └────────┬─────────┘  │
   │                            │                      │           │
   │                            ▼                      ▼           │
   │                     ┌──────────────┐    ┌──────────────────┐  │
   │                     │ Anschreiben  │    │ Bei K.O.:        │  │
   │                     │ generieren   │    │ Überspringen +   │  │
   │                     │ (KI, DIN 5008)│    │ Loggen           │  │
   │                     └──────┬───────┘    └──────────────────┘  │
   └────────────────────────────┼──────────────────────────────────┘
                                │
                                ▼
   ┌──────────────────────────────────────────────────────────────┐
   │                     BEWERBUNGSARTEN                           │
   │                                                              │
   │  ┌──────────────────┐  ┌──────────────┐  ┌────────────────┐  │
   │  │ Webformular      │  │ LinkedIn      │  │ Direkt-E-Mail   │  │
   │  │ ausfüllen (KI)   │  │ Easy Apply    │  │ an HR (SMTP)   │  │
   │  └────────┬─────────┘  └──────┬───────┘  └───────┬────────┘  │
   │           │                   │                   │           │
   │           ▼                   ▼                   ▼           │
   │  ┌──────────────────────────────────────────────────────┐     │
   │  │        Logging in SQLite + PDF speichern             │     │
   │  └──────────────────────────────────────────────────────┘     │
   └──────────────────────────────────────────────────────────────┘
                                │
                                ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  E-Mail-Versand (optional):                                  │
   │  - Packt Bewerbungsdaten in ZIP (Job-Info + Log + PDF)      │
   │  - Sendet an Kandidaten-E-Mail als Backup                   │
   └──────────────────────────────────────────────────────────────┘
```

---

## 🏗️ Architektur-Übersicht

```
AI-JobFinder/
├── agent.py                        # Haupt-Einstiegspunkt (~2600 Zeilen)
│   ├── CLI-Argument-Parser
│   ├── Tkinter-GUI (config editor)
│   ├── Browser-Setup (Playwright)
│   ├── Job-Suche & -Scoring
│   ├── Anschreiben-Generierung & PDF
│   ├── Formular-Ausfüll-Logik
│   └── Datenbank-Operationen
│
├── job_agent/                      # Kern-Paket
│   ├── __init__.py
│   ├── llm.py                      # Gemini API-Client mit Key-Rotation
│   ├── openrouter_llm.py           # OpenRouter-Fallback
│   ├── groq_llm.py                 # Groq-Provider
│   ├── deepseek_llm.py             # DeepSeek-Provider
│   ├── config.py                   # YAML/JSON-Konfigurationsloader
│   ├── db.py                       # SQLite-Datenbank (applications.db)
│   ├── utils.py                    # ANSI-Farben, JSON-Reparatur, TeeStdout
│   ├── email_sender.py             # E-Mail-Paketierung & -Versand
│   └── direct_email_applier.py     # Direktbewerbung per E-Mail
│
├── config/                         # Benutzer-Konfiguration
│   ├── config.yaml                 # API-Keys, SMTP, Chrome-Pfad
│   ├── job_criteria.yaml           # K.O.-Filter, Score-Schwellen
│   ├── candidate_profile.json      # Kandidatenprofil (KI-generiert)
│   ├── prompts.yaml                # Prompt-Vorlagen
│   └── *.sample                    # Vorlagen für Erstsetup
│
├── output/                         # Generierte Dateien
│   ├── Anschreiben_*.pdf           # Deckblatt-PDFs
│   └── applications.db             # SQLite-Datenbank
│
├── documents/                      # Kandidaten-PDFs (CV, Zeugnisse)
│
├── temp_profile/                   # Fallback-Chrome-Profil
│
├── mock_jobs.py                    # Test-Code für Jobsuche-Mock
├── test_pw.py                      # Playwright-Test
├── test_genai.py                   # Gemini-API-Test
└── test_invalid.py                 # Platzhalter-Test
```

---

## 📊 Modulübersicht (UML-Tabelle)

| Modul / Datei | Typ | Verantwortlichkeit | Schlüssel-Funktionen |
|---|---|---|---|
| **`agent.py`** | CLI-Orchestrator | Hauptlogik, CLI-Parsing, Browser-Steuerung | `main()`, `get_browser_context()`, `process_job_url()`, `score_job()`, `generate_anschreiben()`, `save_anschreiben_pdf()`, `fill_page_form()` |
| **`job_agent/llm.py`** | API-Client | Gemini API mit Key-Rotation & Fallback | `init_gemini()`, `generate_content_with_retry()`, `llm_request_with_fallback()` |
| **`job_agent/openrouter_llm.py`** | API-Client | OpenRouter-API (Free-Modelle) | `call_openrouter()` |
| **`job_agent/groq_llm.py`** | API-Client | Groq-API (Llama 3.3) | `call_groq()` |
| **`job_agent/deepseek_llm.py`** | API-Client | DeepSeek-API | `call_deepseek()` |
| **`job_agent/config.py`** | Konfiguration | YAML/JSON-Loader, Default-Prompts | `load_config()`, `load_criteria()`, `load_prompts()`, `restore_active_configs_from_samples()` |
| **`job_agent/db.py`** | Persistenz | SQLite-Datenbank (applications.db) | `init_db()`, `log_application()`, `is_already_applied()`, `log_user_rejection()` |
| **`job_agent/utils.py`** | Hilfsfunktionen | ANSI-Farben, JSON-Reparatur, I/O | `clean_and_repair_json()`, `TeeStdout`, `clean_ansi_escape_codes()` |
| **`job_agent/email_sender.py`** | E-Mail-Versand | Packt Bewerbungen in ZIP und sendet per SMTP | `send_pending_emails()` |
| **`job_agent/direct_email_applier.py`** | E-Mail-Bewerbung | Extrahiert HR-Kontakte, personalisiert Anschreiben | `extract_contact_info()`, `personalize_anschreiben()`, `send_direct_email()` |
| **`mock_jobs.py`** | Test-Helper | Mockt die Jobsuche und führt `main()` aus | – |
| **`test_pw.py`** | Integrationstest | Playwright-Verschachtelungstest | – |
| **`test_genai.py`** | Integrationstest | Gemini-API-Konnektivitätstest | – |

---

## 📦 Abhängigkeiten

### Systemvoraussetzungen

- **Python 3.10+**
- **Google Chrome** oder **Chromium** (für Playwright)
  - Wird automatisch erkannt (auch Brave, Edge)
- **Tkinter** (optional, für die Konfigurations-GUI)
  - Auf Ubuntu/Debian: `sudo apt install python3-tk`

### Python-Pakete

```bash
# Kern-Abhängigkeiten
pip install playwright pyyaml google-genai PyMuPDF

# Browser-Engine installieren
playwright install chromium
```

> **Hinweis:** Die alternativen LLM-Provider (OpenRouter, Groq, DeepSeek) verwenden nur die Python-Standardbibliothek (`urllib.request`) und benötigen keine zusätzlichen Pakete.

---

## 🔧 Konfigurationsdateien

Alle relevanten Konfigurationsdateien befinden sich im `config/`-Verzeichnis.  
Beim ersten Start können `.sample`-Dateien in aktive Konfigurationen umgewandelt werden (via `--reset-candidate`).

### 1. `config/config.yaml` — Hauptkonfiguration

```yaml
user_profile:
  chrome_data_dir: "C:\\Users\\<Username>\\AppData\\Local\\Google\\Chrome\\User Data"
  chrome_profile: "Default"
  cv_path: "../documents/Lebenslauf.pdf"      # Pfad zum CV-PDF
  documents_dir: "../documents"               # Verzeichnis für weitere Dokumente

defaults:
  salary_expectation: "36.000 €"              # Gehaltsvorstellung
  availability: "sofort"                      # Verfügbarkeit
  work_permit: "Germany"                      # Arbeitserlaubnis
  notice_period: "3 Monate zum Quartalsende"  # Kündigungsfrist

criteria:
  min_score: 8.0                              # Min. Score (wird überschrieben)
  min_salary_eur: 36000
  remote_allowed: true
  german_level: "B2"
  excluded_companies:                         # Firmen-Blacklist
    - "Zukunftsmotor"

# Hinweis: Die Bewertungsparameter (min_score, min_salary, etc.)
# werden aus job_criteria.yaml gelesen, nicht aus dieser Section.

gemini:
  model: "gemini-2.5-flash"                   # Standard-Modell
  api_keys:                                    # Bis zu 4 Keys für Rotation
    - "AIzaSy..."                             # Key 1
    - "AIzaSy..."                             # Key 2

llm:
  priority: "gemini"                          # "gemini" oder "openrouter"

smtp:
  host: "smtp.gmail.com"
  port: 587
  username: "your.email@gmail.com"
  password: "your-app-password"               # Google App Password
```

### 2. `config/job_criteria.yaml` — Bewertungskriterien

```yaml
scoring:
  min_score_to_apply: 5.0                     # Mindest-Score für Bewerbung (0–10)

ko_filters:
  salary:
    min_annual_eur: 36000                     # Mindestgehalt (K.O. bei Unterschreitung)
  languages:
    min_required_english: "A2"                # K.O. bei "fließend" oder "C1"
    min_required_german: "B1"                 # K.O. bei C1/C2 oder "verhandlungssicher"
  clearances:
    forbidden_keywords:                       # K.O. bei Sicherheitsfreigaben
      - "U.S. citizenship"
      - "security clearance"
  certifications:
    mandatory_if_specified:                   # K.O. wenn Zertifikat gefordert & fehlt
      - "RHCSA"
      - "CCNA"
  education:
    require_it_degree_strictly: true          # K.O. bei striktem IT-Studium
    block_degree_only_roles: true             # Kein "oder vergleichbare Erfahrung"
  datacenter_physical_work:
    forbidden: true
  spam_providers:
    blocked_keywords:                         # Bildungsanbieter (keine echten Stellen)
      - "GFN"
      - "WBS"
    allow_internship: true                    # Praktika bei Anbietern erlaubt
  companies_blacklist: []
  forbidden_titles:                           # Titel, die ignoriert werden
    - "Full Stack Developer"
    - "Senior"
    - "Consultant"
    - "Support"
  user_rejected_reasons: []                   # Vom User abgelehnte Kriterien

cover_letter:
  career_start_year: 2010                     # Start der IT-Karriere
  mandatory_skills:                           # Fähigkeiten, die im Anschreiben vorkommen MÜSSEN
    - "Java"
    - "Perl"
    - "Kommandozeile (Console)"
```

### 3. `config/candidate_profile.json` — Kandidatenprofil

Wird automatisch via `--parse-cv` aus dem CV-PDF generiert. Enthält:

```json
{
  "personal_info": {
    "first_name": "Max",
    "last_name": "Mustermann",
    "email": "max@example.com",
    "phone": "+49 176 12345678",
    "address": "Hauptstr. 1",
    "city": "60311 Frankfurt am Main",
    "country": "Deutschland"
  },
  "languages": { "Deutsch": "B2", "Englisch": "A2" },
  "skills": ["Linux", "Python", "Java", "Docker", ...],
  "experience_years": 10.0,
  "certifications": ["Cisco CCST", "AZ-900"],
  "education": [...]
}
```

### 4. `config/prompts.yaml` — KI-Prompt-Vorlagen

Enthält die deutschsprachigen Prompts für:
- `scoring_prompt` — Bewertung einer Stellenanzeige (0–10 Score)
- `cover_letter_prompt` — Anschreiben-Generierung (DIN 5008)
- `form_filler_prompt` — Intelligentes Ausfüllen von Webformularen
- `classification_prompt` — Dokumentenklassifikation (CV, Zertifikat, etc.)
- `extract_recruiter_prompt` — Extraktion von HR-Kontaktnamen

---

## 🚀 CLI-Argumente

### Übersicht aller Flags

| Argument | Typ | Standard | Beschreibung |
|---|---|---|---|
| `--generate-dummy-cv` | Flag | – | Generiert ein Dummy-CV-PDF zum Testen |
| `--parse-cv` | Flag | – | Parst das CV-PDF und erzeugt `candidate_profile.json` |
| `--test-score PATH` | String | – | Testet das Scoring anhand einer lokalen JD-Textdatei |
| `--test-anschreiben COMPANY FILE` | 2 Strings | – | Testet die Anschreiben-Generierung |
| `--url URL` | String | – | Einzelne Stellen-URL verarbeiten |
| `--interactive` | Flag | – | Interaktiver Modus (URL-Eingabe) |
| `--search-jobs [KEYWORDS]` | String | `None` | Stellensuche auf Indeed & LinkedIn |
| `--location TEXT` | String | `"Deutschland"` | Ort für die Stellensuche |
| `--radius KM` | Integer | `25` | Suchradius um den Ort (km) |
| `--chrome-data-dir PATH` | String | aus Config | Chrome-Profil-Pfad überschreiben |
| `--headless` | Flag | – | Headless-Modus (unsichtbarer Browser). **Aktiviert automatisch `--auto-approve`** — da kein sichtbares Fenster zur manuellen Überprüfung vorhanden ist. |
| `--auto-approve` | Flag | – | Automatisches Absenden ohne Rückfrage |
| `--config PATH` | String | `config/config.yaml` | Pfad zur Konfigurationsdatei |
| `--profile PATH` | String | `config/candidate_profile.json` | Pfad zum Kandidatenprofil |
| `--criteria PATH` | String | `config/job_criteria.yaml` | Pfad zur Kriteriendatei |
| `--reset-candidate` | Flag | – | Setzt Kandidatendaten zurück (Löscht DB, PDFs) |
| `--send-email` | Flag | – | Sendet ausstehende Bewerbungen als E-Mail-ZIP |

### Detaillierte Beschreibung

#### `--generate-dummy-cv`
Generiert ein Dummy-CV-PDF mit Playwright für erste Tests, falls kein echtes CV vorhanden ist.

#### `--parse-cv`
Analysiert das im `config.yaml` unter `user_profile.cv_path` angegebene CV-PDF mittels Gemini und schreibt das strukturierte Profil in `config/candidate_profile.json`.

#### `--test-score <pfad_zur_jd.txt>`
Lädt eine lokale Textdatei mit einer Stellenbeschreibung, führt das KI-Scoring aus und gibt das Ergebnis (0–10) aus — ohne Browser zu starten.

#### `--test-anschreiben <Firma> <pfad_zur_jd.txt>`
Generiert ein Anschreiben für die angegebene Firma basierend auf einer lokalen JD-Textdatei und erzeugt ein PDF.

#### `--url "<url>"`
Öffnet die angegebene Stellen-URL im Browser, führt Scoring, Anschreiben-Generierung und Formularausfüllung aus.

#### `--interactive`
Startet den interaktiven Modus: Fragt wiederholt nach URLs, bis der Benutzer `exit` eingibt.

#### `--search-jobs [Keywords]` + `--location` + `--radius`
Führt eine automatische Stellensuche auf Indeed und LinkedIn durch. Die Keywords können direkt angegeben werden:
```bash
python agent.py --search-jobs "Linux Administrator" --location "Frankfurt am Main" --radius 25
```

#### `--headless`
Startet Chrome ohne sichtbares Fenster. Im Headless-Modus wird automatisch auch `--auto-approve` aktiviert, da es kein Browserfenster zum manuellen Überprüfen gibt.

#### `--auto-approve`
Bestätigt Bewerbungen automatisch, ohne auf eine manuelle Eingabe zu warten. Wenn das Formular nicht ausgefüllt werden kann, wird das Anschreiben per E-Mail an die Kandidaten-E-Mail gesendet (Fallback).

#### `--reset-candidate`
Erstellt einen Git-Backup-Commit (`RESTORE`), löscht dann:
- Alle generierten PDFs, HTMLs und PNGs
- Die SQLite-Datenbank (`applications.db`)
- Alle aktiven Konfigurationsdateien
Stellt dann `.sample`-Dateien als saubere Vorlagen wieder her.

#### `--send-email`
Durchsucht die Datenbank nach Bewerbungen mit `email_sent = 0`, packt sie in ZIP-Dateien (Job-Info, Terminal-Log, PDF) und sendet sie per SMTP an die Kandidaten-E-Mail.

---

## ✅ Argument-Kompatibilitätsmatrix

| Flag | `--generate-dummy-cv` | `--parse-cv` | `--test-score` | `--test-anschreiben` | `--url` | `--interactive` | `--search-jobs` | `--reset-candidate` | `--send-email` |
|---|---|---|---|---|---|---|---|---|---|
| **`--generate-dummy-cv`** | ✅ Alleinstehend | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **`--parse-cv`** | ❌ | ✅ Alleinstehend | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **`--test-score`** | ❌ | ❌ | ✅ Alleinstehend | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **`--test-anschreiben`** | ❌ | ❌ | ❌ | ✅ Alleinstehend | ❌ | ❌ | ❌ | ❌ | ❌ |
| **`--url`** | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ |
| **`--interactive`** | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ |
| **`--search-jobs`** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ + `--location`, `--radius` | ❌ | ❌ |
| **`--reset-candidate`** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ Alleinstehend | ❌ |
| **`--send-email`** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ Alleinstehend |
| **`--headless`** | ❌ | ❌ | ❌ | ❌ | ⚠️ | ⚠️ | ✅ Empfohlen | ❌ | ❌ |
| **`--auto-approve`** | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ Empfohlen | ❌ | ❌ |
| **`--config`** | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **`--profile`** | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **`--criteria`** | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **`--chrome-data-dir`** | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ❌ | ❌ |

**Legende:**
- ✅ = Kombination möglich oder empfohlen
- ❌ = Sinnlose oder blockierende Kombination
- ⚠️ = Möglich, aber nicht empfohlen (ohne `--auto-approve` wird auf Benutzereingabe gewartet)

**Wichtige Kombinationsregeln:**
1. **`--headless` aktiviert automatisch `--auto-approve`** — da kein Browserfenster sichtbar ist.
2. **`--send-email` aktiviert automatisch `--auto-approve`** — um alle ausstehenden Bewerbungen zu verarbeiten.
3. **`--url` kann mit `--config`/`--profile`/`--criteria`** kombiniert werden, um andere Konfigurationen zu laden.
4. **`--search-jobs` kann mit `--location` und `--radius`** kombiniert werden.
5. **Test-Flags (`--test-score`, `--test-anschreiben`) laufen alleinstehend** — sie starten keinen Browser.
6. **`--reset-candidate` ist ein Reinigungsbefehl** — alle anderen Flags werden ignoriert.

---

## 🚦 Erste Schritte

### 1. Installation

```bash
# Repository klonen (oder fork-en)
git clone <your-repo-url>
cd <project-directory>

# Abhängigkeiten installieren
pip install playwright pyyaml google-genai PyMuPDF openai
playwright install chromium

# Optional: Tkinter für Konfigurations-GUI
# Ubuntu/Debian: sudo apt install python3-tk
```

### 2. Konfiguration

```bash
# Konfigurations-GUI starten (Tkinter) — oder Dateien manuell bearbeiten
python agent.py

# Oder: Schnellstart mit Reset (erstellt .sample → aktive Configs)
python agent.py --reset-candidate

# Dann: Config-Dateien in config/ anpassen:
# - config.yaml: API-Keys, SMTP, Chrome-Pfad
# - job_criteria.yaml: K.O.-Filter, Score
# - candidate_profile.json: Persönliche Daten
```

### 3. Kandidatenprofil erstellen

```bash
# Option A: CV parsen (PDF muss in documents/ liegen)
python agent.py --parse-cv

# Option B: Dummy-CV generieren
python agent.py --generate-dummy-cv

# Option C: Manuell bearbeiten
# → config/candidate_profile.json editieren
```

### 4. Erste Bewerbung testen

```bash
# Einzelne URL verarbeiten (manuelle Freigabe)
python agent.py --url "https://de.indeed.com/viewjob?jk=12345"

# Oder: Vollautomatisch
python agent.py --url "https://de.indeed.com/viewjob?jk=12345" --headless --auto-approve
```

---

## 💡 Anwendungsbeispiele

### 🔍 Stellen suchen & automatisch bewerben

```bash
python agent.py --search-jobs "Remote Hybrid" \
                --location "Frankfurt am Main" \
                --radius 25 \
                --headless \
                --auto-approve
```

### 📨 Ausstehende Bewerbungen per E-Mail versenden

```bash
python agent.py --send-email
```

(Voraussetzung: SMTP-Zugangsdaten in `config.yaml`)

### 🔄 Arbeitsbereich zurücksetzen

```bash
python agent.py --reset-candidate
```

(Erstellt zuerst einen Git-Commit `RESTORE`, löscht dann alle generierten Daten)

### 🧪 Scoring testen (ohne Browser)

```bash
python agent.py --test-score pfad/zur/stellenbeschreibung.txt
```

### ✉️ Anschreiben testen (ohne Browser)

```bash
python agent.py --test-anschreiben "Musterfirma GmbH" pfad/zur/stellenbeschreibung.txt
```

### 🖥️ GUI starten (Konfiguration bearbeiten)

```bash
python agent.py
```

(Ohne Argumente geöffnet: Tkinter-GUI zum Bearbeiten von Config, Profil, Prompts und K.O.-Filtern)

---

## ⚠️ Fehlerbehebung & Bekannte Probleme

### 🔒 Chrome-Profil gesperrt

**Problem:** `FAILED TO LAUNCH PERSISTENT CONTEXT` / "lock" error  
**Lösung:**
- Schließe alle Chrome-Fenster vollständig
- Oder verwende `--headless` (dann wird automatisch ein temporäres Profil verwendet)
- Oder starte Chrome mit Remote-Debugging: `google-chrome --remote-debugging-port=9222`

### 🔑 Gemini-API-Key erschöpft

**Problem:** Alle API-Keys haben ihr tägliches Limit erreicht  
**Lösung:**
- Füge weitere Keys in `config.yaml` unter `gemini.api_keys` hinzu
- Das Tool rotiert automatisch durch alle Keys
- Fallback: OpenRouter (kostenlose Modelle) wird automatisch probiert
- Oder setze `llm.priority: openrouter` in `config.yaml`

### 🌐 Windows-Pfade auf Linux

**Problem:** `config.yaml` enthält `C:\Users\...`-Pfade  
**Lösung:**
- Aktualisiere `chrome_data_dir` auf Linux-Pfad (`~/.config/google-chrome`)
- Oder verwende `--headless` (ignoriert den Chrome-Pfad)

### 🐍 Tkinter nicht installiert

**Problem:** `tkinter`-Import-Fehler  
**Lösung:**
- Ubuntu/Debian: `sudo apt install python3-tk`
- Oder verwende CLI-Flags statt der GUI (`--url`, `--search-jobs`, etc.)

### 📄 Kein Abhängigkeits-Manifest

**Problem:** Keine `requirements.txt` / `pyproject.toml` vorhanden  
**Lösung:** Alle Pakete manuell installieren (siehe [Abhängigkeiten](#-abhängigkeiten)). Bei neuen Importen bitte in der `knowledge.md` dokumentieren.

---

## 🗺️ Roadmap

- [ ] **StepStone / Monster / XING** — Neue Job-Plattform-Module
- [ ] **Claude / Ollama** — Zusätzliche LLM-Provider
- [ ] **Docker-Image** — Containerisierte Ausführung
- [ ] **CI/CD-Pipeline** — Headless-Betrieb in GitHub Actions
- [ ] **Web-Dashboard** — Bewerbungsstatus im Browser einsehen
- [ ] **Unittests** — Formelle Testabdeckung (pytest)
- [ ] **i18n** — Unterstützung für weitere Länder/Sprachen

---

## 📄 Lizenz

Dieses Projekt ist Open Source. Siehe die `LICENSE`-Datei für Details.

---

<div align="center">
  <p>
    <strong>Gemini JobAgent</strong> — gemacht mit ❤️ für den deutschen Arbeitsmarkt.<br>
    <sub>Verbessere das Projekt — erstelle einen Fork und einen Pull Request!</sub>
  </p>
</div>
