import { useState, useEffect, useCallback, useRef } from "react";
import { useSync, useCsvInfo } from "../hooks/useData";
import { useI18n } from "../contexts/I18nContext";
import { useUIState } from "../contexts/UIStateContext";
import { PATSettingsModal } from "./PATSettingsModal";
import { PeriodToggle } from "./PeriodToggle";
import { SourceCodeLink } from "./SourceCodeLink";
import { UserMenu } from "./UserMenu";
import { isDemoMode } from "../demo/demoMode";
import type { AuthUser, UpdateInfo, CsvFetchJob } from "../types";

interface Props {
  consoleOpen: boolean;
  onToggleConsole: () => void;
  onPATChange?: () => void;
  syncing?: boolean;
  currentView: "chat" | "dashboard";
  onViewChange: (view: "chat" | "dashboard") => void;
  onLogout: () => void;
  user?: AuthUser | null;
  settingsOpen: boolean;
  onSettingsOpenChange: (open: boolean) => void;
  /** bumped when a sync completes, so the connection / org count is re-read */
  refreshKey?: number;
}

export function StatusBar({ consoleOpen, onToggleConsole, onPATChange, syncing = false, currentView, onViewChange, onLogout, user, settingsOpen, onSettingsOpenChange: setSettingsOpen, refreshKey = 0 }: Props) {
  const { sync } = useSync();
  const { t } = useI18n();
  const ui = useUIState();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { info: csvInfo, uploadCsv, fetchCsvFromApi, readCsvJob, pollCsvFetch } = useCsvInfo();
  const [csvUploading, setCsvUploading] = useState(false);
  const [csvFetching, setCsvFetching] = useState(false);
  const [csvProgress, setCsvProgress] = useState("");
  const [csvMessage, setCsvMessage] = useState("");
  const [health, setHealth] = useState<{
    status: string;
    version?: string;
    user: string | null;
    users: string[];
    orgs: string[];
    pat_count: number;
    copilot_engine: boolean;
    update?: UpdateInfo;
  } | null>(null);

  const fetchHealth = useCallback(() => {
    fetch("/api/health")
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  useEffect(() => {
    fetchHealth();
  }, [fetchHealth, refreshKey]);

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

  const describeJobResult = useCallback((job: CsvFetchJob) => {
    if (job.errors.length) {
      setCsvMessage(`${t("dashboard.csvFetchFailed")}: ${job.errors[0].error}`);
    } else {
      setCsvMessage(`${t("dashboard.csvFetchSuccess")}: ${job.new_rows}`);
    }
    setTimeout(() => setCsvMessage(""), 10000);
  }, [t]);

  const trackCsvJob = useCallback(async (jobId: string) => {
    setCsvFetching(true);
    try {
      const job = await pollCsvFetch(jobId, (j) => setCsvProgress(
        j.total_steps ? `${Math.min(j.step + 1, j.total_steps)}/${j.total_steps}` : ""
      ));
      if (job) describeJobResult(job);
      else setCsvMessage(t("dashboard.csvFetchFailed"));
    } finally {
      setCsvFetching(false);
      setCsvProgress("");
    }
  }, [pollCsvFetch, describeJobResult, t]);

  // A fetch takes minutes and lives on the server, so reattach to one that is
  // still running rather than leaving the user with no sign of it after a reload.
  useEffect(() => {
    let cancelled = false;
    readCsvJob().then((job) => {
      if (!cancelled && job?.running) trackCsvJob(job.job_id);
    });
    return () => { cancelled = true; };
  }, [readCsvJob, trackCsvJob]);

  const handleCsvFetch = useCallback(async () => {
    setCsvMessage("");
    const started = await fetchCsvFromApi();
    if (started.status === "already_syncing") {
      setCsvMessage(t("dashboard.csvFetchBusy"));
      setTimeout(() => setCsvMessage(""), 10000);
      return;
    }
    if (started.status !== "started" || !started.job_id) {
      setCsvMessage(started.error || t("dashboard.csvFetchFailed"));
      setTimeout(() => setCsvMessage(""), 10000);
      return;
    }
    await trackCsvJob(started.job_id);
  }, [fetchCsvFromApi, trackCsvJob, t]);

  return (
    <div className="status-bar">
      <div className="status-left">
        <span className="app-title">OctoFinance</span>
        {health?.version && (
          <span className="app-version" title={`OctoFinance v${health.version}`}>v{health.version}</span>
        )}
        {isDemoMode() && (
          <span className="demo-mode-badge" title={t("menu.demoHint")}>{t("status.demoMode")}</span>
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
        <PeriodToggle
          value={ui.periodMode ?? "all"}
          onChange={(v) => ui.patch({ periodMode: v })}
        />
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
        <button className="btn btn-small" onClick={handleSync} disabled={syncing}>
          {syncing ? t("status.syncing") : t("status.syncData")}
        </button>
        <div className="csv-upload-group">
          <button
            className="btn btn-small"
            onClick={handleCsvFetch}
            disabled={csvFetching || syncing}
            title={t("dashboard.fetchCsvHint")}
          >
            {csvFetching
              ? `${t("dashboard.csvFetching")}${csvProgress ? ` ${csvProgress}` : ""}`
              : t("dashboard.fetchCsv")}
          </button>
          <input ref={fileInputRef} type="file" accept=".csv" onChange={handleCsvUpload} style={{ display: "none" }} />
          <button
            className="btn btn-small"
            onClick={() => fileInputRef.current?.click()}
            disabled={csvUploading}
            title={t("dashboard.uploadCsvHint")}
          >
            {csvUploading ? t("dashboard.csvUploading") : t("dashboard.uploadCsv")}
          </button>
          {(csvInfo?.ai_usage?.has_data || csvInfo?.usage_report?.has_data) && (
            <div className="csv-date-hints">
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
            </div>
          )}
          {csvMessage && <span className="csv-upload-msg">{csvMessage}</span>}
        </div>
        <SourceCodeLink update={health?.update} />
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
        {user && <UserMenu user={user} onLogout={onLogout} />}
      </div>
      {settingsOpen && (
        <PATSettingsModal onClose={() => setSettingsOpen(false)} onPATChange={handlePATChange} />
      )}
    </div>
  );
}
