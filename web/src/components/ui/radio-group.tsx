import * as RadioGroupPrimitive from "@radix-ui/react-radio-group";
import type * as React from "react";
import { cn } from "@/lib/utils";

export const RadioGroup = RadioGroupPrimitive.Root;

export function RadioGroupItem({ className, ...props }: React.ComponentProps<typeof RadioGroupPrimitive.Item>) {
  return (
    <RadioGroupPrimitive.Item
      className={cn(
        "grid size-3.5 shrink-0 place-items-center rounded-full shadow-[inset_0_0_0_1px_var(--subtle)] transition-[box-shadow] duration-150 data-[state=checked]:shadow-[inset_0_0_0_1px_var(--primary)]",
        className,
      )}
      {...props}
    >
      <RadioGroupPrimitive.Indicator className="size-1.5 rounded-full bg-primary" />
    </RadioGroupPrimitive.Item>
  );
}
