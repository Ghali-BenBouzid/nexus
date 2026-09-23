import { afterEach, describe, expect, it } from "vitest";

import { getRoute } from "./router";

const at = (pathname: string) => {
  (globalThis as { window?: unknown }).window = { location: { pathname } };
  return getRoute();
};

describe("getRoute", () => {
  afterEach(() => {
    delete (globalThis as { window?: unknown }).window;
  });

  it("opens a conversation by its opaque id", () => {
    const id = "3f2b8c1e-9a4d-4e6f-8b1a-2c3d4e5f6a7b";
    expect(at(`/chat/${id}`)).toEqual({ view: "chat", conversationId: id });
    expect(at(`/chat/${id.toUpperCase()}/`)).toEqual({ view: "chat", conversationId: id });
  });

  it("does not read an old integer link as a conversation", () => {
    expect(at("/chat/26")).toEqual({ view: "home", conversationId: null });
  });

  it("keeps a fresh chat fresh", () => {
    expect(at("/chat")).toEqual({ view: "chat", conversationId: null });
  });
});
