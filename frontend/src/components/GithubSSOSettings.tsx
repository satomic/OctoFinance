import { useState, useEffect, useCallback } from "react";
import { useI18n } from "../contexts/I18nContext";
import type { GithubOAuthConfig } from "../types";

/**
 * GitHub OAuth (SSO) configuration section for the admin settings modal.
 * Lets admins register the OAuth App and maintain the admin allow-list.
 */
export function GithubSSOSettings() {
  const { t } = useI18n();
  const [config, setConfig] = useState<GithubOAuthConfig | null>(null);
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [callbackUrl, setCallbackUrl] = useState("");
  const [admins, setAdmins] = useState("");
  const [allowAll, setAllowAll] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/auth/github/config");
      if (!res.ok) return;
      const data: GithubOAuthConfig = await res.json();
      setConfig(data);
      setClientId(data.client_id || "");
      setCallbackUrl(data.callback_url || "");
      setAdmins((data.admins || []).join(", "));
      setAllowAll(data.allow_all_users !== false);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleSave = async () => {
    setSaving(true);
    setMessage("");
    setError("");
    try {
      const body: Record<string, unknown> = {
        client_id: clientId.trim(),
        callback_url: callbackUrl.trim(),
        admins: admins.split(",").map((a) => a.trim()).filter(Boolean),
        allow_all_users: allowAll,
      };
      if (clientSecret.trim()) body.client_secret = clientSecret.trim();
      const res = await fetch("/api/auth/github/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (data.error) {
        setError(data.error);
      } else {
        setConfig(data);
        setClientSecret("");
        setMessage(t("settings.ssoSaved"));
        setTimeout(() => setMessage(""), 5000);
      }
    } catch {
      setError("Network error");
    } finally {
      setSaving(false);
    }
  };

  const defaultCallback = `${window.location.origin}/api/auth/github/callback`;

  return (
    <div className="sync-settings">
      <h3>{t("settings.ssoTitle")}</h3>
      <p className="pat-form-hint">{t("settings.ssoHint")}</p>

      {config && (
        <div className="sso-status-row">
          <span className={`status-dot ${config.enabled ? "green" : "yellow"}`} />
          <span className="status-text">
            {config.enabled ? t("settings.ssoEnabled") : t("settings.ssoDisabled")}
          </span>
        </div>
      )}

      <div className="pat-form-row">
        <label>{t("settings.ssoClientId")}</label>
        <input
          type="text"
          value={clientId}
          onChange={(e) => setClientId(e.target.value)}
          placeholder="Iv1.xxxxxxxxxxxx"
        />
      </div>
      <div className="pat-form-row">
        <label>{t("settings.ssoClientSecret")}</label>
        <input
          type="password"
          value={clientSecret}
          onChange={(e) => setClientSecret(e.target.value)}
          placeholder={config?.client_secret_set ? config.client_secret_masked : "••••••••"}
        />
      </div>
      <div className="pat-form-row">
        <label>{t("settings.ssoCallback")}</label>
        <input
          type="text"
          value={callbackUrl}
          onChange={(e) => setCallbackUrl(e.target.value)}
          placeholder={defaultCallback}
        />
      </div>
      <p className="pat-form-hint">{t("settings.ssoCallbackHint")}: {defaultCallback}</p>

      <div className="pat-form-row">
        <label>{t("settings.ssoAdmins")}</label>
        <input
          type="text"
          value={admins}
          onChange={(e) => setAdmins(e.target.value)}
          placeholder="octocat, monalisa"
        />
      </div>
      <p className="pat-form-hint">{t("settings.ssoAdminsHint")}</p>

      <div className="sync-setting-row">
        <span className="sync-setting-label">{t("settings.ssoAllowAll")}</span>
        <label className="toggle-switch">
          <input type="checkbox" checked={allowAll} onChange={(e) => setAllowAll(e.target.checked)} />
          <span className="toggle-slider" />
        </label>
      </div>
      <p className="pat-form-hint">{t("settings.ssoAllowAllHint")}</p>

      {error && <div className="settings-error">{error}</div>}
      {message && <div className="budget-req-success">{message}</div>}

      <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
        {saving ? "..." : t("settings.ssoSave")}
      </button>
    </div>
  );
}
