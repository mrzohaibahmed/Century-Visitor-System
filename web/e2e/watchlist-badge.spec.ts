import fs from "node:fs";

import { chromium, expect, type Page, test } from "@playwright/test";

import { E2E_ADMIN_PASSWORD } from "../playwright.config";
import { decodeQr, writeQrVideo } from "./fake-camera";

/**
 * Phase 4 in a real browser (Edge), against the real API and database:
 *  1. an administrator adds a watchlist entry and that person is refused at check-in;
 *  2. a guard checks a visitor in with a webcam photo, gets a pass and a badge, prints it,
 *     then checks the visitor out by holding the badge's QR code up to the camera.
 * The webcam is Edge's fake camera (a test pattern, and for the scan a video of the
 * badge's QR code). Real webcams, badge printers and USB scanners are covered by the
 * manual acceptance test (docs in README, "Phase 4").
 */

const GUARD = { username: "e2e.gate", name: "Gate Guard", temp: "Temp-Gate-Pass-1", own: "Own-Gate-Pass-33" };
const BANNED = { cnic: "35202-1111111-1", name: "Kamran Akmal", reason: "Assaulted a security guard." };
const VISITOR = { cnic: "35202-2222222-2", name: "Nadia Hussain" };

test.describe.configure({ mode: "serial" });

async function csrf(page: Page): Promise<string> {
  return (await page.context().cookies()).find((c) => c.name === "cg_csrf")?.value ?? "";
}

async function api<T>(page: Page, method: "GET" | "POST", path: string, data?: unknown): Promise<T> {
  const response = await page.request.fetch(`/api/v1${path}`, {
    method, data, headers: method === "POST" ? { "X-CSRF-Token": await csrf(page) } : {},
  });
  expect(response.ok(), `${method} ${path}: ${response.status()}`).toBeTruthy();
  return (await response.json()) as T;
}

/** Logs in; with several gates (after visits.spec.ts), works at Main Gate. */
async function logIn(page: Page, username: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page).toHaveURL(/\/(dashboard|account\/password)/);
  if (!page.url().includes("/account/password")) await workAtMainGate(page);
}

async function workAtMainGate(page: Page) {
  const gates = await api<{ name: string }[]>(page, "GET", "/gates");
  if (gates.length > 1) {
    await page.getByRole("dialog", { name: "Which gate are you at?" }).getByRole("button", { name: "Main Gate" }).click();
  }
  if (gates.length > 0) await expect(page.getByTestId("current-gate")).toHaveText("Main Gate");
}

/** The gate, department and host this spec needs, whether or not visits.spec.ts ran first. */
async function ensureDirectory(page: Page) {
  const gates = await api<{ name: string }[]>(page, "GET", "/gates");
  if (!gates.some((g) => g.name === "Main Gate")) await api(page, "POST", "/gates", { name: "Main Gate" });
  const departments = await api<{ id: string; name: string }[]>(page, "GET", "/departments");
  const hr = departments.find((d) => d.name === "Human Resources")
    ?? await api<{ id: string }>(page, "POST", "/departments", { name: "Human Resources" });
  const hosts = await api<{ name: string }[]>(page, "GET", "/hosts");
  if (!hosts.some((h) => h.name === "Sara Ahmed")) {
    await api(page, "POST", "/hosts", { name: "Sara Ahmed", department_id: hr.id });
  }
}

test("admin adds a watchlist entry and that person is refused at check-in", async ({ page }) => {
  await logIn(page, "admin", E2E_ADMIN_PASSWORD);
  await ensureDirectory(page);

  await page.getByRole("link", { name: "Watchlist" }).click();
  await expect(page).toHaveURL(/\/watchlist/);
  await page.getByRole("button", { name: "Add to watchlist" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("ID number").fill(BANNED.cnic.replaceAll("-", " "));        // any format
  await dialog.getByLabel("Name (optional)").fill(BANNED.name);
  await dialog.getByLabel("Reason").fill(BANNED.reason);
  await dialog.getByRole("button", { name: "Add to watchlist" }).click();
  await expect(page.getByText(`${BANNED.name} added to the watchlist.`)).toBeVisible();
  const row = page.getByTestId("watchlist-row").filter({ hasText: BANNED.name });
  await expect(row).toContainText(BANNED.cnic);                                       // normalised by the server
  await expect(row).toContainText("Active");
  await expect(row).toContainText("E2E Administrator");

  await page.goto("/check-in");
  await page.getByLabel("ID number").fill(BANNED.cnic.replaceAll("-", ""));
  await page.getByRole("button", { name: "Find visitor" }).click();
  await page.getByLabel("Full name").fill(BANNED.name);
  await page.getByRole("button", { name: "Register and continue" }).click();
  const denied = page.getByTestId("entry-denied");
  await expect(denied).toContainText(`${BANNED.name} is on the watchlist and must not be admitted.`);
  await expect(denied).toContainText(BANNED.reason);
  await expect(page.getByRole("button", { name: "Review" })).toHaveCount(0);

  // The guard account used by the next tests.
  await api(page, "POST", "/users", { username: GUARD.username, display_name: GUARD.name, role: "GUARD",
                                      password: GUARD.temp });
});

let visitNumber = "";
let qrVideo = "";

test("guard checks a visitor in with a photo, a pass and a printed badge", async ({ page }, testInfo) => {
  await page.addInitScript(() => {
    // The print dialog cannot be driven by a test; count the calls instead.
    (window as unknown as { prints: number }).prints = 0;
    window.print = () => { (window as unknown as { prints: number }).prints += 1; };
  });
  await logIn(page, GUARD.username, GUARD.temp);
  await page.getByLabel("Current password").fill(GUARD.temp);
  await page.getByLabel("New password", { exact: true }).fill(GUARD.own);
  await page.getByLabel("Confirm new password").fill(GUARD.own);
  await page.getByRole("button", { name: "Change password" }).click();
  await expect(page).toHaveURL(/\/dashboard/);
  await workAtMainGate(page);

  await expect(page.getByRole("link", { name: "Watchlist" })).toHaveCount(0);
  expect((await page.request.get("/api/v1/watchlist")).status()).toBe(403);

  await page.goto("/check-in");
  await page.getByLabel("ID number").fill(VISITOR.cnic);
  await page.getByRole("button", { name: "Find visitor" }).click();
  await page.getByLabel("Full name").fill(VISITOR.name);
  await page.getByRole("button", { name: "Register and continue" }).click();
  await page.getByLabel("Host (person being visited)").fill("sar");
  await page.getByRole("button", { name: /Sara Ahmed/ }).click();
  await page.getByLabel("Reason for visit").selectOption("OFFICIAL_MEETING");
  await page.getByLabel("Belongings (optional)").fill("laptop");
  await page.getByRole("button", { name: "Review" }).click();

  // Photo: Edge's fake camera → capture → preview → upload (validated and re-encoded by the API).
  await page.getByRole("button", { name: "Start camera" }).click();
  await page.getByRole("button", { name: "Take photo" }).click();
  await expect(page.getByTestId("captured-photo")).toBeVisible();
  await page.getByRole("button", { name: "Retake" }).click();
  await page.getByRole("button", { name: "Take photo" }).click();
  await page.getByRole("button", { name: "Use this photo" }).click();
  const photo = page.getByTestId("visitor-photo");
  await expect(photo).toBeVisible();
  await expect.poll(() => photo.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth)).toBeGreaterThan(0);

  await page.getByRole("button", { name: "Confirm check-in" }).click();
  visitNumber = (await page.getByTestId("visit-number").textContent()) ?? "";
  expect(visitNumber).toMatch(/^V-\d{4}-\d{6}$/);

  // Pass and badge: gate information and a QR code; no ID number anywhere on it.
  const badge = page.getByTestId("badge-card");
  await expect(page.getByTestId("badge-name")).toHaveText(VISITOR.name);
  await expect(page.getByTestId("badge-visit-number")).toHaveText(visitNumber);
  await expect(badge).toContainText("Sara Ahmed");
  await expect(badge).not.toContainText("35202");
  const qr = page.getByTestId("badge-qr");
  await expect(qr).toBeVisible();
  const qrPng = await qr.screenshot();
  const qrText = decodeQr(qrPng);
  expect(qrText).toMatch(/^CGP1:[0-9A-F]{64}$/);                       // only the random token
  qrVideo = testInfo.outputPath("badge-qr.y4m");
  writeQrVideo(qrPng, qrVideo);

  await page.getByRole("button", { name: "Print badge" }).click();
  await expect.poll(() => page.evaluate(() => (window as unknown as { prints: number }).prints)).toBe(1);

  // What the printer receives: one 54 × 86 mm page with only the badge on it.
  await page.emulateMedia({ media: "print" });
  const pdf = await page.pdf({ preferCSSPageSize: true, printBackground: true });
  // Kept in test-results/ for a visual check: what the printer would receive.
  fs.writeFileSync(testInfo.outputPath("badge.pdf"), pdf);
  await page.screenshot({ path: testInfo.outputPath("badge-print-view.png") });
  const text = pdf.toString("latin1");
  const box = text.match(/\/MediaBox\s*\[\s*0 0 ([\d.]+) ([\d.]+)\s*\]/);
  expect(box, "page size in the PDF").not.toBeNull();
  expect(Number(box![1])).toBeCloseTo(153.07, 0);                    // 54 mm in points
  expect(Number(box![2])).toBeCloseTo(243.78, 0);                    // 86 mm in points
  expect(text.match(/\/Type\s*\/Page[^s]/g)?.length).toBe(1);
});

test("guard checks the visitor out by scanning the badge with the camera", async ({ baseURL }) => {
  test.skip(!qrVideo, "needs the badge from the previous test");
  // A browser whose camera shows the badge's QR code.
  const browser = await chromium.launch({
    channel: "msedge",
    args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
           `--use-file-for-fake-video-capture=${qrVideo}`],
  });
  try {
    const context = await browser.newContext({ baseURL, permissions: ["camera"] });
    const page = await context.newPage();
    await logIn(page, GUARD.username, GUARD.own);
    await page.goto("/check-out");
    await expect(page.getByTestId("active-visit").filter({ hasText: visitNumber })).toBeVisible();

    await page.getByRole("button", { name: "Scan badge with camera" }).click();
    const confirm = page.getByTestId("scan-confirm");
    await expect(confirm).toContainText(VISITOR.name, { timeout: 20_000 });
    await expect(confirm).toContainText(visitNumber);
    await expect(confirm).toContainText("Belongings recorded at entry: laptop");
    await expect(confirm.getByTestId("visitor-photo")).toBeVisible();          // the photo taken at check-in
    // Scanning alone changed nothing: the visitor is still listed inside.
    await expect(page.getByTestId("active-visit").filter({ hasText: visitNumber })).toHaveCount(1);
    await confirm.getByRole("button", { name: "Confirm check-out" }).click();
    await expect(page.getByText(`${VISITOR.name} (${visitNumber}) checked out.`)).toBeVisible();
    await expect(page.getByTestId("active-visit").filter({ hasText: visitNumber })).toHaveCount(0);

    // The same badge again: shows who it was, changes nothing.
    await page.getByRole("button", { name: "Scan badge with camera" }).click();
    await expect(page.getByTestId("scan-confirm")).toContainText("already checked out", { timeout: 20_000 });
    await context.close();
  } finally {
    await browser.close();
  }
});
