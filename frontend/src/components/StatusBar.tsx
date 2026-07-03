import { useState, useEffect, useCallback, useRef } from "react";
import { useSync, useCsvInfo } from "../hooks/useData";
import { useTheme } from "../contexts/ThemeContext";
import { useI18n } from "../contexts/I18nContext";
import { PATSettingsModal } from "./PATSettingsModal";

interface Props {
  consoleOpen: boolean;
  onToggleConsole: () => void;
  onPATChange?: () => void;
  syncing?: boolean;
  currentView: "chat" | "dashboard";
  onViewChange: (view: "chat" | "dashboard") => void;
  onLogout: () => void;
}

export function StatusBar({ consoleOpen, onToggleConsole, onPATChange, syncing = false, currentView, onViewChange, onLogout }: Props) {
  const { sync } = useSync();
  const { theme, toggleTheme } = useTheme();
  const { lang, toggleLang, t } = useI18n();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { info: csvInfo, uploadCsv } = useCsvInfo();
  const [csvUploading, setCsvUploading] = useState(false);
  const [csvMessage, setCsvMessage] = useState("");
  const [health, setHealth] = useState<{
    status: string;
    version?: string;
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

  const handleSync = () => {
    if (!syncing) {
      sync();
    }
  };

  const handleCsvUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setCsvUploading(true);
    setCsvMessage("");
    try {
      const result = await uploadCsv(file);
      if (result.error) {
        setCsvMessage(result.error);
      } else if (result.status === "no_new_data") {
        const typeLabel = result.csv_type === "usage_report"
          ? t("csvDash.csvType.usage_report")
          : t("csvDash.csvType.ai_usage");
        setCsvMessage(`${typeLabel}: ${t("dashboard.csvNoDuplicate")}`);
      } else {
        const typeLabel = result.csv_type === "usage_report"
          ? t("csvDash.csvType.usage_report")
          : t("csvDash.csvType.ai_usage");
        const range = result.date_range ? ` (${result.date_range.start} ~ ${result.date_range.end})` : "";
        setCsvMessage(`${typeLabel} ${t("dashboard.csvUploadSuccess")}: ${result.new_rows}${range}`);
      }
      setTimeout(() => setCsvMessage(""), 8000);
    } catch {
      setCsvMessage("Upload failed (network or server error)");
      setTimeout(() => setCsvMessage(""), 6000);
    } finally {
      setCsvUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }, [uploadCsv, t]);

  return (
    <div className="status-bar">
      <div className="status-left">
        <span className="app-title">OctoFinance</span>
        {health?.version && (
          <span className="app-version" title={`OctoFinance v${health.version}`}>v{health.version}</span>
        )}
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
        <div className="view-toggle">
          <button
            className={`btn btn-small btn-toggle ${currentView === "chat" ? "btn-toggle-active" : ""}`}
            onClick={() => onViewChange("chat")}
          >
            {t("nav.chat")}
          </button>
          <button
            className={`btn btn-small btn-toggle ${currentView === "dashboard" ? "btn-toggle-active" : ""}`}
            onClick={() => onViewChange("dashboard")}
          >
            {t("nav.dashboard")}
          </button>
        </div>
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
          {lang === "en" ? "🇺🇸 EN" : lang === "zh" ? "🇨🇳 中文" : "🇻🇳 VI"}
        </button>
        <button className="btn btn-small btn-toggle" onClick={toggleTheme} title="Switch theme">
          {theme === "dark" ? "Light" : "Dark"}
        </button>
        <div className="csv-upload-group">
          <input ref={fileInputRef} type="file" accept=".csv" onChange={handleCsvUpload} style={{ display: "none" }} />
          <button
            className="btn btn-small"
            onClick={() => fileInputRef.current?.click()}
            disabled={csvUploading}
            title={t("dashboard.uploadCsvHint")}
          >
            {csvUploading ? t("dashboard.csvUploading") : t("dashboard.uploadCsv")}
          </button>
          {csvInfo?.ai_usage?.has_data && (
            <span className="csv-date-hint" title={`${t("csvDash.csvType.ai_usage")}: ${csvInfo.ai_usage.earliest_date} ~ ${csvInfo.ai_usage.latest_date}`}>
              AI:{csvInfo.ai_usage.latest_date}
            </span>
          )}
          {csvInfo?.usage_report?.has_data && (
            <span className="csv-date-hint" title={`${t("csvDash.csvType.usage_report")}: ${csvInfo.usage_report.earliest_date} ~ ${csvInfo.usage_report.latest_date}`}>
              U:{csvInfo.usage_report.latest_date}
            </span>
          )}
          {csvMessage && <span className="csv-upload-msg">{csvMessage}</span>}
        </div>
        <button className="btn btn-small" onClick={handleSync} disabled={syncing}>
          {syncing ? t("status.syncing") : t("status.syncData")}
        </button>
        <a
          className="btn btn-small btn-link-icon"
          href="https://github.com/satomic/OctoFinance"
          target="_blank"
          rel="noopener noreferrer"
          title={t("nav.sourceCode")}
          aria-label={t("nav.sourceCode")}
        >
          <svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true">
            <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z" />
          </svg>
          {t("nav.sourceCode")}
        </a>
        <a
          className="btn btn-small btn-link-icon"
          href="https://github.com/satomic/OctoFinance/issues/new"
          target="_blank"
          rel="noopener noreferrer"
          title={t("nav.feedback")}
          aria-label={t("nav.feedback")}
        >
          <svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true">
            <path d="M8 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13ZM0 8a8 8 0 1 1 16 0A8 8 0 0 1 0 8Zm9 3a1 1 0 1 1-2 0 1 1 0 0 1 2 0ZM6.92 6.085h.001a.749.749 0 1 1-1.342-.67c.169-.339.436-.701.849-.977C6.845 4.16 7.369 4 8 4a2.756 2.756 0 0 1 1.637.525c.503.377.863.965.863 1.725 0 .448-.115.83-.329 1.15-.205.307-.47.513-.692.662-.109.072-.22.138-.313.195l-.006.004a6.24 6.24 0 0 0-.26.16.952.952 0 0 0-.276.245.75.75 0 0 1-1.248-.832c.184-.264.42-.489.692-.661.103-.067.207-.132.313-.195l.007-.004c.1-.061.182-.11.258-.161a.969.969 0 0 0 .277-.245C8.96 6.514 9 6.427 9 6.25a.612.612 0 0 0-.262-.525A1.27 1.27 0 0 0 8 5.5c-.369 0-.595.09-.74.187a1.01 1.01 0 0 0-.34.398Z" />
          </svg>
          {t("nav.feedback")}
        </a>
        <button
          className="btn btn-small btn-ghost"
          onClick={async () => {
            await fetch("/api/auth/logout", { method: "POST" });
            onLogout();
          }}
          title={t("auth.logout")}
        >
          {t("auth.logout")}
        </button>
      </div>
      {settingsOpen && (
        <PATSettingsModal onClose={() => setSettingsOpen(false)} onPATChange={handlePATChange} />
      )}
    </div>
  );
}
