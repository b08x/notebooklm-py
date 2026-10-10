import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import type * as React from "react";
import { cn } from "@/lib/utils";

export const buttonVariants = cva(
  [
    "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-lg text-[12.5px] font-medium select-none",
    "transition-[color,background-color,box-shadow,scale,opacity] duration-150 ease-out",
    "active:scale-[0.96] disabled:pointer-events-none disabled:opacity-50",
    "[&_svg]:pointer-events-none [&_svg]:size-3.5 [&_svg]:shrink-0",
  ],
  {
    variants: {
      variant: {
        default: "bg-surface-2 text-fg shadow-[inset_0_0_0_1px_var(--line)] hover:bg-line/60",
        primary: "bg-primary text-primary-fg hover:opacity-90",
        ghost: "text-muted hover:bg-surface-2 hover:text-fg",
        destructive: "bg-surface-2 text-bad shadow-[inset_0_0_0_1px_var(--line)] hover:bg-bad/15",
        solidDestructive: "bg-bad text-white hover:opacity-90",
      },
      size: {
        sm: "h-7 px-2.5",
        md: "h-8 px-3",
        icon: "size-7",
      },
    },
    defaultVariants: { variant: "default", size: "sm" },
  },
);

export function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: React.ComponentProps<"button"> & VariantProps<typeof buttonVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot : "button";
  return <Comp data-slot="button" className={cn(buttonVariants({ variant, size }), className)} {...props} />;
}
