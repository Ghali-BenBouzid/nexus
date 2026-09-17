import { describe, expect, it } from "vitest";

import type { AgentEvent, TimelineEvent } from "../types";
import { steps, summarize } from "./progress";

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
});
