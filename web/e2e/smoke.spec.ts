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

test("map: clicking a projected point opens that chunk (fact-31)", async ({ page, request }) => {
  const auth = { Authorization: `Bearer ${E2E_TOKEN}` };
  const map = await (await request.get(`/v1/corpus/map?notebook_ids=${E2E_NOTEBOOK}`, { headers: auth })).json();
  const points = map.points as { x: number; y: number; external_id: string; preview: string }[];
  expect(points.length).toBeGreaterThan(5);
  expect(map.color_by).toBe("document");

  await page.goto("/ui/map");
  await page.getByRole("checkbox", { name: E2E_NOTEBOOK, exact: true }).click();
  const canvas = page.getByRole("img", { name: `Embedding map of ${points.length} chunks` });
  await expect(canvas).toBeVisible();
  const box = await canvas.boundingBox();
  if (!box) throw new Error("no canvas box");

  // Same projection-to-pixel mapping as MapView (24px padding, y flipped).
  const pad = 24;
  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const target = points[Math.floor(points.length / 2)];
  const px = pad + ((target.x - x0) * (box.width - 2 * pad)) / (x1 - x0 || 1);
  const py = box.height - pad - ((target.y - y0) * (box.height - 2 * pad)) / (y1 - y0 || 1);
  await page.mouse.move(box.x + px, box.y + py);
  await page.mouse.click(box.x + px, box.y + py);
  await expect(page.getByTestId("child-highlight")).toBeVisible();
  const opened = await page.getByTestId("child-highlight").textContent();
  expect(target.preview.startsWith((opened ?? "").slice(0, 20)) || (opened ?? "").startsWith(target.preview.slice(0, 20))).toBe(true);
});
