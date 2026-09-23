import { describe, expect, it } from "vitest";

import { initials } from "./initials";

describe("initials", () => {
  it("takes the first letter of the first two words", () => {
    expect(initials("Ghali")).toBe("G");
    expect(initials("ghali ben bouzid")).toBe("GB");
    expect(initials("  Élodie   Durand ")).toBe("ED");
    expect(initials("Łukasz Çelik")).toBe("ŁC");
  });

  it("never leaves the avatar empty", () => {
    expect(initials("")).toBe("?");
    expect(initials("   ")).toBe("?");
  });
});
