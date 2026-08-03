import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell, PieChart, Pie, Legend,
} from "recharts";
import { useI18n } from "../contexts/I18nContext";
import { useMyDashboard } from "../hooks/useMe";
import type { MyDashboardData, UserBudget } from "../types";

interface Props {
  refreshKey?: number;
  period?: "all" | "current_month";
}

const COLORS = ["#58a6ff", "#3fb950", "#d29922", "#f85149", "#bc8cff", "#f778ba", "#79c0ff", "#56d364"];
const TOOLTIP_STYLE = {
  background: "var(--bg-secondary)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  fontSize: 12,
};

function Section({ title, extra, children }: { title: string; extra?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="dash-section">
      <div className="dash-section-header">
        <span className="dash-section-chevron">▼</span>
        <h3 className="dash-section-title">{title}</h3>
        {extra && <span className="dash-section-extra">{extra}</span>}
      </div>
      <div className="dash-section-body">{children}</div>
    </div>
  );
}

function barColor(pct: number | null | undefined) {
  if (pct == null) return "#3fb950";
  if (pct >= 90) return "#f85149";
  if (pct >= 70) return "#d29922";
  return "#3fb950";
}

/** Amount / consumed / remaining bar for one GitHub budget. */
function BudgetMeter({ amount, consumed, pct }: { amount: number; consumed: number; pct: number | null }) {
  return (
    <div className="me-quota">
      <div className="me-quota-bar">
        <div
          className="me-quota-fill"
          style={{ width: `${Math.min(100, pct ?? 0)}%`, background: barColor(pct) }}
        />
      </div>
      <div className="me-quota-label">
        ${consumed.toFixed(2)} / ${amount.toLocaleString()}
        {pct != null && ` (${pct}%)`}
      </div>
    </div>
  );
}

export function MyDashboard({ refreshKey = 0, period = "all" }: Props) {
  const { t } = useI18n();
  const { data, loading, refetch } = useMyDashboard(refreshKey, period);

  if (loading && !data) return <div className="dashboard-loading">{t("loading")}</div>;
  if (!data || !data.profile) return <div className="dashboard-empty">{t("me.noData")}</div>;

  const d: MyDashboardData = data;
  const { activity, ai_usage: ai, spend, totals, seats, budget, cost_centers: costCenters } = d;
  const isCurrentMonth = d.period?.mode === "current_month";
  const hasBudget = budget && budget.amount > 0;

  return (
    <div className="csv-dashboard">
      {isCurrentMonth && (
        <div className="period-banner">
          {t("period.showingCurrentMonth")}: <strong>{d.period.label}</strong>
          {budget?.live && <span className="period-live-badge">{t("period.live")}</span>}
          <button className="btn btn-small btn-ghost" onClick={() => refetch(true)}>
            ⟳ {t("period.refresh")}
          </button>
        </div>
      )}

      {/* KPI cards */}
      <div className="dashboard-kpi">
        {hasBudget && (
          <>
            <div className="stat-card">
              <div className="stat-value">${budget.amount.toLocaleString()}</div>
              <div className="stat-label">{t("me.kpiBudget")}</div>
            </div>
            <div className="stat-card cost">
              <div className="stat-value cost">${budget.consumed.toFixed(2)}</div>
              <div className="stat-label">{t("me.kpiConsumed")}</div>
            </div>
            <div
              className={`stat-card ${(budget.usage_pct ?? 0) >= 90 ? "warning" : ""}`}
            >
              <div className={`stat-value ${(budget.usage_pct ?? 0) >= 90 ? "warning" : ""}`}>
                ${(budget.remaining ?? 0).toFixed(2)}
              </div>
              <div className="stat-label">{t("me.kpiRemaining")}</div>
            </div>
          </>
        )}
        <div className="stat-card">
          <div className="stat-value">{d.seat_summary.seat_count}</div>
          <div className="stat-label">{t("me.kpiSeats")}</div>
        </div>
        <div className="stat-card cost">
          <div className="stat-value cost">${totals.monthly_seat_cost.toLocaleString()}</div>
          <div className="stat-label">{t("me.kpiSeatCost")}</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{ai.has_data ? ai.kpi.total_requests.toLocaleString() : "—"}</div>
          <div className="stat-label">{t("me.kpiCredits")}</div>
        </div>
        <div className="stat-card cost">
          <div className="stat-value cost">${totals.ai_credit_cost.toFixed(2)}</div>
          <div className="stat-label">{t("me.kpiCreditCost")}</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{activity.has_data ? activity.kpi.total_interactions.toLocaleString() : "—"}</div>
          <div className="stat-label">{t("me.kpiInteractions")}</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{activity.has_data ? `${activity.kpi.acceptance_rate}%` : "—"}</div>
          <div className="stat-label">{t("me.kpiAcceptance")}</div>
        </div>
      </div>

      {/* My GitHub budget */}
      <Section
        title={t("me.budgetTitle")}
        extra={
          budget?.effective_source && (
            <span className="dash-badge dash-badge-muted">
              {budget.effective_source === "personal"
                ? t("me.budgetSourcePersonal")
                : t("me.budgetSourceUniversal")}
            </span>
          )
        }
      >
        {hasBudget ? (
          <>
            <BudgetMeter amount={budget.amount} consumed={budget.consumed} pct={budget.usage_pct} />
            <div className="me-budget-meta">
              <span>
                {t("me.budgetConsumedSource")}:{" "}
                {budget.consumed_source === "github" ? t("me.budgetFromGithub") : t("me.budgetFromUsage")}
              </span>
              {budget.effective?.prevent_further_usage && (
                <span className="dash-badge dash-badge-danger">{t("me.budgetHardLimit")}</span>
              )}
              {budget.effective?.entity_name && (
                <span className="cc-cc-tag">{budget.effective.entity_name}</span>
              )}
            </div>
          </>
        ) : (
          <div className="dashboard-empty">{t("me.noBudget")}</div>
        )}
        {budget?.error && <div className="login-error">{budget.error}</div>}
      </Section>

      {/* Cost centers I belong to */}
      <Section title={t("me.costCentersTitle")}>
        {costCenters && costCenters.length > 0 ? (
          <div className="cc-table-wrap">
            <table className="cc-table">
              <thead>
                <tr>
                  <th className="cc-th">{t("me.ccName")}</th>
                  <th className="cc-th">{t("me.ccEnterprise")}</th>
                  <th className="cc-th">{t("me.ccSource")}</th>
                  <th className="cc-th">{t("me.ccPool")}</th>
                  <th className="cc-th cc-th-num">{t("me.ccBudget")}</th>
                  <th className="cc-th">{t("me.ccUsage")}</th>
                </tr>
              </thead>
              <tbody>
                {costCenters.map((cc) => {
                  const b: UserBudget | null = cc.budget;
                  return (
                    <tr key={`${cc.enterprise}-${cc.id}`} className="cc-table-row">
                      <td className="cc-td"><strong>{cc.name}</strong></td>
                      <td className="cc-td">{cc.enterprise_name || cc.enterprise}</td>
                      <td className="cc-td">
                        {cc.membership_source
                          ? `${cc.membership_source}${cc.membership_source_name ? `: ${cc.membership_source_name}` : ""}`
                          : "—"}
                      </td>
                      <td className="cc-td">
                        {cc.ai_credit_pool_enabled
                          ? <span className="dash-badge dash-badge-success">{t("budgetsDash.on")}</span>
                          : <span className="dash-badge dash-badge-muted">{t("budgetsDash.off")}</span>}
                      </td>
                      <td className="cc-td cc-td-num">
                        {b ? <strong>${b.amount.toLocaleString()}</strong> : "—"}
                      </td>
                      <td className="cc-td">
                        {b && b.consumed_amount != null ? (
                          <BudgetMeter amount={b.amount} consumed={b.consumed_amount} pct={b.usage_pct} />
                        ) : (
                          "—"
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="dashboard-empty">{t("me.noCostCenters")}</div>
        )}
      </Section>

      {/* AI credit quota (plan allowance, separate from budget) */}
      {ai.has_data && ai.kpi.quota > 0 && (
        <Section title={t("me.quotaTitle")}>
          <BudgetMeter amount={ai.kpi.quota} consumed={ai.kpi.total_requests} pct={ai.kpi.usage_pct} />
        </Section>
      )}

      {/* My Copilot seats */}
      {seats.length > 0 && (
        <Section title={t("me.seatsTitle")}>
          <div className="cc-table-wrap">
            <table className="cc-table">
              <thead>
                <tr>
                  <th className="cc-th">{t("me.colOrg")}</th>
                  <th className="cc-th">{t("me.colPlan")}</th>
                  <th className="cc-th">{t("me.colTeam")}</th>
                  <th className="cc-th">{t("me.colAssigned")}</th>
                  <th className="cc-th">{t("me.colLastActive")}</th>
                  <th className="cc-th cc-th-num">{t("me.colSeatCost")}</th>
                </tr>
              </thead>
              <tbody>
                {seats.map((s) => (
                  <tr key={s.org} className="cc-table-row">
                    <td className="cc-td"><strong>{s.org}</strong></td>
                    <td className="cc-td">{s.plan_type}</td>
                    <td className="cc-td">{s.assigning_team || "—"}</td>
                    <td className="cc-td">{s.created_at ? s.created_at.slice(0, 10) : "—"}</td>
                    <td className="cc-td">
                      {s.last_activity_at ? s.last_activity_at.slice(0, 10) : "—"}
                      {s.days_inactive != null && (
                        <span
                          className={`dash-badge ${s.days_inactive > 30 ? "dash-badge-danger" : "dash-badge-muted"}`}
                          style={{ marginLeft: 6 }}
                        >
                          {s.days_inactive}d
                        </span>
                      )}
                    </td>
                    <td className="cc-td cc-td-num">${s.price_per_seat.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      {/* Copilot activity trend */}
      {activity.has_data && activity.daily_trend.length > 0 && (
        <Section title={t("me.activityTrend")}>
          <ResponsiveContainer width="100%" height={240}>
            <AreaChart data={activity.daily_trend}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="day" tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
              <YAxis tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
              <Tooltip contentStyle={TOOLTIP_STYLE} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Area type="monotone" dataKey="interactions" name={t("me.legendInteractions")} stroke="#58a6ff" fill="#58a6ff33" />
              <Area type="monotone" dataKey="accepted" name={t("me.legendAccepted")} stroke="#3fb950" fill="#3fb95033" />
            </AreaChart>
          </ResponsiveContainer>
        </Section>
      )}

      {/* AI credit usage */}
      {ai.has_data && (
        <>
          {ai.daily_trend.length > 0 && (
            <Section title={t("me.creditTrend")}>
              <ResponsiveContainer width="100%" height={220}>
                <AreaChart data={ai.daily_trend}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="day" tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
                  <YAxis tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Area type="monotone" dataKey="requests" name={t("me.legendRequests")} stroke="#bc8cff" fill="#bc8cff33" />
                  <Area type="monotone" dataKey="amount" name={t("me.legendCost")} stroke="#d29922" fill="#d2992233" />
                </AreaChart>
              </ResponsiveContainer>
            </Section>
          )}

          {ai.model_breakdown.length > 0 && (
            <Section title={t("me.modelBreakdown")}>
              <ResponsiveContainer width="100%" height={Math.max(180, ai.model_breakdown.length * 34)}>
                <BarChart data={ai.model_breakdown} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis type="number" tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
                  <YAxis dataKey="model" type="category" width={160} tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} />
                  <Bar dataKey="requests" name={t("me.legendRequests")} radius={[0, 4, 4, 0]}>
                    {ai.model_breakdown.map((_, i) => (
                      <Cell key={i} fill={COLORS[i % COLORS.length]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </Section>
          )}
        </>
      )}

      {/* Feature breakdown */}
      {activity.has_data && activity.feature_breakdown.length > 0 && (
        <Section title={t("me.featureBreakdown")}>
          <ResponsiveContainer width="100%" height={240}>
            <PieChart>
              <Pie
                data={activity.feature_breakdown.filter((f) => f.interactions > 0)}
                dataKey="interactions"
                nameKey="feature"
                outerRadius={90}
                label={({ name }: { name?: string | number }) => String(name ?? "")}
              >
                {activity.feature_breakdown.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip contentStyle={TOOLTIP_STYLE} />
            </PieChart>
          </ResponsiveContainer>
        </Section>
      )}

      {/* Billed spend */}
      {spend.has_data && (
        <Section title={t("me.spendTitle")}>
          <div className="cc-table-wrap">
            <table className="cc-table">
              <thead>
                <tr>
                  <th className="cc-th">{t("me.colSku")}</th>
                  <th className="cc-th cc-th-num">{t("me.colQuantity")}</th>
                  <th className="cc-th cc-th-num">{t("me.colGross")}</th>
                  <th className="cc-th cc-th-num">{t("me.colNet")}</th>
                </tr>
              </thead>
              <tbody>
                {spend.sku_breakdown.map((s) => (
                  <tr key={s.sku} className="cc-table-row">
                    <td className="cc-td">{s.sku}</td>
                    <td className="cc-td cc-td-num">{s.quantity.toLocaleString()}</td>
                    <td className="cc-td cc-td-num">${s.gross_amount.toFixed(4)}</td>
                    <td className="cc-td cc-td-num">${s.net_amount.toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      {!d.has_any_data && <div className="dashboard-empty">{t("me.noData")}</div>}
    </div>
  );
}
