import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PersonalMaterial } from "@/lib/belongings";

import { PersonalMaterialForm } from "./PersonalMaterialForm";

const MATERIAL: PersonalMaterial = {
  contactName: "Sara Ahmed",
  date: "2026-10-09",
  items: [{ description: "Laptop", qtyIn: "1", qtyOut: "" }],
  remarks: "Company device",
  authorisedBy: "A. Manager",
  issuedBy: "Reception",
  gateOfficer: "Officer Khan",
};

beforeEach(() => {
  window.print = vi.fn();
});

afterEach(cleanup);

describe("PersonalMaterialForm printing", () => {
  it("prints a dedicated belongings slip with visit and material details", async () => {
    render(
      <PersonalMaterialForm
        open
        value={MATERIAL}
        vehicle="LEA-1234"
        visitorName="Hamza Tariq"
        visitNumber="V-26-OCT-09-001"
        onClose={vi.fn()}
        onSave={vi.fn()}
      />,
    );

    await waitFor(() => expect(document.querySelector(".belongings-print-root")).toBeTruthy());
    const printRoot = document.querySelector(".belongings-print-root")!;
    expect(printRoot.textContent).toContain("Personal Material Returnable");
    expect(printRoot.textContent).toContain("V-26-OCT-09-001");
    expect(printRoot.textContent).toContain("Hamza Tariq");
    expect(printRoot.textContent).toContain("Laptop");
    expect(printRoot.textContent).toContain("LEA-1234");

    fireEvent.click(screen.getByRole("button", { name: "Print belongings list", hidden: true }));
    expect(window.print).toHaveBeenCalledOnce();
  });

  it("keeps the print copy in sync with unsaved form edits", async () => {
    render(
      <PersonalMaterialForm
        open
        value={MATERIAL}
        vehicle=""
        onClose={vi.fn()}
        onSave={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText("Description 1"), { target: { value: "Camera" } });
    await waitFor(() => expect(document.querySelector(".belongings-print-root")?.textContent).toContain("Camera"));
  });
});
