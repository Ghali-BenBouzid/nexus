import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { I } from "../icons";
import { t } from "../lib/i18n";
import { markTourSeen, tourSteps, type TourStep } from "../lib/tour";

// How far the lit area extends past the control it lifts, and how far the
// popover sits off it.
const PAD = 8;
const GAP = 14;
const CARD_W = 320;

// How long the spotlight takes to travel between steps. A fixed duration meant
// the velocity rose with the distance: the short hop from the mode pill to the
// attach button read well, and the long one across to the Outputs panel covered
// six times the ground in the same time and looked thrown rather than moved.
// Time grows with distance now, so the speed has a ceiling.
const MIN_MS = 400;
const MAX_MS = 760;
const MAX_SPEED = 1200; // pixels per second
type Box = { top: number; left: number; width: number; height: number };

// Only the duration is decided here. The curve is the one every other moving
// thing in the app uses, set in the stylesheet: a tour that eased differently
// from the rest of the interface would be the tour drawing attention to itself.
function travelMs(from: Box | null, to: Box | null): number {
  if (!from || !to) return MIN_MS;
  const dist = Math.hypot(
    to.left + to.width / 2 - (from.left + from.width / 2),
    to.top + to.height / 2 - (from.top + from.height / 2),
  );
  return Math.min(MAX_MS, Math.max(MIN_MS, (dist / MAX_SPEED) * 1000));
}

function find(target: string | null, pad = PAD): Box | null {
  if (!target) return null;
  const el = document.querySelector<HTMLElement>(`[data-tour="${target}"]`);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  if (r.width === 0 && r.height === 0) return null; // rendered but hidden
  return { top: r.top - pad, left: r.left - pad, width: r.width + pad * 2, height: r.height + pad * 2 };
}

// Where the card goes relative to the lit area. Four placements, then a clamp,
// because two were not enough: a full-height target like the Outputs panel has
// no room below it and no room above it either, and the old code answered that
// by placing the card off the top of the screen.
function place(box: Box | null, cardH: number): React.CSSProperties {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  if (!box) return { top: Math.max(12, vh / 2 - cardH / 2), left: vw / 2 - CARD_W / 2 };

  let top: number;
  let left: number;
  if (box.top + box.height + GAP + cardH < vh) {
    top = box.top + box.height + GAP;
    left = box.left + box.width / 2 - CARD_W / 2;
  } else if (box.top - GAP - cardH > 0) {
    top = box.top - GAP - cardH;
    left = box.left + box.width / 2 - CARD_W / 2;
  } else if (box.left + box.width + GAP + CARD_W < vw) {
    left = box.left + box.width + GAP;
    top = box.top + box.height / 2 - cardH / 2;
  } else {
    left = box.left - GAP - CARD_W;
    top = box.top + box.height / 2 - cardH / 2;
  }
  // Whatever the placement decided, the card has to be on screen.
  return {
    top: Math.min(Math.max(12, top), Math.max(12, vh - 12 - cardH)),
    left: Math.min(Math.max(12, left), Math.max(12, vw - 12 - CARD_W)),
  };
}

// A quick tour of what Nexus does, for someone handed a demo account who would
// otherwise never find deep research or fact check. It points, and the user
// acts: nothing is typed or sent on their behalf, so nothing here can spend
// their budget. The one thing it does itself is open a chat, because half the
// features do not exist on the landing page.
export function Tour({
  onView,
  onFinish,
}: {
  // Move the app to where the next step lives. The tour never asks the user to
  // navigate; it would be a poor guide that began by getting you lost.
  onView: (view: "home" | "chat") => void;
  onFinish: () => void;
}) {
  const [steps] = useState(tourSteps);
  const [i, setI] = useState(0);
  const [box, setBox] = useState<Box | null>(null);
  // Measured, not assumed: the placement has to know how tall the card actually
  // is before it can tell whether it fits above or below the target.
  const [cardH, setCardH] = useState(190);
  const cardRef = useRef<HTMLDivElement>(null);
  // Where the spotlight was, so the next move knows how far it has to go.
  const from = useRef<Box | null>(null);
  const [moveMs, setMoveMs] = useState(MIN_MS);
  const step: TourStep | undefined = steps[i];

  const close = () => {
    markTourSeen();
    onFinish();
  };

  // Each step decides where the app has to be before it can point at anything.
  useEffect(() => {
    if (step) onView(step.view);
    // Keyed on the step index alone: onView is rebuilt on every App render and
    // depending on it would re-run this on every keystroke in the composer.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [i]);

  // A target below the fold is brought up once, when the step opens. Doing this
  // inside measure() would fight its own smooth scroll: each frame of the scroll
  // fires a scroll event, which would ask for another scroll.
  useEffect(() => {
    if (!step?.target) return;
    const id = requestAnimationFrame(() => {
      const el = document.querySelector(`[data-tour="${step.target}"]`);
      const r = el?.getBoundingClientRect();
      if (!r) return;
      if (r.top < 8 || r.bottom > window.innerHeight - 8) {
        el?.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    });
    return () => cancelAnimationFrame(id);
  }, [i, step]);

  // The card's own height, read back after it renders. Two steps with different
  // amounts of text are different heights, and a placement that guesses will put
  // one of them half off the screen.
  useLayoutEffect(() => {
    const h = cardRef.current?.getBoundingClientRect().height;
    if (h && Math.abs(h - cardH) > 1) setCardH(h);
  });

  // Measure after the DOM has settled on the new view, and keep measuring while
  // the window moves under it.
  useLayoutEffect(() => {
    if (!step) return;
    let raf = 0;
    const measure = () => {
      const next = find(step.target, step.pad);
      setMoveMs(travelMs(from.current, next));
      from.current = next;
      setBox(next);
    };
    // A frame later: a step that just changed view is pointing at something
    // React has not committed yet.
    raf = requestAnimationFrame(() => {
      measure();
      raf = requestAnimationFrame(measure);
    });
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [i, step]);

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      // The card owns the keyboard while it is up: the page behind it is dimmed
      // and not meant to be typed into.
      if (e.key === "Escape") {
        e.preventDefault();
        close();
      }
      if (e.key === "ArrowRight" || e.key === "Enter") setI((n) => n + 1);
      if (e.key === "ArrowLeft") setI((n) => Math.max(0, n - 1));
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  });

  useEffect(() => {
    if (i >= steps.length) close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [i, steps.length]);

  if (!step) return null;
  const style = place(box, cardH);
  const last = i === steps.length - 1;

  return (
    <div className="tour" role="dialog" aria-modal="true" aria-label={t.tour.title}>
      {/* The mask is one element with a huge spread shadow, so the lit area is a
          real hole: everything outside it dims, and the control underneath stays
          its own colour rather than being tinted by an overlay drawn on top. */}
      <div className={"tour-mask" + (box ? " lit" : "")} onClick={close}>
        {box && (
          <div
            className="tour-hole"
            style={{
              top: box.top,
              left: box.left,
              width: box.width,
              height: box.height,
              transitionDuration: `${moveMs}ms`,
            }}
          />
        )}
      </div>

      <div
        className="tour-card"
        ref={cardRef}
        style={{ ...style, transitionDuration: `${moveMs}ms` }}
      >
        <div className="tour-card-head">
          <h3>{step.title}</h3>
          <button type="button" className="tour-x" onClick={close} aria-label={t.tour.skip}>
            {I.close}
          </button>
        </div>
        <p>{step.body}</p>
        <div className="tour-nav">
          <span className="tour-dots" aria-hidden="true">
            {steps.map((s, n) => (
              <i key={s.id} className={n === i ? "on" : undefined} />
            ))}
          </span>
          <button type="button" className="tour-skip" onClick={close}>
            {t.tour.skip}
          </button>
          {i > 0 && (
            <button type="button" className="tour-back" onClick={() => setI(i - 1)}>
              {t.tour.back}
            </button>
          )}
          <button type="button" className="tour-next" onClick={() => setI(i + 1)}>
            {last ? t.tour.done : t.tour.next}
            {!last && I.arrowRight}
          </button>
        </div>
      </div>
    </div>
  );
}
