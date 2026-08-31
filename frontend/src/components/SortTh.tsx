import type { Sorter } from "../hooks/useSortableRows";

/** Table header cell that toggles sorting on the column identified by `sortKey`. */
export function SortTh({
  label, sortKey, sorter, className, title,
}: {
  label: React.ReactNode;
  sortKey: string;
  sorter: Sorter;
  className?: string;
  title?: string;
}) {
  const active = sorter.sort?.key === sortKey;
  const arrow = active ? (sorter.sort!.dir === "asc" ? "\u25B2" : "\u25BC") : "\u21C5";
  return (
    <th
      className={`th-sortable${active ? " th-sorted" : ""}${className ? ` ${className}` : ""}`}
      onClick={() => sorter.onSort(sortKey)}
      title={title}
    >
      <span className="th-sortable-inner">
        {label}
        <span className="th-sort-arrow">{arrow}</span>
      </span>
    </th>
  );
}
