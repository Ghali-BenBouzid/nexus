import { describe, expect, it } from "vitest";

import type { AgentEvent, TimelineEvent } from "../types";
import { headline, summarize, timeline } from "./progress";

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

const kinds = (events: TimelineEvent[], ended: Parameters<typeof timeline>[1] = null) =>
  timeline(events, ended).map((s) => [s.kind, s.mark]);

describe("timeline", () => {
  it("shows every step in the order the run took it", () => {
    const events = [
      at({ kind: "step", step: 1 }, 0),
      at({ kind: "step_title", step: 1, title: "Checking what is asked" }, 1),
      at({ kind: "tool", action: "search", text: "heat pump -20C" }, 2),
      at({ kind: "tool", action: "read", domain: "energy.gov" }, 3),
      at({ kind: "step", step: 2 }, 4),
    ];

    expect(kinds(events)).toEqual([
      ["think", "ok"],
      ["search", "ok"],
      ["read", "ok"],
      ["think", "run"],
    ]);
    expect(timeline(events, null)[0]).toMatchObject({ kind: "think", title: "Checking what is asked" });
  });

  it("names a thought once its title lands, and leaves it plain until then", () => {
    const untitled = [at({ kind: "step", step: 1 }, 0)];
    expect(timeline(untitled, null)[0]).toMatchObject({ kind: "think", title: null });
  });

  it("nests a research team's plan and researchers under it", () => {
    const events = [
      at({ kind: "tool", action: "research", text: "Why is the sky blue?" }, 0),
      at({ kind: "planner", state: "start" }, 1),
      at({ kind: "plan", items: ["a", "b"] }, 2),
      at({ kind: "researcher", state: "start", index: 1, total: 2, question: "a" }, 3),
      at({ kind: "tool", action: "search", text: "a researcher's query", index: 1 }, 4),
      at({ kind: "researcher", state: "done", index: 1, question: "a", outcome: "found" }, 5),
      at({ kind: "researcher", state: "start", index: 2, total: 2, question: "b" }, 6),
    ];
    const list = timeline(events, null);

    // A researcher's own search is that row's state, not a step of its own.
    expect(list.map((s) => s.kind)).toEqual(["research", "plan", "researcher", "researcher"]);
    expect(list.map((s) => s.mark)).toEqual(["run", "ok", "ok", "run"]);
    expect(list.slice(1).every((s) => "sub" in s && s.sub)).toBe(true);
  });

  it("lists a team's researchers by number, whatever order they started in", () => {
    const events = [3, 1, 2].map((index) =>
      at({ kind: "researcher", state: "start", index, total: 3, question: `q${index}`, team: "a" }, index),
    );
    const list = timeline([at({ kind: "tool", action: "research", text: "x", team: "a" }, 0), ...events], null);

    expect(list.map((s) => (s.kind === "researcher" ? s.row.index : s.kind))).toEqual(["research", 1, 2, 3]);
  });

  it("keeps two research teams in one turn apart", () => {
    const team = (question: string) => [
      at({ kind: "tool", action: "research", text: question }, 0),
      at({ kind: "researcher", state: "start", index: 1, total: 1, question }, 1),
      at({ kind: "researcher", state: "done", index: 1, question, outcome: "found" }, 2),
    ];
    const list = timeline([...team("first"), ...team("second")], "done");

    expect(list.filter((s) => s.kind === "researcher").map((s) => s.kind === "researcher" && s.row.question)).toEqual([
      "first",
      "second",
    ]);
  });

  it("keeps two teams running at once apart, each under the step that sent it", () => {
    const events = [
      at({ kind: "tool", action: "research", text: "Mitsubishi", team: "a" }, 0),
      at({ kind: "tool", action: "research", text: "Daikin", team: "b" }, 0),
      at({ kind: "planner", state: "start", team: "b" }, 1),
      at({ kind: "planner", state: "start", team: "a" }, 1),
      at({ kind: "researcher", state: "start", index: 1, total: 1, question: "daikin 1", team: "b" }, 2),
      at({ kind: "researcher", state: "start", index: 1, total: 1, question: "mitsu 1", team: "a" }, 2),
      at({ kind: "researcher", state: "done", index: 1, question: "mitsu 1", outcome: "found", team: "a" }, 3),
    ];
    const list = timeline(events, null);

    expect(list.map((s) => (s.kind === "researcher" ? s.row.question : s.kind))).toEqual([
      "research",
      "plan",
      "mitsu 1",
      "research",
      "plan",
      "daikin 1",
    ]);
    // Team a is done; team b's researcher is still out.
    expect(list.map((s) => s.mark)).toEqual(["ok", "run", "ok", "run", "run", "run"]);
  });

  it("shows a step the user stopped as stopped, not as still running", () => {
    const writing = [at({ kind: "tool", action: "search", text: "q" }, 0), at({ kind: "writer", state: "start" }, 1)];
    const list = timeline(writing, "stopped");

    expect(list.at(-1)).toEqual({ kind: "write", done: false, mark: "stop", cut: true });
    expect(list.filter((s) => s.mark === "run")).toEqual([]);
  });

  it("marks researchers a failure cut short, and keeps the ones that finished", () => {
    const researching = [
      at({ kind: "researcher", state: "start", index: 1, total: 2, question: "a" }, 2),
      at({ kind: "researcher", state: "start", index: 2, total: 2, question: "b" }, 2),
      at({ kind: "researcher", state: "done", index: 2, question: "b", outcome: "empty" }, 3),
    ];

    expect(timeline(researching, "failed").map((s) => [s.kind, s.mark, s.cut])).toEqual([
      ["researcher", "warn", true],
      ["researcher", "warn", false],
    ]);
  });

  it("keeps a background run as a step of its own, never as work still running", () => {
    // The turn is over long before the run it started; its progress lives in the
    // Outputs panel, so the step here only records that it began.
    const started = [at({ kind: "started", run: "deep_research", text: "All of X" }, 2)];

    expect(timeline(started, null)).toEqual([
      { kind: "started", run: { run: "deep_research", text: "All of X" }, mark: "ok", cut: false },
    ]);
  });

  it("reads the request before anything else has happened", () => {
    expect(timeline([], null)).toEqual([{ kind: "understanding", mark: "run", cut: false }]);
    // A short answer ends that step, and a run cut short leaves it unfinished.
    expect(timeline([], "done")).toEqual([{ kind: "understanding", mark: "ok", cut: false }]);
    expect(timeline([], "stopped")).toEqual([{ kind: "understanding", mark: "stop", cut: true }]);
  });

  it("closes a researcher the run answered over", () => {
    const events = [at({ kind: "researcher", state: "start", index: 1, total: 1, question: "q1" }, 0)];
    expect(kinds(events, "done")).toEqual([["researcher", "ok"]]);
  });
});

describe("headline", () => {
  const head = (events: TimelineEvent[]) => headline(summarize(events), timeline(events, null));

  it("prefers what a researcher is doing right now", () => {
    expect(
      head([
        at({ kind: "researcher", state: "start", index: 1, total: 2, question: "q1" }, 0),
        at({ kind: "researcher", state: "start", index: 2, total: 2, question: "q2" }, 0),
        at({ kind: "tool", action: "read", domain: "reuters.com", index: 1 }, 1),
      ]),
    ).toEqual({ kind: "activity", activity: { kind: "read", domain: "reuters.com", at: 1 } });
  });

  it("names the question when exactly one researcher is left working", () => {
    expect(
      head([
        at({ kind: "researcher", state: "start", index: 1, total: 2, question: "q1" }, 0),
        at({ kind: "researcher", state: "start", index: 2, total: 2, question: "q2" }, 0),
        at({ kind: "researcher", state: "done", index: 1, question: "q1", outcome: "found" }, 1),
        at({ kind: "thinking", agent: "researcher", index: 2 }, 2),
      ]),
    ).toEqual({ kind: "researcher", question: "q2" });
  });

  it("otherwise says what the latest step is doing", () => {
    const h = head([
      at({ kind: "step", step: 1 }, 0),
      at({ kind: "step_title", step: 1, title: "Weighing the costs" }, 1),
    ]);
    expect(h).toMatchObject({ kind: "step", step: { kind: "think", title: "Weighing the costs" } });
  });

  it("falls back to the stage before any step", () => {
    expect(head([])).toEqual({ kind: "stage" });
  });
});
