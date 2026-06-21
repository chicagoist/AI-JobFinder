import sys
import os
import re
import signal
import socket

# ---------------------------------------------------------------------------
# Platform detection helpers
# ---------------------------------------------------------------------------

IS_WINDOWS = sys.platform.startswith("win")
IS_LINUX = sys.platform.startswith("linux")
IS_MACOS = sys.platform.startswith("darwin")


# ---------------------------------------------------------------------------
# ANSI escape colors with Windows console support
# ---------------------------------------------------------------------------

def _enable_windows_ansi() -> None:
    """Enable ANSI escape code support on Windows 10+ terminals.

    Uses SetConsoleMode via ctypes to enable ENABLE_VIRTUAL_TERMINAL_PROCESSING.
    Falls back silently if ctypes is not available or the call fails.
    """
    try:
        import ctypes  # type: ignore[import-untyped]
        from ctypes import wintypes  # type: ignore[import-untyped]
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        STD_OUTPUT_HANDLE = wintypes.DWORD(-11).value
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        handle = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
        INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
        if handle and handle != INVALID_HANDLE_VALUE:
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
    except Exception:
        pass


if IS_WINDOWS:
    _enable_windows_ansi()


class Colors:
    """ANSI escape codes for terminal output.

    On Windows 10+ the _enable_windows_ansi() call above enables
    virtual terminal processing so \\033 sequences work in cmd/PowerShell.
    """
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    MAGENTA = '\033[95m'
    GREY = '\033[90m'
    DIM = '\033[2m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'
    RESET = '\033[0m'


# ---------------------------------------------------------------------------
# Signal handling (Ctrl+C) — platform-safe
# ---------------------------------------------------------------------------

def handle_sigint(sig, frame):
    """Handle Ctrl+C gracefully — no traceback dump."""
    raise KeyboardInterrupt

# Register SIGINT handler (works on both Unix and Windows Python 3.8+)
try:
    signal.signal(signal.SIGINT, handle_sigint)
except (AttributeError, ValueError, OSError):
    # Some platforms (e.g. Windows build tools, some embedded Python) may not
    # support signal.SIGINT. Ignore and proceed without custom handler.
    pass


# ---------------------------------------------------------------------------
# UTF-8 encoding on Windows terminal for German umlauts
# ---------------------------------------------------------------------------

if IS_WINDOWS:
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[union-attr]
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[union-attr]
    except Exception:
        pass

def sanitize_header(text):
    """Remove newlines and extra spaces from a string to make it safe for SMTP headers."""
    if not text:
        return ""
    # Replace newlines and carriage returns with a single space
    text = re.sub(r'[\r\n]+', ' ', str(text))
    # Collapse multiple spaces and strip
    return re.sub(r'\s+', ' ', text).strip()

def clean_json_response(text):
    if not text:
        return ""
    text = text.strip()
    # Remove markdown
    if text.startswith("```json"): text = text[7:]
    elif text.startswith("```"): text = text[3:]
    if text.endswith("```"): text = text[:-3]
    
    # Strip text before first { and after last } to isolate the JSON object
    start = text.find('{')
    end = text.rfind('}')
    
    # Or if it's a JSON array
    if start == -1:
        start = text.find('[')
        end = text.rfind(']')
        
    if start != -1 and end != -1:
        text = text[start:end+1]
    else:
        text = ""
    
    return text.strip()

def clean_and_repair_json(text):
    """
    Cleans markdown code ticks from Gemini JSON responses, removes trailing
    commas, and runs a state-machine to escape unescaped double quotes inside
    JSON string values.
    """
    text = clean_json_response(text)

    # Remove trailing commas before ] or } (common LLM mistake)
    text = re.sub(r',\s*([}\]])', r'\1', text)

    result = []
    i = 0
    n = len(text)
    inside_string = False

    while i < n:
        char = text[i]

        # Handle escaped characters inside string
        if char == '\\' and i + 1 < n:
            result.append(text[i:i+2])
            i += 2
            continue

        if char == '"':
            # 1. Find next non-whitespace character
            next_non_ws = None
            j = i + 1
            while j < n:
                if not text[j].isspace():
                    next_non_ws = text[j]
                    break
                j += 1

            # 2. Find previous non-whitespace character
            prev_non_ws = None
            j = i - 1
            while j >= 0:
                if not text[j].isspace():
                    prev_non_ws = text[j]
                    break
                j -= 1

            if inside_string:
                # We are inside a string. This quote is a valid end-of-string only if
                # the next non-whitespace character is a JSON delimiter: ',', '}', ']', or ':'
                is_end = next_non_ws in (',', '}', ']', ':') or next_non_ws is None
                if is_end:
                    inside_string = False
                    result.append('"')
                else:
                    # Unescaped quote inside string! Escape it.
                    result.append('\\"')
            else:
                # We are outside a string. This quote is a valid start-of-string only if
                # the previous non-whitespace character is '{', '[', ',', or ':'
                is_start = prev_non_ws in ('{', '[', ',', ':') or prev_non_ws is None
                if is_start:
                    inside_string = True
                    result.append('"')
                else:
                    # Unescaped quote outside string.
                    result.append('\\"')
        else:
            result.append(char)
        i += 1

    # Second pass: remove trailing commas (in case the state-machine introduced any)
    return re.sub(r',\s*([}\]])', r'\1', "".join(result))

import io

# Save the original socket.getaddrinfo once at module level to allow
# force_ipv4() to be called safely multiple times without chain-wrapping.
_ORIGINAL_GETADDRINFO = socket.getaddrinfo

_IPV4_FIX_APPLIED = False


def force_ipv4():
    """
    Monkey-patch socket.getaddrinfo to filter out IPv6 addresses.

    Some environments (especially on Kali Linux and certain Docker containers)
    have broken IPv6 connectivity. DNS returns IPv6 addresses, but connecting
    via IPv6 hangs on SSL/TLS handshake until timeout. The httpx library
    (used by the Google Gemini SDK) tries addresses sequentially starting with
    the first one. Simply sorting IPv4 first doesn't work because httpx may
    still try IPv6 if IPv4 fails or if it resolves addresses separately.

    This patch strips IPv6 results entirely when the caller does not explicitly
    request IPv6 (family=0/AF_UNSPEC), ensuring only IPv4 is used.

    **Cross-platform:** Only applies on Linux where IPv6 is commonly broken.
    On Windows and macOS the original getaddrinfo is left untouched.
    """
    global _IPV4_FIX_APPLIED
    if _IPV4_FIX_APPLIED:
        return

    # Only apply IPv4 fix on Linux (broken IPv6 is a Linux-specific problem)
    if not IS_LINUX:
        _IPV4_FIX_APPLIED = True
        return

    def _patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        # If the caller explicitly requested a specific family, respect it.
        # AF_UNSPEC (0) means "any family" — we intercept this to filter.
        if family == 0:
            # Only get IPv4 results
            return _ORIGINAL_GETADDRINFO(host, port, socket.AF_INET, type, proto, flags)
        return _ORIGINAL_GETADDRINFO(host, port, family, type, proto, flags)

    socket.getaddrinfo = _patched_getaddrinfo
    _IPV4_FIX_APPLIED = True


class TeeStdout:
    def __init__(self):
        self.stdout = sys.stdout
        self.buffer = io.StringIO()

    def __enter__(self):
        sys.stdout = self
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout = self.stdout

    def write(self, data):
        self.stdout.write(data)
        self.buffer.write(data)

    def flush(self):
        self.stdout.flush()
        self.buffer.flush()

    def getvalue(self):
        return self.buffer.getvalue()

def clean_ansi_escape_codes(text):
    if not text:
        return ""
    # Regular expression to match ANSI escape sequences
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)


def compact_profile_for_llm(profile: dict) -> str:
    """Convert candidate profile dict to a compact Markdown string for LLM prompts.

    Drops non-essential fields (hr_assessment, phone, address, curriculum details)
    and uses Markdown bullet points instead of JSON — much more token-efficient
    for local LLMs running on slow CPUs.

    Typical output: ~2000 chars vs ~6000 chars for indented JSON (65% reduction).
    """
    lines = []

    # Personal info — keep essentials only
    pi = profile.get("personal_info", {})
    raw_name = pi.get("name", "")
    first = pi.get("first_name", "")
    last = pi.get("last_name", "")
    if first and last:
        name = f"{first} {last}"
    elif raw_name:
        name = raw_name
    else:
        name = "Kandidat"
    lines.append(f"Name: {name}")

    email = pi.get("email", "")
    if email:
        lines.append(f"E-Mail: {email}")

    city = pi.get("city", "") or pi.get("location", "")
    if city:
        lines.append(f"Standort: {city}")

    avail = pi.get("availability", "")
    if avail:
        lines.append(f"Verf\u00fcgbarkeit: {avail}")

    # Languages
    langs = profile.get("languages", {})
    if langs:
        lang_str = ", ".join(f"{k} {v}" for k, v in langs.items())
        lines.append(f"Sprachen: {lang_str}")

    # Skills — keep all, comma-separated
    skills = profile.get("skills", [])
    if skills:
        lines.append(f"F\u00e4higkeiten: {', '.join(str(s) for s in skills)}")

    # Experience — title + company + years only (no duties)
    exp = profile.get("experience", [])
    if exp:
        lines.append("Berufserfahrung:")
        for e in exp[:8]:
            if isinstance(e, dict):
                title = e.get("title", e.get("position", ""))
                company = e.get("company", "")
                years = e.get("years", e.get("duration", ""))
                entry = f"  - {title}" if title else "  -"
                if company:
                    entry += f" bei {company}"
                if years:
                    entry += f" ({years})"
                lines.append(entry)
            else:
                lines.append(f"  - {str(e)}")

    # Education — degree + field + institution only (skip curriculum details)
    edu = profile.get("education", [])
    if edu:
        lines.append("Ausbildung:")
        for e in edu[:5]:
            if isinstance(e, dict):
                degree = e.get("degree", "")
                field = e.get("field", e.get("field_of_study", ""))
                inst = e.get("institution", "")
                year = e.get("year", e.get("graduation_year", ""))
                entry = "  -"
                if degree:
                    entry += f" {degree}"
                if field:
                    entry += f" in {field}"
                if inst:
                    entry += f", {inst}"
                if year:
                    entry += f" ({year})"
                lines.append(entry)
            else:
                lines.append(f"  - {str(e)}")

    # Certifications — names only
    certs = profile.get("certifications", [])
    if certs:
        cert_names = []
        for c in certs[:10]:
            if isinstance(c, dict):
                cert_names.append(c.get("name", str(c)))
            else:
                cert_names.append(str(c))
        lines.append(f"Zertifikate: {', '.join(cert_names)}")

    # Seniority level (important for forbidden title matching)
    seniority = profile.get("seniority_level", "")
    if seniority:
        lines.append(f"Seniorit\u00e4t: {seniority}")

    # Experience years
    exp_years = profile.get("experience_years", 0)
    if exp_years:
        lines.append(f"Berufserfahrung: {exp_years} Jahre")

    return "\n".join(lines)
