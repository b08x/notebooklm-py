import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type * as React from "react";
import { cn } from "@/lib/utils";

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;

export function DialogContent({
  className,
  children,
  side,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Content> & { side?: "right" }) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-black/50" />
      <DialogPrimitive.Content
        className={cn(
          "fixed z-50 rounded-xl bg-surface p-4 text-fg shadow-pop outline-none ring-1 ring-line",
          side === "right"
            ? "top-2 right-2 bottom-2 w-[min(560px,calc(100vw-16px))] overflow-hidden p-0"
            : "top-1/2 left-1/2 w-[min(460px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2",
          className,
        )}
        {...props}
      >
        {children}
        <DialogPrimitive.Close
          className="absolute top-3 right-3 rounded-md p-1 text-muted transition-[color,background-color,scale] duration-150 hover:bg-surface-2 hover:text-fg active:scale-[0.96]"
          aria-label="Close"
        >
          <X className="size-4" />
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

export function DialogTitle({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Title>) {
  return <DialogPrimitive.Title className={cn("text-[14px] font-semibold", className)} {...props} />;
}

export function DialogDescription({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Description>) {
  return <DialogPrimitive.Description className={cn("text-[12.5px] text-muted", className)} {...props} />;
}
