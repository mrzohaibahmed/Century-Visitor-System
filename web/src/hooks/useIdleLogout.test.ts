import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useIdleLogout } from "./useIdleLogout";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

function activity() {
  act(() => { window.dispatchEvent(new Event("keydown")); });
}

describe("useIdleLogout", () => {
  it("signs out after the idle timeout without input", () => {
    const onIdle = vi.fn();
    renderHook(() => useIdleLogout(15, onIdle, vi.fn()));
    act(() => { vi.advanceTimersByTime(14 * 60_000); });
    expect(onIdle).not.toHaveBeenCalled();
    act(() => { vi.advanceTimersByTime(60_000 + 15_000); });
    expect(onIdle).toHaveBeenCalledOnce();
  });

  it("activity postpones the logout", () => {
    const onIdle = vi.fn();
    renderHook(() => useIdleLogout(15, onIdle, vi.fn()));
    act(() => { vi.advanceTimersByTime(10 * 60_000); });
    activity();
    act(() => { vi.advanceTimersByTime(10 * 60_000); });
    expect(onIdle).not.toHaveBeenCalled();
  });

  it("keeps the server session alive while the user is active, at most every few minutes", () => {
    const keepAlive = vi.fn();
    renderHook(() => useIdleLogout(15, vi.fn(), keepAlive));
    activity();
    expect(keepAlive).not.toHaveBeenCalled();                 // just logged in: no need yet
    act(() => { vi.advanceTimersByTime(5 * 60_000); });
    activity();
    activity();
    expect(keepAlive).toHaveBeenCalledOnce();
  });

  it("does not keep an idle session alive", () => {
    const keepAlive = vi.fn();
    renderHook(() => useIdleLogout(15, vi.fn(), keepAlive));
    act(() => { vi.advanceTimersByTime(30 * 60_000); });
    expect(keepAlive).not.toHaveBeenCalled();
  });
});
