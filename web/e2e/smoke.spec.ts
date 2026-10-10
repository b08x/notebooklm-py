import { expect, test } from "@playwright/test";
import { E2E_NOTEBOOK, E2E_TOKEN } from "../playwright.config";

const QUERY = "OOM killer";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(([token]) => {
    localStorage.setItem("ce-token", token);
    // Short undo window so the confirmed delete is sent quickly.
    (window as unknown as { __CE_DELETE_GRACE_MS: number }).__CE_DELETE_GRACE_MS = 300;
  }, [E2E_TOKEN]);
});

test("search → open chunk → delete → Cancel keeps it → delete → Confirm removes it (fact-47)", async ({ page, request }) => {
  await page.goto("/ui/search");
  await page.getByRole("checkbox", { name: E2E_NOTEBOOK, exact: true }).click();
  await page.getByLabel("Search the corpus").fill(QUERY);

  const rows = page.getByTestId("result-row");
  await expect(rows.first()).toBeVisible();
  await expect(rows.first().locator("mark").first()).toHaveText(/OOM|killer/i);
  const target = rows.filter({ hasText: "The OOM killer picks the process with the largest resident set size first." });
  await expect(target).toHaveCount(1);
  const externalId = await target.getAttribute("data-row-id");
  expect(externalId).toContain(`${E2E_NOTEBOOK}-memory`);

  // Open the chunk: the detail pane shows the clause highlighted in its parent.
  await target.click();
  await expect(page.getByTestId("child-highlight")).toHaveText("The OOM killer picks the process with the largest resident set size first.");

  // Delete → the dialog names the counts → Cancel: nothing is deleted.
  await page.getByRole("button", { name: "Delete" }).click();
  await page.getByRole("menuitem", { name: "This chunk" }).click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toContainText("Delete this chunk?");
  await expect(dialog.getByTestId("delete-counts")).toContainText("Clauses1");
  await expect(dialog.getByTestId("delete-counts")).toContainText("Embeddings1");
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toBeHidden();
  await expect(target).toBeVisible();
  const stillThere = await request.get(`/v1/corpus/chunks/${encodeURIComponent(externalId ?? "")}`, {
    headers: { Authorization: `Bearer ${E2E_TOKEN}` },
  });
  expect(stillThere.status()).toBe(200);

  // Delete → Confirm: the row disappears and the chunk is gone server-side.
  await page.getByRole("button", { name: "Delete" }).click();
  await page.getByRole("menuitem", { name: "This chunk" }).click();
  await expect(dialog.getByTestId("delete-counts")).toContainText("Clauses1");
  await dialog.getByRole("button", { name: "Delete" }).click();
  await expect(target).toHaveCount(0);
  await expect(page.getByText("Deleted 1 chunk")).toBeVisible();
  await expect
    .poll(async () => (await request.get(`/v1/corpus/chunks/${encodeURIComponent(externalId ?? "")}`, { headers: { Authorization: `Bearer ${E2E_TOKEN}` } })).status())
    .toBe(404);

  // Search again: the deleted chunk no longer comes back.
  await page.getByLabel("Search the corpus").fill(`${QUERY} process`);
  await expect(rows.first()).toBeVisible();
  await expect(rows.filter({ hasText: "The OOM killer picks the process with the largest resident set size first." })).toHaveCount(0);
});

test("the UI loads at /ui and the footer reports Postgres (facts 1, 9)", async ({ page }) => {
  await page.goto("/ui/");
  await expect(page.getByRole("navigation", { name: "Views" })).toBeVisible();
  await expect(page.getByTestId("status-postgres")).toContainText(/postgres \d+ms/);
  await expect(page.getByTestId("status-embedder")).toContainText("ollama embed down");
});
