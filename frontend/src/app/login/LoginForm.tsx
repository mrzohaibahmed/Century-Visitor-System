"use client";

import { useEffect, useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { TextField } from "@/components/ui/TextField";
import { login } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/client";

export function LoginForm({ next, notice }: { next: string; notice?: string }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  // Until the page is interactive the button stays disabled: a click before then would be a plain
  // HTML form submission instead of the API call.
  const [ready, setReady] = useState(false);
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setReady(true), []);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!username.trim() || !password) {
      setError("Enter your username and password.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const me = await login(username.trim(), password);
      // Full navigation so every page renders with the new session cookie.
      window.location.assign(me.user.must_change_password ? "/account/password" : next);
    } catch (e) {
      // The API's messages are written for users (and deliberately vague about which part was wrong).
      setError(e instanceof ApiError ? e.message : "Something went wrong. Please try again.");
      setPassword("");
      setSubmitting(false);
    }
  }

  return (
    // method="post": even a submission before the page is interactive never puts the password in the URL.
    <form onSubmit={onSubmit} method="post" noValidate className="space-y-4">
      {notice && !error && <Alert tone="info">{notice}</Alert>}
      {error && <Alert tone="danger">{error}</Alert>}
      <TextField
        label="Username"
        name="username"
        autoComplete="username"
        autoFocus
        value={username}
        onChange={(e) => setUsername(e.target.value)}
      />
      <TextField
        label="Password"
        name="password"
        type="password"
        autoComplete="current-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      <Button type="submit" loading={submitting} disabled={!ready} className="w-full">
        {submitting ? "Logging in…" : "Log in"}
      </Button>
    </form>
  );
}
