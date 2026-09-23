import { describe, expect, it } from "vitest";

import { UPLOAD_ACCEPT, dragHasFiles, isSupported } from "./uploads";

const file = (name: string) => new File(["x"], name);

describe("isSupported", () => {
  it("takes what the parser can read", () => {
    expect(isSupported(file("report.pdf"))).toBe(true);
    expect(isSupported(file("notes.md"))).toBe(true);
    expect(isSupported(file("REPORT.PDF"))).toBe(true);
  });

  it("refuses what it cannot", () => {
    // .doc is not .docx: python-docx cannot open the old binary format, so
    // offering it only moves the failure to the server.
    expect(isSupported(file("legacy.doc"))).toBe(false);
    expect(isSupported(file("photo.png"))).toBe(false);
    expect(isSupported(file("pdf"))).toBe(false);
  });

  it("offers the same set to the file dialog", () => {
    expect(UPLOAD_ACCEPT).toContain(".pdf");
    expect(UPLOAD_ACCEPT).not.toContain(".doc,");
  });
});

describe("dragHasFiles", () => {
  const dt = (types: string[]) => ({ types }) as unknown as DataTransfer;

  it("is true only for a drag carrying files", () => {
    expect(dragHasFiles(dt(["Files"]))).toBe(true);
    expect(dragHasFiles(dt(["text/plain"]))).toBe(false);
    expect(dragHasFiles(null)).toBe(false);
  });
});
