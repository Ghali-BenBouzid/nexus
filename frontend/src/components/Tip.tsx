import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { t } from "../lib/i18n";
import type { Tip as TipDef } from "../lib/tour";
import { CARD_W, find, place, type Box } from "./Tour";

// Room left at the screen edge for the ring's pulsing halo.
const EDGE = 12;

const same = (a: Box | null, b: Box | null) =>
  a === b ||
  (!!a && !!b && a.top === b.top && a.left === b.left && a.width === b.width && a.height === b.height);

// A one-time bubble next to something that just happened. Unlike the tour it
// dims nothing and takes no focus: the user may be mid-sentence in the composer,
// and a tip is worth a glance, not an interruption. It stays until "Got it", so
// it cannot vanish before it was read.
export function Tip({ tip, onDone }: { tip: TipDef; onDone: () => void }) {
  const [box, setBox] = useState<Box | null>(null);
  const [near, setNear] = useState<Box | null>(null);
  const [cardH, setCardH] = useState(150);
  const cardRef = useRef<HTMLDivElement>(null);

  // Followed every frame rather than on resize and scroll alone: what it points
  // at moves on its own, as the Outputs panel slides in or a row is added above.
  // ponytail: one querySelector a frame, only while a tip is up.
  useEffect(() => {
    let raf = 0;
    let last: Box | null = null;
    let lastNear: Box | null = null;
    const tick = () => {
      let next: Box | null = null;
      for (const target of tip.targets) if ((next = find(target, 4))) break;
      // A row that runs to the edge of the screen would have its ring cut off
      // there, so the ring stays inside, halo and all.
      if (next) {
        const right = Math.min(next.left + next.width, window.innerWidth - EDGE);
        const left = Math.max(next.left, EDGE);
        next = { ...next, left, width: right - left };
      }
      if (!same(next, last)) setBox((last = next));
      const around = tip.around ? find(tip.around, 0) : null;
      if (!same(around, lastNear)) setNear((lastNear = around));
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [tip]);

  useLayoutEffect(() => {
    const h = cardRef.current?.getBoundingClientRect().height;
    if (h && Math.abs(h - cardH) > 1) setCardH(h);
  });

  // Nothing to point at (the user went home, or the control is not on this
  // screen): wait for it to come back rather than float over nothing.
  if (!box) return null;
  const copy = t.tips[tip.id];
  // Clear of the larger box, but lined up with the ring, so the card still
  // reads as belonging to what it points at.
  const style = place(near ?? box, cardH);
  if (near) style.left = Math.max(12, Math.min(box.left, window.innerWidth - 12 - CARD_W));
  return (
    <>
      <div
        className="tip-ring"
        aria-hidden="true"
        style={{ top: box.top, left: box.left, width: box.width, height: box.height }}
      />
      <div
        className="tour-card tip-card"
        ref={cardRef}
        role="dialog"
        aria-labelledby="tip-title"
        style={style}
      >
        <h3 id="tip-title">{copy.title}</h3>
        <p>{copy.body}</p>
        <div className="tour-nav">
          <button type="button" className="tour-next" onClick={onDone}>
            {t.tips.gotIt}
          </button>
        </div>
      </div>
    </>
  );
}
