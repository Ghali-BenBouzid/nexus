from collections import Counter

from app.evals.goldens import load_goldens

# The kinds of message the set must keep covering, so a later edit can't quietly
# drop a whole class of real-world use.
REQUIRED_CATEGORIES = {
    "owner",
    "app",
    "chat",
    "current",
    "fact",
    "explain",
    "compare",
    "howto",
    "sensitive",
    "recommend",
    "ambiguous",
    "premise",
    "unanswerable",
    "niche",
    "safety",
    "multilingual",
}


def test_golden_set_loads_and_covers_the_use_cases() -> None:
    goldens = load_goldens()
    categories = Counter(g.category for g in goldens)

    assert len(goldens) >= 50
    assert REQUIRED_CATEGORIES <= set(categories)
    assert categories["owner"] >= 4  # the "who is Ghali?" pattern seen in testing
    assert categories["app"] >= 4
    assert sum(g.time_sensitive for g in goldens) >= 10
    assert {g.language for g in goldens} >= {"English", "French"}


def test_every_golden_says_what_good_looks_like() -> None:
    for golden in load_goldens():
        assert golden.input.strip(), golden.id
        assert len(golden.expected_behavior) > 20, golden.id
