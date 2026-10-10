import type * as React from "react";
import { cn } from "@/lib/utils";

export function SectionLabel({ className, ...props }: React.ComponentProps<"h4">) {
  return <h4 className={cn("mb-2 text-[11px] font-semibold tracking-[0.06em] text-subtle uppercase", className)} {...props} />;
}
