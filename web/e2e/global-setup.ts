import { E2E_NOTEBOOK } from "../playwright.config";
import { fixture } from "./fixture";

export default function globalSetup(): void {
  fixture(E2E_NOTEBOOK, true);
  fixture(E2E_NOTEBOOK);
}
