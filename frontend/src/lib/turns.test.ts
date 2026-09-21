import { describe, expect, it } from "vitest";

import { turnsFrom, type ConvMessage } from "./api";

const user = (content: string): ConvMessage => ({
  id: 1,
  role: "user",
  content,
  query_id: null,
  created_at: "2026-09-21T00:00:00Z",
  query: null,
});

const assistant = (query: Partial<NonNullable<ConvMessage["query"]>>): ConvMessage => ({
  id: 2,
  role: "assistant",
  content: "",
  query_id: 9,
  created_at: "2026-09-21T00:00:01Z",
  query: {
    kind: "chat",
    status: "complete",
    title: null,
    report: null,
    reply: null,
    error: null,
    stopped: false,
    sources: [],
    gaps: [],
    ...query,
  },
});

describe("turnsFrom", () => {
  it("reads a deep run's report as what the turn said", () => {
    const [turn] = turnsFrom([
      user("why is the sky blue"),
      assistant({ kind: "deep_research", report: "## Findings", title: "Sky" }),
    ]);

    expect(turn.deep).toBe(true);
    expect(turn.result.report).toBe("## Findings");
    expect(turn.title).toBe("Sky");
  });

  it("leaves a chat turn answering with its reply and no report", () => {
    const [turn] = turnsFrom([
      user("hi"),
      assistant({ kind: "chat", reply: "Hello." }),
    ]);

    expect(turn.deep).toBe(false);
    expect(turn.reply).toBe("Hello.");
    expect(turn.result.report).toBe("");
  });

  it("keeps the question each answer belongs to", () => {
    const turns = turnsFrom([
      user("first"),
      assistant({ reply: "one" }),
      user("second"),
      assistant({ kind: "deep_research", report: "two" }),
    ]);

    expect(turns.map((turn) => turn.query)).toEqual(["first", "second"]);
    expect(turns.map((turn) => turn.deep)).toEqual([false, true]);
  });
});
