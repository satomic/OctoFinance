import { useEffect, useRef, useState } from "react";
import { LANGS, useI18n, type Lang } from "../contexts/I18nContext";
import { useTheme } from "../contexts/ThemeContext";
import type { AuthUser } from "../types";

interface Props {
  user: AuthUser;
  onLogout: () => void;
}

/** Signed-in user chip that opens the appearance settings (language, theme) and logout. */
export function UserMenu({ user, onLogout }: Props) {
  const { t, lang, setLang } = useI18n();
  const { theme, toggleTheme } = useTheme();
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

  const choose = (code: Lang) => setLang(code);

  return (
    <div className="user-menu" ref={ref}>
      <button
        type="button"
        className={`user-chip ${open ? "user-chip-open" : ""}`}
        onClick={() => setOpen((v) => !v)}
        title={`${user.login}${user.is_admin ? " · admin" : ""}`}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        {user.avatar_url && <img src={user.avatar_url} alt="" className="user-chip-avatar" />}
        <span className="user-chip-name">{user.name || user.login}</span>
        {user.is_admin && <span className="user-chip-role">{t("auth.roleAdmin")}</span>}
        <span className="user-chip-caret">{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="user-menu-panel" role="menu">
          <div className="user-menu-identity">
            {user.avatar_url && <img src={user.avatar_url} alt="" className="user-menu-avatar" />}
            <div className="user-menu-identity-text">
              <div className="user-menu-identity-name">{user.name || user.login}</div>
              <div className="user-menu-identity-login">@{user.login}</div>
            </div>
          </div>

          <div className="user-menu-section">
            <div className="user-menu-label">{t("menu.theme")}</div>
            <div className="user-menu-choices">
              <button
                type="button"
                className={`user-menu-choice ${theme === "light" ? "user-menu-choice-active" : ""}`}
                onClick={() => { if (theme !== "light") toggleTheme(); }}
              >
                {t("menu.themeLight")}
              </button>
              <button
                type="button"
                className={`user-menu-choice ${theme === "dark" ? "user-menu-choice-active" : ""}`}
                onClick={() => { if (theme !== "dark") toggleTheme(); }}
              >
                {t("menu.themeDark")}
              </button>
            </div>
          </div>

          <div className="user-menu-section">
            <div className="user-menu-label">{t("menu.language")}</div>
            <ul className="user-menu-langs" role="listbox">
              {LANGS.map((l) => (
                <li key={l.code}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={l.code === lang}
                    className={`user-menu-lang ${l.code === lang ? "user-menu-lang-active" : ""}`}
                    onClick={() => choose(l.code)}
                  >
                    <span className="user-menu-lang-flag">{l.flag}</span>
                    <span>{l.label}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>

          <button
            type="button"
            className="user-menu-logout"
            onClick={async () => {
              setOpen(false);
              await fetch("/api/auth/logout", { method: "POST" });
              onLogout();
            }}
          >
            {t("auth.logout")}
          </button>
        </div>
      )}
    </div>
  );
}
