import type * as React from "react";
import { cn } from "@/lib/utils";

export function Kbd({ className, ...props }: React.ComponentProps<"kbd">) {
  return (
    <kbd
      className={cn(
        "inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-[4px] bg-surface-2 px-1 font-mono text-[11px] font-medium text-muted shadow-[inset_0_0_0_1px_var(--line)]",
        className,
      )}
      {...props}
    />
  );
}
