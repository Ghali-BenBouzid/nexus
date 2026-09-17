"""Template pieces more than one prompt uses. A change here changes the text of
every prompt that includes it, so each of them needs a version bump."""

from datetime import UTC, datetime

# Filled with the language detected on the text the agent works on, or empty when
# detection is inconclusive (the prompt's own "same language" rule then governs).
# Why name it instead of "match the user": see app/agents/language.py.
LANGUAGE = (
    "{{#language}}\n\nIMPORTANT: Write your entire response in {{{language}}}. "
    "Every part of your output must be in {{{language}}}, regardless of the "
    "language of these instructions.{{/language}}"
)


def today() -> str:
    """Today's date (UTC) as the prompts' ``today`` variable, e.g. "Thursday,
    September 17, 2026". Models don't know the date, and without it they treat
    their training cutoff as the present."""
    return datetime.now(UTC).strftime("%A, %B %d, %Y")
