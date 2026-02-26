import { useState, useMemo, useRef, useEffect, useCallback } from "react";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  BarChart, Bar, PieChart, Pie, Cell, Legend, LineChart, Line,
} from "recharts";
import { useI18n } from "../contexts/I18nContext";
import { useUIState } from "../contexts/UIStateContext";
import { useDashboard } from "../hooks/useData";

const COLORS = ["#58a6ff", "#3fb950", "#d29922", "#f85149", "#bc8cff", "#f778ba", "#79c0ff", "#56d364"];
const TOOLTIP_STYLE = { background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 };

interface Props {
  refreshKey: number;
}

/* ---------- Collapsible Section ---------- */
function Section({ sectionKey, title, defaultOpen = true, children }: { sectionKey: string; title: string; defaultOpen?: boolean; children: React.ReactNode }) {
  const { dashboardSections, patch } = useUIState();
  const open = dashboardSections[sectionKey] ?? defaultOpen;
  const toggle = useCallback(() => {
    patch({ dashboardSections: { ...dashboardSections, [sectionKey]: !open } });
  }, [patch, dashboardSections, sectionKey, open]);
  return (
    <div className="dash-section">
      <div className="dash-section-header" onClick={toggle}>
        <span className="dash-section-chevron">{open ? "\u25BC" : "\u25B6"}</span>
        <h3 className="dash-section-title">{title}</h3>
      </div>
      {open && <div className="dash-section-body">{children}</div>}
    </div>
  );
}

/* ---------- Main Dashboard ---------- */
export function Dashboard({ refreshKey }: Props) {
  const { t } = useI18n();
  const ui = useUIState();
  const selectedOrgs = ui.dashboardSelectedOrgs;
  const setSelectedOrgs = useCallback((v: string[] | null | ((prev: string[] | null) => string[] | null)) => {
    const next = typeof v === "function" ? v(ui.dashboardSelectedOrgs) : v;
    ui.patch({ dashboardSelectedOrgs: next });
  }, [ui.patch, ui.dashboardSelectedOrgs]);
  const { data, loading } = useDashboard(selectedOrgs ?? []);

  const dateFrom = ui.dashboardDateFrom;
  const setDateFrom = useCallback((v: string) => ui.patch({ dashboardDateFrom: v }), [ui.patch]);
  const dateTo = ui.dashboardDateTo;
  const setDateTo = useCallback((v: string) => ui.patch({ dashboardDateTo: v }), [ui.patch]);
  const [orgDropdownOpen, setOrgDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

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
      if (prev === null) return allOrgs.filter((o) => o !== org);
      const next = prev.includes(org) ? prev.filter((o) => o !== org) : [...prev, org];
      if (next.length === allOrgs.length) return null;
      return next;
    });
  }, [allOrgs]);

  const toggleAllOrgs = useCallback(() => {
    setSelectedOrgs((prev) => (prev === null ? [] : null));
  }, []);

  const isOrgSelected = useCallback((org: string) => {
    return selectedOrgs === null || selectedOrgs.includes(org);
  }, [selectedOrgs]);

  const isAllSelected = selectedOrgs === null;
  const hasSelection = selectedOrgs === null || selectedOrgs.length > 0;

  const orgTriggerLabel = useMemo(() => {
    if (selectedOrgs === null) return t("dashboard.allOrgs");
    if (selectedOrgs.length === 0) return t("dashboard.noSelection");
    if (selectedOrgs.length === 1) return selectedOrgs[0];
    return `${selectedOrgs.length} / ${allOrgs.length}`;
  }, [selectedOrgs, allOrgs.length, t]);

  const hasData = hasSelection && data && (data.daily_trend.length > 0 || data.top_users.length > 0 || data.kpi.total_seats > 0);

  // Acceptance rate trend
  const acceptRateTrend = useMemo(() => {
    return filteredTrend.map((d) => ({
      day: d.day,
      accept_rate: d.code_gen > 0 ? Math.round((d.code_accept / d.code_gen) * 100) : 0,
      loc_accept_rate: d.loc_suggested > 0 ? Math.round((d.loc_accepted / d.loc_suggested) * 100) : 0,
    }));
  }, [filteredTrend]);

  return (
    <div className="dashboard" key={refreshKey}>
      {/* Filters */}
      <div className="dashboard-filters">
        <div className="dashboard-filter-group">
          <label>{t("dashboard.filters")}:</label>
          <div className="org-dropdown" ref={dropdownRef}>
            <button className="org-dropdown-trigger" onClick={() => setOrgDropdownOpen((v) => !v)}>
              <span>{orgTriggerLabel}</span>
              <span className="org-dropdown-arrow">{orgDropdownOpen ? "\u25B4" : "\u25BE"}</span>
            </button>
            {orgDropdownOpen && (
              <div className="org-dropdown-menu">
                <label className={`org-dropdown-item ${isAllSelected ? "org-dropdown-item-active" : ""}`}>
                  <input type="checkbox" checked={isAllSelected} onChange={toggleAllOrgs} />
                  <span>{t("dashboard.allOrgs")}</span>
                </label>
                <div className="org-dropdown-divider" />
                {allOrgs.map((org) => (
                  <label key={org} className={`org-dropdown-item ${isOrgSelected(org) ? "org-dropdown-item-active" : ""}`}>
                    <input type="checkbox" checked={isOrgSelected(org)} onChange={() => handleOrgToggle(org)} />
                    <span>{org}</span>
                  </label>
                ))}
              </div>
            )}
          </div>
        </div>
        <div className="dashboard-filter-group">
          <input type="date" className="dashboard-date-input" value={dateFrom || data?.date_range?.start || ""} onChange={(e) => setDateFrom(e.target.value)} />
          <span className="dashboard-date-sep">—</span>
          <input type="date" className="dashboard-date-input" value={dateTo || data?.date_range?.end || ""} onChange={(e) => setDateTo(e.target.value)} />
        </div>
      </div>

      {loading && !data && <div className="dashboard-loading">{t("loading")}</div>}
      {!loading && !hasData && <div className="dashboard-empty">{t("dashboard.noData")}</div>}

      {hasData && (
        <>
          {/* ===== KPI Cards ===== */}
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
            {data.chat_stats && (data.chat_stats.ide_chats > 0 || data.chat_stats.dotcom_chats > 0) && (
              <>
                <div className="stat-card">
                  <div className="stat-value">{(data.chat_stats.ide_chats + data.chat_stats.dotcom_chats).toLocaleString()}</div>
                  <div className="stat-label">{t("dashboard.totalChats")}</div>
                </div>
                <div className="stat-card">
                  <div className="stat-value">{data.chat_stats.pr_summaries.toLocaleString()}</div>
                  <div className="stat-label">{t("dashboard.prSummaries")}</div>
                </div>
              </>
            )}
          </div>

          {/* ===== Section: Active User Trends ===== */}
          <Section sectionKey="activeUserTrends" title={t("dashboard.activeUserTrends")}>
            <div className="dashboard-charts">
              <div className="chart-card chart-card-wide">
                <h4>{t("dashboard.dailyTrend")}</h4>
                {filteredTrend.length > 0 ? (
                  <ResponsiveContainer width="100%" height={260}>
                    <AreaChart data={filteredTrend}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                      <XAxis dataKey="day" tick={{ fontSize: 11, fill: "var(--text-muted)" }} tickFormatter={(v) => v.slice(5)} />
                      <YAxis tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
                      <Tooltip contentStyle={TOOLTIP_STYLE} />
                      <Area type="monotone" dataKey="mau" name="MAU" stroke="#bc8cff" fill="#bc8cff" fillOpacity={0.1} />
                      <Area type="monotone" dataKey="wau" name="WAU" stroke="#58a6ff" fill="#58a6ff" fillOpacity={0.15} />
                      <Area type="monotone" dataKey="dau" name="DAU" stroke="#3fb950" fill="#3fb950" fillOpacity={0.2} />
                      <Area type="monotone" dataKey="chat_users" name="Chat" stroke="#d29922" fill="#d29922" fillOpacity={0.1} />
                      <Area type="monotone" dataKey="agent_users" name="Agent" stroke="#f85149" fill="#f85149" fillOpacity={0.1} />
                      <Legend wrapperStyle={{ fontSize: 12 }} />
                    </AreaChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="chart-empty">{t("dashboard.noData")}</div>
                )}
              </div>
            </div>
          </Section>

          {/* ===== Section: Code Productivity ===== */}
          <Section sectionKey="codeProductivity" title={t("dashboard.codeProductivity")}>
            <div className="dashboard-charts">
              <div className="chart-card">
                <h4>{t("dashboard.locTrend")}</h4>
                {filteredTrend.length > 0 ? (
                  <ResponsiveContainer width="100%" height={240}>
                    <AreaChart data={filteredTrend}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                      <XAxis dataKey="day" tick={{ fontSize: 11, fill: "var(--text-muted)" }} tickFormatter={(v) => v.slice(5)} />
                      <YAxis tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
                      <Tooltip contentStyle={TOOLTIP_STYLE} />
                      <Area type="monotone" dataKey="loc_suggested" name="LOC Suggested" stroke="#58a6ff" fill="#58a6ff" fillOpacity={0.15} />
                      <Area type="monotone" dataKey="loc_accepted" name="LOC Accepted" stroke="#3fb950" fill="#3fb950" fillOpacity={0.2} />
                      <Legend wrapperStyle={{ fontSize: 12 }} />
                    </AreaChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="chart-empty">{t("dashboard.noData")}</div>
                )}
              </div>
              <div className="chart-card">
                <h4>{t("dashboard.acceptRate")}</h4>
                {acceptRateTrend.length > 0 ? (
                  <ResponsiveContainer width="100%" height={240}>
                    <LineChart data={acceptRateTrend}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                      <XAxis dataKey="day" tick={{ fontSize: 11, fill: "var(--text-muted)" }} tickFormatter={(v) => v.slice(5)} />
                      <YAxis tick={{ fontSize: 11, fill: "var(--text-muted)" }} domain={[0, 100]} unit="%" />
                      <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v: any) => `${v}%`} />
                      <Line type="monotone" dataKey="accept_rate" name="Code Accept %" stroke="#3fb950" strokeWidth={2} dot={false} />
                      <Line type="monotone" dataKey="loc_accept_rate" name="LOC Accept %" stroke="#58a6ff" strokeWidth={2} dot={false} />
                      <Legend wrapperStyle={{ fontSize: 12 }} />
                    </LineChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="chart-empty">{t("dashboard.noData")}</div>
                )}
              </div>
            </div>
          </Section>

          {/* ===== Section: Feature Usage ===== */}
          <Section sectionKey="featureUsage" title={t("dashboard.featureUsage")}>
            <div className="dashboard-charts">
              <div className="chart-card chart-card-wide">
                {data.feature_usage.length > 0 ? (
                  <div className="dashboard-table-wrap">
                    <table className="dashboard-table">
                      <thead>
                        <tr>
                          <th>Feature</th>
                          <th>Interactions</th>
                          <th>Code Gen</th>
                          <th>Code Accept</th>
                          <th>Accept %</th>
                          <th>LOC Suggested</th>
                          <th>LOC Accepted</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.feature_usage.map((f) => (
                          <tr key={f.feature}>
                            <td className="user-name">{f.feature}</td>
                            <td>{f.interactions.toLocaleString()}</td>
                            <td>{f.code_gen.toLocaleString()}</td>
                            <td>{f.code_accept.toLocaleString()}</td>
                            <td>{f.code_gen > 0 ? `${Math.round((f.code_accept / f.code_gen) * 100)}%` : "—"}</td>
                            <td>{f.loc_suggested.toLocaleString()}</td>
                            <td>{f.loc_accepted.toLocaleString()}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="chart-empty">{t("dashboard.noData")}</div>
                )}
              </div>
            </div>
          </Section>

          {/* ===== Section: Language Distribution ===== */}
          {(data.language_usage.length > 0 || data.code_completions.length > 0) && (
            <Section sectionKey="langDist" title={t("dashboard.langDist")}>
              <div className="dashboard-charts">
                {data.language_usage.length > 0 && (
                  <div className="chart-card">
                    <h4>{t("dashboard.langCodeGen")}</h4>
                    <ResponsiveContainer width="100%" height={Math.max(200, data.language_usage.length * 28)}>
                      <BarChart data={data.language_usage.slice(0, 15)} layout="vertical">
                        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                        <XAxis type="number" tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
                        <YAxis dataKey="language" type="category" width={100} tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
                        <Tooltip contentStyle={TOOLTIP_STYLE} />
                        <Bar dataKey="code_gen" name="Code Gen" fill="#58a6ff" radius={[0, 4, 4, 0]} />
                        <Bar dataKey="code_accept" name="Accepted" fill="#3fb950" radius={[0, 4, 4, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}
                {data.code_completions.length > 0 && (
                  <div className="chart-card">
                    <h4>{t("dashboard.codeCompletions")}</h4>
                    <div className="dashboard-table-wrap">
                      <table className="dashboard-table">
                        <thead>
                          <tr>
                            <th>Language</th>
                            <th>Suggestions</th>
                            <th>Accepted</th>
                            <th>Accept %</th>
                            <th>Lines Sugg.</th>
                            <th>Lines Acc.</th>
                          </tr>
                        </thead>
                        <tbody>
                          {data.code_completions.slice(0, 15).map((c) => (
                            <tr key={c.language}>
                              <td className="user-name">{c.language}</td>
                              <td>{c.suggestions.toLocaleString()}</td>
                              <td>{c.acceptances.toLocaleString()}</td>
                              <td>{c.suggestions > 0 ? `${Math.round((c.acceptances / c.suggestions) * 100)}%` : "—"}</td>
                              <td>{c.lines_suggested.toLocaleString()}</td>
                              <td>{c.lines_accepted.toLocaleString()}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </div>
            </Section>
          )}

          {/* ===== Section: Model & Premium Requests ===== */}
          <Section sectionKey="modelPremium" title={t("dashboard.modelPremium")}>
            <div className="dashboard-charts">
              <div className="chart-card">
                <h4>{t("dashboard.modelUsage")}</h4>
                {data.model_usage.length > 0 ? (
                  <ResponsiveContainer width="100%" height={240}>
                    <PieChart>
                      <Pie
                        data={data.model_usage}
                        dataKey="interactions"
                        nameKey="model"
                        cx="50%" cy="50%" outerRadius={80}
                        label={({ name, percent }: { name?: string; percent?: number }) => `${name || ""} ${((percent || 0) * 100).toFixed(0)}%`}
                        labelLine={false}
                      >
                        {data.model_usage.map((_, i) => (
                          <Cell key={i} fill={COLORS[i % COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip contentStyle={TOOLTIP_STYLE} />
                    </PieChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="chart-empty">{t("dashboard.noData")}</div>
                )}
              </div>
              <div className="chart-card">
                <h4>{t("dashboard.premiumDetail")}</h4>
                {data.premium_detail.length > 0 ? (
                  <div className="dashboard-table-wrap">
                    <table className="dashboard-table">
                      <thead>
                        <tr>
                          <th>Model</th>
                          <th>Gross Qty</th>
                          <th>Discount</th>
                          <th>Net Qty</th>
                          <th>Net Cost</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.premium_detail.map((p) => (
                          <tr key={p.model}>
                            <td className="user-name">{p.model}</td>
                            <td>{p.gross_qty.toLocaleString()}</td>
                            <td>{p.discount_qty.toLocaleString()}</td>
                            <td>{p.net_qty.toLocaleString()}</td>
                            <td>${p.net_amount.toFixed(2)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="chart-empty">{t("dashboard.noData")}</div>
                )}
              </div>
            </div>
          </Section>

          {/* ===== Section: Per-User Premium Requests (from CSV) ===== */}
          {data.user_premium_usage?.has_data && (
            <Section sectionKey="userPremium" title={t("dashboard.userPremium")}>
              <div className="dashboard-charts">
                {/* Daily trend chart */}
                <div className="chart-card">
                  <h4>{t("dashboard.userPremiumTrend")}</h4>
                  {data.user_premium_usage.daily_trend.length > 0 ? (
                    <ResponsiveContainer width="100%" height={240}>
                      <BarChart data={data.user_premium_usage.daily_trend}>
                        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                        <XAxis dataKey="day" tick={{ fontSize: 11, fill: "var(--text-muted)" }} tickFormatter={(v) => v.slice(5)} />
                        <YAxis tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
                        <Tooltip contentStyle={TOOLTIP_STYLE} />
                        <Bar dataKey="requests" name="Requests" fill="#bc8cff" radius={[4, 4, 0, 0]} />
                        <Bar dataKey="active_users" name="Active Users" fill="#3fb950" radius={[4, 4, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  ) : (
                    <div className="chart-empty">{t("dashboard.noData")}</div>
                  )}
                </div>
                {/* Model breakdown pie */}
                <div className="chart-card">
                  <h4>{t("dashboard.userPremiumModel")}</h4>
                  {data.user_premium_usage.model_breakdown.length > 0 ? (
                    <ResponsiveContainer width="100%" height={240}>
                      <PieChart>
                        <Pie
                          data={data.user_premium_usage.model_breakdown}
                          dataKey="requests"
                          nameKey="model"
                          cx="50%" cy="50%" outerRadius={80}
                          label={({ name, percent }: { name?: string; percent?: number }) => `${name || ""} ${((percent || 0) * 100).toFixed(0)}%`}
                          labelLine={false}
                        >
                          {data.user_premium_usage.model_breakdown.map((_, i) => (
                            <Cell key={i} fill={COLORS[i % COLORS.length]} />
                          ))}
                        </Pie>
                        <Tooltip contentStyle={TOOLTIP_STYLE} />
                      </PieChart>
                    </ResponsiveContainer>
                  ) : (
                    <div className="chart-empty">{t("dashboard.noData")}</div>
                  )}
                </div>
                {/* Per-user table */}
                <div className="chart-card chart-card-wide">
                  <h4>{t("dashboard.userPremiumTable")}</h4>
                  {data.user_premium_usage.users.length > 0 ? (
                    <div className="dashboard-table-wrap">
                      <table className="dashboard-table">
                        <thead>
                          <tr>
                            <th>#</th>
                            <th>User</th>
                            <th>Org</th>
                            <th>Requests</th>
                            <th>Cost</th>
                            <th>Quota</th>
                            <th>{t("dashboard.quotaUsage")}</th>
                            <th>Days</th>
                            <th>Top Models</th>
                          </tr>
                        </thead>
                        <tbody>
                          {data.user_premium_usage.users.map((u, i) => (
                            <tr key={u.user}>
                              <td className="rank">{i + 1}</td>
                              <td className="user-name">{u.user}</td>
                              <td>{u.org}</td>
                              <td>{u.requests.toLocaleString()}</td>
                              <td>${u.gross_amount.toFixed(2)}</td>
                              <td>{u.quota.toLocaleString()}</td>
                              <td>
                                <div className="quota-bar-wrap">
                                  <div className="quota-bar">
                                    <div
                                      className={`quota-bar-fill ${u.usage_pct > 80 ? "danger" : u.usage_pct > 50 ? "warning" : "success"}`}
                                      style={{ width: `${Math.min(u.usage_pct, 100)}%` }}
                                    />
                                  </div>
                                  <span className="quota-bar-label">{u.usage_pct}%</span>
                                </div>
                              </td>
                              <td>{u.days_active}</td>
                              <td className="model-tags">
                                {u.models.slice(0, 3).map((m) => (
                                  <span key={m.model} className="dash-badge dash-badge-muted">{m.model}: {m.requests}</span>
                                ))}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <div className="chart-empty">{t("dashboard.noData")}</div>
                  )}
                </div>
              </div>
            </Section>
          )}

          {/* ===== Section: IDE Distribution ===== */}
          <Section sectionKey="ideUsage" title={t("dashboard.ideUsage")}>
            <div className="dashboard-charts">
              <div className="chart-card">
                <h4>{t("dashboard.ideChart")}</h4>
                {data.ide_usage.length > 0 ? (
                  <ResponsiveContainer width="100%" height={240}>
                    <BarChart data={data.ide_usage}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                      <XAxis dataKey="ide" tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
                      <YAxis tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
                      <Tooltip contentStyle={TOOLTIP_STYLE} />
                      <Bar dataKey="interactions" name="Interactions" fill="#d29922" radius={[4, 4, 0, 0]} />
                      <Bar dataKey="code_gen" name="Code Gen" fill="#58a6ff" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="chart-empty">{t("dashboard.noData")}</div>
                )}
              </div>
              <div className="chart-card">
                <h4>{t("dashboard.ideDetail")}</h4>
                {data.ide_usage.length > 0 ? (
                  <div className="dashboard-table-wrap">
                    <table className="dashboard-table">
                      <thead>
                        <tr>
                          <th>IDE</th>
                          <th>Interactions</th>
                          <th>Code Gen</th>
                          <th>Accept</th>
                          <th>LOC Sugg.</th>
                          <th>LOC Acc.</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.ide_usage.map((ide) => (
                          <tr key={ide.ide}>
                            <td className="user-name">{ide.ide}</td>
                            <td>{ide.interactions.toLocaleString()}</td>
                            <td>{ide.code_gen.toLocaleString()}</td>
                            <td>{ide.code_accept.toLocaleString()}</td>
                            <td>{ide.loc_suggested.toLocaleString()}</td>
                            <td>{ide.loc_accepted.toLocaleString()}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="chart-empty">{t("dashboard.noData")}</div>
                )}
              </div>
            </div>
          </Section>

          {/* ===== Section: Seat Management ===== */}
          {data.seat_info && data.seat_info.seats.length > 0 && (
            <Section sectionKey="seatMgmt" title={t("dashboard.seatMgmt")} defaultOpen={false}>
              <div className="dashboard-charts">
                <div className="chart-card chart-card-wide">
                  <div className="dash-seat-summary">
                    {Object.entries(data.seat_info.plans).map(([plan, count]) => (
                      <span key={plan} className="dash-badge">{plan}: {count}</span>
                    ))}
                    {Object.entries(data.seat_info.features).map(([feat, val]) => (
                      <span key={feat} className="dash-badge dash-badge-muted">{feat}: {val}</span>
                    ))}
                    <span className="dash-badge">Pending Invite: {data.seat_info.breakdown.pending_invitation}</span>
                    <span className="dash-badge">Pending Cancel: {data.seat_info.breakdown.pending_cancellation}</span>
                    <span className="dash-badge">Added This Cycle: {data.seat_info.breakdown.added_this_cycle}</span>
                  </div>
                  <div className="dashboard-table-wrap" style={{ maxHeight: 400 }}>
                    <table className="dashboard-table">
                      <thead>
                        <tr>
                          <th>User</th>
                          <th>Org</th>
                          <th>Team</th>
                          <th>Last Activity</th>
                          <th>Editor</th>
                          <th>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.seat_info.seats.map((s) => {
                          const inactive = !s.last_activity_at;
                          const pending = !!s.pending_cancellation_date;
                          return (
                            <tr key={`${s.org}-${s.user}`}>
                              <td className="user-name">
                                {s.avatar && <img src={s.avatar} alt="" className="dash-seat-avatar" />}
                                {s.user}
                              </td>
                              <td>{s.org}</td>
                              <td>{s.team || "—"}</td>
                              <td>{s.last_activity_at ? s.last_activity_at.slice(0, 10) : "Never"}</td>
                              <td>{s.last_activity_editor || "—"}</td>
                              <td>
                                {pending ? <span className="dash-status-badge danger">Cancelling</span>
                                  : inactive ? <span className="dash-status-badge warning">Inactive</span>
                                  : <span className="dash-status-badge success">Active</span>}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            </Section>
          )}

          {/* ===== Section: Top Active Users ===== */}
          <Section sectionKey="topUsers" title={t("dashboard.topUsers")}>
            <div className="dashboard-charts">
              <div className="chart-card chart-card-wide">
                {data.top_users.length > 0 ? (
                  <div className="dashboard-table-wrap">
                    <table className="dashboard-table">
                      <thead>
                        <tr>
                          <th>#</th>
                          <th>User</th>
                          <th>Interactions</th>
                          <th>Code Gen</th>
                          <th>Accept</th>
                          <th>Accept %</th>
                          <th>LOC Sugg.</th>
                          <th>LOC Acc.</th>
                          <th>Days</th>
                          <th>Chat</th>
                          <th>Agent</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.top_users.map((u, i) => (
                          <tr key={u.user}>
                            <td className="rank">{i + 1}</td>
                            <td className="user-name">{u.user}</td>
                            <td>{u.interactions.toLocaleString()}</td>
                            <td>{u.code_gen.toLocaleString()}</td>
                            <td>{u.code_accept.toLocaleString()}</td>
                            <td>{u.code_gen > 0 ? `${Math.round((u.code_accept / u.code_gen) * 100)}%` : "—"}</td>
                            <td>{u.loc_suggested.toLocaleString()}</td>
                            <td>{u.loc_accepted.toLocaleString()}</td>
                            <td>{u.days_active}</td>
                            <td>{u.used_chat ? "\u2713" : ""}</td>
                            <td>{u.used_agent ? "\u2713" : ""}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="chart-empty">{t("dashboard.noData")}</div>
                )}
              </div>
            </div>
          </Section>
        </>
      )}
    </div>
  );
}
