# ask_user, the brainstorm, and deeper runs: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The supervisor asks questions through a docked option panel, brainstorms a structured brief before every deep run, and deep runs go measurably deeper.

**Architecture:** `ask_user` is a supervisor tool with `return_direct=True`: its call ends the turn, and the questions ride on the turn's `Answer` into a nullable JSON column `messages.ask`.
The user's answers come back as an ordinary message whose `ask` holds the answered pairs and whose `content` is the formatted text the model reads.
Depth floors are errors returned by the tools the agents already call (`submit_finding`, `write_report`); the deep writer gets its own length target.

**Tech Stack:** FastAPI, SQLAlchemy + Alembic, LangChain `create_agent`, LangGraph, React + TypeScript, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-25-ask-user-and-deeper-runs-design.md`

## Global Constraints

- No em dash anywhere in code, comments, copy or commits.
- No AI attribution in commits.
- Limits live inside tools, as errors or warnings the agent reads; nothing in code counts panels, orders brainstorm steps or ends a brainstorm.
- `ask_user`: 1 to 4 questions, 2 to 4 options each; "Something else" and Skip belong to the interface.
- Prompt versions bump on every prompt change, then `uv run python -m app.prompts` relocks `app/prompts/versions.lock`.
- Restore `frontend/tsconfig.tsbuildinfo` after a build.
- One runnable check per non-trivial piece of logic; `ponytail:` comments on deliberate simplifications.

## Review Focus

- An `ask_user` call with no text beside it: the turn must still store the questions and replay them in history (content empty is not "nothing said"). Test in Task 2.
- `ask_user` called in the same step as another tool: `return_direct` ends the turn; the other tool's result is dropped. The tool description says to call it alone, last; a test pins that the questions still land. Task 1.
- Every question skipped: the answer message must still send, reading "(skipped)" for each. Task 3 (backend format) and Task 6 (frontend).
- Crawl4AI down in a deep run: `fetch_page` fails every time; the researcher floor counts reads attempted, so it cannot trap a researcher. Task 4.
- A reload while the panel is open, or after it was dismissed: open comes back from the thread; dismissal is per page view only. Task 6.

---

### Task 1: ask_user in the supervisor

**Files:**
- Modify: `app/agents/supervisor.py` (schemas, `_tools`, `respond`, `_last_text`, `Answer`)
- Modify: `app/agents/schemas.py` (`Turn.ask`)
- Test: `tests/agents/test_ask_user.py`

**Interfaces:**
- Produces: `AskQuestion(question: str, options: list[str])`, `AskUserArgs(questions: list[AskQuestion])`, `Answer.ask: list[dict] | None`, `Turn.ask: list[dict] | None`.

- [ ] **Step 1: Failing tests.** With `ScriptedModel` (as in `tests/agents/test_supervisor.py`): (a) a model that writes "Two quick questions." and calls `ask_user` in the same message ends the turn with `answer.text == "Two quick questions."` and `answer.ask == [{"question": ..., "options": [...]}]`, and makes no second model call; (b) a call with one option comes back as a tool error and the model's retry is accepted; (c) an `ask_user` with empty content still returns the questions.
- [ ] **Step 2: Run** `uv run pytest tests/agents/test_ask_user.py -v`; expect failures (no tool).
- [ ] **Step 3: Implement.**

```python
class AskQuestion(BaseModel):
    question: str = Field(description="One short question, in the user's language")
    options: list[str] = Field(
        min_length=2, max_length=4,
        description="2 to 4 short answers built from this conversation. The "
        "interface adds 'Something else' and Skip: never write those.",
    )


class AskUserArgs(BaseModel):
    questions: list[AskQuestion] = Field(min_length=1, max_length=4)
```

In `_tools`, an `asked: list[dict]` holder passed in from `respond`; the tool stores `[q.model_dump() for q in questions]` and returns "Shown to the user. Stop here; their answer comes as their next message." Registered with `return_direct=True` and a description saying to call it alone, as the last step, after writing the reply text.
`_last_text`: when the final message is a `ToolMessage` named `ask_user`, the reply is the text of the `AIMessage` before it.
`respond` returns `Answer(text, sources, ask=asked or None)`.
If validation errors are not fed back by the ToolNode by default, set `handle_tool_errors` accordingly and keep test (b) as the proof.
- [ ] **Step 4: Run** the new tests and `tests/agents/test_supervisor.py`; expect pass.
- [ ] **Step 5: Commit** `feat(supervisor): an ask_user tool that ends the turn with questions`.

### Task 2: storing and replaying a question

**Files:**
- Create: `alembic/versions/f6a7b8c9d0e4_messages_carry_questions.py`
- Modify: `app/models/conversation.py` (`Message.ask`), `app/conversations/repository.py` (`set_content(..., ask=None)`, `add_message(..., ask=None)`, `ask_for_query`), `app/conversations/service.py` (`_history`, `route_message`), `app/agents/supervisor.py` (`_conversation`), `app/conversations/schemas.py` (`MessageResponse.ask`), `app/conversations/router.py`, `app/research/schemas.py` + `app/research/router.py` (`QueryDetail.ask`)
- Test: `tests/conversations/test_ask.py`

- [ ] **Step 1: Failing tests.** Through the API with a scripted supervisor that asks: the conversation detail's assistant message carries `ask`; `GET /research/query/{id}` carries the same `ask`; the next turn's model input contains the questions with numbered options after the assistant text, including when that text is empty.
- [ ] **Step 2: Run**; expect failures.
- [ ] **Step 3: Implement.** Column `ask: Mapped[list | None] = mapped_column(JSONB().with_variant(JSON(), "sqlite"), nullable=True)`; migration adds and drops it. `route_message` saves `answer.ask` with the content. `_history` keeps a message with `ask` even when its content is empty, and `Turn` carries it. `_conversation` renders an assistant turn with `ask` as its text plus:

```
(You asked, with these options:)
1. Which topic?
   1) History  2) Science
```

- [ ] **Step 4: Run** the tests, then `uv run alembic upgrade head` locally; expect pass.
- [ ] **Step 5: Commit** `feat(conversations): a question the supervisor asked is stored and replayed`.

### Task 3: answering through the panel, server side

**Files:**
- Modify: `app/conversations/schemas.py` (`Answered`, `MessageCreate.answers`), `app/conversations/service.py` (`submit_message(..., answers=None)`, `format_answers`), `app/conversations/router.py`
- Test: `tests/conversations/test_ask.py`

- [ ] **Step 1: Failing tests.** `format_answers([{"question": "Which topic?", "answer": "History"}, {"question": "How hard?", "answer": None}])` gives `"Which topic?\n→ History\n\nHow hard?\n→ (skipped)"`; posting `{"content": "", "answers": [...], "mode": "deep"}` stores a user message with that content and `ask` equal to the pairs, and the supervisor receives the formatted text as the message.
- [ ] **Step 2-4:** run, implement (the server builds `content` from `answers`, ignoring any client text), run.
- [ ] **Step 5: Commit** `feat(conversations): answers from the question panel arrive as one message`.

### Task 4: depth floors in the tools

**Files:**
- Modify: `app/agents/research.py` (`Limits.min_pages`: deep 2, normal 0), `app/agents/tools.py` (`retrieval_tools` counts reads), `app/agents/researcher.py` (a per-researcher submit schema with the floor), `app/agents/deep.py` (`_why` with the lead floor), `app/core/config.py` (`deep_min_pages = 2`, `deep_min_rounds = 2`)
- Test: `tests/agents/test_researcher.py`, `tests/agents/test_deep.py`

- [ ] **Step 1: Failing tests.** A deep researcher that submits `found_info=true` after 0 reads gets the floor's error back and submits again after reading; `found_info=false` passes at once; the normal researcher is unaffected. `_why(WriteReportArgs, cap, first=False, final=False, rounds=1)` returns the floor message; with `rounds=2` it returns None; with `final=True` it returns None.
- [ ] **Step 2: Run**; expect failures.
- [ ] **Step 3: Implement.** The floor lives in validation of the submit tool, which `ToolStrategy(handle_errors=...)` already feeds back:

```python
def _submit_schema(read: Callable[[], int], least: int) -> type[SubmitFindingArgs]:
    if not least:
        return SubmitFindingArgs

    class Submit(SubmitFindingArgs):
        model_config = ConfigDict(title="SubmitFindingArgs")

        @model_validator(mode="after")
        def _read_enough(self):
            if self.found_info and read() < least:
                raise ValueError(
                    f"Read at least {least} of the most relevant pages in full "
                    "with fetch_page before submitting: claims from search "
                    "snippets are too thin for a deep report. If nothing "
                    "relevant exists, submit with found_info=false."
                )
            return self

    return Submit
```

The count is `fetch_page` calls made, not pages that loaded (`# ponytail:` a broken crawler must not trap a researcher; LastStep and the forced finish still collect).
Lead: `_why` gains `rounds: int`; a `WriteReportArgs` with `0 < rounds < settings.deep_min_rounds` and not final returns the floor message (the prompt's thin / disagreement / weak-source checklist, asking for a narrower round).
- [ ] **Step 4: Run** `uv run pytest tests/agents -q`; expect pass.
- [ ] **Step 5: Commit** `fix(deep): researchers read before they submit, and the lead looks twice`.

### Task 5: the brief, the brainstorm and the length

**Files:**
- Modify: `app/agents/supervisor.py` (`DeepBrief`, `DeepResearchArgs.brief`, `render_brief`, `_DEEP_MODE`), `app/conversations/service.py` (`_deep_starter`), `app/prompts/supervisor.py` (ask_user bullet, v12), `app/prompts/deep.py` (brief block, outline is structure only, v6), `app/prompts/report.py` (`{{#length}}` block, v2), `app/agents/report.py` (`length=`), `app/agents/deep.py` (`write_node` passes a length), `app/prompts/versions.lock`
- Test: `tests/agents/test_supervisor.py`, `tests/conversations/test_background_runs.py`, `tests/agents/test_claim_check.py`, `tests/agents/test_report.py`

- [ ] **Step 1: Failing tests.** `render_brief(DeepBrief(goal="...", focus=["a","b"], ...))` renders labelled lines and skips empty fields; the stored deep prompt contains the question then the brief block; `deep_length(claims=14) == 1000` and `deep_length(claims=80) == 4500` (70 words per claim, clamped 1000 to 4500); the writer's messages carry the length only when given.
- [ ] **Step 2: Run**; expect failures.
- [ ] **Step 3: Implement.** `DeepBrief` fields: `goal: str`, `reader: str = ""`, `focus: list[str] = []`, `open: list[str] = []`, `decided: list[str] = []`, `out_of_scope: list[str] = []`, `constraints: str = ""`, `shape: str = ""`. Update the three test helpers that pass `goal=` to pass `brief=`. Rewrite `_DEEP_MODE` with a `<brainstorm>` section per the spec: goal panel, a panel generated from the goal, then the confirmation; a third panel only for a real fork; go back when the user changes their mind; options from this subject and from the people who care about it; "Decide for me" last; web_search allowed without citations; never start before the user confirms. Remove the lead prompt's length sentences; say the outline gives sections, order and what each develops. The report prompt gets `# Length` with the target and "shorter when the points cannot fill it; never pad".
- [ ] **Step 4: Run** `uv run python -m app.prompts`, then `uv run pytest -q`; expect pass.
- [ ] **Step 5: Commit** `feat(deep): a brainstormed brief, and a writer that knows how long to write`.

### Task 6: the question panel

**Files:**
- Create: `frontend/src/lib/ask.ts`, `frontend/src/lib/ask.test.ts`, `frontend/src/components/AskPanel.tsx`
- Modify: `frontend/src/types.ts`, `frontend/src/lib/api.ts` (send `answers`, read `ask` from messages and QueryDetail), `frontend/src/App.tsx` (`startResearch(prompt, { answers })`, turn `ask`), `frontend/src/components/Conversation.tsx` (panel above the PromptBar, placeholder), `frontend/src/components/TurnCard.tsx` (answered card), `frontend/src/lib/i18n.ts`, `frontend/src/theme.css`

- [ ] **Step 1: Failing tests** in `ask.test.ts`: `openQuestion(turns)` returns the last turn's questions only when it is complete and the last one; `choose(state, i)` records and advances, and on the last question returns `done`; `skip` records null; `back` keeps earlier answers; `turnsFrom` maps a user message's `ask` to `answers` and an assistant's to `ask`.
- [ ] **Step 2: Run** `npx vitest run src/lib/ask.test.ts`; expect failures.
- [ ] **Step 3: Implement** the reducer in `ask.ts`, then `AskPanel`: question title, "n of m" with ‹ ›, close; numbered options (Enter or digit to choose, arrows to move); a "Something else" row that takes text, with Skip; it calls `onAnswer(pairs)` or `onDismiss()`. `Conversation` renders it above the `PromptBar` when `openQuestion` gives questions and the panel was not dismissed for that turn; the placeholder becomes "Or reply directly…". `TurnCard` renders a user turn with `answers` as question and answer pairs. Copy in both languages.
- [ ] **Step 4: Run** `npx vitest run`, `npx tsc -b`, `npx eslint src`; restore `tsconfig.tsbuildinfo`.
- [ ] **Step 5: Commit** `feat(chat): the question panel, and answers shown as a card`.

### Task 7: end to end

- [ ] Boot the local stack (API :8001 inline, Vite :5174, SearXNG and Crawl4AI when Docker is up) and replay the 2026-09-25 career conversation in deep mode in the browser.
- [ ] Check: the brainstorm panels, "Decide for me", paging and keyboard, the confirmation, the answered cards, the collapse, a reload with the panel open, typing instead of clicking.
- [ ] Read the finished run's events: rounds, pages read, report length, against 107's (1 round, 4 pages, 573 words).
- [ ] Fix anything off, then run the full suites and commit.
