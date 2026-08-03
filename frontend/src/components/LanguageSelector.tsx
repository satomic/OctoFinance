import { useEffect, useRef, useState } from "react";
import { LANGS, useI18n, type Lang } from "../contexts/I18nContext";

interface Props {
  /** Renders the menu above the trigger — used on the login card. */
  dropUp?: boolean;
}

/** Dropdown language picker. */
export function LanguageSelector({ dropUp = false }: Props) {
  const { lang, setLang } = useI18n();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const current = LANGS.find((l) => l.code === lang) ?? LANGS[0];

  const choose = (code: Lang) => {
    setLang(code);
    setOpen(false);
  };

  return (
    <div className="lang-select" ref={ref}>
      <button
        type="button"
        className="btn btn-small btn-toggle lang-select-trigger"
        onClick={() => setOpen((v) => !v)}
        title="Language"
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className="lang-select-flag">{current.flag}</span>
        <span className="lang-select-label">{current.label}</span>
        <span className="lang-select-caret">{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <ul className={`lang-select-menu ${dropUp ? "lang-select-menu-up" : ""}`} role="listbox">
          {LANGS.map((l) => (
            <li key={l.code}>
              <button
                type="button"
                role="option"
                aria-selected={l.code === lang}
                className={`lang-select-item ${l.code === lang ? "lang-select-item-active" : ""}`}
                onClick={() => choose(l.code)}
              >
                <span className="lang-select-flag">{l.flag}</span>
                <span>{l.label}</span>
                {l.code === lang && <span className="lang-select-check">✓</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
