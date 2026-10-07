import { describe, expect, it } from "vitest";

import {
  belongingsFromStored, belongingsList, formatBelonging, personalMaterialFromVisit,
} from "./belongings";

describe("formatBelonging / belongingsList", () => {
  it("appends quantity in when present", () => {
    expect(formatBelonging({ description: "Laptop", qtyIn: "01", qtyOut: "" })).toBe("Laptop (01)");
  });
});

describe("belongingsFromStored", () => {
  it("parses quantity in parentheses", () => {
    expect(belongingsFromStored(["Laptop (01)", "Bag"])).toEqual([
      { description: "Laptop", qtyIn: "01", qtyOut: "" },
      { description: "Bag", qtyIn: "", qtyOut: "" },
    ]);
  });

  it("round-trips through belongingsList", () => {
    const pm = personalMaterialFromVisit(["Laptop (2)", "Charger"]);
    expect(belongingsList(pm)).toEqual(["Laptop (2)", "Charger"]);
  });
});
