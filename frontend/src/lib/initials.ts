// The letters on an account's avatar: the first of the first two words of its
// name. Read as characters rather than UTF-16 units, so an accented or non-Latin
// name keeps its first letter whole.
export function initials(name: string): string {
  const letters = name
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => Array.from(word)[0]);
  return letters.join("").toLocaleUpperCase() || "?";
}
