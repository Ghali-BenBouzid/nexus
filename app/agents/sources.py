"""The turn's source registry: who owns citation numbers.

Every retrieval tool registers what it retrieved here and hands the agent the
numbers back. An agent can only cite a number the registry issued, so a citation
always points at a page that was really fetched, whoever fetched it: the
supervisor answering inline, a researcher inside a sub-agent, or the fact
checker. One registry per turn means one numbering across all of them, which is
why consolidating findings no longer has to renumber anything.
"""

from app.agents.schemas import Source


class Sources:
    def __init__(self) -> None:
        self._numbers: dict[str, int] = {}  # url -> 1-based citation number
        self.all: list[Source] = []

    def register(self, sources: list[Source]) -> list[int]:
        """Record these sources and return their citation numbers, in order. A
        URL seen before keeps the number it already has."""
        return [self._number(source) for source in sources]

    def _number(self, source: Source) -> int:
        number = self._numbers.get(source.url)
        if number is None:
            self.all.append(source)
            number = len(self.all)
            self._numbers[source.url] = number
        return number

    def valid(self, ids: list[int]) -> list[int]:
        """The ids that name a real source, deduped and in order. A model that
        invents a number loses it here rather than in the report."""
        kept: list[int] = []
        for number in ids:
            if 1 <= number <= len(self.all) and number not in kept:
                kept.append(number)
        return kept

    def legend(self, ids: list[int]) -> str:
        """The lines an agent cites from: one per source, with its number."""
        return "\n".join(
            f"[{n}] {self.all[n - 1].title} ({self.all[n - 1].url})" for n in ids
        )

    def __len__(self) -> int:
        return len(self.all)
