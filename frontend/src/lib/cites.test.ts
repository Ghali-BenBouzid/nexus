import { describe, expect, it } from "vitest";

import { segments } from "./cites";

describe("segments", () => {
  it("collapses a run of citations into one group", () => {
    expect(segments("Water is wet [1][3][7].")).toEqual([
      { text: "Water is wet " },
      { ns: [1, 3, 7] },
      { text: "." },
    ]);
  });

  it("keeps citations on different claims apart", () => {
    expect(segments("First [1]. Second [2][3].")).toEqual([
      { text: "First " },
      { ns: [1] },
      { text: ". Second " },
      { ns: [2, 3] },
      { text: "." },
    ]);
  });

  it("groups a run the writer spaced out anyway", () => {
    expect(segments("Claim [1] [2].")).toEqual([
      { text: "Claim " },
      { ns: [1, 2] },
      { text: "." },
    ]);
  });

  it("counts a repeated number once", () => {
    expect(segments("Claim [2][2][5].")).toEqual([
      { text: "Claim " },
      { ns: [2, 5] },
      { text: "." },
    ]);
  });

  it("leaves the writer's order alone", () => {
    expect(segments("Claim [9][2].")).toEqual([
      { text: "Claim " },
      { ns: [9, 2] },
      { text: "." },
    ]);
  });

  it("passes prose with no citations straight through", () => {
    expect(segments("Nothing to cite here.")).toEqual([
      { text: "Nothing to cite here." },
    ]);
  });

  it("does not read a bracketed word as a citation", () => {
    expect(segments("A [note] in brackets.")).toEqual([
      { text: "A [note] in brackets." },
    ]);
  });
});
