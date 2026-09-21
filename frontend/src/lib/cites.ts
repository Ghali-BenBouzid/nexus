// Citations arrive in the prose as [n] tokens, and adjacent ones are one act of
// sourcing: the writer is told to put them back to back ([1][3], never [1, 3]),
// because a claim backed by four pages has four receipts, not four separate
// things to say. Splitting them apart again is what leaves a paragraph carrying
// eight bare numbers, which is noise for every reader who was never going to
// click one. So they are grouped here, before anything renders them.

export type Segment = { text: string } | { ns: number[] };

// A run of citations, whitespace between them tolerated: a model that drifts
// from the house style should still have its citations grouped, not scattered.
const RUN = /((?:\[\d+\])(?:\s*\[\d+\])*)/g;
const ONE = /\[(\d+)\]/g;

export function segments(str: string): Segment[] {
  return str
    .split(RUN)
    .filter((part) => part !== "")
    .map((part) =>
      /^\[\d+\]/.test(part)
        ? // Deduplicated, and left in the writer's order: [2][2] is one receipt,
          // and sorting would quietly disagree with the sentence that earned them.
          { ns: [...new Set([...part.matchAll(ONE)].map((m) => +m[1]))] }
        : { text: part },
    );
}
