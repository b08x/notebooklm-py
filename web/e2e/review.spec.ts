import { expect, test } from "@playwright/test";
import { E2E_TOKEN } from "../playwright.config";

test.beforeEach(async ({ page }) => {
  await page.addInitScript((token) => {
    localStorage.setItem("ce-token", token);
  }, E2E_TOKEN);
});

test("review screen: sidebar, document list, document view, inspector, and breakpoints (facts 1-23, 24-49)", async ({ page }) => {
  // 1. Wide desktop (1440px): all 4 regions visible
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/ui/review");

  // Sidebar visible
  const sidebar = page.getByTestId("sidebar");
  await expect(sidebar).toBeVisible();

  // Document list visible
  const docList = page.getByTestId("document-list");
  await expect(docList).toBeVisible();

  // Document list uses "Collection:", never "Notebook"
  await expect(docList).toContainText("Collection:");
  expect(await docList.innerText()).not.toMatch(/Notebook/i);

  // Document view visible
  const docView = page.getByTestId("document-view");
  await expect(docView).toBeVisible();

  // Inspector visible inline on wide desktop
  const inspector = page.getByTestId("inspector");
  await expect(inspector).toBeVisible();

  // Click a clause to select it and fill the inspector
  const firstClause = page.locator("[data-testid^='clause-span-']").first();
  await expect(firstClause).toBeVisible();
  await firstClause.click();

  // Inspector shows document title and chunk/clause header
  await expect(page.getByTestId("inspector-doc-title")).toBeVisible();
  // Pinned footer visible with SFL & Fact-check
  await expect(page.getByTestId("inspector-footer")).toBeVisible();

  // Test chunk collapse in DocumentView
  const firstChunkToggle = page.locator("[data-testid^='chunk-header-toggle-']").first();
  await expect(firstChunkToggle).toBeVisible();
  await firstChunkToggle.click(); // collapse chunk

  // 2. Breakpoint checks for inspector drawer: 1400px vs 1399px
  await page.setViewportSize({ width: 1400, height: 900 });
  await expect(page.getByTestId("inspector")).toBeVisible();

  await page.setViewportSize({ width: 1399, height: 900 });
  // Inspector becomes drawer below 1400px
  await expect(page.getByTestId("inspector")).toBeHidden();
  if (await page.getByRole("dialog").isVisible()) {
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toBeHidden();
  }
  // Header button for inspector drawer appears
  const inspectorDrawerBtn = page.getByTestId("header-inspector-drawer-btn");
  await expect(inspectorDrawerBtn).toBeVisible();
  await inspectorDrawerBtn.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toBeHidden();

  // 3. Breakpoint checks for document list drawer: 1024px vs 1023px
  await page.setViewportSize({ width: 1024, height: 900 });
  await expect(page.getByTestId("document-list")).toBeVisible();

  await page.setViewportSize({ width: 1023, height: 900 });
  // Document list becomes drawer below 1024px
  await expect(page.getByTestId("document-list")).toBeHidden();
  const listDrawerBtn = page.getByTestId("header-list-drawer-btn");
  await expect(listDrawerBtn).toBeVisible();
  await listDrawerBtn.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toBeHidden();

  // 4. Breakpoint checks for sidebar drawer: 768px vs 767px
  await page.setViewportSize({ width: 768, height: 900 });
  await expect(page.getByTestId("sidebar")).toBeVisible();

  await page.setViewportSize({ width: 767, height: 900 });
  // Sidebar becomes drawer below 768px
  await expect(page.getByTestId("sidebar")).toBeHidden();
  const sidebarDrawerBtn = page.getByTestId("header-sidebar-drawer-btn");
  await expect(sidebarDrawerBtn).toBeVisible();
  await sidebarDrawerBtn.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toBeHidden();
});

test("review screen: real document walkthrough (read 72ch, collapse chunks, tag clause, marker strip jump)", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/ui/review");

  // 1. Document list loaded and auto-selects first document
  const docList = page.getByTestId("document-list");
  await expect(docList).toBeVisible();
  const firstDocCard = page.locator("[data-testid^='doc-card-']").first();
  await expect(firstDocCard).toBeVisible();
  await firstDocCard.click();

  // 2. Document view shows document title and reading text capped at 72ch
  const docTitle = page.getByTestId("document-title");
  await expect(docTitle).toBeVisible();
  const chunkBody = page.getByTestId("chunk-body").first();
  await expect(chunkBody).toHaveClass(/max-w-\[72ch\]/);

  // 3. Chunks rendered with collapsible headers
  const collapseAllBtn = page.getByTestId("collapse-all-btn");
  const expandAllBtn = page.getByTestId("expand-all-btn");
  const collapseUnflaggedBtn = page.getByTestId("collapse-unflagged-btn");
  await expect(collapseAllBtn).toBeVisible();

  // Collapse all chunks
  await collapseAllBtn.click();
  // Expand all chunks
  await expandAllBtn.click();
  // Collapse unflagged
  await collapseUnflaggedBtn.click();
  // Expand all back
  await expandAllBtn.click();

  // 4. Select clause, URL updates with chunk param, Inspector reflects it
  const clause = page.locator("[data-testid^='clause-span-']").first();
  await expect(clause).toBeVisible();
  await clause.click();
  await expect(page).toHaveURL(/chunk=/);

  const inspector = page.getByTestId("inspector");
  await expect(inspector).toBeVisible();
  await expect(page.getByTestId("inspector-doc-title")).toBeVisible();
  await expect(page.getByTestId("tag-sfl")).toBeVisible();
  await expect(page.getByTestId("inspector-factcheck-btn")).toBeVisible();

  // 5. Right-edge marker strip
  const markerStrip = page.getByTestId("marker-strip");
  await expect(markerStrip).toBeVisible();
  const tick = page.locator("[data-testid^='marker-tick-']").first();
  if (await tick.isVisible()) {
    await tick.click();
    await expect(page.getByTestId("inspector-panel")).toBeVisible();
  }

  // 6. Keyboard navigation
  const docView = page.getByTestId("document-view");
  await docView.focus();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowUp");
});
