// Where a source's little mark comes from.
//
// One helper, deliberately: this endpoint tells Google every domain our answers
// cite, which for a tool whose whole point is sourced research is a cost worth
// keeping in one place. Swapping provider, or dropping to monograms only, is a
// change to this file and nothing else.
//
// ponytail: third-party favicons, self-hosted or monogram-only if the privacy
// cost stops being acceptable.

export function domainOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    // A malformed url still has to render something rather than throw inside a
    // citation in the middle of a sentence.
    return url.replace(/^https?:\/\//, "").replace(/^www\./, "").split("/")[0];
  }
}

export function faviconUrl(url: string, size = 64): string | null {
  const domain = domainOf(url);
  if (!domain) return null;
  return `https://www.google.com/s2/favicons?domain=${encodeURIComponent(domain)}&sz=${size}`;
}

// The fallback, and the reason a failed request never leaves a hole: a letter
// and a colour derived from the domain itself, so one site always looks the
// same without anything being fetched or stored.
export function monogram(url: string): { letter: string; hue: number } {
  const domain = domainOf(url);
  let hash = 0;
  for (let i = 0; i < domain.length; i++) hash = (hash * 31 + domain.charCodeAt(i)) >>> 0;
  return { letter: (domain[0] ?? "?").toUpperCase(), hue: hash % 360 };
}
