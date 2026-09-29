import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/client";
import type { EmailSettings } from "@/lib/api/emailSettings";

const api = { get: vi.fn(), save: vi.fn(), remove: vi.fn(), test: vi.fn() };
vi.mock("@/lib/api/emailSettings", async (original) => ({
  ...(await original<typeof import("@/lib/api/emailSettings")>()),
  getEmailSettings: (...a: unknown[]) => api.get(...a),
  saveEmailSettings: (...a: unknown[]) => api.save(...a),
  deleteEmailSettings: (...a: unknown[]) => api.remove(...a),
  sendTestEmail: (...a: unknown[]) => api.test(...a),
}));
const toast = { success: vi.fn() };
vi.mock("sonner", () => ({ toast: { success: (...a: unknown[]) => toast.success(...a) } }));

const { EmailSettingsManager } = await import("./EmailSettingsManager");

const SECRET = "Smtp-App-Pass-9 xyz";

const SAVED: EmailSettings = {
  source: "database", environment_configured: true, saved: true, enabled: true, smtp_host: "smtp.gmail.com",
  smtp_port: 587, security: "starttls", username: "gate.vms@gmail.com", password_status: "SAVED",
  from_email: "gate.vms@gmail.com", from_name: "Century Gate VMS", reply_to: "reception@century.test",
  updated_at: "2026-09-29T08:00:00Z",
};
const ENVIRONMENT: EmailSettings = {
  source: "environment", environment_configured: true, saved: false, enabled: false, smtp_host: null, smtp_port: null,
  security: null, username: null, password_status: "NOT_SET", from_email: null, from_name: null, reply_to: null,
  updated_at: null,
};
const NONE: EmailSettings = { ...ENVIRONMENT, source: "none", environment_configured: false };

// jsdom has no <dialog>.showModal(), so a modal's content counts as hidden.
const inDialog = { hidden: true };
const consoleSpies: ReturnType<typeof vi.spyOn>[] = [];
const setItem = vi.spyOn(Storage.prototype, "setItem");

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  toast.success.mockReset();
  setItem.mockClear();
  api.get.mockResolvedValue(SAVED);
  for (const method of ["log", "info", "warn", "error", "debug"] as const) {
    consoleSpies.push(vi.spyOn(console, method).mockImplementation(() => {}));
  }
});
afterEach(() => {
  cleanup();
  consoleSpies.splice(0).forEach((s) => s.mockRestore());
  localStorage.clear();
  sessionStorage.clear();
});

const field = (label: string) => screen.getByLabelText(label) as HTMLInputElement;
const submit = () => fireEvent.submit(field("SMTP host").closest("form")!);

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((res) => { resolve = res; });
  return { promise, resolve };
}

async function open(settings: EmailSettings = SAVED) {
  api.get.mockResolvedValue(settings);
  render(<EmailSettingsManager />);
  await screen.findByTestId("email-source");
}

describe("EmailSettingsManager: loading and status", () => {
  it("shows a loading state, never an empty form, until the settings arrive", async () => {
    const pending = deferred<EmailSettings>();
    api.get.mockReturnValue(pending.promise);
    render(<EmailSettingsManager />);
    expect(screen.getByText("Loading e-mail settings…")).toBeTruthy();
    expect(screen.queryByLabelText("SMTP host")).toBeNull();
    await act(async () => pending.resolve(SAVED));
    expect(field("SMTP host").value).toBe("smtp.gmail.com");
  });

  it("reports a failed load safely and can try again", async () => {
    api.get.mockRejectedValueOnce(new ApiError(0, "network_error", "Cannot reach the server. Check the network connection."));
    render(<EmailSettingsManager />);
    expect(await screen.findByText("Cannot reach the server. Check the network connection.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByTestId("email-source")).toBeTruthy();
  });

  it("shows nothing of the settings when the server refuses (403)", async () => {
    api.get.mockRejectedValue(new ApiError(403, "forbidden", "You do not have permission to do this."));
    render(<EmailSettingsManager />);
    expect(await screen.findByText("You do not have permission to do this.")).toBeTruthy();
    expect(screen.queryByLabelText("SMTP host")).toBeNull();
    expect(screen.queryByTestId("email-password-status")).toBeNull();
  });

  it("shows saved settings as the source, enabled, with a saved password", async () => {
    await open();
    expect(screen.getByTestId("email-source").textContent).toBe("Saved settings");
    expect(screen.getByTestId("email-status").textContent).toBe("Enabled");
    expect(screen.getByTestId("email-password-status").textContent).toBe("Saved");
  });

  it("shows the environment as the source", async () => {
    await open(ENVIRONMENT);
    expect(screen.getByTestId("email-source").textContent).toBe("Server environment");
    expect(screen.getByTestId("email-status").textContent).toBe("Configured");
    expect(screen.getByText(/uses the SMTP settings in the server environment/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Delete saved settings" })).toBeNull();   // nothing saved to delete
  });

  it("shows when nothing is configured", async () => {
    await open(NONE);
    expect(screen.getByTestId("email-source").textContent).toBe("Not configured");
    expect(screen.getByTestId("email-status").textContent).toBe("Off");
  });

  it("explains switched-off settings", async () => {
    await open({ ...SAVED, enabled: false });
    expect(screen.getByTestId("email-status").textContent).toBe("Disabled");
    expect(screen.getByText(/The saved settings stay stored; nothing is sent until they are/)).toBeTruthy();
    expect(field("Send e-mail notifications").checked).toBe(false);
  });

  it("explains an unreadable password and how to fix it", async () => {
    await open({ ...SAVED, password_status: "UNREADABLE" });
    expect(screen.getByTestId("email-password-status").textContent).toBe("Saved, but cannot be read");
    expect(screen.getByText(/Enter the password again and save the settings\./)).toBeTruthy();
    expect(field("Password").placeholder).toBe("");                        // nothing usable saved: no "leave unchanged"
  });
});

describe("EmailSettingsManager: form", () => {
  it("fills in the saved values, with the password empty", async () => {
    await open();
    expect(field("SMTP host").value).toBe("smtp.gmail.com");
    expect(field("SMTP port").value).toBe("587");
    expect(field("Security").value).toBe("starttls");
    expect(field("User name").value).toBe("gate.vms@gmail.com");
    expect(field("From e-mail").value).toBe("gate.vms@gmail.com");
    expect(field("From name (optional)").value).toBe("Century Gate VMS");
    expect(field("Reply-To (optional)").value).toBe("reception@century.test");
    const password = field("Password");
    expect(password.type).toBe("password");
    expect(password.value).toBe("");
    expect(password.placeholder).toBe("Leave unchanged");
    expect(screen.getByText("A password is already saved. Enter a new one only to replace it.")).toBeTruthy();
  });

  it("offers exactly the server's security values", async () => {
    await open();
    const values = Array.from((field("Security") as unknown as HTMLSelectElement).options).map((o) => [o.value, o.text]);
    expect(values).toEqual([["starttls", "STARTTLS"], ["ssl", "SSL/TLS"], ["none", "None"]]);
  });

  it("keeps the saved password: no password is sent when none is typed", async () => {
    api.save.mockResolvedValue({ ...SAVED, from_name: "Main Gate", updated_at: "2026-09-29T09:00:00Z" });
    await open();
    fireEvent.change(field("From name (optional)"), { target: { value: "Main Gate" } });
    submit();
    await waitFor(() => expect(api.save).toHaveBeenCalledTimes(1));
    const [input] = api.save.mock.calls[0];
    expect(input).toEqual({
      enabled: true, smtp_host: "smtp.gmail.com", smtp_port: 587, security: "starttls", username: "gate.vms@gmail.com",
      from_email: "gate.vms@gmail.com", from_name: "Main Gate", reply_to: "reception@century.test",
    });
    expect("password" in input).toBe(false);
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("E-mail settings saved."));
  });

  it("sends a typed password with the save, then clears it", async () => {
    api.save.mockResolvedValue(SAVED);
    await open();
    fireEvent.change(field("Password"), { target: { value: SECRET } });
    submit();
    await waitFor(() => expect(api.save.mock.calls[0][0].password).toBe(SECRET));
    await waitFor(() => expect(field("Password").value).toBe(""));
  });

  it("sets up new settings: no user name means no login", async () => {
    api.save.mockResolvedValue({ ...SAVED, username: null, password_status: "NOT_SET" });
    await open(NONE);
    fireEvent.change(field("SMTP host"), { target: { value: " 10.10.20.15 " } });
    fireEvent.change(field("SMTP port"), { target: { value: "25" } });
    fireEvent.change(field("Security"), { target: { value: "none" } });
    fireEvent.change(field("From e-mail"), { target: { value: "vms@company.local" } });
    expect(screen.getByText("Unencrypted. Only for an internal mail relay without a login.")).toBeTruthy();
    submit();
    await waitFor(() => expect(api.save).toHaveBeenCalledWith({
      enabled: true, smtp_host: "10.10.20.15", smtp_port: 25, security: "none", username: null,
      from_email: "vms@company.local", from_name: null, reply_to: null,
    }));
  });

  it("checks the obvious mistakes before sending", async () => {
    await open(NONE);
    fireEvent.change(field("SMTP port"), { target: { value: "70000" } });
    fireEvent.change(field("Reply-To (optional)"), { target: { value: "not-an-address" } });
    submit();
    for (const text of ["Enter the SMTP server's host name or IP address.", "The port is a number from 1 to 65535.",
      "Enter the sender's e-mail address.", "Enter a valid e-mail address, or leave it empty."]) {
      expect(await screen.findByText(text)).toBeTruthy();
    }
    expect(api.save).not.toHaveBeenCalled();
  });

  it("shows progress and saves once, even on a double submit", async () => {
    const pending = deferred<EmailSettings>();
    api.save.mockReturnValue(pending.promise);
    await open();
    submit();
    submit();
    expect(api.save).toHaveBeenCalledTimes(1);
    const button = screen.getByRole("button", { name: "Save settings" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    await act(async () => pending.resolve(SAVED));
    expect(button.disabled).toBe(false);
  });

  it("shows the server's field problems", async () => {
    api.save.mockRejectedValue(new ApiError(422, "validation_error", "The request is not valid.", null,
      [{ field: "body.smtp_host", message: "Enter a host name (e.g. smtp.example.com) or an IP address, without a port." }]));
    await open();
    submit();
    expect(await screen.findByText(/Enter a host name \(e\.g\. smtp\.example\.com\)/)).toBeTruthy();
    expect(field("SMTP host").getAttribute("aria-invalid")).toBe("true");
  });

  it("shows the server's 'password needed again' answer on the password field", async () => {
    api.save.mockRejectedValue(new ApiError(422, "email_password_required",
      "Enter the SMTP password again when changing the host, port, security or user name."));
    await open();
    fireEvent.change(field("SMTP host"), { target: { value: "smtp.office365.com" } });
    submit();
    expect(await screen.findByText(/Enter the SMTP password again when changing/)).toBeTruthy();
    expect(field("Password").getAttribute("aria-invalid")).toBe("true");
  });

  it("shows other refusals (e.g. production rules, missing server key) as the server says", async () => {
    api.save.mockRejectedValue(new ApiError(422, "invalid_email_settings",
      "Security 'none' would send the SMTP password unencrypted: use STARTTLS or SSL/TLS."));
    await open();
    submit();
    expect(await screen.findByText(/would send the SMTP password unencrypted/)).toBeTruthy();
  });
});

describe("EmailSettingsManager: switching off and deleting are different", () => {
  it("switching off saves enabled=false and keeps the settings", async () => {
    api.save.mockResolvedValue({ ...SAVED, enabled: false, updated_at: "2026-09-29T09:00:00Z" });
    await open();
    fireEvent.click(field("Send e-mail notifications"));
    submit();
    await waitFor(() => expect(api.save.mock.calls[0][0]).toMatchObject({ enabled: false, smtp_host: "smtp.gmail.com" }));
    expect(api.remove).not.toHaveBeenCalled();
    expect(await screen.findByText("Disabled")).toBeTruthy();

    api.save.mockResolvedValue({ ...SAVED, updated_at: "2026-09-29T10:00:00Z" });
    fireEvent.click(field("Send e-mail notifications"));                      // on again
    submit();
    await waitFor(() => expect(api.save.mock.calls[1][0]).toMatchObject({ enabled: true }));
  });

  it("delete asks first, and Cancel deletes nothing", async () => {
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Delete saved settings" }));
    expect(screen.getByText(/This removes the saved SMTP configuration, including the saved password\./)).toBeTruthy();
    expect(screen.getAllByText(/The server's environment SMTP settings will be used instead\./).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Cancel", ...inDialog }));
    expect(api.remove).not.toHaveBeenCalled();
  });

  it("delete removes the saved settings, and the environment shows as the source again", async () => {
    api.remove.mockResolvedValue(undefined);
    await open();
    api.get.mockResolvedValue(ENVIRONMENT);
    fireEvent.click(screen.getByRole("button", { name: "Delete saved settings" }));
    const buttons = screen.getAllByRole("button", { name: "Delete saved settings", ...inDialog });
    fireEvent.click(buttons[buttons.length - 1]);
    await waitFor(() => expect(api.remove).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByTestId("email-source").textContent).toBe("Server environment"));
    expect(toast.success).toHaveBeenCalledWith("Saved e-mail settings deleted.");
    expect(field("SMTP host").value).toBe("");
  });
});

describe("EmailSettingsManager: test e-mail", () => {
  async function openTest() {
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Send test e-mail" }));
  }
  const recipient = () => screen.getByLabelText("Recipient e-mail") as HTMLInputElement;
  const send = () => fireEvent.submit(recipient().closest("form")!);

  it("checks the recipient before sending", async () => {
    await openTest();
    fireEvent.change(recipient(), { target: { value: "not-an-address" } });
    send();
    expect(await screen.findByText("Enter the e-mail address to send the test to.")).toBeTruthy();
    expect(api.test).not.toHaveBeenCalled();
  });

  it("sends once, shows progress, then success", async () => {
    const pending = deferred<unknown>();
    api.test.mockReturnValue(pending.promise);
    await openTest();
    fireEvent.change(recipient(), { target: { value: " admin@century.test " } });
    send();
    send();
    expect(api.test).toHaveBeenCalledTimes(1);
    expect(api.test).toHaveBeenCalledWith("admin@century.test");
    expect(screen.getByText("Sending test e-mail…")).toBeTruthy();
    await act(async () => pending.resolve({ status: "SENT", code: null, message: null, source: "database" }));
    expect(screen.getByText(/Test e-mail sent successfully\./)).toBeTruthy();
  });

  it("shows the server's safe reason when it fails", async () => {
    api.test.mockResolvedValue({ status: "FAILED", code: "EMAIL_AUTHENTICATION_FAILED",
                                 message: "The mail server refused the user name or password.", source: "database" });
    await openTest();
    fireEvent.change(recipient(), { target: { value: "admin@century.test" } });
    send();
    expect(await screen.findByText("The mail server refused the user name or password.")).toBeTruthy();
    expect(document.body.textContent).not.toContain("EMAIL_AUTHENTICATION_FAILED");
  });

  it("shows a refusal (e.g. a test already running)", async () => {
    api.test.mockRejectedValue(new ApiError(409, "email_test_running", "A test e-mail is already being sent. Wait for it to finish."));
    await openTest();
    fireEvent.change(recipient(), { target: { value: "admin@century.test" } });
    send();
    expect(await screen.findByText("A test e-mail is already being sent. Wait for it to finish.")).toBeTruthy();
  });
});

describe("EmailSettingsManager: the password never leaks", () => {
  it("is not rendered, stored, put in the URL or logged, and only sent with Save", async () => {
    api.save.mockRejectedValueOnce(new ApiError(500, "internal_error", "An unexpected error occurred. Please try again or contact the administrator."));
    api.save.mockResolvedValue({ ...SAVED, updated_at: "2026-09-29T09:00:00Z" });
    api.test.mockResolvedValue({ status: "SENT", code: null, message: null, source: "database" });
    await open();
    fireEvent.change(field("Password"), { target: { value: SECRET } });
    submit();                                                                  // fails first
    expect(await screen.findByText(/An unexpected error occurred/)).toBeTruthy();
    expect(document.body.textContent).not.toContain(SECRET);
    submit();                                                                  // then saves
    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "Send test e-mail" }));
    fireEvent.change(screen.getByLabelText("Recipient e-mail"), { target: { value: "admin@century.test" } });
    fireEvent.submit((screen.getByLabelText("Recipient e-mail") as HTMLInputElement).closest("form")!);
    await waitFor(() => expect(api.test).toHaveBeenCalled());

    expect(document.documentElement.outerHTML).not.toContain(SECRET);        // form reset: nowhere on the page
    expect(window.location.href).not.toContain(SECRET);
    expect(setItem).not.toHaveBeenCalled();
    expect(localStorage.length + sessionStorage.length).toBe(0);
    for (const spy of consoleSpies) expect(JSON.stringify(spy.mock.calls)).not.toContain(SECRET);
    expect(JSON.stringify([api.get.mock.calls, api.test.mock.calls, api.remove.mock.calls])).not.toContain(SECRET);
    expect(api.save.mock.calls.every(([input]) => input.password === SECRET)).toBe(true);
  });
});
