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
          : t("csvDash.csvType.premium_request");
        setCsvMessage(`${typeLabel}: ${t("dashboard.csvNoDuplicate")}`);
      } else {
        const typeLabel = result.csv_type === "usage_report"
          ? t("csvDash.csvType.usage_report")
          : t("csvDash.csvType.premium_request");
        const range = result.date_range ? ` (${result.date_range.start} ~ ${result.date_range.end})` : "";
        setCsvMessage(`${typeLabel} ${t("dashboard.csvUploadSuccess")}: ${result.new_rows}${range}`);
      }
      setTimeout(() => setCsvMessage(""), 8000);
    } catch {
      setCsvMessage("Upload failed");
      setTimeout(() => setCsvMessage(""), 5000);
    } finally {
      setCsvUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }, [uploadCsv, t]);

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
          {lang === "en" ? "\u4e2d\u6587" : "EN"}
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
          {csvInfo?.premium_csv?.has_data && (
            <span className="csv-date-hint" title={`${t("csvDash.csvType.premium_request")}: ${csvInfo.premium_csv.earliest_date} ~ ${csvInfo.premium_csv.latest_date}`}>
              P:{csvInfo.premium_csv.latest_date}
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
