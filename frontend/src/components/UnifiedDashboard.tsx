import { useCallback } from "react";
import { useI18n } from "../contexts/I18nContext";
import { useUIState } from "../contexts/UIStateContext";
import { Dashboard } from "./Dashboard";
import { CsvDashboard } from "./CsvDashboard";

interface Props {
  refreshKey: number;
}

export function UnifiedDashboard({ refreshKey }: Props) {
  const { t } = useI18n();
  const ui = useUIState();
  const tab = ui.dashboardTab ?? "api";
  const setTab = useCallback(
    (v: "api" | "premium" | "usage") => ui.patch({ dashboardTab: v }),
    [ui.patch],
  );

  return (
    <div className="unified-dashboard">
      <div className="dashboard-tab-bar">
        <div className="view-toggle">
          <button
            className={`btn btn-small btn-toggle ${tab === "api" ? "btn-toggle-active" : ""}`}
            onClick={() => setTab("api")}
          >
            {t("nav.dashApi")}
          </button>
          <button
            className={`btn btn-small btn-toggle ${tab === "premium" ? "btn-toggle-active" : ""}`}
            onClick={() => setTab("premium")}
          >
            {t("csvDash.tabs.premium")}
          </button>
          <button
            className={`btn btn-small btn-toggle ${tab === "usage" ? "btn-toggle-active" : ""}`}
            onClick={() => setTab("usage")}
          >
            {t("csvDash.tabs.usage")}
          </button>
        </div>
      </div>

      {tab === "api" ? (
        <Dashboard refreshKey={refreshKey} />
      ) : (
        <CsvDashboard refreshKey={refreshKey} tab={tab} />
      )}
    </div>
  );
}
