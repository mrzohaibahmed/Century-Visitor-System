"use client";

import { X } from "lucide-react";
import { useEffect, useId, useRef } from "react";

/** Accessible modal built on the native <dialog> (focus trap, Escape to close).
 *  m-auto: Tailwind's reset removes the browser default margin that centres a dialog.
 *  `dismissible={false}` hides the close button and ignores Escape (a choice that must be made).
 *  A click on the backdrop never closes it: that would lose what was typed into a form. */
export function Modal({ open, title, description, onClose, dismissible = true, children }: {
  open: boolean;
  title: string;
  description?: string;
  onClose: () => void;
  dismissible?: boolean;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal?.();
    if (!open && dialog.open) dialog.close?.();
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-labelledby={`${id}-title`}
      aria-describedby={description ? `${id}-description` : undefined}
      onCancel={(e) => { e.preventDefault(); if (dismissible) onClose(); }}
      className="m-auto max-h-[90vh] w-[calc(100%-2rem)] max-w-lg overflow-y-auto rounded-2xl border border-border bg-surface-elevated p-0
        text-ink shadow-overlay backdrop:bg-overlay open:animate-dialog-in"
    >
      {open && (
        <div className="p-6">
          <div className="mb-5 flex items-start justify-between gap-4">
            <div>
              <h2 id={`${id}-title`} className="text-heading">{title}</h2>
              {description && <p id={`${id}-description`} className="mt-1 text-sm text-ink-muted">{description}</p>}
            </div>
            {dismissible && (
              <button type="button" onClick={onClose} aria-label="Close"
                      className="-mr-2 -mt-1 inline-flex size-11 shrink-0 items-center justify-center rounded-xl text-ink-muted
                        transition-colors hover:bg-canvas hover:text-ink">
                <X aria-hidden="true" className="size-5" />
              </button>
            )}
          </div>
          {children}
        </div>
      )}
    </dialog>
  );
}
