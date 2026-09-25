# ask_user, the deep-research brainstorm, and deeper runs

Status: approved in conversation on 2026-09-25, written for review.

## Why

Two problems, one feature set.

The supervisor asks the user things in prose ("Would you like: 1. ... 2. ... 3. ... or your call?"), and the user types "3" back.
Its options are often generic ("for a decision, for learning, for writing"), and a deep run it clearly should offer costs the user a second message to confirm.

Deep runs are shallow.
Four recent production runs took 23 to 63 seconds, used 1 or 2 lead rounds and 3 to 7 researchers, read 1 to 4 pages in total against 5 to 30 searches, and wrote 573 to 946 words.
The budget allows 12 minutes, 3 rounds and 15 researchers.
Every depth decision is left to the model, and a fast model takes the minimum at each one: researchers submit from search snippets, the lead writes after one round, and no length reaches the writer because it only travels inside the lead's outline, which rarely carries one.
(Production also ran on the wrong model, since the worker had no `LLM_MODEL`; that is fixed in Railway and is not part of this work.)

## Principle

The agents keep their judgement and their free loop.
Nothing in code counts panels, orders steps, or decides when a brainstorm is over: the prompt guides that, so the supervisor can adapt when the user changes their mind halfway.
Where a limit must hold, it lives inside a tool, as an error or a warning the agent reads and acts on.

## Part 1: ask_user

### What the user sees

The supervisor's reply streams as it does today.
When it called `ask_user`, a question panel docks above the composer, not inside the thread.
The panel shows the question, numbered options, a "Something else" row that takes free text, a Skip button, and a close button.
Several questions share one panel, with "1 of 2" and previous / next arrows; choosing an option moves to the next question, and choosing on the last one sends all the answers.
The keyboard works: up and down to move, Enter or a digit to choose.
While the panel is open the composer's placeholder reads "Or reply directly…".

Answered through the panel, the panel collapses and the user's message appears in the thread as a card of question and answer pairs.
Answered by typing in the composer instead, the panel disappears and the text is sent as an ordinary message.
The close button dismisses the panel without sending anything.
A reload with an unanswered question as the latest assistant message shows the panel again; the state comes from the thread, not from browser storage.
Only the latest question is live.

Answers are sent in whatever mode the composer is in.

### The tool

`ask_user(questions)` takes 1 to 4 questions, each with a short `question` and 2 to 4 short `options`.
"Something else" and Skip are the interface's, never written by the model.
Arguments outside those limits come back from the tool as an error to fix, like any tool call.

Calling it ends the turn: what the supervisor wrote alongside the call is the reply, and the question is attached to that reply.
There is no pause and resume: the answer arrives as the user's next message, and the supervisor reads it like any other.

The tool exists in every mode.
The prompt keeps it for real choices where options help: not small talk, not yes / no confirmations of the obvious, not a habit.
Outside deep mode it never offers a deep run; that stays a one-line suggestion to switch the mode on.

### Storage and history

One nullable JSON column, `messages.ask`.
On an assistant message it holds the questions.
On the user's answer it holds the questions with the chosen answer for each, so the thread can render the card.
The answer message's `content` is the text the model reads, one block per question: the question, then the answer, with "(skipped)" for a skipped one.

When the history is replayed to the supervisor, an assistant turn that asked appends its questions and their numbered options after its text, so a typed "3" still maps to an option.

`MessageResponse` gains `ask`, and the frontend reads it from the thread as it reads everything else.

## Part 2: the brainstorm before a deep run

A section in the deep-mode prompt, written like a skill, replaces today's "make sure you know" list.

Before any deep run the supervisor brainstorms the brief with the user through `ask_user`.
It is short by default:

1. **The goal.** One panel pinning down what the user wants the report for, phrased as a concrete goal for this subject ("wants X so that Y"), unless the conversation already makes it clear.
2. **What that goal needs.** One panel of 2 to 4 questions generated from the goal, only on the dimensions that would change what gets researched: the reader and what they already know, the priority areas, depth or breadth, constraints such as region or timeframe, the shape of the report.
3. **Confirmation.** Two or three sentences restating the brief in the user's language, then one question: launch, or adjust.

A third question panel comes in only when an answer opened a real fork.
When the user changes their mind at any point, the supervisor goes back to whichever step the change touches; that is its call.
A message that already carries a clear goal and scope can go straight to the confirmation.

Good questions, as the prompt teaches them:
- Options are built from this subject and this conversation, not from abstract purposes.
- Options for the angles to take come from the people who would care about the subject (for a French AI job market question: recruiters, hiring managers, a self-taught engineer), not from a generic list.
- Every question that asks the user to choose ends with a "Decide for me" option in the user's language.
- A question already answered by the conversation is not asked.

The supervisor may use `web_search` while preparing its questions, to ground the options in what is current.
Those searches need no citations and no summary of what was found.

### The brief

`deep_research` takes a structured `brief` in place of today's loose `goal` text:

- `goal`: what the report is for, as "wants X so that Y".
- `reader`: who reads it and what they already know.
- `focus`: the priority areas, most important first.
- `open`: what the user left open, for the lead to decide.
- `decided`: what the user delegated with "Decide for me", and what was chosen.
- `out_of_scope`: what to leave out.
- `constraints`: region, timeframe, language of sources.
- `shape`: comparison, recommendation, primer, or what the user asked for.

It is rendered as a clear block in the run's prompt, which the lead reads, and which is stored on the run's row as today.

## Part 3: deeper runs

These are tool feedback, consistent with the principle: the agent is told and adapts.

**Researcher floor, deep runs only.**
`submit_finding` returns an error until the researcher has read at least two pages in full, unless it submits `found_info=false` after spending its searches.
The last-step and out-of-time paths keep submitting what was read, so the floor never loses a finding.

**Lead floor.**
`write_report` returns an error after the first round, with the checklist the prompt already carries (areas still thin, disagreements unsettled, claims on one weak source).
The lead's last-step path, when the budget is spent, is unaffected.

**Length lives in the writer's deep prompt.**
The deep writer gets its own length guidance, scaled to the findings it receives, so a thin run is short and says why instead of being padded.
The lead's outline goes back to structure only: sections, order, what each develops.

## Out of scope

- Showing the lead's plan of sub-questions before the run (Gemini, NVIDIA AI-Q): the lead plans round by round from what comes back, so a plan shown up front would be stale by the second round.
- An `ask_user` option that switches deep mode on.
- The one-shot research writer's time limit.

## Testing

- `ask_user`: the schema limits come back as errors; calling it ends the turn with the reply and the questions attached.
- `messages.ask`: round-trip through the API; the answer message's content format.
- History: an assistant turn that asked is replayed with its numbered options.
- Brief: rendered into the run's prompt.
- Researcher floor: an early `submit_finding` is refused with its reason; `found_info=false` passes; the forced finish still submits.
- Lead floor: `write_report` after round one is refused; after round two it passes; the last step still writes.
- Frontend: the panel's paging, keyboard, Skip, Something else, close, the formatted answer, the collapse, and the panel coming back on reload.
- End to end in the browser: the career-strategy conversation from 2026-09-25 in deep mode, through the brainstorm and confirmation to a finished report, checking its rounds, pages read and length against the numbers above.
