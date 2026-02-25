import { useState } from "react";
import { useI18n } from "../contexts/I18nContext";
import { usePATs } from "../hooks/usePATs";

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
  const { pats, loading, error, addPAT, removePAT, clearError, settings, updateSettings } = usePATs();
  const [label, setLabel] = useState("");
  const [token, setToken] = useState("");
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  const handleAdd = async () => {
    if (!token.trim()) return;
    clearError();
    const result = await addPAT(label.trim() || "Untitled", token.trim());
    if (result) {
      setLabel("");
      setToken("");
      onPATChange?.();
    }
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
                      <strong>{pat.user_login || "Validating..."}</strong>
                      <span className="pat-item-orgs">{pat.orgs?.length || 0} orgs</span>
                    </div>
                    <div className="pat-item-meta">
                      {pat.label} &middot; {pat.token_masked}
                    </div>
                  </div>
                </div>
                <button
                  className={`btn btn-small ${confirmDelete === pat.id ? "btn-danger" : "btn-ghost"}`}
                  onClick={() => handleDelete(pat.id)}
                >
                  {confirmDelete === pat.id ? t("settings.patDeleteConfirm") : t("settings.patDelete")}
                </button>
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
            <button
              className="btn btn-primary"
              onClick={handleAdd}
              disabled={loading || !token.trim()}
            >
              {loading ? t("settings.patAdding") : t("settings.addPat")}
            </button>
            <p className="pat-form-hint">{t("settings.patHint")}</p>
          </div>

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
          </div>
        </div>
      </div>
    </div>
  );
}
