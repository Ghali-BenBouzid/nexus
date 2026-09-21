import { describe, expect, it } from "vitest";

import { sseFrames, type StreamFrame } from "./sse";

// A body that hands back exactly these pieces, so a test can split a frame
// across reads the way a socket does.
function body(...chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

const frame = (payload: object) => `data: ${JSON.stringify(payload)}\n\n`;

async function read(stream: ReadableStream<Uint8Array>): Promise<StreamFrame[]> {
  const frames: StreamFrame[] = [];
  for await (const f of sseFrames(stream)) frames.push(f);
  return frames;
}

describe("sseFrames", () => {
  it("reads whole frames", async () => {
    const frames = await read(
      body(frame({ type: "token", message: "Hel" }), frame({ type: "token", message: "lo" })),
    );

    expect(frames.map((f) => f.message).join("")).toBe("Hello");
  });

  it("holds back a frame split across reads", async () => {
    const whole = frame({ type: "token", message: "Hello" });
    const cut = Math.floor(whole.length / 2);

    const frames = await read(body(whole.slice(0, cut), whole.slice(cut)));

    expect(frames).toHaveLength(1);
    expect(frames[0].message).toBe("Hello");
  });

  it("joins several frames arriving in one read", async () => {
    const frames = await read(
      body(frame({ type: "thought", message: "a" }) + frame({ type: "token", message: "b" })),
    );

    expect(frames.map((f) => f.type)).toEqual(["thought", "token"]);
  });

  it("ignores keep-alive comments", async () => {
    const frames = await read(body(": keep-alive\n\n", frame({ type: "done", message: "" })));

    expect(frames.map((f) => f.type)).toEqual(["done"]);
  });

  it("drops a frame it cannot read, not the stream", async () => {
    const frames = await read(
      body("data: {not json\n\n", frame({ type: "token", message: "still here" })),
    );

    expect(frames.map((f) => f.message)).toEqual(["still here"]);
  });

  it("keeps the cursor on a stored frame and leaves a live one without", async () => {
    const frames = await read(
      body(frame({ id: 7, type: "thinking", message: "" }), frame({ type: "token", message: "x" })),
    );

    expect(frames[0].id).toBe(7);
    expect(frames[1].id).toBeUndefined();
  });
});
