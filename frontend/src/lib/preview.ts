// How an attached file is shown when it is opened. Decided by extension, the
// same way the parser decides how to read it, so the two never disagree about
// what a file is.
export type PreviewKind = "pdf" | "markdown" | "docx" | "text";

const TEXT = [".txt", ".csv", ".json", ".rst", ".log"];

export function previewKind(filename: string): PreviewKind | null {
  const name = filename.toLowerCase();
  if (name.endsWith(".pdf")) return "pdf";
  if (name.endsWith(".md") || name.endsWith(".markdown")) return "markdown";
  if (name.endsWith(".docx")) return "docx";
  if (TEXT.some((ext) => name.endsWith(ext))) return "text";
  return null;
}

// JSON reads better indented, and a file that says .json but is not is shown
// as it is rather than refused.
export function prettyText(filename: string, text: string): string {
  if (!filename.toLowerCase().endsWith(".json")) return text;
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}
