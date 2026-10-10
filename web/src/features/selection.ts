import { actions, store } from "@/state/store";
import { getAnchor, getRowIds, setAnchor } from "@/state/rows";

/** Checkbox / ``x`` toggle; shift extends from the last toggled row. */
export function toggleRow(id: string, shift: boolean): void {
  const anchor = getAnchor();
  if (shift && anchor && anchor !== id) {
    actions.selectRange(getRowIds(), anchor, id);
  } else {
    actions.toggleSelect(id);
  }
  setAnchor(id);
  store.set({ cursor: id });
}
