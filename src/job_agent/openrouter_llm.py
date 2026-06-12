import os
import json
import time
import yaml
import urllib.request
import urllib.error

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = None

# Free OpenRouter models (verified working)
_FREE_MODELS = [
    "openai/gpt-oss-120b:free",
    "openai/gpt-oss-20b:free",
    "deepseek/deepseek-v4-flash:free",
    "deepseek/deepseek-r1-0528:free",
    "moonshotai/kimi-k2.6:free",
    "cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
    "z-ai/glm-4.5-air:free",
]

class OpenRouterResponse:
    def __init__(self, text, model_used=None):
        self.text = text
        self.model_used = model_used

def _get_config_path():
    """Find the config.yaml path relative to this file."""
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "config.yaml")


def _read_openrouter_config():
    """Read the openrouter section from config.yaml once. Returns {} on failure."""
    try:
        config_path = _get_config_path()
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            return config.get("openrouter", {}) or {}
    except Exception:
        pass
    return {}


def _get_api_key():
    # Priority: environment variable > config.yaml
    for var in ["OPENROUTER_API_KEY", "OPENROUTER_KEY"]:
        key = os.environ.get(var)
        if key:
            return key.strip()
    try:
        key = _read_openrouter_config().get("api_key", "")
        if key and "<" not in key:
            return key.strip()
    except Exception:
        pass
    return None


def _get_model():
    global OPENROUTER_MODEL
    if OPENROUTER_MODEL:
        return OPENROUTER_MODEL
    # Priority: environment > config.yaml > default
    env_model = os.environ.get("OPENROUTER_MODEL")
    if env_model:
        OPENROUTER_MODEL = env_model.strip()
        return OPENROUTER_MODEL
    try:
        model = _read_openrouter_config().get("model", "")
        if model and "<" not in model:
            OPENROUTER_MODEL = model.strip()
            return OPENROUTER_MODEL
    except Exception:
        pass
    OPENROUTER_MODEL = "openai/gpt-oss-120b:free"
    return OPENROUTER_MODEL

def call_openrouter(prompt, max_retries=5, initial_delay=2.0, **kwargs):
    api_key = _get_api_key()
    if not api_key:
        print("[OpenRouter] No API key found in environment (OPENROUTER_API_KEY).")
        return None

    model = _get_model()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 8192
    }

    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    url = f"{OPENROUTER_BASE_URL}/chat/completions"

    delay = initial_delay
    rate_limit_hit = False
    for attempt in range(max_retries):
        try:
            if rate_limit_hit:
                time.sleep(3.0)
            else:
                time.sleep(4.0)
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = resp.read().decode("utf-8")
                result = json.loads(body)
                content = result["choices"][0]["message"]["content"]
                return OpenRouterResponse(content)

        except urllib.error.HTTPError as e:
            status = e.code
            error_body = e.read().decode("utf-8", errors="replace")[:500]
            if status == 429:
                rate_limit_hit = True
                wait = min(delay, 60.0)
                print(f"[OpenRouter] Rate limited (429). Waiting {wait:.0f}s before retry {attempt+1}/{max_retries}...")
                time.sleep(wait)
                delay *= 2.0
            elif status in (401, 403):
                print(f"[OpenRouter] Auth error ({status}): {error_body}")
                return None
            elif status == 402:
                print(f"[OpenRouter] Insufficient credits (402): {error_body}")
                return None
            else:
                print(f"[OpenRouter] HTTP {status}: {error_body[:200]}")
                if attempt == max_retries - 1:
                    return None
                time.sleep(delay)
                delay *= 2.0

        except urllib.error.URLError as e:
            print(f"[OpenRouter] Connection error: {e.reason}")
            if attempt == max_retries - 1:
                return None
            time.sleep(delay)
            delay *= 2.0

        except json.JSONDecodeError as e:
            print(f"[OpenRouter] Invalid JSON response: {e}")
            return None

        except Exception as e:
            print(f"[OpenRouter] Request failed: {e}")
            if attempt == max_retries - 1:
                return None
            time.sleep(delay)
            delay *= 2.0

    return None
