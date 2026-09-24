"""Detect the user's language and pin each agent to it explicitly.

Small models follow an explicit "write in X" instruction far more reliably than a
soft "match the user's language", and naming the language that was actually
detected avoids a subtle failure: a fixed example in a prompt ("if French, write
in French") primes a small model toward that example language even for an English
query. So the prompts stay language-neutral and the concrete language fills their
``language`` variable, per request, from the text the agent is actually working on
(the wording lives in app/prompts/common.py).
"""

import re
from collections import Counter

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


# The small words a sentence cannot do without, per language. On a short query
# langdetect guesses from letter patterns, and names pull it off course at full
# confidence: "compare morroco's economy to algeria's" came back Italian, and
# every agent, down to the step titles, was told to write in Italian. The "to"
# in it settles the matter, which is how a short text is read reliably.
# ponytail: Latin-script languages only; other scripts are not confused by
# names, and langdetect reads them well.
_FUNCTION_WORDS = {
    "English": "the of to and is are was what how why who which does do can in "
    "on for with this that it my your about between from should would you i",
    "French": "le la les des du de un une et est sont qui que qu quoi comment "
    "pourquoi quel quelle quels quelles pour avec dans sur ce cette ces mon ma "
    "mes je tu vous nous il elle au aux l d c j n pas entre ou",
    "Spanish": "el la los las del de y es son qué que cómo por para con una uno "
    "en un cuál entre",
    "German": "der die das und ist sind wie was warum wer ein eine mit für von "
    "zu im den dem nicht ich sie",
    "Italian": "il lo gli la della dello dell dei di del nel e è sono che come "
    "perché chi cosa un una per con l tra",
    "Portuguese": "o os as do da dos das e é são que como por para com um uma "
    "em no na entre",
    "Dutch": "de het een en is zijn wat hoe waarom wie van voor met niet op dat dit ik",
}
_WORDS = {language: set(words.split()) for language, words in _FUNCTION_WORDS.items()}


def _by_function_words(text: str) -> str | None:
    """The language whose function words the text uses most, or None when
    it uses none or two languages tie."""
    votes: Counter[str] = Counter()
    for word in re.findall(r"[^\W\d_]+", text.lower()):
        for language, words in _WORDS.items():
            if word in words:
                votes[language] += 1
    ranked = votes.most_common(2)
    if not ranked or (len(ranked) == 2 and ranked[0][1] == ranked[1][1]):
        return None
    return ranked[0][0]


def detect_language(text: str) -> str | None:
    """Best-effort language name for ``text``, or None when it is too short, the
    detection is not confident or the language is unrecognized. Never raises.

    Function words decide when they point one way: they are what makes a short
    query readable at all. langdetect answers the rest, other scripts and text
    with no telling small words."""
    text = (text or "").strip()
    if len(text) < _MIN_CHARS:
        return None
    return _by_function_words(text) or _by_letters(text)


def _by_letters(text: str) -> str | None:
    try:
        # Shouting is lowercased: all-caps English reads as German. Only shouting,
        # since German capitalizes its nouns and lowercased German reads as Dutch.
        best = detect_langs(text.lower() if text.isupper() else text)[0]
    except LangDetectException:
        return None
    if best.prob < _MIN_CONFIDENCE:
        return None
    return _LANGUAGE_NAMES.get(best.lang)
