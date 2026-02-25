import { useState, useMemo, useRef, useEffect, useCallback } from "react";
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
  // null = all orgs, string[] = explicit selection (empty [] = none selected)
  const [selectedOrgs, setSelectedOrgs] = useState<string[] | null>(null);
  // Hook always receives string[]: null→[] means "all" for the API
  const { data, loading } = useDashboard(selectedOrgs ?? []);

  // Date range filter state
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  // Org dropdown state
  const [orgDropdownOpen, setOrgDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Close dropdown on outside click
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOrgDropdownOpen(false);
      }
    };
    if (orgDropdownOpen) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [orgDropdownOpen]);

  // Filtered daily trend by date range
  const filteredTrend = useMemo(() => {
    if (!data) return [];
    let trend = data.daily_trend;
    if (dateFrom) trend = trend.filter((d) => d.day >= dateFrom);
    if (dateTo) trend = trend.filter((d) => d.day <= dateTo);
    return trend;
  }, [data, dateFrom, dateTo]);

  const allOrgs = data?.orgs || [];

  const handleOrgToggle = useCallback((org: string) => {
    setSelectedOrgs((prev) => {
      // If currently "all" (null), switch to all-except-this-one
      if (prev === null) {
        return allOrgs.filter((o) => o !== org);
      }
      const next = prev.includes(org) ? prev.filter((o) => o !== org) : [...prev, org];
      // If all orgs re-selected, reset to null (= all)
      if (next.length === allOrgs.length) return null;
      return next;
    });
  }, [allOrgs]);

  // Toggle "All": if all selected → deselect all; otherwise → select all
  const toggleAllOrgs = useCallback(() => {
    setSelectedOrgs((prev) => (prev === null ? [] : null));
  }, []);

  const isOrgSelected = useCallback((org: string) => {
    return selectedOrgs === null || selectedOrgs.includes(org);
  }, [selectedOrgs]);

  const isAllSelected = selectedOrgs === null;
  const hasSelection = selectedOrgs === null || selectedOrgs.length > 0;

  // Derive trigger label
  const orgTriggerLabel = useMemo(() => {
    if (selectedOrgs === null) return t("dashboard.allOrgs");
    if (selectedOrgs.length === 0) return t("dashboard.noSelection");
    if (selectedOrgs.length === 1) return selectedOrgs[0];
    return `${selectedOrgs.length} / ${allOrgs.length}`;
  }, [selectedOrgs, allOrgs.length, t]);

  const hasData = hasSelection && data && (data.daily_trend.length > 0 || data.top_users.length > 0 || data.kpi.total_seats > 0);

  return (
    <div className="dashboard" key={refreshKey}>
      {/* Filters — always visible */}
      <div className="dashboard-filters">
        <div className="dashboard-filter-group">
          <label>{t("dashboard.filters")}:</label>
          <div className="org-dropdown" ref={dropdownRef}>
            <button
              className="org-dropdown-trigger"
              onClick={() => setOrgDropdownOpen((v) => !v)}
            >
              <span>{orgTriggerLabel}</span>
              <span className="org-dropdown-arrow">{orgDropdownOpen ? "\u25B4" : "\u25BE"}</span>
            </button>
            {orgDropdownOpen && (
              <div className="org-dropdown-menu">
                <label className={`org-dropdown-item ${isAllSelected ? "org-dropdown-item-active" : ""}`}>
                  <input
                    type="checkbox"
                    checked={isAllSelected}
                    onChange={toggleAllOrgs}
                  />
                  <span>{t("dashboard.allOrgs")}</span>
                </label>
                <div className="org-dropdown-divider" />
                {allOrgs.map((org) => (
                  <label key={org} className={`org-dropdown-item ${isOrgSelected(org) ? "org-dropdown-item-active" : ""}`}>
                    <input
                      type="checkbox"
                      checked={isOrgSelected(org)}
                      onChange={() => handleOrgToggle(org)}
                    />
                    <span>{org}</span>
                  </label>
                ))}
              </div>
            )}
          </div>
        </div>
        <div className="dashboard-filter-group">
          <input
            type="date"
            className="dashboard-date-input"
            value={dateFrom || data?.date_range?.start || ""}
            onChange={(e) => setDateFrom(e.target.value)}
          />
          <span className="dashboard-date-sep">—</span>
          <input
            type="date"
            className="dashboard-date-input"
            value={dateTo || data?.date_range?.end || ""}
            onChange={(e) => setDateTo(e.target.value)}
          />
        </div>
      </div>

      {/* Loading state */}
      {loading && !data && (
        <div className="dashboard-loading">{t("loading")}</div>
      )}

      {/* Empty state — filters remain accessible */}
      {!loading && !hasData && (
        <div className="dashboard-empty">{t("dashboard.noData")}</div>
      )}

      {/* Content — only when we have data */}
      {hasData && (
        <>
          {/* KPI Cards */}
          <div className="dashboard-kpi">
            <div className="stat-card">
              <div className="stat-value">{data.kpi.total_seats}</div>
              <div className="stat-label">{t("sidebar.totalSeats")}</div>
            </div>
            <div className="stat-card">
              <div className={`stat-value ${data.kpi.utilization_pct >= 80 ? "success" : data.kpi.utilization_pct >= 50 ? "warning" : "danger"}`}>
                {data.kpi.utilization_pct}%
              </div>
              <div className="stat-label">{t("sidebar.utilization")}</div>
            </div>
            <div className="stat-card">
              <div className="stat-value cost">${data.kpi.monthly_cost.toLocaleString()}</div>
              <div className="stat-label">{t("sidebar.monthlyCost")}</div>
            </div>
            <div className="stat-card">
              <div className={`stat-value ${data.kpi.monthly_waste > 0 ? "danger" : ""}`}>
                ${data.kpi.monthly_waste.toLocaleString()}
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
        </>
      )}
    </div>
  );
}
