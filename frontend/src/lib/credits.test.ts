import { describe, expect, it } from "vitest";

import { creditsLeft } from "./credits";

describe("creditsLeft", () => {
  it("shows the share of the budget left", () => {
    expect(creditsLeft(0.43, 0.5)).toBe(86);
  });

  it("only reads 0% once nothing is left", () => {
    expect(creditsLeft(0.0001, 0.5)).toBe(1);
    expect(creditsLeft(0, 0.5)).toBe(0);
  });

  it("stays between 0 and 100", () => {
    expect(creditsLeft(0.7, 0.5)).toBe(100);
    expect(creditsLeft(-0.01, 0.5)).toBe(0);
    expect(creditsLeft(0, 0)).toBe(0);
  });
});
