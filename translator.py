"""OpenAI wrapper (gpt-4o-mini). Every call degrades gracefully: callers get the
untranslated text back instead of a crash, so a bad OpenAI day never blocks posts."""
import os
import re

MODEL = "gpt-4o-mini"
_client = None


def _openai():
    global _client
    if _client is None:
        from openai import OpenAI

        key = (os.getenv("OPENAI_API_KEY") or "").strip()
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        _client = OpenAI(api_key=key)
    return _client


def chat(messages, max_tokens=1500, temperature=0.3):
    r = _openai().chat.completions.create(
        model=MODEL, messages=messages, max_tokens=max_tokens, temperature=temperature
    )
    return r.choices[0].message.content.strip()


_HTML_RULES = "Allowed HTML tags: <b> <i> <u> <s> <code> <a>. No other tags, no markdown, no code fences."


def translate_message(subject, body):
    """Inbox message → English with an ACTION/INFO header line. Returns Telegram HTML."""
    prompt = (
        "Translate this Estonian kindergarten message to English for a parent's Telegram channel.\n"
        "Line 1: '⚠️ ACTION: <one short line>' if the message contains a deadline, something the parent "
        "must do, or a question needing a reply; otherwise exactly 'INFO'.\n"
        "Line 2: blank.\n"
        f"Line 3+: the translation. Start with the subject as a bold line. {_HTML_RULES}\n\n"
        f"Subject: {subject}\n\nBody:\n{body}"
    )
    try:
        raw = chat([{"role": "user", "content": prompt}])
    except Exception as e:
        print(f"  ⚠️  translate failed ({type(e).__name__}); posting original text")
        return f"<b>{subject}</b>\n\n{body}"
    head, _, rest = raw.partition("\n\n")
    head, rest = head.strip(), rest.strip()
    if head.upper().startswith(("⚠️ ACTION", "ACTION")):
        head = head if head.startswith("⚠️") else "⚠️ " + head
        return f"<b>{head}</b>\n\n{rest}" if rest else f"<b>{head}</b>"
    return rest if head == "INFO" and rest else raw


def translate_diary(text):
    """Diary entry → English Telegram HTML. The caller adds the date/child header."""
    try:
        return chat(
            [
                {"role": "system", "content": "Translate Estonian to English. Output only the translation."},
                {"role": "user", "content": f"Kindergarten diary entry, format for Telegram. {_HTML_RULES}\n\n{text}"},
            ],
            max_tokens=800,
        )
    except Exception as e:
        print(f"  ⚠️  translate failed ({type(e).__name__}); posting original text")
        return text


def describe_album(thumb_urls):
    """One short sentence about a set of photos, from ONE vision call on up to 4 small
    thumbnails. Replaces the old per-photo calls (up to 40+ per entry). "" on failure."""
    urls = [u for u in thumb_urls if u][:4]
    if not urls:
        return ""
    content = [{"type": "text", "text": "In one short sentence (max 15 words), what are the children doing in these kindergarten photos? Output only the sentence."}]
    content += [{"type": "image_url", "image_url": {"url": u, "detail": "low"}} for u in urls]
    try:
        return chat([{"role": "user", "content": content}], max_tokens=40).strip().rstrip(".")
    except Exception as e:
        print(f"  ⚠️  describe_album failed ({type(e).__name__})")
        return ""


def strip_html(html):
    if not html:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", html)
    text = re.sub(r"</?p[^>]*>", "\n", text)
    text = re.sub(r"<li[^>]*>", "• ", text)
    text = re.sub(r"</li>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\n{3,}", "\n\n", text).strip()
