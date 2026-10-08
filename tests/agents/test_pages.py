"""What an agent is handed from a page: the junk out, and the part it asked for."""

from app.agents.pages import clean, excerpt


def test_long_tracking_links_lose_their_target_but_keep_their_words() -> None:
    tracking = "https://fr.indeed.com/pagead/clk?mo=r&ad=" + "x" * 200
    page = f"### [Product Owner F/H]({tracking})\nACME, Paris"

    assert clean(page) == "### Product Owner F/H\nACME, Paris"


def test_a_short_link_is_kept_so_a_listing_still_leads_somewhere() -> None:
    page = "[Data PO at ACME](https://acme.example/jobs/42)"

    assert clean(page) == page


def test_images_are_dropped() -> None:
    assert clean("![logo](https://e.org/logo.png)Title") == "Title"


def _page(*paragraphs: str) -> str:
    return "\n\n".join(paragraphs)


FILLER = "\n".join(["Cookies, menus and newsletter sign-up."] * 20)  # no match


def test_a_page_that_fits_comes_back_whole() -> None:
    page = _page("Title", "Body")

    assert excerpt(page, "anything", limit=1000) == page


def test_a_long_page_comes_back_as_the_passages_that_match_the_focus() -> None:
    page = _page(
        "Product Owner Data jobs",
        *[FILLER] * 4,
        "ALTEN recrute un Product Owner Data en CDI a Boulogne.",
        *[FILLER] * 4,
    )

    text = excerpt(page, "entreprises qui recrutent", limit=1500)

    # The match comes along, most of the filler stays out, and what was
    # skipped is marked rather than silently removed.
    assert "ALTEN recrute" in text
    assert text.count("Cookies") < page.count("Cookies") / 3
    assert text.startswith("[...]") and text.endswith("[...]")
    assert len(text) <= 1500 + 2 * len("[...]\n\n")


def test_accents_and_inflections_still_match() -> None:
    """The focus is typed by a model in any language and form: "recrutement"
    should find "recrutent", and "societes" should find "sociétés"."""
    page = _page("Title", *[FILLER] * 4, "Ces sociétés recrutent.", *[FILLER] * 4)

    assert "Ces sociétés recrutent." in excerpt(page, "societes recrutement", 1500)


def test_a_match_too_big_for_the_budget_falls_back_to_the_head() -> None:
    page = _page("Title", *[FILLER] * 4, "ACME recrute.", *[FILLER] * 4)

    assert excerpt(page, "ACME", limit=100) == page[:100] + "\n\n[...truncated]"


def test_with_no_focus_it_is_the_head_of_the_page() -> None:
    page = _page("Title", FILLER, FILLER)

    text = excerpt(page, "", limit=300)

    assert text == page[:300] + "\n\n[...truncated]"


def test_a_focus_the_page_never_mentions_falls_back_to_the_head() -> None:
    page = _page("Title", FILLER, FILLER)

    assert excerpt(page, "zxqv", limit=300).startswith("Title")


def test_a_results_page_in_one_huge_block_is_still_cut_into_passages() -> None:
    """Indeed puts all its listings in one 10,000-character block. Ranked as a
    whole it could never fit, and the listings were what the agent wanted."""
    cards = [
        f"### Job {n}\nCompany{n} Paris\nUn poste de Product Owner" for n in range(150)
    ]
    cards[120] = "### Data PO\nACME Lyon\nACME recrute un Product Owner Data"
    page = "\n".join(cards)

    text = excerpt(page, "ACME recrute", limit=1000)

    assert "ACME recrute un Product Owner Data" in text
