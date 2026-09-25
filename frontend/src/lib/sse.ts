// Reading a server-sent events body.
//
// Its own module because the parsing is the fiddly part and deserves a test:
// frames are separated by a blank line and a read can end anywhere, including
// halfway through one, so whatever follows the last separator is held back
// until the rest of it turns up.

// One frame of the agent feed. A stored event carries the feed cursor as `id`;
// a live one (a thought, a token) has none, because it is never stored.
export type StreamFrame = {
  id?: number;
  at?: string; // when a replayed event happened; a live one happens now
  type: string;
  message: string;
  data: Record<string, unknown> | null;
};

export async function* sseFrames(
  body: ReadableStream<Uint8Array>,
  signal?: AbortSignal,
): AsyncGenerator<StreamFrame> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (!signal?.aborted) {
      const { done, value } = await reader.read();
      if (done) return;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() ?? "";
      for (const part of parts) {
        const frame = parseFrame(part);
        if (frame) yield frame;
      }
    }
  } finally {
    await reader.cancel().catch(() => {});
  }
}

// One frame, or null for anything we should ignore: a keep-alive comment, or a
// frame we cannot read. A bad frame is dropped, never the stream that carries
// every other one.
function parseFrame(part: string): StreamFrame | null {
  const line = part.split("\n").find((l) => l.startsWith("data: "));
  if (!line) return null;
  try {
    return JSON.parse(line.slice("data: ".length)) as StreamFrame;
  } catch {
    return null;
  }
}
