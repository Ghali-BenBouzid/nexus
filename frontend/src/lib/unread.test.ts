import { describe, expect, it } from "vitest";

import type { Output } from "../types";
import { isUnread, markSeen, unreadCount } from "./unread";

const output = (over: Partial<Output> = {}): Output => ({
  id: 1,
  kind: "deep_research",
  title: "A report",
  prompt: "a question",
  status: "complete",
  conversationId: null,
  error: null,
  createdAt: "2026-09-21T00:00:00Z",
  completedAt: "2026-09-21T00:05:00Z",
  ...over,
});

describe("isUnread", () => {
  it("a finished report nobody opened is unread", () => {
    expect(isUnread(output(), {})).toBe(true);
  });

  it("opening it clears the mark", () => {
    const o = output();
    expect(isUnread(o, markSeen({}, o))).toBe(false);
  });

  it("new content after a refresh brings the mark back", () => {
    const o = output();
    const seen = markSeen({}, o);
    expect(isUnread({ ...o, completedAt: "2026-09-21T01:00:00Z" }, seen)).toBe(true);
  });

  it("a run still working has nothing to read yet", () => {
    expect(isUnread(output({ status: "running", completedAt: null }), {})).toBe(false);
    expect(isUnread(output({ status: "failed" }), {})).toBe(false);
  });

  it("a report opened while it was running is unread once it finishes", () => {
    const running = output({ status: "running", completedAt: null });
    const seen = markSeen({}, running);
    expect(isUnread(output(), seen)).toBe(true);
  });
});

describe("unreadCount", () => {
  it("counts only the finished, unopened ones", () => {
    const a = output({ id: 1 });
    const b = output({ id: 2 });
    const c = output({ id: 3, status: "running", completedAt: null });
    expect(unreadCount([a, b, c], markSeen({}, a))).toBe(1);
  });
});
