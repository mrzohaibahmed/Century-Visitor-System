import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import QRCode from "qrcode";

import { ApiError } from "@/lib/api/client";
import type { PersonalMaterial } from "@/lib/belongings";

const api = vi.hoisted(() => ({ printablePass: vi.fn(), verifyPassForPrint: vi.fn() }));
vi.mock("@/lib/api/passes", async (original) => ({
  ...(await original<typeof import("@/lib/api/passes")>()),
  printablePass: api.printablePass,
  verifyPassForPrint: api.verifyPassForPrint,
}));

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
const PASS = `CGP1:${"0123456789ABCDEF".repeat(4)}`;

beforeEach(() => {
  api.printablePass.mockReset();
  api.verifyPassForPrint.mockReset();
  api.verifyPassForPrint.mockResolvedValue({ qr_text: PASS });
  window.print = vi.fn();
});

afterEach(() => { window.dispatchEvent(new Event("afterprint")); cleanup(); });

describe("PersonalMaterialForm printing", () => {
  it("prints a dedicated belongings slip with visit and material details", async () => {
    render(
      <PersonalMaterialForm
        open
        value={MATERIAL}
        vehicle="LEA-1234"
        visitorName="Hamza Tariq"
        visitId="visit1"
        visitNumber="V-26-OCT-09-001"
        passQrText={PASS}
        onClose={vi.fn()}
        onSave={vi.fn()}
      />,
    );

    await waitFor(() => expect(document.querySelector(".belongings-print-root")).toBeTruthy());
    const printRoot = document.querySelector(".belongings-print-root")!;
    expect(printRoot.textContent).toContain("Personal Material Returnable");
    expect(printRoot.textContent).toContain("V-26-OCT-09-001");
    expect(printRoot.textContent).toContain("Hamza Tariq");
    expect(printRoot.textContent).toContain("LAPTOP");
    expect(printRoot.textContent).toContain("LEA-1234");
    expect(printRoot.textContent).toContain("Company device");
    expect(printRoot.querySelector(".belongings-print-footer")?.textContent)
      .toContain("All listed material must be verified at the gate before release.");
    expect(printRoot.querySelector('img[alt="Century Paper and Board Mills logo"]')).toBeTruthy();
    const expectedQr = await QRCode.toDataURL(PASS, { errorCorrectionLevel: "M", margin: 2, width: 480 });
    await waitFor(() => expect(printRoot.querySelector('img[alt="Visitor badge QR code"]')?.getAttribute("src"))
      .toBe(expectedQr));
    expect((screen.getByLabelText("S. No.") as HTMLInputElement).value).toBe("V-26-OCT-09-001");
    expect(printRoot.querySelectorAll(".belongings-print-table tbody tr")).toHaveLength(15);

    fireEvent.click(screen.getByRole("button", { name: "Print belongings list", hidden: true }));
    await waitFor(() => expect(window.print).toHaveBeenCalledOnce());
    expect(document.body.dataset.printTarget).toBe("belongings");
    expect(api.verifyPassForPrint).toHaveBeenCalledWith("visit1", PASS);
  });

  it("keeps the print copy in sync with unsaved form edits", async () => {
    const onSave = vi.fn();
    render(
      <PersonalMaterialForm
        open
        value={MATERIAL}
        vehicle=""
        onClose={vi.fn()}
        onSave={onSave}
      />,
    );

    expect((screen.getByLabelText("Company Cont. Name") as HTMLInputElement).value).toBe("Sara Ahmed");
    fireEvent.change(screen.getByLabelText("Description 1"), { target: { value: "Camera" } });
    fireEvent.change(screen.getByLabelText("Remarks"), { target: { value: "Needs gate approval" } });
    fireEvent.change(screen.getByLabelText("Veh. #"), { target: { value: "lea-1234" } });
    await waitFor(() => expect(document.querySelector(".belongings-print-root")?.textContent).toContain("CAMERA"));
    expect(document.querySelector(".belongings-print-root")?.textContent).toContain("Needs gate approval");
    expect((screen.getByLabelText("Description 1") as HTMLInputElement).value).toBe("CAMERA");
    expect((screen.getByLabelText("Remarks") as HTMLTextAreaElement).value).toBe("Needs gate approval");
    fireEvent.click(screen.getByRole("button", { name: "Save belongings", hidden: true }));
    expect(onSave).toHaveBeenCalledWith({
      personalMaterial: expect.objectContaining({ contactName: "Sara Ahmed", remarks: "Needs gate approval" }),
      vehicle: "lea-1234",
    });
  });

  it("loads the current badge QR without reissuing the badge", async () => {
    api.printablePass.mockResolvedValue({ qr_text: PASS });
    render(<PersonalMaterialForm open value={MATERIAL} vehicle="" visitId="visit1"
                                 visitNumber="V-26-OCT-09-001" onClose={vi.fn()} onSave={vi.fn()} />);
    await waitFor(() => expect(document.querySelector(".belongings-print-root img[alt='Visitor badge QR code']"))
      .toBeTruthy());
    expect(api.printablePass).toHaveBeenCalledWith("visit1");
    expect(api.verifyPassForPrint).not.toHaveBeenCalled();
    expect((screen.getByRole("button", { name: "Print belongings list", hidden: true }) as HTMLButtonElement).disabled)
      .toBe(false);
  });

  it("accepts a scan of an older matching badge", async () => {
    api.printablePass.mockRejectedValue(new ApiError(409, "pass_not_recoverable", "Scan the current badge."));
    api.verifyPassForPrint.mockResolvedValue({ qr_text: PASS });
    render(<PersonalMaterialForm open value={MATERIAL} vehicle="" visitId="visit1"
                                 visitNumber="V-26-OCT-09-001" onClose={vi.fn()} onSave={vi.fn()} />);
    fireEvent.change(await screen.findByLabelText("Scan current visitor badge"), { target: { value: PASS } });
    fireEvent.click(screen.getByRole("button", { name: "Use scanned badge", hidden: true }));
    await waitFor(() => expect(document.querySelector(".belongings-print-root img[alt='Visitor badge QR code']"))
      .toBeTruthy());
    expect(api.verifyPassForPrint).toHaveBeenCalledWith("visit1", PASS);
  });

  it("refuses to print a QR after its badge has been replaced", async () => {
    render(<PersonalMaterialForm open value={MATERIAL} vehicle="" visitId="visit1"
                                 visitNumber="V-26-OCT-09-001" passQrText={PASS}
                                 onClose={vi.fn()} onSave={vi.fn()} />);
    await waitFor(() => expect(document.querySelector(".belongings-print-root img[alt='Visitor badge QR code']"))
      .toBeTruthy());
    api.verifyPassForPrint.mockRejectedValue(new ApiError(409, "pass_mismatch", "Scan the current badge."));
    fireEvent.click(screen.getByRole("button", { name: "Print belongings list", hidden: true }));
    await waitFor(() => expect(screen.getByText("Scan the current badge.")).toBeTruthy());
    expect(window.print).not.toHaveBeenCalled();
  });

  it("waits for check-in before enabling a numbered QR slip", () => {
    render(<PersonalMaterialForm open value={MATERIAL} vehicle="" onClose={vi.fn()} onSave={vi.fn()} />);
    expect((screen.getByLabelText("S. No.") as HTMLInputElement).value).toBe("Assigned at check-in");
    expect((screen.getByRole("button", { name: "Print belongings list", hidden: true }) as HTMLButtonElement).disabled)
      .toBe(true);
  });

  it("allows fifteen item rows and prevents a sixteenth", () => {
    render(
      <PersonalMaterialForm
        open
        value={MATERIAL}
        vehicle=""
        onClose={vi.fn()}
        onSave={vi.fn()}
      />,
    );

    const add = screen.getByRole("button", { name: "Add item", hidden: true });
    for (let i = 1; i < 15; i += 1) fireEvent.click(add);

    expect(screen.getByLabelText("Description 15")).toBeTruthy();
    expect(screen.queryByLabelText("Description 16")).toBeNull();
    expect((add as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("1 of 15 items")).toBeTruthy();
  });
});
