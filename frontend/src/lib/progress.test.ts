import { describe, expect, it } from "vitest";

import type { AgentEvent, TimelineEvent } from "../types";
import { headline, lastSentence, steps, summarize } from "./progress";

let seq = 0;
const at = (event: AgentEvent, when: number): TimelineEvent => ({ ...event, id: seq++, delay: 0, at: when });

describe("summarize", () => {
  it("counts the researchers still working and keeps what each did last", () => {
    const p = summarize([
      at({ kind: "planner", state: "start" }, 0),
      at({ kind: "plan", items: ["a", "b", "c"] }, 1),
      at({ kind: "researcher", state: "start", index: 1, total: 3, question: "a" }, 2),
      at({ kind: "researcher", state: "start", index: 2, total: 3, question: "b" }, 2),
      at({ kind: "tool", action: "search", text: "a query", index: 1 }, 3),
      at({ kind: "thinking", agent: "researcher", index: 2 }, 4),
      at({ kind: "researcher", state: "done", index: 1, question: "a", outcome: "found" }, 5),
    ]);

    expect(p.stage).toBe("researching");
    expect(p.total).toBe(3);
    expect(p.active).toBe(1);
    expect(p.researchers.map((r) => r.outcome)).toEqual(["found", "running"]);
    expect(p.researchers[1].activity).toEqual({ kind: "thinking", at: 4 });
    expect(p.latest).toEqual({ kind: "thinking", at: 4 });
    expect(p.lastAt).toBe(5);
  });

  it("shows the writer thinking until its next event", () => {
    const writing = [
      at({ kind: "writer", state: "start" }, 1),
      at({ kind: "thinking", agent: "writer" }, 2),
    ];

    expect(summarize(writing)).toMatchObject({ stage: "writing", thinking: true, lastAt: 2 });
    expect(summarize([...writing, at({ kind: "writer", state: "done" }, 9)])).toMatchObject({
      stage: "done",
      thinking: false,
    });
  });

  it("has nothing to time before the first event", () => {
    expect(summarize([])).toMatchObject({ stage: "starting", active: 0, lastAt: null, latest: null });
  });
});

describe("steps", () => {
  const writing = [
    at({ kind: "plan", items: ["a", "b"] }, 1),
    at({ kind: "researcher", state: "start", index: 1, total: 2, question: "a" }, 2),
    at({ kind: "researcher", state: "done", index: 1, question: "a", outcome: "found" }, 3),
    at({ kind: "writer", state: "start" }, 4),
    at({ kind: "thinking", agent: "writer" }, 5),
  ];

  it("keeps a live run's current step running", () => {
    expect(steps(summarize(writing), null).at(-1)).toEqual({ kind: "write", mark: "run", cut: false });
  });

  it("shows a step the user stopped as stopped, not as still running", () => {
    const list = steps(summarize(writing), "stopped");

    expect(list.at(-1)).toEqual({ kind: "write", mark: "stop", cut: true });
    expect(list.filter((s) => s.mark === "run")).toEqual([]);
    expect(list[1]).toMatchObject({ kind: "researcher", mark: "ok", cut: false });
  });

  it("marks researchers a failure cut short, and keeps the ones that finished", () => {
    const researching = [
      at({ kind: "plan", items: ["a", "b"] }, 1),
      at({ kind: "researcher", state: "start", index: 1, total: 2, question: "a" }, 2),
      at({ kind: "researcher", state: "start", index: 2, total: 2, question: "b" }, 2),
      at({ kind: "researcher", state: "done", index: 2, question: "b", outcome: "empty" }, 3),
    ];

    expect(steps(summarize(researching), "failed").map((s) => [s.kind, s.mark, s.cut])).toEqual([
      ["plan", "ok", false],
      ["researcher", "warn", true],
      ["researcher", "warn", false],
    ]);
  });

  it("keeps a background run as a step of its own, never as work still running", () => {
    // The turn is over long before the run it started; its progress lives in the
    // Outputs panel, so the step here only records that it began.
    const started = [
      at({ kind: "thinking", agent: "supervisor" }, 1),
      at({ kind: "started", run: "deep_research", text: "All of X" }, 2),
    ];

    const list = steps(summarize(started), null);

    expect(list.at(-1)).toEqual({
      kind: "started",
      run: { run: "deep_research", text: "All of X" },
      mark: "ok",
      cut: false,
    });
  });

  it("reads a document as activity, not as a search", () => {
    const reading = [at({ kind: "tool", action: "document", text: "claims.pdf" }, 1)];

    expect(summarize(reading).latest).toEqual({
      kind: "document",
      text: "claims.pdf",
      at: 1,
    });
  });
});

describe("lastSentence", () => {
  it("ignores the half-written tail a stream is still producing", () => {
    expect(lastSentence("The user wants a comparison. I should check the")).toBe(
      "The user wants a comparison.",
    );
  });

  it("is empty until the first sentence has finished", () => {
    expect(lastSentence("I should start by")).toBeNull();
    expect(lastSentence("")).toBeNull();
  });

  it("takes the most recent finished sentence", () => {
    expect(lastSentence("First thought. Second thought. ")).toBe("Second thought.");
  });

  it("treats a line break as an end, so a list of notes still reads", () => {
    expect(lastSentence("Checking the filings\nComparing the two")).toBe("Checking the filings");
  });

  it("cuts a sentence too long for one line", () => {
    const long = "x".repeat(200) + ".";
    const out = lastSentence(long, 40)!;
    expect(out).toHaveLength(40);
    expect(out.endsWith("\u2026")).toBe(true);
  });
});

describe("headline", () => {
  const working = (events: TimelineEvent[]) => summarize(events);

  it("prefers what a researcher is doing right now", () => {
    const p = working([
      at({ kind: "researcher", state: "start", index: 1, total: 2, question: "q1" }, 0),
      at({ kind: "researcher", state: "start", index: 2, total: 2, question: "q2" }, 0),
      at({ kind: "tool", action: "read", domain: "reuters.com", index: 1 }, 1),
    ]);
    expect(headline(p, "A thought.")).toEqual({
      kind: "activity",
      activity: { kind: "read", domain: "reuters.com", at: 1 },
    });
  });

  it("names the question when exactly one researcher is left working", () => {
    const p = working([
      at({ kind: "researcher", state: "start", index: 1, total: 2, question: "q1" }, 0),
      at({ kind: "researcher", state: "start", index: 2, total: 2, question: "q2" }, 0),
      at({ kind: "researcher", state: "done", index: 1, question: "q1", outcome: "found" }, 1),
      at({ kind: "thinking", agent: "researcher", index: 2 }, 2),
    ]);
    expect(headline(p, "")).toEqual({ kind: "researcher", question: "q2" });
  });

  it("falls back to the model's own words before any event is specific", () => {
    const p = working([at({ kind: "thinking", agent: "supervisor" }, 0)]);
    expect(headline(p, "Working out what is being asked. And then")).toEqual({
      kind: "thought",
      text: "Working out what is being asked.",
    });
  });

  it("does not describe the run with a read that has already finished", () => {
    const p = working([
      at({ kind: "researcher", state: "start", index: 1, total: 1, question: "q1" }, 0),
      at({ kind: "tool", action: "read", domain: "reuters.com", index: 1 }, 1),
      at({ kind: "researcher", state: "done", index: 1, question: "q1", outcome: "found" }, 2),
      at({ kind: "writer", state: "start" }, 3),
    ]);
    expect(headline(p, "")).toEqual({ kind: "stage" });
  });
});
