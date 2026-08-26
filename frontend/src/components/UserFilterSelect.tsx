import { useState, useMemo, useRef, useEffect } from "react";
import { useI18n } from "../contexts/I18nContext";

interface Props {
  options: string[];
  value: string;
  onChange: (v: string) => void;
}

/**
 * Single-select user filter with type-ahead search.
 *
 * Only one user can be selected at a time; picking the "all users" entry
 * clears the filter.
 */
export function UserFilterSelect({ options, value, onChange }: Props) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    if (open) document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  const toggle = () => {
    if (open) {
      setOpen(false);
      return;
    }
    setQuery("");
    setOpen(true);
  };

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = q ? options.filter((o) => o.toLowerCase().includes(q)) : options;
    return list.slice(0, 200);
  }, [options, query]);

  const select = (v: string) => {
    onChange(v);
    setOpen(false);
  };

  return (
    <div className="org-dropdown" ref={ref} style={{ minWidth: 160 }}>
      <button
        className="org-dropdown-trigger"
        data-filter="user"
        onClick={toggle}
        title={t("userFilter.hint")}
      >
        <span>{value || t("userFilter.all")}</span>
        <span className="org-dropdown-arrow">{open ? "\u25B4" : "\u25BE"}</span>
      </button>
      {open && (
        <div className="org-dropdown-menu">
          <div className="org-dropdown-search">
            <input
              ref={inputRef}
              type="text"
              className="org-dropdown-search-input"
              placeholder={t("userFilter.search")}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && filtered.length > 0) select(filtered[0]);
                if (e.key === "Escape") setOpen(false);
              }}
            />
          </div>
          <div
            className={`org-dropdown-item ${!value ? "org-dropdown-item-active" : ""}`}
            onClick={() => select("")}
          >
            <span>{t("userFilter.all")}</span>
          </div>
          <div className="org-dropdown-divider" />
          {filtered.length === 0 ? (
            <div className="org-dropdown-item org-dropdown-empty">
              <span>{t("userFilter.noMatch")}</span>
            </div>
          ) : (
            filtered.map((opt) => (
              <div
                key={opt}
                className={`org-dropdown-item ${value === opt ? "org-dropdown-item-active" : ""}`}
                onClick={() => select(opt)}
              >
                <span>{opt}</span>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
