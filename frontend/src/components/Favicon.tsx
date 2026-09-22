import { useState } from "react";

import { faviconUrl, monogram } from "../lib/favicon";

// A source's mark. It tries the real favicon and falls back to a letter the
// moment anything goes wrong: a blocked request, an offline browser, a domain
// with no icon. The fallback is not an error state, it is the normal look for
// a fair share of sources, so it is drawn to belong rather than to apologise.
export function Favicon({ url, size = 16 }: { url: string; size?: number }) {
  const [failed, setFailed] = useState(false);
  const src = failed ? null : faviconUrl(url, size <= 16 ? 32 : 64);

  if (!src) {
    const { letter, hue } = monogram(url);
    return (
      <span
        className="fav fav-mono"
        aria-hidden="true"
        style={{
          width: size,
          height: size,
          fontSize: Math.round(size * 0.6),
          background: `hsl(${hue} 42% 42%)`,
        }}
      >
        {letter}
      </span>
    );
  }

  return (
    <img
      className="fav"
      src={src}
      alt=""
      width={size}
      height={size}
      loading="lazy"
      onError={() => setFailed(true)}
    />
  );
}
