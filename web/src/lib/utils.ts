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

export function clauseNumber(externalId: string): string {
  const parts = externalId.split(":");
  return parts.length >= 3 ? `${parts[parts.length - 2]}:${parts[parts.length - 1]}` : externalId;
}

export function formatElapsed(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}
