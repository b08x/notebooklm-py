import { AnimatePresence, motion } from "motion/react";
import { ArrowUp } from "lucide-react";
import { fmt } from "@/lib/utils";

/** "↑ N new chunks" — shown while ingestion adds rows; click refreshes the results. */
export function NewChunksPill({ count, onClick }: { count: number; onClick: () => void }) {
  return (
    <AnimatePresence initial={false}>
      {count > 0 && (
        <motion.button
          type="button"
          key="pill"
          initial={{ opacity: 0, scale: 0.9, filter: "blur(4px)" }}
          animate={{ opacity: 1, scale: 1, filter: "blur(0px)" }}
          exit={{ opacity: 0, scale: 0.9, filter: "blur(4px)" }}
          transition={{ duration: 0.16, ease: "easeOut" }}
          onClick={onClick}
          className="ml-auto inline-flex items-center gap-1 rounded-full bg-primary-soft px-2.5 py-0.5 text-[12px] font-medium text-primary transition-[scale] duration-150 active:scale-[0.96]"
        >
          <ArrowUp className="size-3" />
          {fmt.format(count)} new {count === 1 ? "chunk" : "chunks"}
        </motion.button>
      )}
    </AnimatePresence>
  );
}
