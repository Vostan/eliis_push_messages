"""
Thin OpenAI wrapper used by the scripts in this repo.

Exposes:
  - chat(messages, ...) — chat completion via gpt-4o-mini, returns the text.
  - describe_image(url) — short caption for an image; returns "" on failure
    so callers can degrade gracefully rather than crash.
  - strip_html(html) — plain text from a snippet of HTML.
"""
import os
import re

from openai import OpenAI

_MODEL = "gpt-4o-mini"

_client = None


def _openai():
    global _client
    if _client is not None:
        return _client
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    _client = OpenAI(api_key=key)
    return _client


def chat(messages, max_tokens=2000, temperature=0.4):
    resp = _openai().chat.completions.create(
        model=_MODEL,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return resp.choices[0].message.content.strip()


def describe_image(url):
    """Return a 3-6 word description of an image. Empty string on failure —
    this is a nice-to-have caption, never blocking."""
    try:
        out = chat(
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Describe this kindergarten photo in 3 to 6 words. "
                                "Output only the description, no leading or trailing punctuation. "
                                "Examples: 'children painting at table', 'outdoor snack time', "
                                "'kid holding crafted bird'."
                            ),
                        },
                        {"type": "image_url", "image_url": {"url": url, "detail": "low"}},
                    ],
                }
            ],
            max_tokens=30,
            temperature=0.3,
        )
        return out.strip().rstrip(".").strip()
    except Exception as e:
        print(f"  ⚠️  describe_image failed: {type(e).__name__}: {str(e)[:120]}")
        return ""


def strip_html(html):
    """Convert HTML to plain text suitable for translation input."""
    if not html:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", html)
    text = re.sub(r"</?p[^>]*>", "\n", text)
    text = re.sub(r"<li[^>]*>", "• ", text)
    text = re.sub(r"</li>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
