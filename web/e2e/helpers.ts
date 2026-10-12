import type { Page } from "@playwright/test";
import { E2E_NOTEBOOK_TITLE } from "../playwright.config";

/** Tick the fixture notebook in the Filters facet, expanding it first when a real corpus pushes it past the top 8. */
export async function selectFixtureNotebook(page: Page): Promise<void> {
  const facet = page.getByRole("region", { name: "Notebook" });
  const box = facet.getByRole("checkbox", { name: E2E_NOTEBOOK_TITLE, exact: true });
  const showAll = facet.getByRole("button", { name: /^Show all/ });
  await facet.getByRole("checkbox").first().waitFor();
  if (!(await box.isVisible()) && (await showAll.isVisible())) await showAll.click();
  await box.click();
}
