# -*- coding: utf-8 -*-
import os
import sys
import time
import json
from google import genai
from google.genai import types
from google.genai import errors as genai_errors
from job_agent.config import load_config
from job_agent.utils import Colors, clean_and_repair_json, force_ipv4
from job_agent.openrouter_llm import call_openrouter

# Global state for API key rotation and fallback models
API_KEYS = [
    "<YOUR_GEMINI_API_KEY_1>",
    "<YOUR_GEMINI_API_KEY_2>",
    "<YOUR_GEMINI_API_KEY_3>",
    "<YOUR_GEMINI_API_KEY_4>"
]
KEY_STATUS: dict[int, str] = {}
CURRENT_KEY_INDEX = 0
GEMINI_MODEL = "gemini-2.5-flash"
IS_CONFIG_DRIVEN_KEYS = False
INITIALIZED = False
PRIORITY_LLM = "gemini"  # "gemini" or "openrouter"

def init_gemini(config_path=None, force=False):
    global CURRENT_KEY_INDEX, API_KEYS, GEMINI_MODEL, IS_CONFIG_DRIVEN_KEYS, INITIALIZED, KEY_STATUS, PRIORITY_LLM
    
    if INITIALIZED and not force:
        return

    # Force IPv4 preference to work around broken IPv6 in some environments
    force_ipv4()

    try:
        config = load_config(config_path)
        config_keys = config.get("gemini", {}).get("api_keys", [])
        if config_keys:
            API_KEYS = [k.strip() for k in config_keys if k.strip()]
            IS_CONFIG_DRIVEN_KEYS = True
        model_val = config.get("gemini", {}).get("model")
        if model_val:
            GEMINI_MODEL = model_val
        priority = config.get("llm", {}).get("priority", "gemini")
        if priority in ("gemini", "openrouter"):
            PRIORITY_LLM = priority
    except Exception:
        pass

    KEY_STATUS = {i: "active" for i in range(len(API_KEYS))}

    # Prioritize config-based API keys if they exist, to allow rotation
    if IS_CONFIG_DRIVEN_KEYS and API_KEYS:
        if CURRENT_KEY_INDEX >= len(API_KEYS):
            CURRENT_KEY_INDEX = 0
        api_key = API_KEYS[CURRENT_KEY_INDEX]
        print(f"Using configured API key from config at index {CURRENT_KEY_INDEX}")
    else:
        api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GOOGLE_GENERATIVE_AI_API_KEY")
        if api_key:
            print("Using API key from environment override")
        else:
            if CURRENT_KEY_INDEX >= len(API_KEYS):
                CURRENT_KEY_INDEX = 0
            api_key = API_KEYS[CURRENT_KEY_INDEX]
            print(f"Using default configured API key index {CURRENT_KEY_INDEX}")
    INITIALIZED = True

def generate_content_with_retry(model_name, prompt, max_retries=3, initial_delay=2.0, max_delay=15.0, **kwargs):
    global GEMINI_MODEL, CURRENT_KEY_INDEX, API_KEYS, IS_CONFIG_DRIVEN_KEYS, KEY_STATUS
    
    # Rate limit spacing (15 RPM is max, sleep 3s is safe)
    time.sleep(3.0)
    
    models_fallback = ["gemini-2.5-flash", "gemini-3.1-flash-lite", "gemini-2.5-flash-lite", "gemini-flash-latest"]
    
    # Ensure current model is in fallback list
    if model_name not in models_fallback:
        models_fallback = [model_name] + [m for m in models_fallback if m != model_name]
        
    model_idx = 0
    while model_idx < len(models_fallback):
        active_model_name = models_fallback[model_idx]
        GEMINI_MODEL = active_model_name
        # Reset keys for each new model attempt
        KEY_STATUS_FOR_MODEL = dict(KEY_STATUS)

        while True: # Try loop for active keys on current model
            # Find next active key
            active_indices = [i for i, status in KEY_STATUS_FOR_MODEL.items() if status == "active"]

            if not active_indices:
                # All keys exhausted for this model — break to outer loop to try next model
                break

            # Ensure we are on an active key
            if KEY_STATUS_FOR_MODEL.get(CURRENT_KEY_INDEX) != "active":
                CURRENT_KEY_INDEX = active_indices[0]

            current_key = API_KEYS[CURRENT_KEY_INDEX]

            # Try the call
            delay = initial_delay
            last_err = None

            for attempt in range(max_retries):
                try:
                    client = genai.Client(api_key=current_key, http_options=types.HttpOptions(timeout=120.0))
                    gen_config = kwargs.get("generation_config")
                    config_obj = types.GenerateContentConfig(**gen_config) if gen_config else None
                    result = client.models.generate_content(
                        model=active_model_name,
                        contents=prompt,
                        config=config_obj
                    )
                    # Also update global KEY_STATUS to reflect exhaustions found
                    KEY_STATUS.update(KEY_STATUS_FOR_MODEL)
                    return result  # Success!
                except genai_errors.ClientError as e:
                    last_err = e
                    if e.code in (400, 403):
                        break  # Key invalid or permanently denied
                    if e.code == 429:
                        print(f"\n{Colors.YELLOW}[Gemini API] 429 Quota Exceeded (RPM or RPD) on key index {CURRENT_KEY_INDEX}. Sleeping 30s and retrying...{Colors.END}")
                        time.sleep(30.0)
                        continue # Retry after sleep
                    # Other 4xx — retry
                    if attempt == max_retries - 1:
                        break
                    print(f"\n[Gemini API] Request failed (ClientError {e.code}) on key index {CURRENT_KEY_INDEX}. Retrying in {delay}s...")
                    sys.stdout.flush()
                    time.sleep(delay)
                    delay = min(delay * 2.0, max_delay)
                except Exception as e:
                    last_err = e
                    err_name = type(e).__name__
                    err_msg = str(e)
                    if attempt == max_retries - 1:
                        break
                    # Provide helpful diagnostics for common network/SSL errors
                    if 'ssl' in err_name.lower() or 'ssl' in err_msg.lower() or 'handshake' in err_msg.lower():
                        print(f"\n{Colors.YELLOW}[Gemini API] SSL/TLS error (key {CURRENT_KEY_INDEX}): {err_msg[:200]}{Colors.END}")
                        if attempt == 0:
                            print(f"{Colors.CYAN}  Tip: This often means IPv6 is broken on this machine. The agent has applied a patch to prefer IPv4. Retrying...{Colors.END}")
                    elif 'timeout' in err_name.lower() or 'timeout' in err_msg.lower():
                        print(f"\n{Colors.YELLOW}[Gemini API] Timeout (key {CURRENT_KEY_INDEX}): {err_msg[:200]}{Colors.END}")
                        print(f"{Colors.CYAN}  Tip: Check your internet connection or try increasing the timeout value in job_agent/llm.py{Colors.END}")
                    else:
                        print(f"\n[Gemini API] Request failed ({err_name}) on key index {CURRENT_KEY_INDEX}. Retrying in {delay}s...")
                    sys.stdout.flush()
                    time.sleep(delay)
                    delay = min(delay * 2.0, max_delay)

            # If we reached here, check if key is exhausted or a real error
            err_msg = str(last_err).lower() if last_err else ""
            if any(kw in err_msg for kw in ["api key", "invalid", "denied"]):
                print(f"\n{Colors.YELLOW}[Gemini API] Key index {CURRENT_KEY_INDEX} invalid or denied for model '{active_model_name}'. Trying next key...{Colors.END}")
                KEY_STATUS_FOR_MODEL[CURRENT_KEY_INDEX] = "exhausted"
                KEY_STATUS[CURRENT_KEY_INDEX] = "exhausted"
                continue  # Loop back to find next active key
            elif last_err:
                raise last_err

        # All keys exhausted for this model — try next model
        model_idx += 1
        if model_idx < len(models_fallback):
            print(f"\n{Colors.YELLOW}[Gemini API] All keys exhausted for model '{active_model_name}'. Falling back to model '{models_fallback[model_idx]}'...{Colors.END}")
            KEY_STATUS = {i: "active" for i in range(len(API_KEYS))}
        else:
            # All models and all keys exhausted — try OpenRouter fallback
            print(f"\n{Colors.YELLOW}[Gemini API] All Gemini models and keys exhausted. Trying OpenRouter fallback...{Colors.END}")
            try:
                or_response = call_openrouter(prompt, **kwargs)
                if or_response is not None:
                    print(f"{Colors.GREEN}[OpenRouter] Fallback successful. Response received.{Colors.END}")
                    return or_response
                else:
                    print(f"{Colors.RED}[OpenRouter] Fallback returned no response.{Colors.END}")
            except Exception as or_err:
                print(f"{Colors.RED}[OpenRouter] Fallback failed: {or_err}{Colors.END}")

            print(f"\n{Colors.RED}[Gemini API] ERROR: All models and all API keys are exhausted!{Colors.END}")
            return None
def llm_request_with_fallback(prompt, **kwargs):
    """
    Tries the priority LLM first (Gemini with rotation or Groq).
    On failure, falls back to the other LLM.
    """
    global PRIORITY_LLM

    if PRIORITY_LLM == "openrouter":
        print(f"{Colors.CYAN}[LLM] Priority: OpenRouter (free). Trying OpenRouter first...{Colors.END}")
        or_resp = call_openrouter(prompt, **kwargs)
        if or_resp:
            return or_resp
        print(f"{Colors.YELLOW}[LLM] OpenRouter failed or unavailable. Falling back to Gemini...{Colors.END}")
        return generate_content_with_retry(GEMINI_MODEL, prompt, **kwargs)

    # Default: try Gemini with rotation first
    try:
        return generate_content_with_retry(GEMINI_MODEL, prompt, **kwargs)
    except Exception as e:
        print(f"\n{Colors.RED}[Gemini API] Failed: {e}. Trying OpenRouter fallback...{Colors.END}")
        or_resp = call_openrouter(prompt, **kwargs)
        if or_resp:
            return or_resp
        raise RuntimeError("Both Gemini and OpenRouter failed.")


