import type * as React from "react";

const STOP = new Set(["the", "and", "or", "of", "a", "an", "to", "in", "is", "on", "for"]);

/** Query terms worth highlighting (websearch operators and stop words dropped). */
export function queryTerms(query: string): string[] {
  return Array.from(
    new Set(
      query
        .toLowerCase()
        .replace(/["()]/g, " ")
        .split(/\s+/)
        .map((t) => t.replace(/^[-+]/, ""))
        .filter((t) => t.length > 1 && !STOP.has(t) && t !== "or"),
    ),
  );
}

function escape(term: string): string {
  return term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Wrap every occurrence of the query terms in ``<mark>``. */
export function Highlight({ text, query }: { text: string; query: string }): React.ReactNode {
  const terms = queryTerms(query);
  if (!terms.length) return text;
  const re = new RegExp(`(${terms.map(escape).join("|")})`, "gi");
  const parts = text.split(re);
  return parts.map((part, i) =>
    i % 2 === 1 ? <mark key={i}>{part}</mark> : <span key={i}>{part}</span>,
  );
}
