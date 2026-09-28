import { CircleAlert, CircleCheck, Info, LoaderCircle, TriangleAlert } from "lucide-react";
import { Toaster as Sonner } from "sonner";

/**
 * Short, non-blocking confirmations ("Visitor checked out"). Call `toast.success(...)` from
 * "sonner". Anything the user must act on stays on the page as an <Alert>, not in a toast.
 * Colours come from the app tokens (globals.css, [data-sonner-toaster]).
 */
export function Toaster() {
  return (
    <Sonner
      position="top-center"
      richColors
      closeButton
      duration={5000}
      icons={{
        success: <CircleCheck className="size-5" />,
        error: <CircleAlert className="size-5" />,
        warning: <TriangleAlert className="size-5" />,
        info: <Info className="size-5" />,
        loading: <LoaderCircle className="size-5 animate-spin" />,
      }}
      toastOptions={{ classNames: { toast: "shadow-overlay text-sm", title: "font-semibold" } }}
    />
  );
}
