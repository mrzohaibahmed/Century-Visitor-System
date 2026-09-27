"use client";

import { useEffect, useRef } from "react";

/** Accessible modal built on the native <dialog> (focus trap, Escape to close).
 *  m-auto: Tailwind's reset removes the browser default margin that centres a dialog. */
export function Modal({ open, title, onClose, children }: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal?.();
    if (!open && dialog.open) dialog.close?.();
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-labelledby="modal-title"
      onCancel={(e) => { e.preventDefault(); onClose(); }}
      className="m-auto max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl border border-border bg-surface p-0 text-ink shadow-xl backdrop:bg-black/40"
    >
      {open && (
        <div className="p-6">
          <h2 id="modal-title" className="mb-4 text-lg font-semibold">{title}</h2>
          {children}
        </div>
      )}
    </dialog>
  );
}
