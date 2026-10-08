import { useState } from "react";
import { useI18n } from "../contexts/I18nContext";
import { usePATs } from "../hooks/usePATs";
import { CopilotChatSettings } from "./CopilotChatSettings";
import { GithubSSOSettings } from "./GithubSSOSettings";
import type { PATInfo } from "../types";

interface Props {
  onClose: () => void;
  onPATChange?: () => void;
}

const CRON_PRESETS = [
  { label: "30min", cron: "*/30 * * * *" },
  { label: "1h", cron: "0 */1 * * *" },
  { label: "6h", cron: "0 */6 * * *" },
  { label: "24h", cron: "0 0 * * *" },
  { label: "Off", cron: "" },
];

function describeCron(cron: string): string {
  if (!cron.trim()) return "";
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return "";
  const [minute, hour, dom, , ] = parts;
  const stepMin = minute.match(/^\*\/(\d+)$/);
  if (stepMin && hour === "*" && dom === "*") {
    const n = parseInt(stepMin[1]);
    return n === 1 ? "Every minute" : `Every ${n} minutes`;
  }
  const stepHr = hour.match(/^\*\/(\d+)$/);
  if (minute === "0" && stepHr && dom === "*") {
    const n = parseInt(stepHr[1]);
    return n === 1 ? "Every hour" : `Every ${n} hours`;
  }
  if (minute === "0" && hour === "0" && dom === "*") return "Daily";
  const stepDay = dom.match(/^\*\/(\d+)$/);
  if (minute === "0" && hour === "0" && stepDay) {
    return `Every ${stepDay[1]} days`;
  }
  return "";
}

export function PATSettingsModal({ onClose, onPATChange }: Props) {
  const { t } = useI18n();
  const { pats, loading, error, addPAT, removePAT, updatePAT, clearError, settings, updateSettings } = usePATs();
  const [label, setLabel] = useState("");
  const [token, setToken] = useState("");
  const [host, setHost] = useState("");
  const [enterpriseSlug, setEnterpriseSlug] = useState("");
  const [includeOrganizations, setIncludeOrganizations] = useState(true);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  // PAT whose token is being replaced, and the new token typed for it
  const [replacingId, setReplacingId] = useState<string | null>(null);
  const [newToken, setNewToken] = useState("");
  const [replaceSaving, setReplaceSaving] = useState(false);

  // Numeric settings are edited as a draft and committed on blur, so a partially
  // typed value is never PUT (and rejected) mid-keystroke. A null draft means
  // "not editing", so the field tracks the saved setting.
  const [csvPollDraft, setCsvPollDraft] = useState<string | null>(null);
  const [csvTimeoutDraft, setCsvTimeoutDraft] = useState<string | null>(null);
  const csvPoll = csvPollDraft ?? String(settings.csv_fetch_poll_seconds);
  const csvTimeout = csvTimeoutDraft ?? String(settings.csv_fetch_timeout_minutes);

  const commitCsvNumber = (
    key: "csv_fetch_poll_seconds" | "csv_fetch_timeout_minutes",
    raw: string,
    min: number,
    max: number,
    clearDraft: (v: string | null) => void,
  ) => {
    const n = Math.round(Number(raw));
    clearDraft(null);
    if (!Number.isFinite(n) || n < min || n > max) return;
    if (n !== settings[key]) updateSettings({ [key]: n });
  };

  const handleAdd = async () => {
    if (!token.trim()) return;
    clearError();
    const slugs = enterpriseSlug.trim()
      ? enterpriseSlug.split(",").map((s) => s.trim()).filter(Boolean)
      : [];
    const result = await addPAT(label.trim() || "Untitled", token.trim(), slugs, includeOrganizations, host.trim());
    if (result) {
      setLabel("");
      setToken("");
      setHost("");
      setEnterpriseSlug("");
      setIncludeOrganizations(true);
      onPATChange?.();
    }
  };

  const handleToggleIncludeOrganizations = async (pat: PATInfo) => {
    const ok = await updatePAT(pat.id, { include_organizations: !pat.include_organizations });
    if (ok) {
      onPATChange?.();
    }
  };

  const handleReplaceToken = async (pat: PATInfo) => {
    if (!newToken.trim()) return;
    clearError();
    setReplaceSaving(true);
    const ok = await updatePAT(pat.id, { token: newToken.trim() });
    setReplaceSaving(false);
    if (ok) {
      setReplacingId(null);
      setNewToken("");
      onPATChange?.();
    }
  };

  const credentialBadge = (pat: PATInfo) => {
    const c = pat.credential;
    if (!c || c.state === "ok") return null;
    const label = c.state === "invalid" ? t("settings.patCredInvalid")
      : c.state === "forbidden" ? t("settings.patCredForbidden")
      : c.state === "unreachable" ? t("settings.patCredUnreachable")
      : `${t("settings.patCredExpiring")} ${c.expires_at ? new Date(c.expires_at).toLocaleDateString() : ""}`;
    const title = [c.status ? `HTTP ${c.status}` : "", c.detail, `${t("settings.patCredChecked")} ${new Date(c.checked_at).toLocaleString()}`]
      .filter(Boolean).join(" · ");
    return (
      <span className={`pat-cred-badge pat-cred-${c.state === "expiring" ? "warning" : "error"}`} title={title}>
        {label}
      </span>
    );
  };

  const handleDelete = async (id: string) => {
    if (confirmDelete !== id) {
      setConfirmDelete(id);
      return;
    }
    setConfirmDelete(null);
    const ok = await removePAT(id);
    if (ok) {
      onPATChange?.();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleAdd();
    }
  };

  return (
    <div className="settings-modal-overlay" onClick={onClose}>
      <div className="settings-modal" onClick={(e) => e.stopPropagation()}>
        <div className="settings-modal-header">
          <h2>{t("settings.title")}</h2>
          <button className="settings-close-btn" onClick={onClose}>&times;</button>
        </div>

        <div className="settings-modal-body">
          <h3>{t("settings.pats")}</h3>

          {error && (
            <div className="settings-error">
              {t("settings.patError")}: {error}
            </div>
          )}

          <div className="pat-list">
            {pats.length === 0 && (
              <div className="pat-empty">{t("settings.noPats")}</div>
            )}
            {pats.map((pat) => (
              <div key={pat.id} className="pat-item">
                <div className="pat-item-left">
                  {pat.user_avatar && (
                    <img
                      src={pat.user_avatar}
                      alt={pat.user_login}
                      className="pat-avatar"
                    />
                  )}
                  <div className="pat-item-info">
                    <div className="pat-item-user">
                      <strong>{pat.label || pat.user_login || "Untitled"}</strong>
                      <span className="pat-item-orgs">{pat.orgs?.length || 0} orgs</span>
                      {(() => {
                        // Orgs where the PAT owner is only a member: GitHub refuses their Copilot data
                        const notAdmin = Object.entries(pat.org_roles ?? {})
                          .filter(([, role]) => role === "member")
                          .map(([org]) => org);
                        return notAdmin.length > 0 ? (
                          <span
                            className="pat-item-orgs-notadmin"
                            title={`${t("settings.patOrgsNotAdminHint")} ${notAdmin.join(", ")}`}
                          >
                            {t("settings.patOrgsNotAdmin")}: {notAdmin.length}
                          </span>
                        ) : null;
                      })()}
                      {pat.host && pat.host !== "github.com" && (
                        <span className="pat-item-enterprise">{pat.host}</span>
                      )}
                      {pat.enterprise_slugs?.length > 0 && (
                        <span className="pat-item-enterprise">
                          {pat.enterprise_slugs.join(", ")}
                        </span>
                      )}
                      {credentialBadge(pat)}
                    </div>
                    <div className="pat-item-meta">
                      {pat.user_login || (pat.credential && pat.credential.state !== "ok" ? "—" : "Validating...")} &middot; {pat.token_masked}
                    </div>
                    <div className="pat-item-include-orgs">
                      <label className="toggle-switch toggle-switch-small">
                        <input
                          type="checkbox"
                          checked={pat.include_organizations !== false}
                          onChange={() => handleToggleIncludeOrganizations(pat)}
                        />
                        <span className="toggle-slider" />
                      </label>
                      <span>{t("settings.patIncludeOrganizations")}</span>
                    </div>
                    {replacingId === pat.id && (
                      <div className="pat-replace-row">
                        <input
                          type="password"
                          value={newToken}
                          autoFocus
                          placeholder={t("settings.patReplacePlaceholder")}
                          onChange={(e) => setNewToken(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") handleReplaceToken(pat);
                            if (e.key === "Escape") { e.stopPropagation(); setReplacingId(null); }
                          }}
                          disabled={replaceSaving}
                        />
                        <button className="btn btn-small btn-approve" onClick={() => handleReplaceToken(pat)} disabled={replaceSaving || !newToken.trim()}>
                          {replaceSaving ? t("settings.patReplaceSaving") : t("settings.patReplaceSave")}
                        </button>
                        <button className="btn btn-small" onClick={() => setReplacingId(null)} disabled={replaceSaving}>
                          {t("settings.patReplaceCancel")}
                        </button>
                      </div>
                    )}
                  </div>
                </div>
                <div className="pat-item-actions">
                <button
                  className={`btn btn-small ${pat.credential && pat.credential.state !== "ok" ? "btn-approve" : "btn-ghost"}`}
                  onClick={() => { clearError(); setNewToken(""); setReplacingId(replacingId === pat.id ? null : pat.id); }}
                >
                  {t("settings.patReplaceToken")}
                </button>
                <button
                  className={`btn btn-small ${confirmDelete === pat.id ? "btn-danger" : "btn-ghost"}`}
                  onClick={() => handleDelete(pat.id)}
                >
                  {confirmDelete === pat.id ? t("settings.patDeleteConfirm") : t("settings.patDelete")}
                </button>
                </div>
              </div>
            ))}
          </div>

          <div className="pat-form">
            <h4>{t("settings.addPat")}</h4>
            <div className="pat-form-row">
              <label>{t("settings.patLabel")}</label>
              <input
                type="text"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="e.g. Work PAT"
                onKeyDown={handleKeyDown}
              />
            </div>
            <div className="pat-form-row">
              <label>{t("settings.patToken")}</label>
              <input
                type="password"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="ghp_..."
                onKeyDown={handleKeyDown}
              />
            </div>
            <div className="pat-form-row">
              <label>{t("settings.patHost")}</label>
              <input
                type="text"
                value={host}
                onChange={(e) => setHost(e.target.value)}
                placeholder="github.com"
                onKeyDown={handleKeyDown}
              />
            </div>
            <p className="pat-form-hint">{t("settings.patHostHint")}</p>
            <div className="pat-form-row">
              <label>{t("settings.patEnterprise")}</label>
              <input
                type="text"
                value={enterpriseSlug}
                onChange={(e) => setEnterpriseSlug(e.target.value)}
                placeholder="e.g. my-enterprise"
                onKeyDown={handleKeyDown}
              />
            </div>
            <p className="pat-form-hint pat-enterprise-hint">{t("settings.patEnterpriseHint")}</p>
            <div className="pat-form-row pat-form-row-checkbox">
              <label className="pat-form-checkbox-label">
                <input
                  type="checkbox"
                  checked={includeOrganizations}
                  onChange={(e) => setIncludeOrganizations(e.target.checked)}
                />
                <span>{t("settings.patIncludeOrganizations")}</span>
              </label>
            </div>
            <p className="pat-form-hint">{t("settings.patIncludeOrganizationsHint")}</p>
            <button
              className="btn btn-primary"
              onClick={handleAdd}
              disabled={loading || !token.trim()}
            >
              {loading ? t("settings.patAdding") : t("settings.addPat")}
            </button>
            <p className="pat-form-hint">{t("settings.patHint")}</p>
          </div>

          <CopilotChatSettings />

          {/* Sync Settings */}
          <div className="sync-settings">
            <h3>{t("settings.syncSettings")}</h3>

            <div className="sync-setting-row">
              <span className="sync-setting-label">{t("settings.autoSync")}</span>
              <label className="toggle-switch">
                <input
                  type="checkbox"
                  checked={settings.auto_sync_on_startup}
                  onChange={(e) => updateSettings({ auto_sync_on_startup: e.target.checked })}
                />
                <span className="toggle-slider" />
              </label>
            </div>

            <div className="sync-setting-row">
              <span className="sync-setting-label">{t("settings.syncCron")}</span>
              <div className="sync-cron-input-group">
                <input
                  type="text"
                  className="sync-cron-input"
                  value={settings.sync_cron}
                  onChange={(e) => updateSettings({ sync_cron: e.target.value })}
                  placeholder="e.g. 0 */6 * * *"
                />
                {describeCron(settings.sync_cron) && (
                  <span className="sync-cron-desc">{describeCron(settings.sync_cron)}</span>
                )}
              </div>
            </div>

            <div className="sync-cron-presets">
              {CRON_PRESETS.map((p) => (
                <button
                  key={p.label}
                  className={`btn btn-small btn-preset ${settings.sync_cron === p.cron ? "btn-preset-active" : ""}`}
                  onClick={() => updateSettings({ sync_cron: p.cron })}
                >
                  {p.label}
                </button>
              ))}
            </div>
            <p className="pat-form-hint">{t("settings.cronHint")}</p>
            <p className="pat-form-hint">{t("settings.syncIncludesCsv")}</p>
          </div>

          {/* CSV Fetch Settings — these apply only to the Fetch CSV button */}
          <div className="sync-settings">
            <h3>{t("settings.csvFetchSettings")}</h3>

            <div className="sync-setting-row">
              <span className="sync-setting-label">{t("settings.csvPollInterval")}</span>
              <div className="sync-cron-input-group">
                <input
                  type="number"
                  min={10}
                  max={600}
                  className="sync-cron-input"
                  value={csvPoll}
                  onChange={(e) => setCsvPollDraft(e.target.value)}
                  onBlur={() => commitCsvNumber("csv_fetch_poll_seconds", csvPoll, 10, 600, setCsvPollDraft)}
                />
                <span className="sync-cron-desc">{t("settings.csvSecondsUnit")}</span>
              </div>
            </div>

            <div className="sync-setting-row">
              <span className="sync-setting-label">{t("settings.csvTimeout")}</span>
              <div className="sync-cron-input-group">
                <input
                  type="number"
                  min={5}
                  max={1440}
                  className="sync-cron-input"
                  value={csvTimeout}
                  onChange={(e) => setCsvTimeoutDraft(e.target.value)}
                  onBlur={() => commitCsvNumber("csv_fetch_timeout_minutes", csvTimeout, 5, 1440, setCsvTimeoutDraft)}
                />
                <span className="sync-cron-desc">{t("settings.csvMinutesUnit")}</span>
              </div>
            </div>

            <p className="pat-form-hint">{t("settings.csvFetchHint")}</p>
            <p className="pat-form-hint">
              {t("settings.csvPreviewNotice")}{" "}
              <a
                href="https://github.com/orgs/community/discussions/186162"
                target="_blank"
                rel="noopener noreferrer"
              >
                {t("settings.csvPreviewLink")}
              </a>
            </p>
          </div>

          <GithubSSOSettings />
        </div>
      </div>
    </div>
  );
}
