import { expect, type Page, test } from "@playwright/test";

import { E2E_ADMIN_PASSWORD } from "../playwright.config";

const GUARD = { username: "e2e.guard", name: "E2E Guard", temp: "Temp-Guard-Pass-1", own: "Own-Guard-Pass-22" };

async function logIn(page: Page, username: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Log in" }).click();
}

test.describe.configure({ mode: "serial" });

test("protected pages send anonymous visitors to the login page", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login/);
  await page.goto("/users");
  await expect(page).toHaveURL(/\/login/);
});

test("a wrong password is refused with a generic message", async ({ page }) => {
  await logIn(page, "admin", "Not-The-Password-1");
  await expect(page.locator("form").getByRole("alert")).toHaveText("Invalid username or password.");
  await expect(page).toHaveURL(/\/login/);
});

test("admin logs in, creates a guard and logs out", async ({ page }) => {
  await logIn(page, "admin", E2E_ADMIN_PASSWORD);
  await expect(page).toHaveURL(/\/dashboard/);
  await expect(page.getByText("E2E Administrator")).toBeVisible();

  // The session cookie is HttpOnly: page scripts cannot read it.
  const readable = await page.evaluate(() => document.cookie);
  expect(readable).not.toContain("cg_session");
  expect(readable).toContain("cg_csrf");

  await page.getByRole("link", { name: "Users" }).click();
  await expect(page).toHaveURL(/\/users/);
  await page.getByRole("button", { name: "New user" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Username").fill(GUARD.username);
  await dialog.getByLabel("Full name").fill(GUARD.name);
  await dialog.getByLabel("Temporary password").fill(GUARD.temp);
  await dialog.getByRole("button", { name: "Create user" }).click();
  await expect(page.getByText(`${GUARD.username} created.`)).toBeVisible();
  const row = page.getByRole("row", { name: new RegExp(GUARD.name) });
  await expect(row.getByText("Must change password")).toBeVisible();

  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/login\?reason=logged_out/);
  await expect(page.getByText("You have been logged out.")).toBeVisible();
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login/);                       // the old session no longer works
});

test("a new guard must choose a password and cannot reach admin pages", async ({ page }) => {
  await logIn(page, GUARD.username, GUARD.temp);
  await expect(page).toHaveURL(/\/account\/password/);
  await page.getByLabel("Current password").fill(GUARD.temp);
  await page.getByLabel("New password", { exact: true }).fill(GUARD.own);
  await page.getByLabel("Confirm new password").fill(GUARD.own);
  await page.getByRole("button", { name: "Change password" }).click();
  await expect(page).toHaveURL(/\/dashboard/);

  await expect(page.getByRole("link", { name: "Users" })).toHaveCount(0);     // hidden in the menu (UX)
  await page.goto("/users");
  await expect(page).toHaveURL(/\/dashboard/);                                  // page refused (UX)
  const api = await page.request.get("/api/v1/users");                          // API refuses (security)
  expect(api.status()).toBe(403);
});

test("the guard's new password works and the temporary one does not", async ({ page }) => {
  await logIn(page, GUARD.username, GUARD.temp);
  await expect(page.locator("form").getByRole("alert")).toHaveText("Invalid username or password.");
  await logIn(page, GUARD.username, GUARD.own);
  await expect(page).toHaveURL(/\/dashboard/);
  await expect(page.getByText(GUARD.name)).toBeVisible();
});
