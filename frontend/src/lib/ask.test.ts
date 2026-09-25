import { describe, expect, it } from "vitest";

import { back, choose, closing, forward, formatAnswers, openQuestion, start } from "./ask";
import { turnsFrom, type ConvMessage } from "./api";
import type { Question, Turn } from "../types";

const TOPIC: Question = { question: "Which topic?", options: ["History", "Science"] };
const LEVEL: Question = { question: "How hard?", options: ["Easy", "Hard"] };

const turn = (patch: Partial<Turn>): Turn => ({
  id: 1,
  query: "quiz me",
  status: "complete",
  events: [],
  result: null,
  outcome: "ok",
  error: null,
  startedAt: 0,
  endedAt: 1,
  ...patch,
});

describe("the question panel", () => {
  it("records a choice and moves on, then finishes on the last", () => {
    const questions = [TOPIC, LEVEL];
    const first = choose(start(questions), questions, "History");
    expect(first.done).toBeNull();
    expect(first.state.index).toBe(1);

    const last = choose(first.state, questions, "Hard");
    expect(last.done).toEqual([
      { question: "Which topic?", answer: "History" },
      { question: "How hard?", answer: "Hard" },
    ]);
  });

  it("reads a skipped or never-reached question as skipped", () => {
    const questions = [TOPIC, LEVEL];
    const moved = forward(start(questions), questions);
    const { done } = choose(moved, questions, null);
    expect(done).toEqual([
      { question: "Which topic?", answer: null },
      { question: "How hard?", answer: null },
    ]);
  });

  it("goes back without losing what was answered", () => {
    const questions = [TOPIC, LEVEL];
    const { state } = choose(start(questions), questions, "Science");
    const again = back(state);
    expect(again.index).toBe(0);
    expect(again.answers[0]).toBe("Science");
    expect(back(again).index).toBe(0);
    expect(forward(forward(again, questions), questions).index).toBe(1);
  });

  it("writes answers the way the server does", () => {
    expect(
      formatAnswers([
        { question: "Which topic?", answer: "History" },
        { question: "How hard?", answer: null },
      ]),
    ).toBe("Which topic?\n→ History\n\nHow hard?\n→ (skipped)");
  });
});

describe("openQuestion", () => {
  it("is the latest turn's question, once that turn is done", () => {
    expect(openQuestion([turn({ ask: [TOPIC] })])).toEqual([TOPIC]);
    expect(openQuestion([turn({ ask: [TOPIC], status: "running" })])).toBeNull();
    expect(openQuestion([turn({ ask: [TOPIC] }), turn({ id: 2 })])).toBeNull();
    expect(openQuestion([])).toBeNull();
  });
});

describe("turnsFrom with questions", () => {
  const base = { query_id: null, created_at: "2026-09-25T00:00:00Z", query: null };
  it("keeps what an assistant asked and what the user answered", () => {
    const messages: ConvMessage[] = [
      { ...base, id: 1, role: "user", content: "quiz me" },
      { ...base, id: 2, role: "assistant", content: "Two questions.", ask: [TOPIC] },
      {
        ...base,
        id: 3,
        role: "user",
        content: "Which topic?\n→ History",
        ask: [{ question: "Which topic?", answer: "History" }],
      },
      { ...base, id: 4, role: "assistant", content: "Great." },
    ];

    const [asked, answered] = turnsFrom(messages);

    expect(asked.ask).toEqual([TOPIC]);
    expect(asked.answers).toBeUndefined();
    expect(answered.answers).toEqual([{ question: "Which topic?", answer: "History" }]);
    expect(answered.ask).toBeUndefined();
  });
});

describe("turnsFrom and the mode a question was asked in", () => {
  it("keeps the mode of the turn, so a reopened thread answers in it", () => {
    const [turn] = turnsFrom([
      { id: 1, role: "user", content: "career plan", query_id: null, created_at: "", query: null },
      {
        id: 2,
        role: "assistant",
        content: "",
        query_id: 7,
        created_at: "",
        ask: [TOPIC],
        query: {
          status: "complete",
          title: null,
          report: null,
          error: null,
          sources: [],
          gaps: [],
          mode: "deep",
        },
      },
    ]);
    expect(turn.mode).toBe("deep");
  });
});

describe("closing the panel", () => {
  it("answers a go-ahead as skipped, so the supervisor can say it is waiting", () => {
    const go: Question = { question: "Launch it?", options: ["Launch"], confirm: true };
    expect(closing([go])).toEqual([{ question: "Launch it?", answer: null }]);
  });

  it("sends nothing for ordinary questions: closing them is not an answer", () => {
    expect(closing([TOPIC, LEVEL])).toBeNull();
  });
});
