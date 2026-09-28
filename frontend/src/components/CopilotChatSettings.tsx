import { useState, useEffect, useCallback } from "react";
import { useI18n } from "../contexts/I18nContext";
import type { ChatAuthResponse, ChatAuthStatus } from "../types";

/**
 * AI chat (Copilot CLI) credentials for the admin settings modal.
 * A token saved here takes precedence over the COPILOT_GITHUB_TOKEN env var,
 * and the status line shows who chat is actually signed in as, and where.
 */
export function CopilotChatSettings() {
  const { t } = useI18n();
  const [data, setData] = useState<ChatAuthResponse | null>(null);
  const [token, setToken] = useState("");
  const [host, setHost] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const apply = (res: ChatAuthResponse) => {
    setData(res);
    setHost(res.config.host || "");
  };

  const load = useCallback(async (refresh = false) => {
    try {
      const res = await fetch(`/api/chat/auth${refresh ? "?refresh=true" : ""}`);
      if (res.ok) apply(await res.json());
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const save = async (body: Record<string, unknown>) => {
    setBusy(true);
    setMessage("");
    setError("");
    try {
      const res = await fetch("/api/chat/auth", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const json = await res.json();
      if (!res.ok || json.error) {
        setError(json.error || json.detail || "Error");
      } else {
        apply(json);
        setToken("");
        setMessage(t("settings.chatSaved"));
        setTimeout(() => setMessage(""), 5000);
      }
    } catch {
      setError("Network error");
    } finally {
      setBusy(false);
    }
  };

  const recheck = async () => {
    setBusy(true);
    await load(true);
    setBusy(false);
  };

  const status = data?.status;
  const config = data?.config;

  return (
    <div className="sync-settings">
      <h3>{t("settings.chatTitle")}</h3>
      <p className="pat-form-hint">{t("settings.chatHint")}</p>

      {status && <StatusLine status={status} />}

      <div className="pat-form-row">
        <label>{t("settings.chatToken")}</label>
        <input
          type="password"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          placeholder={config?.token_set ? config.token_masked : "github_pat_..."}
        />
      </div>
      <p className="pat-form-hint">{t("settings.chatTokenHint")}</p>

      <div className="pat-form-row">
        <label>{t("settings.chatHost")}</label>
        <input
          type="text"
          value={host}
          onChange={(e) => setHost(e.target.value)}
          placeholder={t("settings.chatHostAuto")}
        />
      </div>
      <p className="pat-form-hint">{t("settings.chatHostHint")}</p>

      {error && <div className="settings-error">{error}</div>}
      {message && <div className="budget-req-success">{message}</div>}

      <div className="chat-auth-actions">
        <button
          className="btn btn-primary"
          disabled={busy}
          onClick={() => save({ token: token.trim() || null, host: host.trim() })}
        >
          {busy ? t("settings.chatConnecting") : t("settings.chatSave")}
        </button>
        <button className="btn btn-ghost" disabled={busy} onClick={recheck}>
          {t("settings.chatRecheck")}
        </button>
        {config?.token_set && (
          <button className="btn btn-ghost" disabled={busy} onClick={() => save({ clear_token: true })}>
            {t("settings.chatRemoveToken")}
          </button>
        )}
      </div>
    </div>
  );
}

function StatusLine({ status }: { status: ChatAuthStatus }) {
  const { t } = useI18n();
  const source = status.source || { kind: "cli_login", detail: "", token_masked: "" };
  const sourceLabel = {
    settings: t("settings.chatSourceSettings"),
    env: `${t("settings.chatSourceEnv")} ${source.detail}`,
    pat: `${t("settings.chatSourcePat")} "${source.detail}"`,
    cli_login: t("settings.chatSourceCli"),
  }[source.kind] ?? source.kind;

  const denied = status.authenticated && status.models_available === 0 && !!status.models_error;
  const ok = status.authenticated && !denied && !status.fallback_used;
  const where = [status.login, status.host].filter(Boolean).join(" @ ");

  return (
    <div className="chat-auth-status">
      <div className="sso-status-row">
        <span className={`status-dot ${ok ? "green" : status.authenticated ? "yellow" : "red"}`} />
        <span className="status-text">
          {status.authenticated
            ? `${t("settings.chatConnectedAs")} ${where}`
            : t("settings.chatNotConnected")}
        </span>
      </div>
      <div className="pat-form-hint">
        {t("settings.chatSource")}: {sourceLabel}
        {source.token_masked ? ` (${source.token_masked})` : ""}
      </div>
      {status.fallback_used && (
        <div className="settings-error">
          {t("settings.chatFallback")} {status.error}
        </div>
      )}
      {denied && (
        <div className="settings-error">
          {t("settings.chatDenied")} {status.models_error}
        </div>
      )}
      {!status.authenticated && status.error && <div className="settings-error">{status.error}</div>}
    </div>
  );
}
