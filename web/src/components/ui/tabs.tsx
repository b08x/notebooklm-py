import * as TabsPrimitive from "@radix-ui/react-tabs";
import type * as React from "react";
import { cn } from "@/lib/utils";

export const Tabs = TabsPrimitive.Root;
export const TabsContent = TabsPrimitive.Content;

export function TabsList({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.List>) {
  return <TabsPrimitive.List className={cn("flex items-center gap-0.5", className)} {...props} />;
}

export function TabsTrigger({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        "rounded-md px-2.5 py-1 text-[12.5px] text-muted transition-[color,background-color,scale] duration-150 hover:text-fg active:scale-[0.96]",
        "data-[state=active]:bg-surface-2 data-[state=active]:text-fg",
        className,
      )}
      {...props}
    />
  );
}
