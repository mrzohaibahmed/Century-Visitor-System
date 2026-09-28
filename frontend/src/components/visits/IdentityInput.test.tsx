import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";

import type { IdentityType } from "@/lib/api/visitors";

import { cnicDigits, IdentityInput } from "./IdentityInput";

afterEach(cleanup);

function Harness({ initialType = "CNIC", initialNumber = "" }: { initialType?: IdentityType; initialNumber?: string }) {
  const [type, setType] = useState<IdentityType>(initialType);
  const [number, setNumber] = useState(initialNumber);
  return <IdentityInput type={type} number={number} onType={setType} onNumber={setNumber} />;
}

const field = () => screen.getByLabelText("ID number") as HTMLInputElement;
const type = (value: string) => fireEvent.change(field(), { target: { value } });

describe("IdentityInput", () => {
  it.each([["35201-1234567-1", "3520112345671"], ["35201 1234567 1", "3520112345671"], ["abc123", "123"],
           ["35201123456719999", "3520112345671"], ["", ""]])("cnicDigits(%j) → %j", (input, expected) => {
    expect(cnicDigits(input)).toBe(expected);
  });

  it("a CNIC accepts digits only, 13 at most", () => {
    render(<Harness />);
    type("35201-1234567-1");                                   // pasted with dashes: all 13 digits kept
    expect(field().value).toBe("3520112345671");
    type("35201-12a34567-1");
    expect(field().value).toBe("3520112345671");
    type("35201123456719");
    expect(field().value).toBe("3520112345671");
    expect(field().inputMode).toBe("numeric");
    expect(screen.getByText("Exactly 13 digits, numbers only (13 of 13).")).toBeTruthy();
  });

  it("counts the digits entered so far", () => {
    render(<Harness />);
    type("35201");
    expect(screen.getByText("Exactly 13 digits, numbers only (5 of 13).")).toBeTruthy();
  });

  it("passports and other IDs keep letters and separators", () => {
    render(<Harness initialType="PASSPORT" />);
    type("AB-1234567");
    expect(field().value).toBe("AB-1234567");
  });

  it("switching to CNIC drops what cannot be part of one", () => {
    render(<Harness initialType="PASSPORT" initialNumber="AB1234567" />);
    fireEvent.change(screen.getByLabelText("ID type"), { target: { value: "CNIC" } });
    expect(field().value).toBe("1234567");
  });
});
