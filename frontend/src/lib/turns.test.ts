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
  it("answers a turn with its reply and its cited sources", () => {
    const [turn] = turnsFrom([
      user("hi"),
      assistant({
        reply: "Hello.",
        title: "Greeting",
        sources: [{ title: "A page", url: "https://example.org" }],
      }),
    ]);

    expect(turn.reply).toBe("Hello.");
    expect(turn.title).toBe("Greeting");
    expect(turn.result.sources).toHaveLength(1);
  });

  it("keeps the question each answer belongs to", () => {
    const turns = turnsFrom([
      user("first"),
      assistant({ reply: "one" }),
      user("second"),
      assistant({ reply: "two" }),
    ]);

    expect(turns.map((turn) => turn.query)).toEqual(["first", "second"]);
    expect(turns.map((turn) => turn.reply)).toEqual(["one", "two"]);
  });

  // The announcement a deep run leaves behind: a plain message with no run to
  // follow, which must still read as an answer rather than as an empty turn.
  it("keeps a message that carries no run at all", () => {
    const [turn] = turnsFrom([
      user("go deep on X"),
      { ...assistant({}), query_id: null, query: null, content: "Starting deep research." },
    ]);

    expect(turn.queryId).toBeNull();
    expect(turn.reply).toBe("Starting deep research.");
    expect(turn.status).toBe("complete");
  });
});
