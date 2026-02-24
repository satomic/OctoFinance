import { useState } from "react";
import { useI18n } from "../contexts/I18nContext";
import { usePATs } from "../hooks/usePATs";

interface Props {
  onClose: () => void;
  onPATChange?: () => void;
}

export function PATSettingsModal({ onClose, onPATChange }: Props) {
  const { t } = useI18n();
  const { pats, loading, error, addPAT, removePAT, clearError } = usePATs();
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
        </div>
      </div>
    </div>
  );
}
