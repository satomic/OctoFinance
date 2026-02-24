import { useState, useEffect, useCallback } from "react";
import { useSync } from "../hooks/useData";
import { useTheme } from "../contexts/ThemeContext";
import { useI18n } from "../contexts/I18nContext";
import { PATSettingsModal } from "./PATSettingsModal";

interface Props {
  consoleOpen: boolean;
  onToggleConsole: () => void;
  onPATChange?: () => void;
}

export function StatusBar({ consoleOpen, onToggleConsole, onPATChange }: Props) {
  const { syncing, sync } = useSync();
  const { theme, toggleTheme } = useTheme();
  const { lang, toggleLang, t } = useI18n();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [health, setHealth] = useState<{
    status: string;
    user: string | null;
    users: string[];
    orgs: string[];
    pat_count: number;
    copilot_engine: boolean;
  } | null>(null);

  const fetchHealth = useCallback(() => {
    fetch("/api/health")
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  useEffect(() => {
    fetchHealth();
  }, [fetchHealth]);

  const handlePATChange = () => {
    fetchHealth();
    onPATChange?.();
  };

  return (
    <div className="status-bar">
      <div className="status-left">
        <span className="app-title">OctoFinance</span>
        {health && (
          <>
            <span className={`status-dot ${health.status === "ok" ? "green" : "red"}`} />
            <span className="status-text">
              {health.users?.length
                ? health.users.join(", ")
                : health.user || t("status.notConnected")} &middot; {health.orgs?.length || 0} {t("status.orgs")}
            </span>
            <span className={`status-dot ${health.copilot_engine ? "green" : "yellow"}`} />
            <span className="status-text">
              {health.copilot_engine ? t("status.aiReady") : t("status.aiStarting")}
            </span>
          </>
        )}
      </div>
      <div className="status-right">
        <button
          className="btn btn-small btn-toggle"
          onClick={() => setSettingsOpen(true)}
          title={t("settings.title")}
        >
          {t("settings.title")}
        </button>
        <button
          className={`btn btn-small btn-toggle ${consoleOpen ? "btn-toggle-active" : ""}`}
          onClick={onToggleConsole}
          title={t("console.title")}
        >
          {t("console.title")}
        </button>
        <button className="btn btn-small btn-toggle" onClick={toggleLang} title="Switch language">
          {lang === "en" ? "\u4e2d\u6587" : "EN"}
        </button>
        <button className="btn btn-small btn-toggle" onClick={toggleTheme} title="Switch theme">
          {theme === "dark" ? "Light" : "Dark"}
        </button>
        <button className="btn btn-small" onClick={sync} disabled={syncing}>
          {syncing ? t("status.syncing") : t("status.syncData")}
        </button>
      </div>
      {settingsOpen && (
        <PATSettingsModal onClose={() => setSettingsOpen(false)} onPATChange={handlePATChange} />
      )}
    </div>
  );
}
