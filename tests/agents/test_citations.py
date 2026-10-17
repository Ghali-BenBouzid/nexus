from app.agents.citations import finalize
from app.agents.schemas import Source

ONE = [Source(title="A", url="https://a.example")]


def test_a_stripped_marker_takes_its_space_with_it() -> None:
    """A follow-up can cite a source from an earlier turn, which this turn does
    not have. Dropping the marker alone left "predicted ." on the page."""
    content, _, stripped = finalize("sooner than theory predicted [3].", ONE)
    assert content == "sooner than theory predicted."
    assert stripped == [3]


def test_a_stripped_marker_mid_sentence_leaves_one_space() -> None:
    content, _, _ = finalize("grew [7] far sooner [1].", ONE)
    assert content == "grew far sooner [1]."


def test_a_stripped_marker_never_joins_two_lines() -> None:
    content, _, _ = finalize("First point.\n[9] Second point [1].", ONE)
    assert content == "First point.\n Second point [1]."


def test_a_backed_marker_keeps_its_space() -> None:
    content, kept, stripped = finalize("as measured [1].", ONE)
    assert content == "as measured [1]."
    assert kept == ONE
    assert stripped == []
