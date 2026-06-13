from app.agents.language import detect_language, language_directive


def test_detects_english() -> None:
    text = "How are small language models changing on-device AI in 2026?"
    assert detect_language(text) == "English"


def test_detects_french() -> None:
    text = "Comment les petits modeles de langage transforment-ils l'IA embarquee ?"
    assert detect_language(text) == "French"


def test_short_text_is_inconclusive() -> None:
    # Too short to detect reliably, so we abstain rather than guess.
    assert detect_language("hi") is None
    assert detect_language("") is None


def test_directive_names_the_detected_language() -> None:
    directive = language_directive(
        "How are small language models changing on-device AI in 2026?"
    )
    assert "English" in directive
    # The neutralized prompts must not name a language; the directive supplies the
    # concrete one, so a French query never gets an English directive.
    fr = language_directive(
        "Comment les petits modeles de langage transforment-ils l'IA embarquee ?"
    )
    assert "French" in fr
    assert "English" not in fr


def test_directive_empty_when_inconclusive() -> None:
    # No directive for short text, so the agent's neutral instruction governs.
    assert language_directive("hi") == ""


def test_prompts_do_not_name_a_specific_language() -> None:
    # The fixed-example wording ("if French, write in French") primed small models
    # toward that language; detection replaced it, so it must not creep back in.
    from app.agents import planner, researcher, writer

    assert "French" not in researcher._SYSTEM_PROMPT
    assert "French" not in planner._system_prompt(3)
    assert "French" not in writer._SYSTEM_PROMPT_TEMPLATE
