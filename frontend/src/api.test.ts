import { afterEach, describe, expect, it, vi } from "vitest";

import { api, ApiError } from "./api";
import { startOfToday, toISO } from "./format";

afterEach(() => vi.unstubAllGlobals());

const reply = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

describe("api requests", () => {
  it("tell the server what day it is for the visitor", async () => {
    const fetchMock = vi.fn().mockResolvedValue(reply([]));
    vi.stubGlobal("fetch", fetchMock);
    await api.commitments();
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(new Headers(init.headers).get("X-Kept-Today")).toBe(toISO(startOfToday()));
  });

  it("keep the content type of a JSON post alongside the date", async () => {
    const fetchMock = vi.fn().mockResolvedValue(reply({}));
    vi.stubGlobal("fetch", fetchMock);
    await api.prepare(3, "Austin");
    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(path).toBe("/api/commitments/3/prepare");
    expect(headers.get("content-type")).toBe("application/json");
    expect(headers.get("X-Kept-Today")).toBeTruthy();
    expect(JSON.parse(String(init.body))).toEqual({ details: "Austin" });
  });

  it("report what Kept needs when it cannot do a promise alone", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply({ detail: "Needs you", needs: ["city", 7] }, 409)));
    const error = await api.prepare(1).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toBe("Needs you");
    expect((error as ApiError).needs).toEqual(["city"]);
  });

  it("report ordinary failures without a needs list", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply({ detail: "Nope" }, 502)));
    const error = (await api.sweep().catch((e: unknown) => e)) as ApiError;
    expect(error.message).toBe("Nope");
    expect(error.needs).toBeNull();
  });

  it("explain when the server cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    await expect(api.commitments()).rejects.toThrow("Can't reach the Kept server");
  });
});
