from app.agents.language import detect_language


def test_detects_english() -> None:
    text = "How are small language models changing on-device AI in 2026?"
    assert detect_language(text) == "English"


def test_detects_french() -> None:
    text = "Comment les petits modèles de langage transforment-ils l'IA embarquée ?"
    assert detect_language(text) == "French"


def test_detects_german_nouns_intact() -> None:
    assert detect_language("Wer hat den Ballon d'Or gewonnen?") != "Dutch"
    assert detect_language("Wie funktioniert das deutsche Rentensystem?") == "German"


def test_short_text_is_inconclusive() -> None:
    # Too short to detect reliably, so we abstain rather than guess.
    assert detect_language("hi") is None
    assert detect_language("") is None


def test_names_and_casing_do_not_fool_detection() -> None:
    # Each of these used to pin every agent to the wrong language (Dutch, German,
    # Somali, Finnish, German), so "Who is Ghali Ben Bouzid?" came back as a German
    # report. Abstaining is fine: the agent then matches the user's language itself.
    expected = {
        "Who is Ghali Ben Bouzid?": "English",
        "Qui est Ghali Ben Bouzid ?": "French",
        "Who is Ghali?": "English",
        "Tell me a joke": "English",
        "WHY IS MY INTERNET SO SLOW EVERY EVENING???": "English",
    }
    for text, language in expected.items():
        assert detect_language(text) in (None, language), text
    assert detect_language("WHY IS MY INTERNET SO SLOW EVERY EVENING???") == "English"


def test_gibberish_is_inconclusive() -> None:
    assert detect_language("asdkjh qwpoeiru zmxncb") is None

