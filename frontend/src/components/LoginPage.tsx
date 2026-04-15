import { useState } from "react";
import { useI18n } from "../contexts/I18nContext";

interface Props {
  setupRequired: boolean;
  onLogin: () => void;
}

export function LoginPage({ setupRequired, onLogin }: Props) {
  const { t, lang, toggleLang } = useI18n();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

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
          <h1>OctoFinance</h1>
          <p>{setupRequired ? t("auth.createAccount") : t("auth.welcome")}</p>
        </div>

        <form onSubmit={handleSubmit} className="login-form">
          {error && <div className="login-error">{error}</div>}

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

        <div className="login-footer">
          <button className="btn btn-small btn-toggle" onClick={toggleLang}>
            {lang === "en" ? "🇺🇸 EN" : lang === "zh" ? "🇨🇳 中文" : "🇻🇳 VI"}
          </button>
        </div>
      </div>
    </div>
  );
}
