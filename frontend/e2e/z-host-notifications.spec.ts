import { expect, type Page, test } from "@playwright/test";

import { E2E_ADMIN_PASSWORD } from "../playwright.config";

/**
 * Phase 6A in a real browser: a host linked to the admin's app account; a visitor for that host checks in;
 * the admin's bell shows the arrival, which can be read. ("z-" makes this file run after the specs that set
 * up the shared E2E database: the Main Gate and the host Sara Ahmed come from visits.spec.ts.)
 * E-mail is off in the E2E API (no SMTP server): delivery is covered by the backend tests.
 */

const VISITOR = { cnic: "35202-3333333-3", name: "Bilal Ahmed" };

test.describe.configure({ mode: "serial" });

async function logIn(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill(E2E_ADMIN_PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page).toHaveURL(/\/dashboard/);
  // With several gates (after visits.spec.ts) the gate must be chosen first.
  const chooser = page.getByRole("dialog", { name: "Which gate are you at?" });
  await expect(chooser.or(page.getByTestId("current-gate"))).toBeVisible();
  if (await chooser.isVisible()) await chooser.getByRole("button", { name: "Main Gate" }).click();
  await expect(page.getByTestId("current-gate")).toHaveText("Main Gate");
}

test("a host's visitor arrival reaches the linked app account's bell", async ({ page }) => {
  await logIn(page);
  await expect(page.getByTestId("notification-count")).toHaveCount(0);

  // Admin links the host directory entry to an existing app account (the host does not log in).
  await page.goto("/directory/hosts");
  await page.getByRole("row", { name: /Sara Ahmed/ }).getByRole("button", { name: "Edit" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Linked app account").selectOption({ label: "E2E Administrator (admin)" });
  await dialog.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("row", { name: /Sara Ahmed/ })).toContainText("App: E2E Administrator");

  // A visitor for Sara Ahmed checks in.
  await page.goto("/check-in");
  await page.getByLabel("ID number").fill(VISITOR.cnic);
  await page.getByRole("button", { name: "Find visitor" }).click();
  await page.getByLabel("Full name").fill(VISITOR.name);
  await page.getByRole("button", { name: "Register and continue" }).click();
  await page.getByLabel("Host (person being visited)").fill("sar");
  await page.getByRole("button", { name: /Sara Ahmed/ }).click();
  await page.getByLabel("Reason for visit").selectOption("OFFICIAL_MEETING");
  await page.getByRole("button", { name: "Review" }).click();
  await page.getByRole("button", { name: "Continue without a photo" }).click();
  await page.getByRole("button", { name: "Confirm check-in" }).click();
  await expect(page.getByTestId("visit-number")).toHaveText(/^V-\d{2}-[A-Z]{3}-\d{2}-\d{3}$/);

  // The bell shows it (counted by the server), and it can be read.
  await page.reload();
  await expect(page.getByTestId("notification-count")).toHaveText("1");
  await page.getByRole("button", { name: "Notifications, 1 unread" }).click();
  const item = page.getByRole("button", { name: new RegExp(`Unread: Visitor arrived. ${VISITOR.name} has arrived`) });
  await expect(item).toContainText(`${VISITOR.name} has arrived to visit Sara Ahmed.`);
  await expect(item).toContainText("Main Gate");
  await item.click();
  await expect(page.getByTestId("notification-count")).toHaveCount(0);

  // Still read after a reload; the full list agrees.
  await page.reload();
  await expect(page.getByTestId("notification-count")).toHaveCount(0);
  await page.goto("/notifications");
  await expect(page.getByRole("button", { name: new RegExp(`^Visitor arrived. ${VISITOR.name}`) })).toBeVisible();
  await page.getByLabel("Unread only").check();
  await expect(page.getByText("No notifications.")).toBeVisible();
});

test("a guard's bell stays empty: notifications are private to their recipient", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Username").fill("e2e.gate");
  await page.getByLabel("Password").fill("Own-Gate-Pass-33");
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page).toHaveURL(/\/dashboard/);
  const api = await page.request.get("/api/v1/notifications");
  expect((await api.json()).unread_count).toBe(0);
  expect((await api.json()).items).toEqual([]);
});
