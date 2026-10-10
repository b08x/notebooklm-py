import { Fragment } from "react";
import { actions } from "@/state/store";

/** Answer text with ``[Cn]`` turned into chips that open the cited chunk. */
export function AnswerText({ text, labels }: { text: string; labels: Record<string, string> }) {
  const parts = text.split(/(\[C\d+\])/g);
  return (
    <p className="text-[14px] leading-[1.65] whitespace-pre-wrap text-pretty" data-testid="answer">
      {parts.map((part, i) => {
        const m = /^\[(C\d+)\]$/.exec(part);
        const id = m ? labels[m[1]] : undefined;
        if (!m || !id) return <Fragment key={i}>{part}</Fragment>;
        return (
          <button
            key={i}
            type="button"
            onClick={() => actions.open(id)}
            title={id}
            className="mx-0.5 rounded-[4px] bg-primary-soft px-1 align-[2px] font-semibold text-[11px] text-primary transition-[scale,background-color] duration-150 hover:bg-primary/25 active:scale-[0.96]"
          >
            {m[1]}
          </button>
        );
      })}
    </p>
  );
}
