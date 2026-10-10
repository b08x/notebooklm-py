/** Ids of the rows the active list shows, in order (for j/k and shift-click ranges). */
let rowIds: string[] = [];
let anchor: string | null = null;

export function setRowIds(ids: string[]): void {
  rowIds = ids;
}

export function getRowIds(): string[] {
  return rowIds;
}

export function setAnchor(id: string | null): void {
  anchor = id;
}

export function getAnchor(): string | null {
  return anchor;
}
