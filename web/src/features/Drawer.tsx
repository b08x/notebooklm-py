import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type * as React from "react";
import { cn } from "@/lib/utils";

export interface DrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  side?: "left" | "right";
  width?: number | string;
  title?: string;
  description?: string;
  children: React.ReactNode;
  className?: string;
}

export function Drawer({
  open,
  onOpenChange,
  side = "right",
  width,
  title,
  description,
  children,
  className,
}: DrawerProps) {
  const defaultWidth = side === "left" ? 320 : 360;
  const w = width ?? defaultWidth;
  const widthStyle = typeof w === "number" ? `${w}px` : w;

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-black/50 backdrop-blur-[1px] transition-opacity duration-150 animate-in fade-in" />
        <DialogPrimitive.Content
          aria-describedby={description ? "drawer-desc" : undefined}
          style={{ width: `min(${widthStyle}, calc(100vw - 16px))` }}
          className={cn(
            "fixed z-50 rounded-xl bg-surface text-fg shadow-pop outline-none ring-1 ring-line top-2 bottom-2 overflow-hidden flex flex-col p-0 transition-transform duration-150",
            side === "left" ? "left-2 animate-in slide-in-from-left" : "right-2 animate-in slide-in-from-right",
            className,
          )}
        >
          {title ? (
            <DialogPrimitive.Title className="sr-only">{title}</DialogPrimitive.Title>
          ) : (
            <DialogPrimitive.Title className="sr-only">Drawer</DialogPrimitive.Title>
          )}
          {description && (
            <DialogPrimitive.Description id="drawer-desc" className="sr-only">
              {description}
            </DialogPrimitive.Description>
          )}
          <DialogPrimitive.Close
            className="absolute top-2.5 right-2.5 z-50 rounded-md p-1 text-muted transition-[color,background-color,scale] duration-150 hover:bg-surface-2 hover:text-fg active:scale-[0.96]"
            aria-label="Close"
          >
            <X className="size-4" />
          </DialogPrimitive.Close>
          <div className="flex-1 min-h-0 min-w-0 overflow-hidden flex flex-col">
            {children}
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
