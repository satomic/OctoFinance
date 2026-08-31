import { useCallback, useState } from "react";

export type SortDir = "asc" | "desc";
export type SortValue = string | number | boolean | null | undefined;
export type SortState = { key: string; dir: SortDir } | null;

export interface Sorter {
  sort: SortState;
  onSort: (key: string) => void;
}

function compare(a: SortValue, b: SortValue): number {
  const aEmpty = a === null || a === undefined || a === "";
  const bEmpty = b === null || b === undefined || b === "";
  if (aEmpty && bEmpty) return 0;
  if (aEmpty) return 1;
  if (bEmpty) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  if (typeof a === "boolean" || typeof b === "boolean") return Number(a) - Number(b);
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

/**
 * Sorts rows by a column key. Columns whose value is not a plain property of the
 * row (derived percentages, joined lists) need an entry in `accessors`.
 */
export function useSortableRows<T>(
  rows: T[],
  accessors?: Record<string, (row: T) => SortValue>,
  initial: SortState = null,
): { rows: T[]; sort: SortState; onSort: (key: string) => void } {
  const [sort, setSort] = useState<SortState>(initial);

  const onSort = useCallback((key: string) => {
    setSort((prev) =>
      prev && prev.key === key
        ? { key, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { key, dir: "desc" },
    );
  }, []);

  if (!sort) return { rows, sort, onSort };

  const custom = accessors?.[sort.key];
  const get = custom ?? ((row: T) => (row as Record<string, unknown>)[sort.key] as SortValue);
  const dir = sort.dir === "asc" ? 1 : -1;
  const sorted = [...rows].sort((a, b) => compare(get(a), get(b)) * dir);

  return { rows: sorted, sort, onSort };
}
