import { usePendingActions } from "../hooks/useData";
import { useI18n } from "../contexts/I18nContext";

export function ActionPanel() {
  const { recommendations, loading, executeAction, rejectAction } = usePendingActions();
  const { t } = useI18n();

  if (loading) return <div className="sidebar-section loading">{t("loading.actions")}</div>;

  return (
    <div className="sidebar-section">
      {recommendations.length === 0 ? (
        <div className="empty">{t("actions.empty")}</div>
      ) : (
        <div className="action-list">
          {recommendations.map((rec) => (
            <div key={rec.id} className="action-card">
              <div className="action-header">
                <span className="action-type">{rec.type.replace(/_/g, " ")}</span>
                <span className="action-org">{rec.org}</span>
              </div>
              <div className="action-description">{rec.description}</div>
              {rec.affected_users.length > 0 && (
                <div className="action-users">
                  {t("actions.users")}: {rec.affected_users.join(", ")}
                </div>
              )}
              {rec.estimated_monthly_savings > 0 && (
                <div className="action-savings">
                  {t("actions.savings")}: ${rec.estimated_monthly_savings}/month
                </div>
              )}
              <div className="action-buttons">
                <button
                  className="btn btn-approve"
                  onClick={() => executeAction(rec.id)}
                >
                  {t("actions.approve")}
                </button>
                <button
                  className="btn btn-reject"
                  onClick={() => rejectAction(rec.id)}
                >
                  {t("actions.reject")}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
