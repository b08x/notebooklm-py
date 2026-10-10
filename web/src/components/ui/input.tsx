import type * as React from "react";
import { cn } from "@/lib/utils";

export function Input({ className, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      className={cn(
        "h-8 w-full rounded-lg bg-surface px-2.5 text-[13px] text-fg shadow-[inset_0_0_0_1px_var(--line)] outline-none placeholder:text-subtle",
        "transition-[box-shadow] duration-150 focus-visible:shadow-[inset_0_0_0_1px_var(--primary)] focus-visible:outline-none",
        className,
      )}
      {...props}
    />
  );
}
