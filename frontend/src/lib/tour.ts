// The quick tour: what a first-time visitor is shown, in order.
//
// Targets are found by a `data-tour` attribute rather than a class, so the tour
// survives a restyle. A step whose target is missing is skipped rather than
// pointing at nothing, which is what keeps it safe on a narrow screen where
// some controls are not rendered at all.
import { t } from "./i18n";

export type TourStep = {
  id: string;
  // The `data-tour` value to spotlight. Null centres the popover with no
  // cut-out, for a step that is about the product rather than a control.
  target: string | null;
  title: string;
  body: string;
  // Where the tour must be for this step to make sense. The tour moves the app
  // there itself; it never asks the user to navigate.
  view: "home" | "chat";
};

const SEEN_KEY = "nexus-tour-seen";

export function tourSeen(): boolean {
  try {
    return localStorage.getItem(SEEN_KEY) === "1";
  } catch {
    // A browser that refuses storage gets the tour every time, which is a far
    // better failure than never showing it at all.
    return false;
  }
}

export function markTourSeen(): void {
  try {
    localStorage.setItem(SEEN_KEY, "1");
  } catch {
    /* a lost flag costs a repeat tour, nothing more */
  }
}

// Four steps. What a chat box is for needs no explaining in 2026, so the tour
// spends its half-minute on the parts that are genuinely not obvious: that the
// two background runs exist at all, and where their reports end up.
export function tourSteps(): TourStep[] {
  // Landing first, then into a chat once, rather than bouncing between the two:
  // starting inside a chat would throw a first-time visitor somewhere they never
  // asked to go before saying anything at all.
  return [
    { id: "history", target: "history", view: "home", ...t.tour.history },
    { id: "deep", target: "mode", view: "chat", ...t.tour.deep },
    { id: "attach", target: "attach", view: "chat", ...t.tour.attach },
    { id: "outputs", target: "outputs", view: "chat", ...t.tour.outputs },
  ];
}
