import { useState } from "react";
import { useI18n } from "../contexts/I18nContext";
import type { CredentialProblem, SyncHealth } from "../types";

interface Props {
  health: SyncHealth | null;
  onOpenSettings: () => void;
  onOpenConsole: () => void;
}

const DISMISSED_KEY = "octofinance-dismissed-sync-alerts";
const BLOCKING = new Set(["invalid", "forbidden", "unreachable"]);

function readDismissed(): string[] {
  try {
    return JSON.parse(localStorage.getItem(DISMISSED_KEY) || "[]");
  } catch {
    return [];
  }
}

function formatTime(iso: string | null | undefined) {
  return iso ? new Date(iso).toLocaleString() : "";
}

/**
 * Admin notice for syncs that cannot keep the data current: rejected or
 * expiring PATs and a failed last run. Scheduled syncs run unattended, so
 * without this an admin would assume the dashboards are up to date.
 */
export function SyncAlertBanner({ health, onOpenSettings, onOpenConsole }: Props) {
  const { t } = useI18n();
  const [dismissed, setDismissed] = useState<string[]>(readDismissed);

  if (!health) return null;
  const { sync, credential_problems: problems } = health;
  const blocking = problems.filter((p) => BLOCKING.has(p.state));
  const expiring = problems.filter((p) => p.state === "expiring");
  const failedRun = sync.last_run?.status === "failed" ? sync.last_run : null;

  // A dismissed notice comes back as soon as a newer check or run fails again
  const errorKey = `error:${failedRun?.finished_at ?? ""}:${blocking.map((p) => p.checked_at).join(",")}`;
  const expiringKey = `expiring:${expiring.map((p) => `${p.pat_id}@${p.expires_at}`).join(",")}`;

  const dismiss = (key: string) => {
    const next = [...dismissed.filter((k) => k.split(":")[0] !== key.split(":")[0]), key];
    setDismissed(next);
    try {
      localStorage.setItem(DISMISSED_KEY, JSON.stringify(next));
    } catch {
      // per-browser convenience only
    }
  };

  const reason = (p: CredentialProblem) => {
    const code = p.status ? `HTTP ${p.status}${p.detail ? ` ${p.detail}` : ""}` : p.detail;
    const text = p.state === "invalid"
      ? t("syncAlert.patInvalid")
      : p.state === "forbidden" ? t("syncAlert.patForbidden") : t("syncAlert.patUnreachable");
    return `${text}${code ? ` (${code})` : ""}`;
  };

  const showError = (blocking.length > 0 || failedRun) && !dismissed.includes(errorKey);
  const showExpiring = expiring.length > 0 && !dismissed.includes(expiringKey);
  if (!showError && !showExpiring) return null;

  return (
    <div className="sync-alerts">
      {showError && (
        <div className="sync-alert sync-alert-error" role="alert">
          <span className="sync-alert-icon" aria-hidden="true">!</span>
          <div className="sync-alert-body">
            <strong>{t("syncAlert.title")}</strong>
            <ul>
              {blocking.map((p) => (
                <li key={p.pat_id}>
                  <b>PAT “{p.label || p.user_login}”</b> ({p.host}): {reason(p)}
                </li>
              ))}
              {failedRun && (
                <li>
                  <b>{t("syncAlert.lastRun")} ({t(`syncAlert.trigger.${failedRun.trigger}` as "syncAlert.trigger.manual")})</b>
                  {" "}{formatTime(failedRun.finished_at)} · {failedRun.error_count} {t("syncAlert.errors")}
                  {/* The PAT lines above already explain a credential failure */}
                  {failedRun.errors[0] && !(blocking.length && failedRun.errors[0].startsWith("PAT '")) && (
                    <span className="sync-alert-detail">: {failedRun.errors[0]}</span>
                  )}
                </li>
              )}
            </ul>
            <span className="sync-alert-meta">
              {t("syncAlert.lastSuccess")}: {sync.last_success_at ? formatTime(sync.last_success_at) : t("syncAlert.never")}
              {sync.cron_description && ` · ${t("syncAlert.schedule")}: ${sync.cron_description}`}
            </span>
          </div>
          <div className="sync-alert-actions">
            <button className="btn btn-small sync-alert-primary" onClick={onOpenSettings}>{t("syncAlert.openSettings")}</button>
            <button className="btn btn-small" onClick={onOpenConsole}>{t("syncAlert.viewConsole")}</button>
            <button className="btn btn-small btn-toggle" onClick={() => dismiss(errorKey)}>{t("syncAlert.dismiss")}</button>
          </div>
        </div>
      )}
      {showExpiring && (
        <div className="sync-alert sync-alert-warning" role="status">
          <span className="sync-alert-icon" aria-hidden="true">!</span>
          <div className="sync-alert-body">
            <strong>{t("syncAlert.expiringTitle")}</strong>
            <ul>
              {expiring.map((p) => (
                <li key={p.pat_id}>
                  <b>PAT “{p.label || p.user_login}”</b> ({p.host}) {t("syncAlert.expiresOn")} {formatTime(p.expires_at)}
                </li>
              ))}
            </ul>
            <span className="sync-alert-meta">{t("syncAlert.expiringHint")}</span>
          </div>
          <div className="sync-alert-actions">
            <button className="btn btn-small sync-alert-primary" onClick={onOpenSettings}>{t("syncAlert.openSettings")}</button>
            <button className="btn btn-small btn-toggle" onClick={() => dismiss(expiringKey)}>{t("syncAlert.dismiss")}</button>
          </div>
        </div>
      )}
    </div>
  );
}
