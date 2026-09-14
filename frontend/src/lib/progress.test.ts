import { describe, expect, it } from "vitest";

import type { AgentEvent, TimelineEvent } from "../types";
import { summarize } from "./progress";

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
