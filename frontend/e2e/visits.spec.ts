import { expect, type Page, test } from "@playwright/test";

import { E2E_ADMIN_PASSWORD } from "../playwright.config";

const CNIC = "35202-7654321-3";
const VISITOR = "Hamza Tariq";

async function logIn(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill(E2E_ADMIN_PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page).toHaveURL(/\/dashboard/);
}

async function addEntry(page: Page, kind: "gates" | "departments" | "hosts", singular: string,
                        fill: (dialog: ReturnType<Page["getByRole"]>) => Promise<void>, name: string) {
  await page.goto(`/directory/${kind}`);
  await page.getByRole("button", { name: `New ${singular}` }).click();
  const dialog = page.getByRole("dialog");
  await fill(dialog);
  await dialog.getByRole("button", { name: "Add" }).click();
  await expect(page.getByText(`${name} added.`)).toBeVisible();
}

test.describe.configure({ mode: "serial" });

test("admin sets up a gate, a department and a host", async ({ page }) => {
  await logIn(page);
  await addEntry(page, "gates", "gate", (d) => d.getByLabel("Name").fill("Main Gate"), "Main Gate");
  await addEntry(page, "departments", "department", (d) => d.getByLabel("Name").fill("Human Resources"),
                 "Human Resources");
  await addEntry(page, "hosts", "host", async (d) => {
    await d.getByLabel("Full name").fill("Sara Ahmed");
    await d.getByLabel("Department").selectOption({ label: "Human Resources" });
  }, "Sara Ahmed");
  await expect(page.getByRole("row", { name: /Sara Ahmed/ })).toContainText("Human Resources");

  // Names and departments read in capitals; an e-mail address keeps its exact form.
  await addEntry(page, "hosts", "host", async (d) => {
    await d.getByLabel("Full name").fill("Omar Farooq");
    await d.getByLabel("Department").selectOption({ label: "Human Resources" });
    await d.getByLabel("Email").fill("omar.farooq@example.com");
  }, "Omar Farooq");
  const omar = page.getByRole("row", { name: /Omar Farooq/i });
  await expect(omar).toContainText("OMAR FAROOQ", { useInnerText: true });
  await expect(omar).toContainText("HUMAN RESOURCES · omar.farooq@example.com", { useInnerText: true });

  // With exactly one gate, the session is assigned to it automatically.
  await page.reload();
  await expect(page.getByTestId("current-gate")).toHaveText("Main Gate");
});

let visitNumber = "";

test("a new visitor is registered and checked in", async ({ page }) => {
  await logIn(page);
  await page.getByRole("link", { name: "Check in" }).first().click();
  await expect(page).toHaveURL(/\/check-in/);

  await page.getByLabel("ID number").fill(CNIC.replaceAll("-", ""));
  await page.getByRole("button", { name: "Find visitor" }).click();
  await expect(page.getByText("This ID number is not registered yet.")).toBeVisible();
  await page.getByLabel("Full name").fill(VISITOR);
  await page.getByLabel("Phone (optional)").fill("0300-1112223");
  await page.getByRole("button", { name: "Register and continue" }).click();

  await expect(page.getByTestId("visitor-name")).toHaveText(VISITOR);                               // stored as typed
  await expect(page.getByTestId("visitor-name")).toHaveText(VISITOR.toUpperCase(), { useInnerText: true }); // shown in capitals
  await page.getByLabel("Host (person being visited)").fill("sar");
  await page.getByRole("button", { name: /Sara Ahmed/ }).click();
  await expect(page.getByTestId("selected-host")).toHaveText("Sara Ahmed");
  await page.getByLabel("Reason for visit").selectOption("INTERVIEW");
  await page.getByLabel("Belongings (optional)").fill("laptop, bag");
  await page.getByRole("button", { name: "Review" }).click();
  await page.getByRole("button", { name: "Continue without a photo" }).click();       // photo step (Phase 4)

  await expect(page.getByText("Human Resources")).toBeVisible();          // department taken from the host
  await page.getByRole("button", { name: "Confirm check-in" }).click();
  const number = page.getByTestId("visit-number");
  await expect(number).toHaveText(/^V-\d{4}-\d{6}$/);
  visitNumber = (await number.textContent()) ?? "";
});

test("the same visitor cannot be checked in twice", async ({ page }) => {
  await logIn(page);
  await page.goto("/check-in");
  await page.getByLabel("ID number").fill(CNIC);
  await page.getByRole("button", { name: "Find visitor" }).click();
  await expect(page.getByText("Already inside")).toBeVisible();
  await expect(page.getByText(visitNumber)).toBeVisible();
});

test("the visitor is listed inside and checked out", async ({ page }) => {
  await logIn(page);
  await expect(page.getByTestId("inside-count")).toHaveText("1");
  await page.goto("/check-out");
  const row = page.getByTestId("active-visit").filter({ hasText: visitNumber });
  await expect(row).toContainText(VISITOR);
  await row.getByRole("button", { name: /Check out/ }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("laptop, bag");
  await dialog.getByRole("button", { name: "Confirm check-out" }).click();
  await expect(page.getByText(`${VISITOR} (${visitNumber}) checked out.`)).toBeVisible();
  await expect(page.getByText("Nobody is checked in.")).toBeVisible();

  // Checking out again by visit number is harmless and says so.
  await page.getByLabel("Visit number or ID number").fill(visitNumber.toLowerCase());
  await page.getByLabel("Visit number or ID number").press("Enter");
  await expect(page.getByText(/was already checked out/)).toBeVisible();
});

test("the visit appears in the history and on the visitor's record", async ({ page }) => {
  await logIn(page);
  await page.goto("/visits");
  const row = page.getByTestId("visit-row").filter({ hasText: visitNumber });
  await expect(row).toContainText("Checked out");
  await expect(row).toContainText("Sara Ahmed");

  await page.goto("/visitors");
  await page.getByLabel("Search visitors").fill(CNIC);
  await page.getByRole("button", { name: "Search" }).click();
  await page.getByRole("link", { name: new RegExp(VISITOR) }).click();
  await expect(page.getByRole("heading", { name: VISITOR })).toBeVisible();
  await expect(page.getByTestId("visit-row")).toContainText(visitNumber);

  // Capitals are display only: a lower-case name search still finds the visitor.
  await page.goto("/visitors");
  await page.getByLabel("Search visitors").fill(VISITOR.split(" ")[0].toLowerCase());
  await page.getByRole("button", { name: "Search" }).click();
  await expect(page.getByRole("link", { name: new RegExp(VISITOR) })).toContainText(VISITOR.toUpperCase(), { useInnerText: true });
});

test("with several gates the user must choose one", async ({ page }) => {
  await logIn(page);
  await addEntry(page, "gates", "gate", (d) => d.getByLabel("Name").fill("East Gate"), "East Gate");
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/login\?reason=logged_out/);

  await logIn(page);
  const dialog = page.getByRole("dialog", { name: "Which gate are you at?" });
  await expect(dialog).toBeVisible();
  await page.keyboard.press("Escape");                                       // cannot be dismissed
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "East Gate" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByTestId("current-gate")).toHaveText("East Gate");
});
