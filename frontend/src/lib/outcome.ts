import type { Outcome, Status } from "../types";

// The single rule for deriving a turn's display outcome from its status and
// result. Shared by the live poller and the rehydration paths so a freshly-run
// turn and a reloaded one never disagree. Only terminal states carry a real
// outcome: a non-terminal status (pending, running, awaiting_plan) has no outcome
// yet, so it defaults to "ok" (the plan/activity is shown by status, not outcome).
export function outcomeFor(status: Status, report: string, sourceCount: number): Outcome {
  if (status === "failed") return "failed";
  if (status === "complete" && !report.trim() && sourceCount === 0) return "empty";
  return "ok";
}
