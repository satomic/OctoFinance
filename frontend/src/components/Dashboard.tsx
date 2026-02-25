import { useState, useMemo } from "react";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  BarChart, Bar, PieChart, Pie, Cell, Legend,
} from "recharts";
import { useI18n } from "../contexts/I18nContext";
import { useDashboard } from "../hooks/useData";

const COLORS = ["#58a6ff", "#3fb950", "#d29922", "#f85149", "#bc8cff", "#f778ba", "#79c0ff", "#56d364"];

interface Props {
  refreshKey: number;
}

export function Dashboard({ refreshKey }: Props) {
  const { t } = useI18n();
  const [selectedOrgs, setSelectedOrgs] = useState<string[]>([]);
  const { data, loading } = useDashboard(selectedOrgs);

  // Date range filter state
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  // Filtered daily trend by date range
  const filteredTrend = useMemo(() => {
    if (!data) return [];
    let trend = data.daily_trend;
    if (dateFrom) trend = trend.filter((d) => d.day >= dateFrom);
    if (dateTo) trend = trend.filter((d) => d.day <= dateTo);
    return trend;
  }, [data, dateFrom, dateTo]);

  const handleOrgToggle = (org: string) => {
    setSelectedOrgs((prev) =>
      prev.includes(org) ? prev.filter((o) => o !== org) : [...prev, org]
    );
  };

  const selectAllOrgs = () => setSelectedOrgs([]);

  if (loading && !data) {
    return <div className="dashboard"><div className="dashboard-loading">{t("loading")}</div></div>;
  }

  if (!data || (!data.daily_trend.length && !data.top_users.length && data.kpi.total_seats === 0)) {
    return <div className="dashboard"><div className="dashboard-empty">{t("dashboard.noData")}</div></div>;
  }

  const kpi = data.kpi;

  return (
    <div className="dashboard" key={refreshKey}>
      {/* Filters */}
      <div className="dashboard-filters">
        <div className="dashboard-filter-group">
          <label>{t("dashboard.filters")}:</label>
          <button
            className={`btn btn-small btn-preset ${selectedOrgs.length === 0 ? "btn-preset-active" : ""}`}
            onClick={selectAllOrgs}
          >
            {t("dashboard.allOrgs")}
          </button>
          {data.orgs.map((org) => (
            <button
              key={org}
              className={`btn btn-small btn-preset ${
                selectedOrgs.length === 0 || selectedOrgs.includes(org) ? "btn-preset-active" : ""
              }`}
              onClick={() => handleOrgToggle(org)}
            >
              {org}
            </button>
          ))}
        </div>
        <div className="dashboard-filter-group">
          <input
            type="date"
            className="dashboard-date-input"
            value={dateFrom || data.date_range.start}
            onChange={(e) => setDateFrom(e.target.value)}
          />
          <span className="dashboard-date-sep">—</span>
          <input
            type="date"
            className="dashboard-date-input"
            value={dateTo || data.date_range.end}
            onChange={(e) => setDateTo(e.target.value)}
          />
        </div>
      </div>

      {/* KPI Cards */}
      <div className="dashboard-kpi">
        <div className="stat-card">
          <div className="stat-value">{kpi.total_seats}</div>
          <div className="stat-label">{t("sidebar.totalSeats")}</div>
        </div>
        <div className="stat-card">
          <div className={`stat-value ${kpi.utilization_pct >= 80 ? "success" : kpi.utilization_pct >= 50 ? "warning" : "danger"}`}>
            {kpi.utilization_pct}%
          </div>
          <div className="stat-label">{t("sidebar.utilization")}</div>
        </div>
        <div className="stat-card">
          <div className="stat-value cost">${kpi.monthly_cost.toLocaleString()}</div>
          <div className="stat-label">{t("sidebar.monthlyCost")}</div>
        </div>
        <div className="stat-card">
          <div className={`stat-value ${kpi.monthly_waste > 0 ? "danger" : ""}`}>
            ${kpi.monthly_waste.toLocaleString()}
          </div>
          <div className="stat-label">{t("sidebar.monthlyWaste")}</div>
        </div>
      </div>

      {/* Charts Grid */}
      <div className="dashboard-charts">
        {/* Daily Active Trend */}
        <div className="chart-card chart-card-wide">
          <h4>{t("dashboard.dailyTrend")}</h4>
          {filteredTrend.length > 0 ? (
            <ResponsiveContainer width="100%" height={260}>
              <AreaChart data={filteredTrend}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="day" tick={{ fontSize: 11, fill: "var(--text-muted)" }} tickFormatter={(v) => v.slice(5)} />
                <YAxis tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
                <Tooltip contentStyle={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} />
                <Area type="monotone" dataKey="mau" name="MAU" stroke="#bc8cff" fill="#bc8cff" fillOpacity={0.1} />
                <Area type="monotone" dataKey="wau" name="WAU" stroke="#58a6ff" fill="#58a6ff" fillOpacity={0.15} />
                <Area type="monotone" dataKey="dau" name="DAU" stroke="#3fb950" fill="#3fb950" fillOpacity={0.2} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="chart-empty">No trend data</div>
          )}
        </div>

        {/* Feature Usage */}
        <div className="chart-card">
          <h4>{t("dashboard.featureUsage")}</h4>
          {data.feature_usage.length > 0 ? (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={data.feature_usage} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis type="number" tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
                <YAxis dataKey="feature" type="category" width={140} tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
                <Tooltip contentStyle={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} />
                <Bar dataKey="interactions" name="Interactions" fill="#58a6ff" radius={[0, 4, 4, 0]} />
                <Bar dataKey="code_gen" name="Code Gen" fill="#3fb950" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="chart-empty">No feature data</div>
          )}
        </div>

        {/* Model Usage Pie */}
        <div className="chart-card">
          <h4>{t("dashboard.modelUsage")}</h4>
          {data.model_usage.length > 0 ? (
            <ResponsiveContainer width="100%" height={240}>
              <PieChart>
                <Pie
                  data={data.model_usage}
                  dataKey="interactions"
                  nameKey="model"
                  cx="50%"
                  cy="50%"
                  outerRadius={80}
                  label={({ name, percent }: { name?: string; percent?: number }) => `${name || ""} ${((percent || 0) * 100).toFixed(0)}%`}
                  labelLine={false}
                >
                  {data.model_usage.map((_, i) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }}
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  formatter={((value: any, name: any, props: any) => {
                    const pr = props?.payload?.premium_requests;
                    return [`Interactions: ${value}${pr ? `, Premium: ${pr}` : ""}`, name];
                  }) as any}
                />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <div className="chart-empty">No model data</div>
          )}
        </div>

        {/* IDE Distribution */}
        <div className="chart-card">
          <h4>{t("dashboard.ideUsage")}</h4>
          {data.ide_usage.length > 0 ? (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={data.ide_usage}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="ide" tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
                <YAxis tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
                <Tooltip contentStyle={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} />
                <Bar dataKey="interactions" name="Interactions" fill="#d29922" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="chart-empty">No IDE data</div>
          )}
        </div>
      </div>

      {/* Top Users Table */}
      <div className="chart-card chart-card-wide">
        <h4>{t("dashboard.topUsers")}</h4>
        {data.top_users.length > 0 ? (
          <div className="dashboard-table-wrap">
            <table className="dashboard-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>User</th>
                  <th>Interactions</th>
                  <th>Code Gen</th>
                  <th>Days Active</th>
                </tr>
              </thead>
              <tbody>
                {data.top_users.map((u, i) => (
                  <tr key={u.user}>
                    <td className="rank">{i + 1}</td>
                    <td className="user-name">{u.user}</td>
                    <td>{u.interactions}</td>
                    <td>{u.code_gen}</td>
                    <td>{u.days_active}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="chart-empty">No user data</div>
        )}
      </div>
    </div>
  );
}
