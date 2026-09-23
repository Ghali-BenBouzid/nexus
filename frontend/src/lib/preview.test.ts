import { describe, expect, it } from "vitest";

import { UPLOAD_EXTENSIONS } from "./uploads";
import { prettyText, previewKind } from "./preview";

describe("previewKind", () => {
  it("has a way to show every file that can be attached", () => {
    for (const ext of UPLOAD_EXTENSIONS) expect(previewKind("f" + ext)).not.toBeNull();
  });

  it("tells the formats apart", () => {
    expect(previewKind("Report.PDF")).toBe("pdf");
    expect(previewKind("notes.markdown")).toBe("markdown");
    expect(previewKind("brief.docx")).toBe("docx");
    expect(previewKind("data.csv")).toBe("text");
    expect(previewKind("photo.png")).toBeNull();
  });
});

describe("prettyText", () => {
  it("indents JSON and leaves a broken file as it came", () => {
    expect(prettyText("a.json", '{"a":1}')).toBe('{\n  "a": 1\n}');
    expect(prettyText("a.json", "{nope")).toBe("{nope");
    expect(prettyText("a.txt", '{"a":1}')).toBe('{"a":1}');
  });
});
