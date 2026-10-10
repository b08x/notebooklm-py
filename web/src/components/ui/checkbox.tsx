import * as CheckboxPrimitive from "@radix-ui/react-checkbox";
import { Check } from "lucide-react";
import type * as React from "react";
import { cn } from "@/lib/utils";

export function Checkbox({ className, ...props }: React.ComponentProps<typeof CheckboxPrimitive.Root>) {
  return (
    <CheckboxPrimitive.Root
      className={cn(
        "grid size-3.5 shrink-0 place-items-center rounded-[4px] shadow-[inset_0_0_0_1px_var(--subtle)] transition-[background-color,box-shadow,scale] duration-150 active:scale-[0.96]",
        "data-[state=checked]:bg-primary data-[state=checked]:shadow-none",
        className,
      )}
      {...props}
    >
      <CheckboxPrimitive.Indicator>
        <Check className="size-3 text-primary-fg" strokeWidth={3} />
      </CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  );
}
