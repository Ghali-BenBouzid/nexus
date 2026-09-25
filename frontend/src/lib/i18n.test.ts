import { describe, expect, it } from "vitest";

import * as i18n from "./i18n";

describe("setLang", () => {
  it("switches the dictionary in place and tells the app, without a reload", () => {
    let told = 0;
    const stop = i18n.onLangChange(() => told++);

    i18n.setLang("fr");
    // Read through the module, as a component does at render: the binding is live.
    expect(i18n.lang).toBe("fr");
    expect(i18n.t.uploads.reading).toBe("Lecture");
    i18n.setLang("en");
    expect(i18n.t.uploads.reading).toBe("Reading");
    expect(told).toBe(2);

    stop();
    i18n.setLang("fr");
    expect(told).toBe(2);
    i18n.setLang("en");
  });
});
