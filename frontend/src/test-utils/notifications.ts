import type { AppNotification } from "@/lib/api/notifications";

/** A host-arrival notification for unit tests, created two minutes ago. */
export function arrival(id: string, visitor: string, read = false): AppNotification {
  return {
    id, type: "HOST_VISITOR_ARRIVAL", title: "Visitor arrived", message: `${visitor} has arrived to visit Sara Ahmed.`,
    created_at: new Date(Date.now() - 2 * 60000).toISOString(), read, read_at: read ? new Date().toISOString() : null,
    arrival: { visitor_name: visitor, host_name: "Sara Ahmed", gate_name: "Main Gate", department_name: "HR",
               check_in_at: new Date().toISOString() },
    email_status: "SENT",
  };
}
