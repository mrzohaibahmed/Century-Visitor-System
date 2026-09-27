import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CAMERA_MESSAGES } from "@/components/camera/camera";
import { looksLikePass } from "@/lib/api/passes";
import { installCamera } from "@/test-utils/camera";

import { QrScanner } from "./QrScanner";

afterEach(cleanup);

describe("QrScanner", () => {
  it("starts the camera and releases it when closed", async () => {
    const camera = installCamera();
    const { unmount } = render(<QrScanner onScan={vi.fn()} onCancel={vi.fn()} />);
    await vi.waitFor(() => expect(camera.tracks).toHaveLength(1));
    unmount();
    await vi.waitFor(() => expect(camera.tracks[0].stopped).toBe(true));
  });

  it("explains a refused camera and can try again", async () => {
    const camera = installCamera({ fail: "NotAllowedError" });
    render(<QrScanner onScan={vi.fn()} onCancel={vi.fn()} />);
    expect(await screen.findByText(CAMERA_MESSAGES.denied)).toBeTruthy();
    camera.getUserMedia.mockResolvedValueOnce({ getTracks: () => [] } as unknown as MediaStream);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await vi.waitFor(() => expect(camera.getUserMedia).toHaveBeenCalledTimes(2));
  });

  it("can be cancelled", () => {
    installCamera();
    const onCancel = vi.fn();
    render(<QrScanner onScan={vi.fn()} onCancel={onCancel} />);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalled();
  });
});

describe("looksLikePass", () => {
  it.each([[`CGP1:${"A".repeat(64)}`, true], [` cgp1:${"a".repeat(64)} `, true], ["V-2026-000001", false],
           ["35201-1234567-1", false]])("%s → %s", (text, expected) => {
    expect(looksLikePass(text)).toBe(expected);
  });
});
