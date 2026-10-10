import { cva, type VariantProps } from "class-variance-authority";
import type * as React from "react";
import { cn } from "@/lib/utils";

const badgeVariants = cva("inline-flex items-center gap-1 rounded-[4px] px-1.5 font-mono text-[11px] leading-[18px] whitespace-nowrap", {
  variants: {
    tone: {
      neutral: "bg-surface-2 text-muted",
      bad: "bg-bad/15 text-bad",
      ok: "bg-ok/15 text-ok",
      warn: "bg-warn/15 text-warn",
      primary: "bg-primary-soft text-primary",
      info: "bg-secondary/15 text-secondary",
    },
  },
  defaultVariants: { tone: "neutral" },
});

export function Badge({ className, tone, ...props }: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}
