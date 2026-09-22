import { useEffect, useLayoutEffect, useState } from "react";

import { I } from "../icons";
import { t } from "../lib/i18n";
import { markTourSeen, tourSteps, type TourStep } from "../lib/tour";

// How far the lit area extends past the control it lifts, and how far the
// popover sits off it.
const PAD = 8;
const GAP = 14;
const CARD_W = 320;

type Box = { top: number; left: number; width: number; height: number };

function find(target: string | null): Box | null {
  if (!target) return null;
  const el = document.querySelector<HTMLElement>(`[data-tour="${target}"]`);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  if (r.width === 0 && r.height === 0) return null; // rendered but hidden
  return { top: r.top - PAD, left: r.left - PAD, width: r.width + PAD * 2, height: r.height + PAD * 2 };
}

// Where the card goes relative to the lit area: below it when there is room,
// above it otherwise, and centred on screen when nothing is lit.
function place(box: Box | null): React.CSSProperties {
  if (!box) return { top: "50%", left: "50%", transform: "translate(-50%, -50%)" };
  const below = window.innerHeight - (box.top + box.height) > 190;
  const left = Math.min(
    Math.max(12, box.left + box.width / 2 - CARD_W / 2),
    window.innerWidth - CARD_W - 12,
  );
  return below
    ? { top: box.top + box.height + GAP, left }
    : { bottom: window.innerHeight - box.top + GAP, left };
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

  // Measure after the DOM has settled on the new view, and keep measuring while
  // the window moves under it.
  useLayoutEffect(() => {
    if (!step) return;
    let raf = 0;
    const measure = () => setBox(find(step.target));
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
      if (e.key === "Escape") close();
      if (e.key === "ArrowRight" || e.key === "Enter") setI((n) => n + 1);
      if (e.key === "ArrowLeft") setI((n) => Math.max(0, n - 1));
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  });

  useEffect(() => {
    if (i >= steps.length) close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [i, steps.length]);

  if (!step) return null;
  const style = place(box);
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
            style={{ top: box.top, left: box.left, width: box.width, height: box.height }}
          />
        )}
      </div>

      <div className="tour-card" style={style}>
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
