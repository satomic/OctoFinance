import { useState, useEffect } from "react";
import { useI18n } from "../contexts/I18nContext";
import { LanguageSelector } from "./LanguageSelector";

interface Props {
  setupRequired: boolean;
  githubEnabled: boolean;
  onLogin: () => void;
}

/** Map an ?auth_error=... query param coming back from the OAuth callback. */
const OAUTH_ERROR_KEYS: Record<string, string> = {
  github_not_configured: "auth.ghNotConfigured",
  invalid_state: "auth.ghInvalidState",
  token_exchange_failed: "auth.ghTokenFailed",
  github_api_error: "auth.ghApiError",
  not_allowed: "auth.ghNotAllowed",
  missing_code: "auth.ghMissingCode",
  no_login: "auth.ghApiError",
  access_denied: "auth.ghDenied",
};

export function LoginPage({ setupRequired, githubEnabled, onLogin }: Props) {
  const { t } = useI18n();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [version, setVersion] = useState("");
  const [showLocal, setShowLocal] = useState(setupRequired || !githubEnabled);

  useEffect(() => {
    fetch("/api/auth/status")
      .then((r) => r.json())
      .then((d) => setVersion(d.version || ""))
      .catch(() => {});
  }, []);

  // Surface OAuth callback failures returned as ?auth_error=...
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const authError = params.get("auth_error");
    if (authError) {
      const key = OAUTH_ERROR_KEYS[authError];
      setError(key ? t(key as Parameters<typeof t>[0]) : authError);
    }
    // Landing here with ?login=github means the cookie from the OAuth callback
    // was not accepted by the browser (wrong origin, or blocked).
    if (!authError && params.get("login") === "github") {
      setError(t("auth.ghCookieLost"));
    }
    if (authError || params.has("login")) {
      params.delete("auth_error");
      params.delete("login");
      const qs = params.toString();
      window.history.replaceState({}, "", window.location.pathname + (qs ? `?${qs}` : ""));
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (!username.trim() || !password.trim()) {
      setError(t("auth.error"));
      return;
    }

    if (setupRequired && password !== confirmPassword) {
      setError(t("auth.passwordMismatch"));
      return;
    }

    setLoading(true);
    try {
      const endpoint = setupRequired ? "/api/auth/setup" : "/api/auth/login";
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username.trim(), password }),
      });
      const data = await res.json();
      if (data.error) {
        setError(data.error);
      } else if (data.ok) {
        onLogin();
      }
    } catch {
      setError("Network error");
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-header">
          <h1>
            OctoFinance
            {version && <span className="app-version">v{version}</span>}
          </h1>
          <p>{setupRequired ? t("auth.createAccount") : t("auth.welcome")}</p>
        </div>

        {error && <div className="login-error">{error}</div>}

        {githubEnabled && !setupRequired && (
          <>
            <a className="btn btn-github-login" href="/api/auth/github/login">
              <svg viewBox="0 0 16 16" width="18" height="18" fill="currentColor" aria-hidden="true">
                <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z" />
              </svg>
              {t("auth.githubLogin")}
            </a>
            <p className="login-hint">{t("auth.githubHint")}</p>
            <div className="login-divider">
              <span>{t("auth.or")}</span>
            </div>
            {!showLocal && (
              <button
                type="button"
                className="btn btn-small btn-ghost login-toggle-local"
                onClick={() => setShowLocal(true)}
              >
                {t("auth.useLocal")}
              </button>
            )}
          </>
        )}

        {showLocal && (
          <form onSubmit={handleSubmit} className="login-form">
            <div className="login-field">
              <label>{t("auth.username")}</label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={t("auth.username")}
                autoFocus
                autoComplete="username"
              />
            </div>

            <div className="login-field">
              <label>{t("auth.password")}</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={t("auth.password")}
                autoComplete={setupRequired ? "new-password" : "current-password"}
              />
            </div>

            {setupRequired && (
              <div className="login-field">
                <label>{t("auth.confirmPassword")}</label>
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={t("auth.confirmPassword")}
                  autoComplete="new-password"
                />
              </div>
            )}

            <button
              type="submit"
              className="btn btn-primary login-submit"
              disabled={loading || !username.trim() || !password.trim()}
            >
              {loading
                ? "..."
                : setupRequired
                  ? t("auth.setup")
                  : t("auth.loginBtn")}
            </button>
          </form>
        )}

        <div className="login-footer">
          <LanguageSelector dropUp />
        </div>
      </div>
    </div>
  );
}
