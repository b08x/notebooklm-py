import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export const fmt = new Intl.NumberFormat("en-US");

export function shortId(id: string | null | undefined, n = 8): string {
  if (!id) return "—";
  return id.length > n ? `${id.slice(0, n)}…` : id;
}

/** Notebook title, or a short id plus an "untitled" marker — never a full UUID. */
export function notebookLabel(id: string | null | undefined, titles: Map<string, string | null>): string {
  if (!id) return "—";
  const title = titles.get(id);
  return title || `${shortId(id, 8)} untitled`;
}

/** True when a real title is known for the notebook (styles the untitled marker muted). */
export function hasNotebookTitle(id: string | null | undefined, titles: Map<string, string | null>): boolean {
  return !!id && !!titles.get(id);
}

export function clauseNumber(externalId: string): string {
  const parts = externalId.split(":");
  return parts.length >= 3 ? `${parts[parts.length - 2]}:${parts[parts.length - 1]}` : externalId;
}

export function formatElapsed(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}
