import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const WEB = path.resolve(__dirname, "..", "..");
const pkg = JSON.parse(readFileSync(path.join(WEB, "package.json"), "utf-8")) as {
  dependencies: Record<string, string>;
  devDependencies: Record<string, string>;
};

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name);
    return statSync(full).isDirectory() ? files(full) : [full];
  });
}

describe("frontend stack (fact-5)", () => {
  it("is Vite + React + TypeScript + Tailwind + shadcn/ui + TanStack Query/Table", () => {
    const all = { ...pkg.dependencies, ...pkg.devDependencies };
    for (const dep of ["vite", "react", "react-dom", "typescript", "tailwindcss", "@tailwindcss/vite", "@tanstack/react-query", "@tanstack/react-table", "@tanstack/react-virtual", "cmdk", "motion"]) {
      expect(all, dep).toHaveProperty(dep);
    }
    const shadcn = JSON.parse(readFileSync(path.join(WEB, "components.json"), "utf-8")) as { aliases: { ui: string } };
    expect(shadcn.aliases.ui).toBe("@/components/ui");
  });

  it("builds into the server's static/ui directory under the /ui base", () => {
    const config = readFileSync(path.join(WEB, "vite.config.ts"), "utf-8");
    expect(config).toContain('base: "/ui/"');
    expect(config).toContain('outDir: "../src/notebooklm/server/static/ui"');
  });
});

describe("motion and press rules (fact-44)", () => {
  const sources = files(path.join(WEB, "src")).filter((f) => /\.(tsx?|css)$/.test(f) && !f.endsWith(".test.ts") && !f.endsWith(".test.tsx"));

  it("no stylesheet or class uses transition: all", () => {
    for (const f of sources) {
      const text = readFileSync(f, "utf-8");
      expect(text, f).not.toMatch(/transition:\s*all|transition-all/);
    }
  });

  it("buttons scale to 0.96 on press", () => {
    const button = readFileSync(path.join(WEB, "src/components/ui/button.tsx"), "utf-8");
    expect(button).toContain("active:scale-[0.96]");
    expect(button).toMatch(/transition-\[[^\]]*scale/);
  });
});
