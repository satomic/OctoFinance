import { useCallback } from "react";
import { useI18n } from "../contexts/I18nContext";
import { useUIState } from "../contexts/UIStateContext";
import { Dashboard } from "./Dashboard";
import { CsvDashboard } from "./CsvDashboard";
import { CostCenterDashboard } from "./CostCenterDashboard";

interface Props {
  refreshKey: number;
}

export function UnifiedDashboard({ refreshKey }: Props) {
  const { t } = useI18n();
  const ui = useUIState();
  const tab = ui.dashboardTab ?? "metrics";
  const setTab = useCallback(
    (v: "metrics" | "premium" | "usage" | "costcenter") => ui.patch({ dashboardTab: v }),
    [ui.patch],
  );

  return (
    <div className="unified-dashboard">
      <div className="dashboard-tab-bar">
        <div className="view-toggle">
          <button
            className={`btn btn-small btn-toggle ${tab === "metrics" ? "btn-toggle-active" : ""}`}
            onClick={() => setTab("metrics")}
          >
            {t("nav.dashMetrics")}
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
          <button
            className={`btn btn-small btn-toggle ${tab === "costcenter" ? "btn-toggle-active" : ""}`}
            onClick={() => setTab("costcenter")}
          >
            {t("ccDash.tab")}
          </button>
        </div>
      </div>

      {tab === "metrics" ? (
        <Dashboard refreshKey={refreshKey} />
      ) : tab === "costcenter" ? (
        <CostCenterDashboard refreshKey={refreshKey} />
      ) : (
        <CsvDashboard refreshKey={refreshKey} tab={tab as "premium" | "usage"} />
      )}
    </div>
  );
}
