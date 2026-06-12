import sys
import os
import re
import signal
import socket

# ANSI Escape colors for terminal highlighting
class Colors:
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    MAGENTA = '\033[95m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'

# Handle Ctrl+C gracefully at the OS level to prevent traceback prints
def handle_sigint(sig, frame):
    raise KeyboardInterrupt

signal.signal(signal.SIGINT, handle_sigint)

# Ensure UTF-8 encoding on Windows terminal for German umlauts
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
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
    """
    global _IPV4_FIX_APPLIED
    if _IPV4_FIX_APPLIED:
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


