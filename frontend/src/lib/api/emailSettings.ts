import { apiRequest } from "./client";

/**
 * E-mail (SMTP) settings, administrators only. Mirrors app/schemas/email_settings.py.
 * Generic SMTP for any provider. The SMTP password is only ever SENT (when set or replaced); the API
 * never returns it, only whether one is saved. It is never kept in the browser beyond the open form.
 */
export type SmtpSecurity = "starttls" | "ssl" | "none";
export type EmailSource = "database" | "environment" | "none";
export type SmtpPasswordStatus = "NOT_SET" | "SAVED" | "UNREADABLE";

export type EmailSettings = {
  source: EmailSource;
  environment_configured: boolean;
  saved: boolean;
  enabled: boolean;
  smtp_host: string | null;
  smtp_port: number | null;
  security: SmtpSecurity | null;
  username: string | null;
  password_status: SmtpPasswordStatus;
  from_email: string | null;
  from_name: string | null;
  reply_to: string | null;
  updated_at: string | null;
};

/** `password` omitted: keep the saved one. `username` null: no login (the saved password is removed). */
export type EmailSettingsInput = {
  enabled: boolean;
  smtp_host: string;
  smtp_port: number;
  security: SmtpSecurity;
  username: string | null;
  password?: string;
  from_email: string;
  from_name: string | null;
  reply_to: string | null;
};

export type EmailTestResult = {
  status: "SENT" | "FAILED";
  code: string | null;          // e.g. EMAIL_AUTHENTICATION_FAILED
  message: string | null;       // safe to show; never an SMTP reply or a credential
  source: EmailSource;
};

const PATH = "/settings/email";

export function getEmailSettings(): Promise<EmailSettings> {
  return apiRequest<EmailSettings>(PATH);
}

export function saveEmailSettings(input: EmailSettingsInput): Promise<EmailSettings> {
  return apiRequest<EmailSettings>(PATH, { method: "PUT", body: input });
}

/** Removes the saved settings and password: the server environment (CG_SMTP_*) applies again. */
export function deleteEmailSettings(): Promise<void> {
  return apiRequest<void>(PATH, { method: "DELETE" });
}

/** Sends one test e-mail with the settings in use (saved, else the server environment). */
export function sendTestEmail(to: string): Promise<EmailTestResult> {
  return apiRequest<EmailTestResult>(`${PATH}/test`, { method: "POST", body: { to } });
}
