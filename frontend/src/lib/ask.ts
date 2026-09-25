// The question panel's logic, apart from how it looks: which question is open,
// what has been chosen, and the message the answers become. Kept pure so it can
// be checked on its own; AskPanel only draws it and turns keys into calls.

import type { Answered, Question, Turn } from "../types";

// `answers` has one slot per question: a choice, null for a skip, undefined
// while it has not been reached.
export type AskState = { index: number; answers: (string | null | undefined)[] };

export const start = (questions: Question[]): AskState => ({
  index: 0,
  answers: questions.map(() => undefined),
});

// Record the open question's answer (null: skipped) and move to the next. On
// the last one, `done` holds every question's answer, ready to send.
export function choose(
  state: AskState,
  questions: Question[],
  answer: string | null,
): { state: AskState; done: Answered[] | null } {
  const answers = state.answers.map((a, i) => (i === state.index ? answer : a));
  const last = state.index >= questions.length - 1;
  const next = { index: last ? state.index : state.index + 1, answers };
  return { state: next, done: last ? toPairs(questions, answers) : null };
}

export const back = (state: AskState): AskState => ({
  ...state,
  index: Math.max(0, state.index - 1),
});

export const forward = (state: AskState, questions: Question[]): AskState => ({
  ...state,
  index: Math.min(questions.length - 1, state.index + 1),
});

const toPairs = (questions: Question[], answers: (string | null | undefined)[]): Answered[] =>
  questions.map((q, i) => ({ question: q.question, answer: answers[i] ?? null }));

// The message text the answers make. The server writes the same from the pairs
// it receives; this is the text the thread shows until the turn is reloaded.
export const formatAnswers = (pairs: Answered[]): string =>
  pairs.map((p) => `${p.question}\n→ ${p.answer ?? "(skipped)"}`).join("\n\n");

// The questions waiting for an answer: the latest turn's, once it has finished.
// Any later message, typed or clicked, makes a newer turn and closes them.
export function openQuestion(turns: Turn[]): Question[] | null {
  const last = turns[turns.length - 1];
  if (!last || last.status !== "complete" || !last.ask?.length) return null;
  return last.ask;
}
