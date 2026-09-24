import { describe, expect, it } from "vitest";

import { elapsed, when } from "./when";

// A fixed "now" in local time, so the day boundaries are the machine's own.
const now = new Date(2026, 8, 24, 20, 30); // 24 September 2026, 8:30 PM
const at = (y: number, mo: number, d: number, h: number, mi = 0) => new Date(y, mo, d, h, mi).toISOString();

describe("when", () => {
  it("says just now, then minutes, then hours while it is recent", () => {
    expect(when(at(2026, 8, 24, 20, 30), now, "en-US")).toBe("just now");
    expect(when(at(2026, 8, 24, 20, 29), now, "en-US")).toBe("a minute ago");
    expect(when(at(2026, 8, 24, 19, 53), now, "en-US")).toBe("37 minutes ago");
    expect(when(at(2026, 8, 24, 20, 28), now, "en-US")).toBe("2 minutes ago");
    expect(when(at(2026, 8, 24, 19, 0), now, "en-US")).toBe("an hour ago");
    expect(when(at(2026, 8, 24, 15, 0), now, "en-US")).toBe("5 hours ago");
  });

  it("gives the time of day once hours stop being useful", () => {
    expect(when(at(2026, 8, 24, 9, 5), now, "en-US")).toBe("Today at 9:05 AM");
    expect(when(at(2026, 8, 23, 18, 0), now, "en-US")).toBe("Yesterday at 6:00 PM");
  });

  it("gives the date for anything older, with the year only when it differs", () => {
    expect(when(at(2026, 8, 21, 18, 0), now, "en-US")).toBe("September 21, 6:00 PM");
    expect(when(at(2025, 11, 30, 9, 0), now, "en-US")).toBe("December 30, 2025, 9:00 AM");
  });

  it("stays relative across midnight while it is still recent", () => {
    const justAfterMidnight = new Date(2026, 8, 25, 0, 30);
    expect(when(at(2026, 8, 24, 23, 0), justAfterMidnight, "en-US")).toBe("an hour ago");
  });

  it("says nothing for a date it cannot read", () => {
    expect(when("not a date", now, "en-US")).toBe("");
  });
});

describe("elapsed", () => {
  it("reads as a clock, with hours only past the hour", () => {
    expect(elapsed(at(2026, 8, 24, 20, 27), now)).toBe("3:00");
    expect(elapsed(new Date(now.getTime() - 3_849_000).toISOString(), now)).toBe("1:04:09");
    expect(elapsed(new Date(now.getTime() + 5_000).toISOString(), now)).toBe("0:00");
  });
});
