"""
Chat-completion helper that tries OpenAI first, then falls back to Google
Gemini (via Gemini's OpenAI-compatible endpoint) on any failure — quota
exhaustion, auth error, network blip, etc.

A provider is only attempted if its API key env var is set, so the workflow
keeps working when only one of OPENAI_API_KEY / GOOGLE_API_KEY is configured.
Raises if both attempts fail (or neither is configured).
"""
import os

from openai import OpenAI

_MODEL_OPENAI = "gpt-4o-mini"
_MODEL_GEMINI = "gemini-2.0-flash"
_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

_openai_client = None
_gemini_client = None


def _openai():
    global _openai_client
    if _openai_client is not None:
        return _openai_client
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        return None
    _openai_client = OpenAI(api_key=key)
    return _openai_client


def _gemini():
    global _gemini_client
    if _gemini_client is not None:
        return _gemini_client
    key = (os.getenv("GOOGLE_API_KEY") or "").strip()
    if not key:
        return None
    _gemini_client = OpenAI(api_key=key, base_url=_GEMINI_BASE_URL)
    return _gemini_client


def chat(messages, max_tokens=2000, temperature=0.4):
    """Run a chat completion with OpenAI → Gemini fallback. Returns the
    string content of the first choice. Raises if no provider succeeds."""
    openai_client = _openai()
    if openai_client is not None:
        try:
            resp = openai_client.chat.completions.create(
                model=_MODEL_OPENAI,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"  ⚠️  OpenAI failed ({type(e).__name__}: {str(e)[:160]}). Falling back to Gemini.")

    gemini_client = _gemini()
    if gemini_client is None:
        raise RuntimeError(
            "Translation failed: OpenAI errored and GOOGLE_API_KEY is not set. "
            "Set either OPENAI_API_KEY (with credit) or GOOGLE_API_KEY."
        )
    resp = gemini_client.chat.completions.create(
        model=_MODEL_GEMINI,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return resp.choices[0].message.content.strip()
