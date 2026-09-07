import { useState, useMemo, useRef, useEffect, useCallback } from "react";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  BarChart, Bar, PieChart, Pie, Cell, Legend, LineChart, Line,
} from "recharts";
import { useI18n } from "../contexts/I18nContext";
import { useUIState } from "../contexts/UIStateContext";
import { useDashboard } from "../hooks/useData";
import { UserFilterSelect } from "./UserFilterSelect";
import { SortTh } from "./SortTh";
import { useSortableRows } from "../hooks/useSortableRows";
import { currentMonthRange } from "../utils/period";

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
  const period = ui.periodMode;
  const dateFrom = period === "current_month" ? currentMonthRange().start : ui.dashboardDateFrom;
  // Current Month pins the range, so picking a date has to leave that mode or the
  // choice would be silently discarded. The untouched bound keeps the month value
  // that was on screen.
  const setDateFrom = useCallback((v: string) => {
    if (ui.periodMode === "current_month") {
      ui.patch({ periodMode: "all", dashboardDateFrom: v, dashboardDateTo: currentMonthRange().end });
    } else {
      ui.patch({ dashboardDateFrom: v });
    }
  }, [ui.patch, ui.periodMode]);
  const dateTo = period === "current_month" ? currentMonthRange().end : ui.dashboardDateTo;
  const setDateTo = useCallback((v: string) => {
    if (ui.periodMode === "current_month") {
      ui.patch({ periodMode: "all", dashboardDateTo: v, dashboardDateFrom: currentMonthRange().start });
    } else {
      ui.patch({ dashboardDateTo: v });
    }
  }, [ui.patch, ui.periodMode]);
  const { data, loading } = useDashboard(selectedOrgs ?? [], ui.dashboardEnterpriseTeam, ui.dashboardUser, dateFrom, dateTo);
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

  const modelInteractionTotal = useMemo(
    () => (data?.model_usage ?? []).reduce((s, m) => s + m.interactions, 0),
    [data?.model_usage],
  );

  const langGenTotal = useMemo(
    () => (data?.language_usage ?? []).reduce((s, l) => s + l.code_gen, 0),
    [data?.language_usage],
  );

  const rate = (num: number, den: number) => (den > 0 ? num / den : -1);

  const featureSorter = useSortableRows(data?.feature_usage ?? [], {
    accept_rate: (f) => rate(f.code_accept, f.code_gen),
  });
  const langSorter = useSortableRows(data?.language_usage ?? [], {
    share: (l) => l.code_gen,
    accept_rate: (l) => rate(l.code_accept, l.code_gen),
  });
  const completionSorter = useSortableRows(data?.code_completions ?? [], {
    accept_rate: (c) => rate(c.acceptances, c.suggestions),
  });
  const modelSorter = useSortableRows(data?.model_usage ?? [], {
    share: (m) => m.interactions,
  });
  const ideSorter = useSortableRows(data?.ide_usage ?? []);
  const seatSorter = useSortableRows(data?.seat_info?.seats ?? [], {
    status: (s) => (s.pending_cancellation_date ? 2 : s.last_activity_at ? 0 : 1),
  });
  const topUserSorter = useSortableRows(data?.top_users ?? [], {
    accept_rate: (u) => rate(u.code_accept, u.code_gen),
  });

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
          <div className="org-dropdown" style={{ width: 140 }}>
            <select
              className="cc-native-select"
              value={ui.dashboardEnterpriseTeam}
              onChange={(e) => ui.patch({ dashboardEnterpriseTeam: e.target.value })}
              title={t("etFilter.hint")}
            >
              <option value="">{t("etFilter.all")}</option>
              {(data?.enterprise_teams ?? []).map((tm) => (
                <option key={tm.slug} value={tm.slug}>
                  {tm.slug === "__no_team__" ? t("etFilter.none") : tm.name} ({tm.member_count})
                </option>
              ))}
            </select>
          </div>
          <UserFilterSelect
            options={data?.users ?? []}
            value={ui.dashboardUser}
            onChange={(v) => ui.patch({ dashboardUser: v })}
          />
        </div>
        <div className="dashboard-filter-group">
          <input type="date" className="dashboard-date-input" value={dateFrom || data?.date_range?.start || ""} onChange={(e) => setDateFrom(e.target.value)} />
          <span className="dashboard-date-sep">—</span>
          <input type="date" className="dashboard-date-input" value={dateTo || data?.date_range?.end || ""} onChange={(e) => setDateTo(e.target.value)} />
        </div>
      </div>

      {data?.team_filtered && (
        <div className="dash-note">
          {data.team_member_count === null
            ? t("etFilter.noteNone")
            : `${t("etFilter.note")} ${data.team_member_count}`}
        </div>
      )}

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
          {(dateFrom || dateTo) && <div className="chart-hint kpi-hint">{t("dashboard.kpiSnapshotHint")}</div>}

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
                          <SortTh label="Feature" sortKey="feature" sorter={featureSorter} />
                          <SortTh label="Interactions" sortKey="interactions" sorter={featureSorter} />
                          <SortTh label="Code Gen" sortKey="code_gen" sorter={featureSorter} />
                          <SortTh label="Code Accept" sortKey="code_accept" sorter={featureSorter} />
                          <SortTh label="Accept %" sortKey="accept_rate" sorter={featureSorter} />
                          <SortTh label="LOC Suggested" sortKey="loc_suggested" sorter={featureSorter} />
                          <SortTh label="LOC Accepted" sortKey="loc_accepted" sorter={featureSorter} />
                        </tr>
                      </thead>
                      <tbody>
                        {featureSorter.rows.map((f) => (
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
                {data.language_usage.length > 0 && (
                  <div className="chart-card">
                    <h4>{t("dashboard.langShareTable")}</h4>
                    <div className="dashboard-table-wrap">
                      <table className="dashboard-table">
                        <thead>
                          <tr>
                            <th>#</th>
                            <SortTh label={t("dashboard.language")} sortKey="language" sorter={langSorter} />
                            <SortTh label={t("dashboard.codeGen")} sortKey="code_gen" sorter={langSorter} />
                            <SortTh label={t("csvDash.share")} sortKey="share" sorter={langSorter} />
                            <SortTh label={t("dashboard.accepted")} sortKey="code_accept" sorter={langSorter} />
                            <SortTh label={t("dashboard.acceptRate")} sortKey="accept_rate" sorter={langSorter} />
                          </tr>
                        </thead>
                        <tbody>
                          {langSorter.rows.map((l, i) => {
                            const pct = langGenTotal > 0 ? (l.code_gen / langGenTotal) * 100 : 0;
                            return (
                              <tr key={l.language}>
                                <td className="rank">{i + 1}</td>
                                <td className="user-name">
                                  <span className="dash-dot" style={{ background: COLORS[i % COLORS.length] }} />
                                  {l.language}
                                </td>
                                <td>{l.code_gen.toLocaleString()}</td>
                                <td>
                                  <div className="quota-bar-wrap">
                                    <div className="quota-bar">
                                      <div className="quota-bar-fill" style={{ width: `${Math.min(pct, 100)}%`, background: COLORS[i % COLORS.length] }} />
                                    </div>
                                    <span className="quota-bar-label">{pct.toFixed(1)}%</span>
                                  </div>
                                </td>
                                <td>{l.code_accept.toLocaleString()}</td>
                                <td>{l.code_gen > 0 ? `${Math.round((l.code_accept / l.code_gen) * 100)}%` : "—"}</td>
                              </tr>
                            );
                          })}
                        </tbody>
                        <tfoot>
                          <tr>
                            <td />
                            <td className="user-name">{t("csvDash.total")}</td>
                            <td>{langGenTotal.toLocaleString()}</td>
                            <td>100%</td>
                            <td>{data.language_usage.reduce((s, l) => s + l.code_accept, 0).toLocaleString()}</td>
                            <td />
                          </tr>
                        </tfoot>
                      </table>
                    </div>
                  </div>
                )}
                {data.code_completions.length > 0 && (
                  <div className="chart-card">
                    <h4>{t("dashboard.codeCompletions")}</h4>
                    <div className="dashboard-table-wrap">
                      <table className="dashboard-table">
                        <thead>
                          <tr>
                            <SortTh label="Language" sortKey="language" sorter={completionSorter} />
                            <SortTh label="Suggestions" sortKey="suggestions" sorter={completionSorter} />
                            <SortTh label="Accepted" sortKey="acceptances" sorter={completionSorter} />
                            <SortTh label="Accept %" sortKey="accept_rate" sorter={completionSorter} />
                            <SortTh label="Lines Sugg." sortKey="lines_suggested" sorter={completionSorter} />
                            <SortTh label="Lines Acc." sortKey="lines_accepted" sorter={completionSorter} />
                          </tr>
                        </thead>
                        <tbody>
                          {completionSorter.rows.slice(0, 15).map((c) => (
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

          {/* ===== Section: Model & AI Credits ===== */}
          <Section sectionKey="modelAi" title={t("dashboard.modelAiCredits")}>
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
                <h4>{t("csvDash.modelShareTable")}</h4>
                <div className="chart-hint">
                  {t("dashboard.modelShareHint")
                    .replace("{usage}", `${data.date_range.start} ~ ${data.date_range.end}`)
                    .replace("{credit}", data.ai_credit_period || "-")}
                </div>
                {data.model_usage.length > 0 ? (
                  <div className="dashboard-table-wrap">
                    <table className="dashboard-table">
                      <thead>
                        <tr>
                          <th>#</th>
                          <SortTh label={t("csvDash.model")} sortKey="model" sorter={modelSorter} />
                          <SortTh label={t("etDash.colInteractions")} sortKey="interactions" sorter={modelSorter} />
                          <SortTh label={t("csvDash.share")} sortKey="share" sorter={modelSorter} />
                          <SortTh label={t("csvDash.requests")} sortKey="ai_credits" sorter={modelSorter} />
                        </tr>
                      </thead>
                      <tbody>
                        {modelSorter.rows.map((m, i) => {
                          const pct = modelInteractionTotal > 0 ? (m.interactions / modelInteractionTotal) * 100 : 0;
                          return (
                            <tr key={m.model}>
                              <td className="rank">{i + 1}</td>
                              <td className="user-name">
                                <span className="dash-dot" style={{ background: COLORS[i % COLORS.length] }} />
                                {m.model}
                              </td>
                              <td>{m.interactions.toLocaleString()}</td>
                              <td>
                                <div className="quota-bar-wrap">
                                  <div className="quota-bar">
                                    <div className="quota-bar-fill" style={{ width: `${Math.min(pct, 100)}%`, background: COLORS[i % COLORS.length] }} />
                                  </div>
                                  <span className="quota-bar-label">{pct.toFixed(1)}%</span>
                                </div>
                              </td>
                              <td>{m.ai_credits.toLocaleString(undefined, { maximumFractionDigits: 2 })}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                      <tfoot>
                        <tr>
                          <td />
                          <td className="user-name">{t("csvDash.total")}</td>
                          <td>{modelInteractionTotal.toLocaleString()}</td>
                          <td>100%</td>
                          <td>{data.model_usage.reduce((s, m) => s + m.ai_credits, 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}</td>
                        </tr>
                      </tfoot>
                    </table>
                  </div>
                ) : (
                  <div className="chart-empty">{t("dashboard.noData")}</div>
                )}
              </div>
            </div>
          </Section>

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
                          <SortTh label="IDE" sortKey="ide" sorter={ideSorter} />
                          <SortTh label="Interactions" sortKey="interactions" sorter={ideSorter} />
                          <SortTh label="Code Gen" sortKey="code_gen" sorter={ideSorter} />
                          <SortTh label="Accept" sortKey="code_accept" sorter={ideSorter} />
                          <SortTh label="LOC Sugg." sortKey="loc_suggested" sorter={ideSorter} />
                          <SortTh label="LOC Acc." sortKey="loc_accepted" sorter={ideSorter} />
                        </tr>
                      </thead>
                      <tbody>
                        {ideSorter.rows.map((ide) => (
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
                          <SortTh label="User" sortKey="user" sorter={seatSorter} />
                          <SortTh label="Org" sortKey="org" sorter={seatSorter} />
                          <SortTh label="Team" sortKey="team" sorter={seatSorter} />
                          <SortTh label="Last Activity" sortKey="last_activity_at" sorter={seatSorter} />
                          <SortTh label="Editor" sortKey="last_activity_editor" sorter={seatSorter} />
                          <SortTh label="Status" sortKey="status" sorter={seatSorter} />
                        </tr>
                      </thead>
                      <tbody>
                        {seatSorter.rows.map((s) => {
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
                          <SortTh label="User" sortKey="user" sorter={topUserSorter} />
                          <SortTh label="Interactions" sortKey="interactions" sorter={topUserSorter} />
                          <SortTh label="Code Gen" sortKey="code_gen" sorter={topUserSorter} />
                          <SortTh label="Accept" sortKey="code_accept" sorter={topUserSorter} />
                          <SortTh label="Accept %" sortKey="accept_rate" sorter={topUserSorter} />
                          <SortTh label="LOC Sugg." sortKey="loc_suggested" sorter={topUserSorter} />
                          <SortTh label="LOC Acc." sortKey="loc_accepted" sorter={topUserSorter} />
                          <SortTh label="Days" sortKey="days_active" sorter={topUserSorter} />
                          <SortTh label="Chat" sortKey="used_chat" sorter={topUserSorter} />
                          <SortTh label="Agent" sortKey="used_agent" sorter={topUserSorter} />
                        </tr>
                      </thead>
                      <tbody>
                        {topUserSorter.rows.map((u, i) => (
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
