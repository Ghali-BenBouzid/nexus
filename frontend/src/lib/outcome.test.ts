import { describe, expect, it } from "vitest";

import { outcomeFor } from "./outcome";

describe("outcomeFor", () => {
  it("calls a turn that produced nothing at all empty", () => {
    expect(outcomeFor("complete", "", 0)).toBe("empty");
  });

  it("calls an answer with no sources fine, as long as it said something", () => {
    expect(outcomeFor("complete", "Paris is the capital of France.", 0)).toBe("ok");
  });

  it("keeps a failure a failure", () => {
    expect(outcomeFor("failed", "", 0)).toBe("failed");
  });
});
