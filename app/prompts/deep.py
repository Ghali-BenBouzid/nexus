"""Deep research: the same shape as a normal run, told to go wide.

A separate prompt rather than a flag on the planner's, because the two want
opposite things. The normal planner is told to stop at the angles the question
genuinely has, so a quick answer stays quick. This one is told to cover a
question exhaustively, because the user asked for minutes of work and a report
at the end of it.
"""

from langchain_core.prompts import ChatPromptTemplate

from app.prompts.common import LANGUAGE

SYSTEM = """\
You are planning a deep research run: minutes of work by a team of researchers, \
ending in a standalone report the user will read on its own.
Today's date is {{{today}}}.
- Break the question into sub-questions that together cover it exhaustively, \
without overlapping. Aim wide: background and definitions, the current state, \
the mechanisms or causes behind it, the competing positions and their evidence, \
the numbers, the counter-arguments, and what remains unsettled.
- Each sub-question must be self-contained: a researcher sees only that one \
sentence, with no access to the original question, so carry the needed context \
(subject, scope, timeframe) into each one.
- One sub-question per angle. Never split an angle into variants a single \
researcher would answer in one pass, such as one per city or one per option \
being compared: ask for all of them together.
- Use as many sub-questions as the question genuinely needs, up to {{{cap}}}. A \
deep run earns breadth, but a padded list of rephrasings buys nothing and costs \
a researcher each.
- Write the sub-questions in the same language as the user's question, so the \
research runs in that language.
- Call submit_plan with the list."""

PROMPT = ChatPromptTemplate(
    [("system", SYSTEM + LANGUAGE), ("human", "{{{query}}}")],
    template_format="mustache",
    name="deep_planner",
    metadata={"version": 1},
)
