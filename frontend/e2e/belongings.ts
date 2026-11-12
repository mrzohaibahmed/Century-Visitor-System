import { expect, type Page } from "@playwright/test";

/**
 * Records belongings on the check-in details step through the "Personal material returnable" slip:
 * opens the dialog, fills one description per item (adding rows as needed) and saves it.
 * The slip stores descriptions in capitals, so check-out shows them that way (e.g. "LAPTOP, BAG").
 */
export async function addBelongings(page: Page, items: string[]) {
  await page.getByRole("button", { name: /Open form/ }).click();
  const slip = page.getByRole("dialog", { name: "PERSONAL MATERIAL RETURNABLE" });
  await expect(slip).toBeVisible();
  for (const [index, item] of items.entries()) {
    if (index > 0) await slip.getByRole("button", { name: "Add item" }).click();
    await slip.getByLabel(`Description ${index + 1}`).fill(item);
  }
  await slip.getByRole("button", { name: "Save belongings" }).click();
  await expect(slip).toBeHidden();
  // The details step now lists them on the button that opens the slip.
  await expect(page.getByRole("button", { name: /Edit/ }).filter({ hasText: items[0].toUpperCase() })).toBeVisible();
}
