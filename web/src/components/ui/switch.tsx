import * as SwitchPrimitive from "@radix-ui/react-switch";
import type * as React from "react";
import { cn } from "@/lib/utils";

export function Switch({ className, ...props }: React.ComponentProps<typeof SwitchPrimitive.Root>) {
  return (
    <SwitchPrimitive.Root
      className={cn(
        "relative inline-flex h-4 w-7 shrink-0 items-center rounded-full bg-surface-2 shadow-[inset_0_0_0_1px_var(--line)] transition-[background-color] duration-150 data-[state=checked]:bg-primary",
        className,
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb className="block size-3 translate-x-0.5 rounded-full bg-muted transition-[translate,background-color] duration-150 data-[state=checked]:translate-x-[14px] data-[state=checked]:bg-primary-fg" />
    </SwitchPrimitive.Root>
  );
}
