import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SystemHealth } from "@/hooks/useSystemHealth";

import { SystemStatusCard } from "./SystemStatusCard";

afterEach(cleanup);

function health(overrides: Partial<SystemHealth>): SystemHealth {
  return { state: "checking", checks: null, version: null, checkedAt: null, refresh: vi.fn(), ...overrides };
}

describe("SystemStatusCard", () => {
  it("shows each readiness check when the system is ready", () => {
    render(<SystemStatusCard health={health({
      state: "ready", version: "0.1.0", checkedAt: new Date(),
      checks: { database: "ok", schema_version: "ok", transactions: "ok" },
    })} />);
    expect(screen.getByText("System online")).toBeTruthy();
    expect(screen.getByText("Database connection")).toBeTruthy();
    expect(screen.getAllByText("OK")).toHaveLength(3);
    expect(screen.getByText("API version 0.1.0")).toBeTruthy();
  });

  it("tells the operator to migrate when the schema is missing", () => {
    render(<SystemStatusCard health={health({
      state: "degraded", checks: { database: "ok", schema_version: "missing", transactions: "ok" },
    })} />);
    expect(screen.getByText("Database problem")).toBeTruthy();
    expect(screen.getByText("Not set up — run the migration")).toBeTruthy();
  });

  it("explains when the server cannot be reached", () => {
    render(<SystemStatusCard health={health({ state: "offline" })} />);
    expect(screen.getByText("Server unreachable")).toBeTruthy();
    expect(screen.getByText(/cannot be reached/)).toBeTruthy();
  });

  it("re-checks on demand", () => {
    const refresh = vi.fn();
    render(<SystemStatusCard health={health({ refresh })} />);
    screen.getByRole("button", { name: "Check again" }).click();
    expect(refresh).toHaveBeenCalledOnce();
  });
});
