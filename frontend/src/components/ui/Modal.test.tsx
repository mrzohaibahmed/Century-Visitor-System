import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Modal } from "./Modal";

afterEach(cleanup);

// jsdom has no <dialog>.showModal(), so the modal's content counts as hidden.
describe("Modal", () => {
  it("names each dialog by its own title, even with several on the page", () => {
    render(
      <>
        <Modal open title="Check out visitor" onClose={() => {}}>one</Modal>
        <Modal open title="Reprint badge" onClose={() => {}}>two</Modal>
      </>,
    );
    // jsdom cannot compute names inside a closed <dialog>; check the labelling references directly.
    const titles = screen.getAllByRole("dialog", { hidden: true })
      .map((d) => document.getElementById(d.getAttribute("aria-labelledby") ?? "")?.textContent);
    expect(titles).toEqual(["Check out visitor", "Reprint badge"]);
  });

  it("closes from the close button and from Escape", () => {
    const onClose = vi.fn();
    render(<Modal open title="Edit visitor" onClose={onClose}>form</Modal>);
    screen.getByRole("button", { name: "Close", hidden: true }).click();
    fireEvent(screen.getByRole("dialog", { hidden: true }), new Event("cancel", { cancelable: true }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("cannot be dismissed when a choice is required", () => {
    const onClose = vi.fn();
    render(<Modal open title="Which gate are you at?" dismissible={false} onClose={onClose}>gates</Modal>);
    expect(screen.queryByRole("button", { name: "Close", hidden: true })).toBeNull();
    fireEvent(screen.getByRole("dialog", { hidden: true }), new Event("cancel", { cancelable: true }));
    expect(onClose).not.toHaveBeenCalled();
  });
});
