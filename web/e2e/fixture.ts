import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

/** Run scripts/seed_corpus_fixture.py (seed, or remove with ``--remove``). */
export function fixture(notebook: string, remove = false): Record<string, unknown> {
  const args = ["run", "python", "scripts/seed_corpus_fixture.py", "--notebook", notebook];
  if (remove) args.push("--remove");
  const out = execFileSync("uv", args, { cwd: ROOT, encoding: "utf-8", stdio: ["ignore", "pipe", "inherit"] });
  return JSON.parse(out.trim().split("\n").pop() ?? "{}") as Record<string, unknown>;
}
