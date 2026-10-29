import { describe, expect, it } from "vitest";
import { formatCost, formatMs, parseTime, pathOf, plural, shortUrl, timeAgo } from "./format";

describe("formatMs", () => {
  it("scales from milliseconds to minutes", () => {
    expect(formatMs(420)).toBe("420 ms");
    expect(formatMs(4200)).toBe("4.2 s");
    expect(formatMs(125_000)).toBe("2m 05s");
    expect(formatMs(119_700)).toBe("2m 00s");
  });
});

describe("formatCost", () => {
  it("handles missing, zero, tiny and normal costs", () => {
    expect(formatCost(null)).toBe("n/a");
    expect(formatCost(0)).toBe("$0");
    expect(formatCost(0.00412)).toBe("$0.0041");
    expect(formatCost(1.23456)).toBe("$1.235");
  });
});

describe("timeAgo", () => {
  const now = Date.parse("2026-10-28T12:00:00Z");
  it("reads naive timestamps as UTC", () => {
    expect(timeAgo("2026-10-28T11:55:00", now)).toBe("5 minutes ago");
    expect(timeAgo("2026-10-28T11:59:50+00:00", now)).toBe("just now");
    expect(timeAgo("2026-10-27T12:00:00Z", now)).toBe("yesterday");
  });
  it("returns an empty string for garbage", () => {
    expect(timeAgo("not a date", now)).toBe("");
  });
});

describe("parseTime", () => {
  it("accepts offsets, Z and naive UTC alike", () => {
    const t = Date.parse("2026-10-28T15:31:31Z");
    expect(parseTime("2026-10-28T15:31:31+00:00")).toBe(t);
    expect(parseTime("2026-10-28T15:31:31Z")).toBe(t);
    expect(parseTime("2026-10-28T15:31:31")).toBe(t);
    expect(parseTime("2026-10-28T17:31:31+02:00")).toBe(t);
  });
});

describe("urls", () => {
  it("shortens to host and path", () => {
    expect(shortUrl("http://localhost:8100/demo/shop/")).toBe("localhost:8100/demo/shop/");
    expect(shortUrl("https://example.com/")).toBe("example.com");
    expect(shortUrl("nope")).toBe("nope");
  });
  it("shows same-origin URLs as paths", () => {
    expect(pathOf("http://localhost:8100/demo/shop/cart?x=1", "http://localhost:8100/demo/shop/")).toBe(
      "/demo/shop/cart?x=1",
    );
    expect(pathOf("https://cdn.example.com/a.js", "http://localhost:8100/")).toBe("cdn.example.com/a.js");
  });
});

it("pluralizes", () => {
  expect(plural(1, "bug")).toBe("1 bug");
  expect(plural(3, "bug")).toBe("3 bugs");
  expect(plural(2, "flaky test", "flaky tests")).toBe("2 flaky tests");
});
