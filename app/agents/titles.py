"""Short titles for the supervisor's thinking, for the live feed.

The model's reasoning is a scratchpad: long, half-formed, and fast. Streaming it
raw is what made the feed scroll too fast to read. The large chat products show
a summary instead, written by a smaller model (Anthropic and OpenAI both do), and
this is that: each stretch of thinking becomes one step in the feed, and a small,
cheap model names it in a few words ("Weighing the running costs").

A step is one model call's thinking, keyed by the id its streamed chunks share.
The step itself is announced the moment it starts, so it lands in the feed in
order, ahead of the tool calls it leads to; its title follows about a second
later, without holding anything up. A long stretch is renamed as it goes, so the
title keeps up with what the model is actually doing.
"""

import asyncio
import logging
import re
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.model import PacedChatOpenAI
from app.agents.schemas import AgentEvent
from app.core.config import settings

logger = logging.getLogger(__name__)

# Characters of new thinking before a step is (re)named. The first title comes
# early so a step is not "Thinking" for long; later ones are spaced out so a long
# stretch is renamed every few seconds, not every sentence.
FIRST_TITLE_AT = 160
RETITLE_EVERY = 3_000
# What the titler reads: the latest stretch is what the title should describe.
WINDOW = 2_000
# How long a finished turn waits for titles still being written.
CLOSE_TIMEOUT = 5.0

PROMPT = (
    "You title one step in an AI assistant's live progress feed. Read the "
    "assistant's private reasoning and reply with ONE title of 3 to 6 words "
    "saying what it is doing right now. Start with a verb in -ing form. Write in "
    "sentence case: only the first word and proper nouns start with a capital "
    "letter. Write it in {language}. No quotes, no final period, nothing else.\n\n"
    "Good titles: Weighing the running costs / Checking Daikin's datasheets / "
    "Planning two research teams / Comparing prices in France"
)

# French titles read naturally as noun phrases ("Comparaison des prix"), and a
# small model asked for them in English writes participles ("Comparant les
# prix") however it is told. Asked in French, it writes them right.
PROMPT_FR = (
    "Tu donnes un titre à une étape du fil de progression d'un assistant IA. "
    "Lis le raisonnement privé de l'assistant et réponds par UN seul titre en "
    "français, de 3 à 6 mots, qui dit ce qu'il fait en ce moment. Un groupe "
    "nominal, jamais un participe présent. Majuscule au premier mot et aux noms "
    "propres seulement. Pas de guillemets, pas de point final, rien d'autre.\n\n"
    "Bons titres : Comparaison des coûts de fonctionnement / Vérification des "
    "fiches Daikin / Préparation de deux équipes de recherche / Rédaction de la "
    "réponse"
)


def step_titles(
    model: BaseChatModel, emit, language: str | None
) -> "StepTitles | None":
    """The titler for a turn on ``model``, or None when titles are switched off.

    The titler is a copy of the turn's own model with another name, so it keeps
    the model's billing callbacks: a title is billed to the same account as the
    turn it names. It runs unpaced and without the reasoning settings, which are
    the main model's and would only slow a four-word answer down.
    """
    name = settings.step_title_model
    if not name or not isinstance(model, PacedChatOpenAI):
        return None
    titler = model.model_copy(
        update={
            "model_name": name,
            "extra_body": None,
            "pacing": None,
            "max_tokens": 24,
            "temperature": 0.2,
            "streaming": False,
        }
    )
    return StepTitles(titler, emit, language)


class StepTitles:
    def __init__(self, model: BaseChatModel, emit, language: str | None) -> None:
        self.model = model
        self.emit = emit
        self.prompt = (
            PROMPT_FR
            if language == "French"
            else PROMPT.format(
                language=language or "the language the reasoning is about"
            )
        )
        self.step = 0
        self.key: Any = None
        self.text = ""
        self.named_at = 0  # len(self.text) when the last title was asked for
        self.pending: set[asyncio.Task] = set()
        self.naming = False  # one title in flight per step, at most

    async def think(self, key: Any, text: str) -> None:
        """More reasoning from the call ``key``: a new key starts a new step."""
        if key != self.key:
            await self.end()
            self.key = key
            self.step += 1
            await self.emit(
                AgentEvent(
                    type="step",
                    message="Thinking",
                    data={"agent": "supervisor", "step": self.step},
                )
            )
        self.text += text
        due = FIRST_TITLE_AT if self.named_at == 0 else self.named_at + RETITLE_EVERY
        if not self.naming and len(self.text) >= due:
            self._name()

    async def end(self) -> None:
        """The step's thinking is over: name what is left, if it said more."""
        if self.key is not None and len(self.text) > self.named_at:
            if self.named_at == 0 or len(self.text) - self.named_at >= FIRST_TITLE_AT:
                self._name()
        self.key = None
        self.text = ""
        self.named_at = 0
        self.naming = False

    async def close(self) -> None:
        """The turn is over: wait, briefly, for the titles still on their way."""
        await self.end()
        if self.pending:
            await asyncio.wait(self.pending, timeout=CLOSE_TIMEOUT)

    def cancel(self) -> None:
        for task in self.pending:
            task.cancel()

    def _name(self) -> None:
        self.named_at = len(self.text)
        self.naming = True
        task = asyncio.create_task(
            self._title(self.step, self.text[-WINDOW:], self.key)
        )
        self.pending.add(task)
        task.add_done_callback(self.pending.discard)

    async def _title(self, step: int, reasoning: str, key: Any) -> None:
        try:
            reply = await self.model.ainvoke(
                [
                    SystemMessage(self.prompt),
                    HumanMessage(reasoning),
                ]
            )
            title = clean(reply.text, reasoning)
            if title:
                await self.emit(
                    AgentEvent(
                        type="step_title",
                        message=title,
                        data={"agent": "supervisor", "step": step},
                    )
                )
        except Exception:  # noqa: BLE001 -- a missing title is a generic step, not a failed turn
            logger.warning("could not title step %s", step, exc_info=True)
        finally:
            if key == self.key:
                self.naming = False


def clean(text: str, reasoning: str = "") -> str:
    """One short line, without the quotes and full stop small models add, and
    in sentence case, which the small model forgets about one time in three."""
    line = text.strip().splitlines()[0] if text.strip() else ""
    line = line.strip().strip("\"'*`“”«» ").rstrip(".").strip()
    return sentence_case(line, reasoning)[:80]


def sentence_case(title: str, reasoning: str) -> str:
    """Lower every capital after the first word, unless the reasoning writes
    that word capitalised too. A proper noun (Daikin, Mitsubishi) is spelled that
    way wherever the model uses it; "Specs" in "Reviewing Mitsubishi's Specs" is
    not, so only the title's own capital is dropped. Acronyms (COP, PAC) and
    names with capitals inside (MaPrimeRénov') are left alone. Words after an
    apostrophe or a hyphen count ("d'Installation", "air-Eau")."""

    def fix(match: re.Match) -> str:
        word = match.group(0)
        if sum(c.isupper() for c in word) > 1 or re.search(
            rf"(?<!\w){re.escape(word)}(?!\w)", reasoning
        ):
            return word
        return word[0].lower() + word[1:]

    return re.sub(r"(?<=[\s'’-])[^\W\d_]\w*", fix, title)
