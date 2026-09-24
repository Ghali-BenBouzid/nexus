// A heading's anchor, the way GitHub makes one: lowercase, punctuation dropped,
// spaces hyphenated.
//
// Its own module because both ends have to agree on the spelling. A report's
// summary table links to its own sections, so the slug a heading gets here is
// the slug the model has to have written in the table. Where it does not match
// exactly, `resolve` below is what closes the gap.
export function slug(text: string): string {
  return decoded(text)
    // Accents go, letters stay: "Vérifié" and the link written for it both
    // become "verifie". Dropping the letter instead broke every French link.
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s-]/gu, "")
    .trim()
    // Runs collapse to one. A claim header reads "Supported - the merger
    // closed", and the dash plus its two spaces would otherwise become three
    // hyphens, while the link the model writes for it has one.
    .replace(/[\s-]+/g, "-")
    .replace(/^-|-$/g, "");
}

// The id a link means, among the ids a document actually has.
//
// Tolerant on purpose. A model writing a link to its own heading gets the slug
// close but not always exact: it drops the verdict the heading carries, or
// keeps a word the heading dropped. An exact match wins; otherwise the one
// heading that contains the target (or is contained by it) does. Anything
// ambiguous resolves to nothing, because scrolling somewhere arbitrary is
// worse than not scrolling.
export function resolve(target: string, ids: string[]): string | null {
  const want = slug(target.replace(/^#/, ""));
  if (ids.includes(want)) return want;
  const near = ids.filter((id) => id.includes(want) || want.includes(id));
  if (near.length === 1) return near[0];
  // A model sometimes rewords the claim in the link. The heading that shares
  // most of its words wins, if it clearly does.
  const scored = ids
    .map((id) => ({ id, score: overlap(want, id) }))
    .sort((a, b) => b.score - a.score);
  const [best, next] = scored;
  if (!best || best.score < 0.5) return null;
  return next && next.score === best.score ? null : best.id;
}

// The share of words two slugs have in common, of the smaller one's.
function overlap(a: string, b: string): number {
  const x = new Set(a.split("-"));
  const y = new Set(b.split("-"));
  const shared = [...x].filter((w) => y.has(w)).length;
  return shared / Math.min(x.size, y.size);
}

// A link's target arrives percent-encoded ("v%C3%A9rifi%C3%A9"), a heading's
// text does not.
function decoded(text: string): string {
  try {
    return decodeURIComponent(text);
  } catch {
    return text;
  }
}
