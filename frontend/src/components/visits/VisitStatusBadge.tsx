import { StatusBadge } from "@/components/ui/StatusBadge";
import type { VisitStatus } from "@/lib/api/visits";

export function VisitStatusBadge({ status }: { status: VisitStatus }) {
  return status === "CHECKED_IN"
    ? <StatusBadge tone="ok">Inside</StatusBadge>
    : <StatusBadge tone="neutral">Checked out</StatusBadge>;
}
