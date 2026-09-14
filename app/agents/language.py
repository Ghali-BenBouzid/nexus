"""Detect the user's language and pin each agent to it explicitly.

Small models follow an explicit "write in X" instruction far more reliably than a
soft "match the user's language", and naming the language that was actually
detected avoids a subtle failure: a fixed example in a prompt ("if French, write
in French") primes a small model toward that example language even for an English
query. So the prompts stay language-neutral and the concrete language is injected
here, per request, from the text the agent is actually working on.
"""

from langdetect import DetectorFactory, LangDetectException, detect_langs

# langdetect samples internally, so the same text can yield different codes across
# runs. Seeding the factory makes detection deterministic (important for tests and
# reproducibility).
DetectorFactory.seed = 0

# langdetect votes over seven seeded samples, so its confidence moves in sevenths:
# text it actually recognizes gets six or seven votes. Its misfires on short text
# full of names ("Who is Ghali Ben Bouzid?" -> Dutch at 5/7, "Qui est Ghali Ben
# Bouzid ?" -> German at 4/7) come in lower, and a wrong directive is worse than
# none: every agent was told to write in Dutch.
_MIN_CONFIDENCE = 0.8

# langdetect ISO codes -> the language name we put in the instruction. Limited to
# languages a user is plausibly querying in; an unmapped code yields no directive,
# so the agent falls back to its neutral "same language as the user" instruction.
_LANGUAGE_NAMES = {
    "en": "English",
    "fr": "French",
    "es": "Spanish",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "ru": "Russian",
    "ar": "Arabic",
    "tr": "Turkish",
    "pl": "Polish",
    "ja": "Japanese",
    "ko": "Korean",
    "zh-cn": "Chinese",
    "zh-tw": "Chinese",
}

# Below this many characters detection is too unreliable to trust, so we abstain.
_MIN_CHARS = 12


def detect_language(text: str) -> str | None:
    """Best-effort language name for ``text``, or None when it is too short, the
    detection is not confident or the language is unrecognized. Never raises."""
    text = (text or "").strip()
    if len(text) < _MIN_CHARS:
        return None
    try:
        # Shouting is lowercased: all-caps English reads as German. Only shouting,
        # since German capitalizes its nouns and lowercased German reads as Dutch.
        best = detect_langs(text.lower() if text.isupper() else text)[0]
    except LangDetectException:
        return None
    if best.prob < _MIN_CONFIDENCE:
        return None
    return _LANGUAGE_NAMES.get(best.lang)


def language_directive(text: str) -> str:
    """A system-prompt suffix pinning the response to ``text``'s language, or an
    empty string when detection is inconclusive (the agent's neutral instruction
    then governs). Appended to an agent's system prompt."""
    name = detect_language(text)
    if not name:
        return ""
    return (
        f"\n\nIMPORTANT: Write your entire response in {name}. Every part of your "
        f"output must be in {name}, regardless of the language of these instructions."
    )
