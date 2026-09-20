// A heading's anchor, the way GitHub makes one: lowercase, punctuation dropped,
// spaces hyphenated.
//
// Its own module because both ends have to agree on the spelling. A report's
// summary table links to its own sections, so the slug a heading gets here is
// the slug the model has to have written in the table. Where it does not match
// exactly, `resolve` below is what closes the gap.
export function slug(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\w\s-]/g, "")
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
  return near.length === 1 ? near[0] : null;
}
