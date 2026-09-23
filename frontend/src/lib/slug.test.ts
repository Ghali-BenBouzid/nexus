import { describe, expect, it } from "vitest";

import { resolve, slug } from "./slug";

describe("slug", () => {
  it("lowercases, drops punctuation and hyphenates", () => {
    expect(slug("Revenue grew 40% in 2026")).toBe("revenue-grew-40-in-2026");
    expect(slug("Who said it, and when?")).toBe("who-said-it-and-when");
  });

  it("is stable across the colons and dashes a heading carries", () => {
    expect(slug("Supported: the merger closed")).toBe("supported-the-merger-closed");
  });

  it("collapses the dash separating a verdict from its claim", () => {
    // The header a fact check writes, and the link it writes for that header,
    // have to land on the same spelling.
    expect(slug("Supported - Llama 4 was the first MoE Llama")).toBe(
      "supported-llama-4-was-the-first-moe-llama",
    );
    expect(slug("Supported - Mixtral 8x7B outperformed GPT 3.5")).toBe(
      "supported-mixtral-8x7b-outperformed-gpt-35",
    );
  });

  it("keeps a hyphen that belongs to a word", () => {
    expect(slug("Open-weight models lead")).toBe("open-weight-models-lead");
  });
});

describe("resolve", () => {
  const ids = ["overall", "supported-the-merger-closed", "unverifiable-the-2019-figure"];

  it("takes an exact match", () => {
    expect(resolve("#overall", ids)).toBe("overall");
  });

  it("finds the heading when the link drops the verdict", () => {
    // What a model actually writes: the claim, without the verdict the
    // heading carries.
    expect(resolve("#the-merger-closed", ids)).toBe("supported-the-merger-closed");
  });

  it("finds the heading when the link carries more than the heading", () => {
    expect(resolve("#overall-assessment", ids)).toBe("overall");
  });

  it("slugifies a target that was not written as a slug", () => {
    expect(resolve("#The Merger Closed", ids)).toBe("supported-the-merger-closed");
  });

  it("matches a French heading to the encoded link written for it", () => {
    // The renderer percent-encodes accents in a link; the heading keeps them.
    const french = [slug("Vérifié - Le pont a ouvert en 1937")];
    expect(french).toEqual(["verifie-le-pont-a-ouvert-en-1937"]);
    expect(resolve("#v%C3%A9rifi%C3%A9-le-pont-a-ouvert-en-1937", french)).toBe(french[0]);
  });

  it("finds the heading when the link rewords the claim", () => {
    // From a live report: the link and its heading said the claim differently.
    const headings = [
      "supported-toll-is-collected-only-from-southbound-drivers",
      "supported-electronic-tolling-only-since-2013",
    ];
    expect(
      resolve("#supported-toll-collection-has-been-entirely-electronic-since-2013", headings),
    ).toBe("supported-electronic-tolling-only-since-2013");
  });

  it("refuses an ambiguous target rather than guessing", () => {
    expect(resolve("#the", ["the-first", "the-second"])).toBeNull();
  });

  it("refuses a target that matches nothing", () => {
    expect(resolve("#nowhere", ids)).toBeNull();
  });
});
