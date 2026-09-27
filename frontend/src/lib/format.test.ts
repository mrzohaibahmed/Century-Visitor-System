import { describe, expect, it } from "vitest";

import { ApiError, fieldErrors } from "./api/client";
import { formatDuration, isoDay, parseList } from "./format";

describe("formatDuration", () => {
  const start = "2026-09-27T08:00:00Z";
  it.each([
    ["2026-09-27T08:00:30Z", "0 min"],
    ["2026-09-27T08:45:00Z", "45 min"],
    ["2026-09-27T10:05:00Z", "2 h 05 min"],
    ["2026-09-30T12:00:00Z", "3 d 4 h"],
    ["2026-09-27T07:00:00Z", "0 min"], // clock skew never shows a negative time
  ])("until %s is %s", (end, expected) => {
    expect(formatDuration(start, end)).toBe(expected);
  });

  it("measures until now when the visit is still open", () => {
    expect(formatDuration(start, null, new Date("2026-09-27T09:30:00Z"))).toBe("1 h 30 min");
  });
});

describe("parseList", () => {
  it("splits on commas, semicolons and new lines and drops blanks", () => {
    expect(parseList(" laptop, bag;;umbrella\n , ")).toEqual(["laptop", "bag", "umbrella"]);
  });
});

describe("isoDay", () => {
  it("formats a local date for date inputs", () => {
    expect(isoDay(new Date(2026, 0, 5))).toBe("2026-01-05");
  });
});

describe("fieldErrors", () => {
  it("keys validation messages by top-level body field", () => {
    const error = new ApiError(422, "validation_error", "Invalid", null, [
      { field: "body.identity.number", message: "A CNIC must have exactly 13 digits." },
      { field: "body.full_name", message: "Enter a name." },
      { field: "body", message: "Nothing to change." },
    ]);
    expect(fieldErrors(error)).toEqual({
      identity: "A CNIC must have exactly 13 digits.", full_name: "Enter a name.", _form: "Nothing to change.",
    });
  });

  it("is empty for anything that is not an API validation error", () => {
    expect(fieldErrors(new Error("boom"))).toEqual({});
  });
});
