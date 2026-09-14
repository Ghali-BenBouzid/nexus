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
    "edge",
    "compound",
}


def test_golden_set_loads_and_covers_the_use_cases() -> None:
    goldens = load_goldens()
    categories = Counter(g.category for g in goldens)

    # ~150 so a change of a few points between two runs is signal, not noise.
    assert len(goldens) >= 150
    assert REQUIRED_CATEGORIES <= set(categories)
    assert min(categories.values()) >= 4  # a per-category mean needs a few runs
    assert categories["owner"] >= 8  # the "who is Ghali?" pattern seen in testing
    assert categories["app"] >= 8
    assert sum(g.time_sensitive for g in goldens) >= 30
    assert {g.language for g in goldens} >= {"English", "French"}


def test_every_golden_says_what_good_looks_like() -> None:
    for golden in load_goldens():
        assert golden.input.strip(), golden.id
        assert len(golden.expected_behavior) > 20, golden.id
