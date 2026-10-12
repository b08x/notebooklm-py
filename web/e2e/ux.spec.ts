import { expect, test } from "@playwright/test";
import { E2E_TOKEN } from "../playwright.config";
import { selectFixtureNotebook } from "./helpers";

test.beforeEach(async ({ page }) => {
  await page.addInitScript((token) => {
    localStorage.setItem("ce-token", token);
  }, E2E_TOKEN);
});

test("browse: dragging the Document column handle resizes it, double-click resets (fact-8)", async ({ page }) => {
  await page.goto("/ui/browse");
  await selectFixtureNotebook(page);
  const handle = page.getByTestId("resize-doc");
  await expect(handle).toBeVisible();
  await expect(page.locator("[data-row-id]").first()).toBeVisible();

  // The Text column is the 1fr track, so widening Document shrinks Text and the handle
  // (on Document's right edge) stays put — measure the header cell's width instead.
  const header = handle.locator("..");
  const width = async (): Promise<number> => (await header.boundingBox())?.width ?? 0;
  const before = await handle.boundingBox();
  if (!before) throw new Error("no resize handle box");
  const w0 = await width();
  await page.mouse.move(before.x + before.width / 2, before.y + before.height / 2);
  await page.mouse.down();
  await page.mouse.move(before.x + before.width / 2 + 80, before.y + before.height / 2, { steps: 8 });
  await page.mouse.up();
  await expect.poll(width).toBeGreaterThanOrEqual(w0 + 70);

  // A double-click restores the default width.
  await handle.dblclick();
  await expect.poll(async () => Math.abs((await width()) - w0)).toBeLessThan(5);
});

test("map: wheel zoom changes the transform and Reset restores it (facts 19-21)", async ({ page }) => {
  await page.goto("/ui/map");
  await selectFixtureNotebook(page);
  const canvas = page.getByRole("img", { name: /^Embedding map of/ });
  await expect(canvas).toBeVisible();
  await expect(page.getByTestId("map")).toHaveAttribute("data-k", "1.00");

  const box = await canvas.boundingBox();
  if (!box) throw new Error("no canvas box");
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.wheel(0, -400);
  await expect.poll(async () => Number(await page.getByTestId("map").getAttribute("data-k"))).toBeGreaterThan(1);

  await page.getByTestId("map-reset").click();
  await expect(page.getByTestId("map")).toHaveAttribute("data-k", "1.00");
});

test("history: Back/Forward walk tabs and the open chunk; a deep URL restores the view (facts 25-27)", async ({ page }) => {
  await page.goto("/ui/browse");
  await selectFixtureNotebook(page);
  const row = page.locator("[data-row-id]").first();
  await expect(row).toBeVisible();
  await row.click();
  await expect(page.getByTestId("child-highlight")).toBeVisible();
  const chunkUrl = page.url();
  expect(chunkUrl).toContain("/ui/browse?");
  expect(chunkUrl).toContain("chunk=");

  // Switching tabs pushes another entry.
  await page.getByRole("navigation", { name: "Views" }).getByRole("button", { name: "Map" }).click();
  await expect(page).toHaveURL(/\/ui\/map/);

  // Back: Browse with the chunk still open.
  await page.goBack();
  await expect(page).toHaveURL(/\/ui\/browse\?/);
  await expect(page.getByTestId("child-highlight")).toBeVisible();

  // Back again: Browse with no chunk (the filter entry, not a new one).
  await page.goBack();
  expect(page.url()).toContain("/ui/browse");
  expect(page.url()).not.toContain("chunk=");
  await expect(page.getByTestId("child-highlight")).toBeHidden();

  // Forward: the chunk is open again.
  await page.goForward();
  await expect(page.getByTestId("child-highlight")).toBeVisible();

  // Reloading the deep URL restores the same view.
  await page.goto(chunkUrl);
  await expect(page.getByTestId("child-highlight")).toBeVisible();
  await expect(page.getByTestId("breadcrumb")).toBeVisible();
});
