import { AppShell } from "@/components/layout/AppShell";

// Phase 2: verify the session on the server (GET /api/v1/auth/me) and redirect to /login.
export default function AppLayout({ children }: LayoutProps<"/">) {
  return <AppShell>{children}</AppShell>;
}
