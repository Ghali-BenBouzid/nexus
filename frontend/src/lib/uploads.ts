// What can be attached, in one place. The file dialog's filter, the drop
// target's filter and the message a rejected file gets all have to agree, and
// they have to agree with the parser: anything else is accepted by the UI and
// then refused by the server, which is the worst of both.
//
// Mirrors SUPPORTED in app/documents/parser.py.
export const UPLOAD_EXTENSIONS = [
  ".pdf",
  ".docx",
  ".txt",
  ".md",
  ".markdown",
  ".csv",
  ".json",
  ".rst",
  ".log",
];

export const UPLOAD_ACCEPT = UPLOAD_EXTENSIONS.join(",");

export function isSupported(file: File): boolean {
  const name = file.name.toLowerCase();
  return UPLOAD_EXTENSIONS.some((ext) => name.endsWith(ext));
}

// A drag carries files only once it is dropped: before that the browser exposes
// the items but not their names, so a drag is judged by kind alone.
export function dragHasFiles(dt: DataTransfer | null): boolean {
  return !!dt && Array.from(dt.types).includes("Files");
}
