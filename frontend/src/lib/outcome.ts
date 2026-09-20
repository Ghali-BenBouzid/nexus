import type { Outcome, Status } from "../types";

// The single rule for deriving a turn's display outcome from its status and what
// it produced. Shared by the live poller and the rehydration paths so a freshly
// run turn and a reloaded one never disagree. Only terminal states carry a real
// outcome: a non-terminal status has none yet, so it defaults to "ok".
// "empty" means the turn finished with nothing to show, which is the one case
// worth offering to reword.
export function outcomeFor(status: Status, answer: string, sourceCount: number): Outcome {
  if (status === "failed") return "failed";
  if (status === "complete" && !answer.trim() && sourceCount === 0) return "empty";
  return "ok";
}
