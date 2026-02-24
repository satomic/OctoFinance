import { useOverview } from "../hooks/useData";
import { useI18n } from "../contexts/I18nContext";

export function OverviewPanel() {
  const { overview, loading } = useOverview();
  const { t } = useI18n();

  if (loading) {
    return <div className="sidebar-section loading">{t("loading")}</div>;
  }

  if (!overview) return null;

  return (
    <div className="sidebar-overview">
      <div className="overview-cards">
        <div className="stat-card">
          <div className="stat-value">{overview.total_seats}</div>
          <div className="stat-label">{t("sidebar.totalSeats")}</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{overview.total_active_seats}</div>
          <div className="stat-label">{t("sidebar.active")}</div>
        </div>
        <div className="stat-card warning">
          <div className="stat-value">{overview.total_inactive_seats}</div>
          <div className="stat-label">{t("sidebar.inactive")}</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{overview.utilization_pct}%</div>
          <div className="stat-label">{t("sidebar.utilization")}</div>
        </div>
        <div className="stat-card cost">
          <div className="stat-value">${overview.monthly_cost.toLocaleString()}</div>
          <div className="stat-label">{t("sidebar.monthlyCost")}</div>
        </div>
        <div className="stat-card danger">
          <div className="stat-value">${overview.monthly_waste.toLocaleString()}</div>
          <div className="stat-label">{t("sidebar.monthlyWaste")}</div>
        </div>
      </div>
    </div>
  );
}
