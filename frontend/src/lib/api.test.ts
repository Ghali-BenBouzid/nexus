import { afterEach, describe, expect, it, vi } from "vitest";

import { redeemInvite } from "./api";
import { t } from "./i18n";

function respond(status: number, detail: string) {
  const store = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  });
  vi.stubGlobal("fetch", async () => new Response(JSON.stringify({ detail }), { status }));
}

describe("redeemInvite", () => {
  afterEach(() => vi.unstubAllGlobals());

  // The server says why in English; the visitor gets it in the page's language,
  // with what to do next.
  it("explains a link that is not valid", async () => {
    respond(401, "This invite link is not valid.");
    await expect(redeemInvite("nope")).rejects.toThrow(t.access.invalid);
  });

  it("explains a link that has expired", async () => {
    respond(403, "This demo access has expired. Ask for a new invite link.");
    await expect(redeemInvite("old")).rejects.toThrow(t.access.expired);
  });

  it("keeps the server's reason for anything else", async () => {
    respond(500, "Something broke.");
    await expect(redeemInvite("x")).rejects.toThrow("Something broke.");
  });
});
