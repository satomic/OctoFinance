import { useCallback, useState } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from "recharts";
import { useI18n } from "../contexts/I18nContext";
import { useUIState } from "../contexts/UIStateContext";
import { useBudgetsDashboard, useDatasetSync } from "../hooks/useData";
import type { Budget } from "../types";

interface Props {
  refreshKey: number;
}

const COLORS = ["#58a6ff", "#3fb950", "#d29922", "#f85149", "#bc8cff", "#f778ba", "#79c0ff", "#56d364"];
const TOOLTIP_STYLE = { background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 };

const SCOPE_COLORS: Record<string, string> = {
  enterprise: "var(--accent)",
  organization: "#3fb950",
  cost_center: "#d29922",
  repository: "#bc8cff",
  multi_user_customer: "#f778ba",
  user: "#79c0ff",
};

const SCOPE_LABEL_KEYS = [
  "enterprise", "organization", "repository", "cost_center", "multi_user_customer", "user",
] as const;

export function BudgetsDashboard({ refreshKey }: Props) {
  const { t } = useI18n();
  const ui = useUIState();

  const enterprise = ui.budgetsDashEnterprise;
  const scope = ui.budgetsDashScope || "all";

  const [searchInput, setSearchInput] = useState(ui.budgetsDashSearch);
  const commitSearch = useCallback((v: string) => ui.patch({ budgetsDashSearch: v }), [ui.patch]); // eslint-disable-line react-hooks/exhaustive-deps

  const { data, loading, refetch } = useBudgetsDashboard({
    enterprise, scope, search: ui.budgetsDashSearch,
  });
  const { syncing, runSync } = useDatasetSync();
  const handleSync = useCallback(() => runSync("budgets", refetch), [runSync, refetch]);

  const setEnterprise = useCallback((v: string) => ui.patch({ budgetsDashEnterprise: v }), [ui.patch]); // eslint-disable-line react-hooks/exhaustive-deps
  const setScope = useCallback((v: string) => ui.patch({ budgetsDashScope: v }), [ui.patch]); // eslint-disable-line react-hooks/exhaustive-deps

  const scopeLabel = (s: string) =>
    (SCOPE_LABEL_KEYS as readonly string[]).includes(s)
      ? t(`budgetsDash.scope.${s}` as Parameters<typeof t>[0])
      : s;

  if (loading && !data) return <div className="dashboard-loading">{t("loading")}</div>;

  if (!data || data.no_data) {
    return (
      <div className="csv-dashboard">
        <div className="csv-filters">
          <button
            className="btn btn-small"
            style={{ marginLeft: "auto" }}
            onClick={handleSync}
            disabled={syncing}
            title={t("budgetsDash.syncHint")}
          >
            {syncing ? t("status.syncing") : `⟳ ${t("budgetsDash.sync")}`}
          </button>
        </div>
        <div className="dashboard-empty">{t("budgetsDash.noData")}</div>
      </div>
    );
  }

  const enterpriseOptions = data.enterprises.map((e) => e.slug);
  const handleEnterpriseSelect = (slug: string) => setEnterprise(slug);

  return (
    <div className="csv-dashboard" key={refreshKey}>
      {/* Filters */}
      <div className="csv-filters">
        {enterpriseOptions.length > 1 && (
          <div className="org-dropdown" style={{ minWidth: 160 }}>
            <select
              className="cc-native-select"
              value={enterprise || data.selected_enterprise}
              onChange={(e) => handleEnterpriseSelect(e.target.value)}
            >
              {enterpriseOptions.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
        )}

        {/* Scope filter */}
        <div className="org-dropdown" style={{ minWidth: 150 }}>
          <select
            className="cc-native-select"
            value={scope}
            onChange={(e) => setScope(e.target.value)}
          >
            <option value="all">{t("budgetsDash.allScopes")}</option>
            {data.scopes.map((s) => (
              <option key={s} value={s}>{scopeLabel(s)}</option>
            ))}
          </select>
        </div>

        {/* Search */}
        <input
          type="text"
          className="cc-search-input"
          placeholder={t("budgetsDash.search")}
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          onBlur={() => commitSearch(searchInput)}
          onKeyDown={(e) => { if (e.key === "Enter") commitSearch(searchInput); }}
        />

        {/* Sync */}
        <button
          className="btn btn-small"
          style={{ marginLeft: "auto" }}
          onClick={handleSync}
          disabled={syncing}
          title={t("budgetsDash.syncHint")}
        >
          {syncing ? t("status.syncing") : `⟳ ${t("budgetsDash.sync")}`}
        </button>
      </div>

      {/* KPI cards */}
      <div className="dashboard-kpi">
        <div className="stat-card">
          <div className="stat-value">{data.total_budgets}</div>
          <div className="stat-label">{t("budgetsDash.totalBudgets")}</div>
        </div>
        <div className="stat-card cost">
          <div className="stat-value cost">${data.total_amount.toLocaleString()}</div>
          <div className="stat-label">{t("budgetsDash.totalAmount")}</div>
        </div>
        <div className="stat-card warning">
          <div className="stat-value warning">{data.hard_limit_count}</div>
          <div className="stat-label">{t("budgetsDash.hardLimits")}</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{data.alerting_count}</div>
          <div className="stat-label">{t("budgetsDash.alerting")}</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{data.enterprise_name || data.selected_enterprise}</div>
          <div className="stat-label">Enterprise</div>
        </div>
      </div>

      {/* Scope breakdown chart */}
      {data.scope_breakdown.length > 0 && (
        <div className="dash-section">
          <div className="dash-section-header">
            <span className="dash-section-chevron">▼</span>
            <h3 className="dash-section-title">{t("budgetsDash.scopeBreakdown")}</h3>
          </div>
          <div className="dash-section-body">
            <ResponsiveContainer width="100%" height={Math.max(160, data.scope_breakdown.length * 44)}>
              <BarChart data={data.scope_breakdown.map((s) => ({ ...s, label: scopeLabel(s.scope) }))} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis type="number" tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
                <YAxis dataKey="label" type="category" width={150} tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
                <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v: any, name?: string) => name === "amount" ? `$${Number(v).toLocaleString()}` : v} />
                <Bar dataKey="amount" name="amount" radius={[0, 4, 4, 0]}>                  {data.scope_breakdown.map((s, i) => (
                    <Cell key={i} fill={SCOPE_COLORS[s.scope] ?? COLORS[i % COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Budgets table */}
      <div className="dash-section">
        <div className="dash-section-header">
          <span className="dash-section-chevron">▼</span>
          <h3 className="dash-section-title">{t("budgetsDash.sectionBudgets")}</h3>
        </div>
        <div className="dash-section-body">
          <div className="cc-table-wrap">
            <table className="cc-table">
              <thead>
                <tr>
                  <th className="cc-th">{t("budgetsDash.colScope")}</th>
                  <th className="cc-th">{t("budgetsDash.colEntity")}</th>
                  <th className="cc-th">{t("budgetsDash.colType")}</th>
                  <th className="cc-th">{t("budgetsDash.colSkus")}</th>
                  <th className="cc-th cc-th-num">{t("budgetsDash.colAmount")}</th>
                  <th className="cc-th">{t("budgetsDash.colHardLimit")}</th>
                  <th className="cc-th">{t("budgetsDash.colAlerting")}</th>
                </tr>
              </thead>
              <tbody>
                {data.budgets.map((b: Budget) => (
                  <tr key={b.id} className="cc-table-row">
                    <td className="cc-td">
                      <span
                        className="cc-state-badge"
                        style={{ borderColor: SCOPE_COLORS[b.scope] ?? "var(--border)", color: SCOPE_COLORS[b.scope] ?? "var(--text-primary)" }}
                      >
                        {scopeLabel(b.scope)}
                      </span>
                    </td>
                    <td className="cc-td">{b.entity_name || "—"}</td>
                    <td className="cc-td">{b.budget_type || "—"}</td>
                    <td className="cc-td">
                      <div className="cc-resource-tags">
                        {b.skus.length
                          ? b.skus.map((s, i) => <span key={i} className="cc-cc-tag">{s}</span>)
                          : "—"}
                      </div>
                    </td>
                    <td className="cc-td cc-td-num"><strong>${b.amount.toLocaleString()}</strong></td>
                    <td className="cc-td">
                      {b.prevent_further_usage
                        ? <span className="dash-badge dash-badge-danger">{t("budgetsDash.hardLimit")}</span>
                        : <span className="dash-badge dash-badge-muted">{t("budgetsDash.softLimit")}</span>}
                    </td>
                    <td className="cc-td">
                      {b.will_alert
                        ? <span className="dash-badge dash-badge-muted" title={b.alert_recipients.join(", ")}>
                            {t("budgetsDash.on")}{b.alert_recipients.length ? ` (${b.alert_recipients.length})` : ""}
                          </span>
                        : <span className="dash-badge dash-badge-muted">{t("budgetsDash.off")}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
