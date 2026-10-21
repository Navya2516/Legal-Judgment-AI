import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, request } from "../src/api/client";

function mockFetch(impl) {
  globalThis.fetch = vi.fn(impl);
  return globalThis.fetch;
}
const json = (status, body) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));

afterEach(() => vi.restoreAllMocks());

describe("request", () => {
  it("returns parsed JSON", async () => {
    mockFetch(() => json(200, { ok: 1 }));
    expect(await request("/x")).toEqual({ ok: 1 });
  });
  it("turns the backend error shape into ApiError", async () => {
    mockFetch(() => json(404, { error: { code: "not_generated", message: "No summary yet." } }));
    await expect(request("/x")).rejects.toMatchObject({ name: "ApiError", status: 404, code: "not_generated", message: "No summary yet." });
  });
  it("copes with non-JSON error bodies", async () => {
    mockFetch(() => Promise.resolve(new Response("<html>bad gateway</html>", { status: 502 })));
    await expect(request("/x")).rejects.toMatchObject({ status: 502, code: "http_502" });
  });
  it("reports an unreachable server as network", async () => {
    mockFetch(() => Promise.reject(new TypeError("Failed to fetch")));
    await expect(request("/x")).rejects.toMatchObject({ code: "network" });
  });
  it("handles 204 with no body", async () => {
    mockFetch(() => Promise.resolve(new Response(null, { status: 204 })));
    expect(await request("/x", { method: "DELETE" })).toBeNull();
  });
});

describe("api", () => {
  it("builds the right calls", async () => {
    const f = mockFetch(() => json(200, {}));
    await api.readSummary("abc", "ta");
    expect(f.mock.calls[0][0]).toMatch(/\/api\/v1\/documents\/abc\/summary\/ta$/);
    await api.generateContinuation("abc", "high_court");
    expect(f.mock.calls[1][0]).toMatch(/continuation\?court_level=high_court$/);
    await api.generateContinuation("abc", undefined);
    expect(f.mock.calls[2][0]).toMatch(/continuation$/);
    await api.ask("abc", { question: "Why?", lang: "hi" });
    expect(f.mock.calls[3][1].method).toBe("POST");
    expect(JSON.parse(f.mock.calls[3][1].body)).toEqual({ question: "Why?", lang: "hi", top_k: 6 });
  });
  it("encodes the document id", async () => {
    const f = mockFetch(() => json(200, {}));
    await api.getDocument("a/b");
    expect(f.mock.calls[0][0]).toMatch(/documents\/a%2Fb$/);
  });
  it("uploads as multipart without a manual content type", async () => {
    const f = mockFetch(() => json(202, { id: "1" }));
    await api.uploadDocument(new File(["%PDF"], "j.pdf", { type: "application/pdf" }));
    const init = f.mock.calls[0][1];
    expect(init.body).toBeInstanceOf(FormData);
    expect(init.headers["Content-Type"]).toBeUndefined();
  });
  it("exposes ApiError", () => expect(new ApiError({ code: "x" })).toBeInstanceOf(Error));
});
