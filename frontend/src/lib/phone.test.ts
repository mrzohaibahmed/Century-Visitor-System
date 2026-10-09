import { describe, expect, it } from "vitest";

import { normalizePhone, phoneError } from "./phone";

describe("normalizePhone", () => {
  it.each([
    ["0300-1234567", "03001234567"],
    ["(042) 3571-2345", "04235712345"],
    ["0300 123 4567", "03001234567"],
    ["+92 300 1234567", "+923001234567"],
    ["+92 (42) 3571-2345", "+924235712345"],
    ["", null],
    ["   ", null],
  ])("normalises %j to %j", (raw, expected) => {
    expect(normalizePhone(raw)).toBe(expected);
  });

  it.each(["123", "13001234567", "0300+1234567", "+920300123456", "0300-123456789012345", "call me"])("rejects %j", (raw) => {
    expect(() => normalizePhone(raw)).toThrow(/11 digits/);
  });
});

describe("phoneError", () => {
  it("is null for empty or valid numbers", () => {
    expect(phoneError("")).toBeNull();
    expect(phoneError("03001234567")).toBeNull();
    expect(phoneError("+92 300 1234567")).toBeNull();
  });

  it("returns a message for implausible numbers", () => {
    expect(phoneError("123")).toMatch(/11 digits/);
  });
});
