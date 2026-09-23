// The letters on an account's avatar: the first of the first two words of its
// name, as plain letters. Accents are dropped (Élodie gives E), and letters are
// read as characters rather than UTF-16 units, so a non-Latin name keeps its
// first letter whole.
export function initials(name: string): string {
  const letters = name
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => Array.from(word)[0]);
  return letters.join("").toLocaleUpperCase() || "?";
}
