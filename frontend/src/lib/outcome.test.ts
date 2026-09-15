import { describe, expect, it } from "vitest";

import { outcomeFor } from "./outcome";

describe("outcomeFor", () => {
  it("calls a research run with no report and no sources empty", () => {
    expect(outcomeFor("complete", "", 0)).toBe("empty");
  });

  it("never calls a direct answer empty, though it has no report or sources", () => {
    // A reloaded answer used to come back "empty" and offer to reword the question.
    expect(outcomeFor("complete", "", 0, "Paris is the capital of France.")).toBe("ok");
  });

  it("keeps a failure a failure", () => {
    expect(outcomeFor("failed", "", 0, null)).toBe("failed");
  });
});
