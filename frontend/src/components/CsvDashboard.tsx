import { useState, useMemo, useRef, useEffect, useCallback } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend, AreaChart, Area,
} from "recharts";
import { useI18n } from "../contexts/I18nContext";
import { useUIState } from "../contexts/UIStateContext";
import { useCsvDashboard } from "../hooks/useData";
import type { PremiumCsvSection, UsageReportSection } from "../types";

const COLORS = ["#58a6ff", "#3fb950", "#d29922", "#f85149", "#bc8cff", "#f778ba", "#79c0ff", "#56d364"];
const TOOLTIP_STYLE = { background: "var(--bg-secondary)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 };

interface Props {
  refreshKey: number;
  tab: "premium" | "usage";
}

/* ---------- Multi-select Dropdown ---------- */
function MultiSelect({
  label, options, selected, onChange,
}: {
  label: string;
  options: string[];
  selected: string[];
  onChange: (v: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    if (open) document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const isAll = selected.length === 0;
  const triggerLabel = isAll ? label : selected.length === 1 ? selected[0] : `${selected.length} / ${options.length}`;

  const toggle = (v: string) => {
    onChange(selected.includes(v) ? selected.filter((x) => x !== v) : [...selected, v]);
  };

  return (
    <div className="org-dropdown" ref={ref} style={{ minWidth: 140 }}>
      <button className="org-dropdown-trigger" onClick={() => setOpen((o) => !o)}>
        <span>{triggerLabel}</span>
        <span className="org-dropdown-arrow">{open ? "▴" : "▾"}</span>
      </button>
      {open && (
        <div className="org-dropdown-menu">
          <label className={`org-dropdown-item ${isAll ? "org-dropdown-item-active" : ""}`}>
            <input type="checkbox" checked={isAll} onChange={() => onChange([])} />
            <span>{label}</span>
          </label>
          <div className="org-dropdown-divider" />
          {options.map((opt) => (
            <label key={opt} className={`org-dropdown-item ${selected.includes(opt) ? "org-dropdown-item-active" : ""}`}>
              <input type="checkbox" checked={selected.includes(opt)} onChange={() => toggle(opt)} />
              <span>{opt}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------- Collapsible Section ---------- */
function Section({ sectionKey, title, defaultOpen = true, children }: {
  sectionKey: string; title: string; defaultOpen?: boolean; children: React.ReactNode;
}) {
  const { dashboardSections, patch } = useUIState();
  const open = dashboardSections[`csv_${sectionKey}`] ?? defaultOpen;
  const toggle = useCallback(() => {
    patch({ dashboardSections: { ...dashboardSections, [`csv_${sectionKey}`]: !open } });
  }, [patch, dashboardSections, sectionKey, open]);
  return (
    <div className="dash-section">
      <div className="dash-section-header" onClick={toggle}>
        <span className="dash-section-chevron">{open ? "▼" : "▶"}</span>
        <h3 className="dash-section-title">{title}</h3>
      </div>
      {open && <div className="dash-section-body">{children}</div>}
    </div>
  );
}

/* ---------- Premium CSV content ---------- */
function PremiumContent({ data }: { data: PremiumCsvSection }) {
  const { t } = useI18n();

  if (!data.has_data) {
    return <div className="dashboard-empty">{t("csvDash.noDataType")}</div>;
  }

  return (
    <>
      <div className="dashboard-kpi">
        <div className="stat-card">
          <div className="stat-value">{data.kpi.total_requests.toLocaleString()}</div>
          <div className="stat-label">{t("csvDash.totalRequests")}</div>
        </div>
        <div className="stat-card cost">
          <div className="stat-value cost">${data.kpi.total_cost.toFixed(2)}</div>
          <div className="stat-label">{t("csvDash.totalCost")}</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{data.kpi.unique_users}</div>
          <div className="stat-label">{t("csvDash.uniqueUsers")}</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{data.kpi.unique_orgs}</div>
          <div className="stat-label">{t("csvDash.uniqueOrgs")}</div>
        </div>
      </div>

      <Section sectionKey="premiumTrend" title={t("csvDash.dailyTrend")}>
        <div className="dashboard-charts">
          <div className="chart-card chart-card-wide">
            {data.daily_trend.length > 0 ? (
              <ResponsiveContainer width="100%" height={240}>
                <AreaChart data={data.daily_trend}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="day" tick={{ fontSize: 11, fill: "var(--text-muted)" }} tickFormatter={(v) => v.slice(5)} />
                  <YAxis tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} />
                  <Area type="monotone" dataKey="requests" name="Requests" stroke="#bc8cff" fill="#bc8cff" fillOpacity={0.15} />
                  <Area type="monotone" dataKey="active_users" name="Active Users" stroke="#3fb950" fill="#3fb950" fillOpacity={0.15} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                </AreaChart>
              </ResponsiveContainer>
            ) : <div className="chart-empty">{t("csvDash.noData")}</div>}
          </div>
        </div>
      </Section>

      <Section sectionKey="premiumBreakdowns" title={t("csvDash.modelBreakdown")}>
        <div className="dashboard-charts">
          <div className="chart-card">
            <h4>{t("csvDash.modelBreakdown")}</h4>
            {data.model_breakdown.length > 0 ? (
              <ResponsiveContainer width="100%" height={240}>
                <PieChart>
                  <Pie data={data.model_breakdown} dataKey="requests" nameKey="model"
                    cx="50%" cy="50%" outerRadius={80}
                    label={({ name, percent }: { name?: string; percent?: number }) =>
                      `${(name || "").split(":").pop()?.trim() || name} ${((percent || 0) * 100).toFixed(0)}%`}
                    labelLine={false}>
                    {data.model_breakdown.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                  </Pie>
                  <Tooltip contentStyle={TOOLTIP_STYLE} />
                </PieChart>
              </ResponsiveContainer>
            ) : <div className="chart-empty">{t("csvDash.noData")}</div>}
          </div>
          <div className="chart-card">
            <h4>{t("csvDash.orgBreakdown")}</h4>
            {data.org_breakdown.length > 0 ? (
              <ResponsiveContainer width="100%" height={Math.max(200, data.org_breakdown.length * 36)}>
                <BarChart data={data.org_breakdown} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis type="number" tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
                  <YAxis dataKey="org" type="category" width={120} tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} />
                  <Bar dataKey="requests" name="Requests" fill="#58a6ff" radius={[0, 4, 4, 0]} />
                  <Bar dataKey="user_count" name="Users" fill="#3fb950" radius={[0, 4, 4, 0]} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                </BarChart>
              </ResponsiveContainer>
            ) : <div className="chart-empty">{t("csvDash.noData")}</div>}
          </div>
          <div className="chart-card">
            <h4>{t("dashboard.costCenterBreakdown")}</h4>
            {data.cost_center_breakdown.length > 0 ? (
              <ResponsiveContainer width="100%" height={Math.max(200, data.cost_center_breakdown.length * 36)}>
                <BarChart data={data.cost_center_breakdown} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis type="number" tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
                  <YAxis dataKey="cost_center" type="category" width={140} tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v: any, name?: string) => name === "amount" ? `$${Number(v).toFixed(2)}` : v} />
                  <Bar dataKey="requests" name="Requests" fill="#bc8cff" radius={[0, 4, 4, 0]} />
                  <Bar dataKey="user_count" name="Users" fill="#58a6ff" radius={[0, 4, 4, 0]} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                </BarChart>
              </ResponsiveContainer>
            ) : <div className="chart-empty">{t("csvDash.noData")}</div>}
          </div>
        </div>
      </Section>

      <Section sectionKey="premiumUsers" title={t("csvDash.userTable")}>
        <div className="dashboard-charts">
          <div className="chart-card chart-card-wide">
            {data.users.length > 0 ? (
              <div className="dashboard-table-wrap">
                <table className="dashboard-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>{t("csvDash.user")}</th>
                      <th>{t("csvDash.org")}</th>
                      <th>{t("csvDash.costCenter")}</th>
                      <th>{t("csvDash.requests")}</th>
                      <th>{t("csvDash.grossAmount")}</th>
                      <th>{t("csvDash.quota")}</th>
                      <th>{t("csvDash.quotaUsage")}</th>
                      <th>{t("csvDash.daysActive")}</th>
                      <th>{t("csvDash.models")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.users.map((u, i) => (
                      <tr key={u.user}>
                        <td className="rank">{i + 1}</td>
                        <td className="user-name">{u.user}</td>
                        <td>{u.org}</td>
                        <td>{u.cost_center || "—"}</td>
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
                            <span key={m.model} className="dash-badge dash-badge-muted">
                              {m.model.split(":").pop()?.trim()}: {m.requests}
                            </span>
                          ))}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <div className="chart-empty">{t("csvDash.noData")}</div>}
          </div>
        </div>
      </Section>
    </>
  );
}

/* ---------- Usage Report content ---------- */
function UsageContent({ data }: { data: UsageReportSection }) {
  const { t } = useI18n();

  if (!data.has_data) {
    return <div className="dashboard-empty">{t("csvDash.noDataType")}</div>;
  }

  return (
    <>
      <div className="dashboard-kpi">
        <div className="stat-card cost">
          <div className="stat-value cost">${data.kpi.total_gross.toFixed(2)}</div>
          <div className="stat-label">{t("csvDash.totalGross")}</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">${data.kpi.total_net.toFixed(2)}</div>
          <div className="stat-label">{t("csvDash.totalNet")}</div>
        </div>
        <div className="stat-card warning">
          <div className="stat-value warning">${data.kpi.total_discount.toFixed(2)}</div>
          <div className="stat-label">{t("csvDash.totalDiscount")}</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{data.kpi.unique_users}</div>
          <div className="stat-label">{t("csvDash.uniqueUsers")}</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{data.kpi.unique_orgs}</div>
          <div className="stat-label">{t("csvDash.uniqueOrgs")}</div>
        </div>
      </div>

      <Section sectionKey="usageTrend" title={t("csvDash.dailyTrend")}>
        <div className="dashboard-charts">
          <div className="chart-card chart-card-wide">
            {data.daily_trend.length > 0 ? (
              <ResponsiveContainer width="100%" height={240}>
                <AreaChart data={data.daily_trend}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="day" tick={{ fontSize: 11, fill: "var(--text-muted)" }} tickFormatter={(v) => v.slice(5)} />
                  <YAxis tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v: any) => `$${Number(v).toFixed(4)}`} />
                  <Area type="monotone" dataKey="gross_amount" name="Gross" stroke="#58a6ff" fill="#58a6ff" fillOpacity={0.15} />
                  <Area type="monotone" dataKey="net_amount" name="Net" stroke="#3fb950" fill="#3fb950" fillOpacity={0.15} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                </AreaChart>
              </ResponsiveContainer>
            ) : <div className="chart-empty">{t("csvDash.noData")}</div>}
          </div>
        </div>
      </Section>

      <Section sectionKey="usageBreakdowns" title={`${t("csvDash.productBreakdown")} & ${t("csvDash.skuBreakdown")}`}>
        <div className="dashboard-charts">
          <div className="chart-card">
            <h4>{t("csvDash.productBreakdown")}</h4>
            {data.product_breakdown.length > 0 ? (
              <ResponsiveContainer width="100%" height={Math.max(120, data.product_breakdown.length * 40)}>
                <BarChart data={data.product_breakdown} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis type="number" tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
                  <YAxis dataKey="product" type="category" width={80} tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v: any, name?: string) => name?.includes("amount") ? `$${Number(v).toFixed(4)}` : v} />
                  <Bar dataKey="gross_amount" name="Gross" fill="#58a6ff" radius={[0, 4, 4, 0]} />
                  <Bar dataKey="net_amount" name="Net" fill="#3fb950" radius={[0, 4, 4, 0]} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                </BarChart>
              </ResponsiveContainer>
            ) : <div className="chart-empty">{t("csvDash.noData")}</div>}
          </div>
          <div className="chart-card">
            <h4>{t("csvDash.skuBreakdown")}</h4>
            {data.sku_breakdown.length > 0 ? (
              <ResponsiveContainer width="100%" height={Math.max(160, data.sku_breakdown.length * 40)}>
                <BarChart data={data.sku_breakdown} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis type="number" tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
                  <YAxis dataKey="sku" type="category" width={180} tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v: any, name?: string) => name?.includes("amount") ? `$${Number(v).toFixed(4)}` : v} />
                  <Bar dataKey="gross_amount" name="Gross" fill="#d29922" radius={[0, 4, 4, 0]} />
                  <Bar dataKey="net_amount" name="Net" fill="#bc8cff" radius={[0, 4, 4, 0]} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                </BarChart>
              </ResponsiveContainer>
            ) : <div className="chart-empty">{t("csvDash.noData")}</div>}
          </div>
          <div className="chart-card">
            <h4>{t("csvDash.orgBreakdown")}</h4>
            {data.org_breakdown.length > 0 ? (
              <ResponsiveContainer width="100%" height={Math.max(160, data.org_breakdown.length * 36)}>
                <BarChart data={data.org_breakdown} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis type="number" tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
                  <YAxis dataKey="org" type="category" width={120} tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v: any, name?: string) => name?.includes("amount") ? `$${Number(v).toFixed(4)}` : v} />
                  <Bar dataKey="gross_amount" name="Gross" fill="#58a6ff" radius={[0, 4, 4, 0]} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                </BarChart>
              </ResponsiveContainer>
            ) : <div className="chart-empty">{t("csvDash.noData")}</div>}
          </div>
          <div className="chart-card">
            <h4>{t("dashboard.costCenterBreakdown")}</h4>
            {data.cost_center_breakdown.length > 0 ? (
              <ResponsiveContainer width="100%" height={Math.max(160, data.cost_center_breakdown.length * 36)}>
                <BarChart data={data.cost_center_breakdown} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis type="number" tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
                  <YAxis dataKey="cost_center" type="category" width={140} tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v: any, name?: string) => name?.includes("amount") ? `$${Number(v).toFixed(4)}` : v} />
                  <Bar dataKey="gross_amount" name="Gross" fill="#bc8cff" radius={[0, 4, 4, 0]} />
                  <Bar dataKey="net_amount" name="Net" fill="#f778ba" radius={[0, 4, 4, 0]} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                </BarChart>
              </ResponsiveContainer>
            ) : <div className="chart-empty">{t("csvDash.noData")}</div>}
          </div>
        </div>
      </Section>

      <Section sectionKey="usageUsers" title={t("csvDash.userTable")}>
        <div className="dashboard-charts">
          <div className="chart-card chart-card-wide">
            {data.users.length > 0 ? (
              <div className="dashboard-table-wrap">
                <table className="dashboard-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>{t("csvDash.user")}</th>
                      <th>{t("csvDash.org")}</th>
                      <th>{t("csvDash.costCenter")}</th>
                      <th>{t("csvDash.grossAmount")}</th>
                      <th>{t("csvDash.netAmount")}</th>
                      <th>{t("csvDash.quantity")}</th>
                      <th>{t("csvDash.daysActive")}</th>
                      <th>{t("csvDash.skus")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.users.map((u, i) => (
                      <tr key={u.user}>
                        <td className="rank">{i + 1}</td>
                        <td className="user-name">{u.user}</td>
                        <td>{u.org}</td>
                        <td>{u.cost_center || "—"}</td>
                        <td>${u.gross_amount.toFixed(4)}</td>
                        <td>${u.net_amount.toFixed(4)}</td>
                        <td>{u.quantity.toFixed(4)}</td>
                        <td>{u.days_active}</td>
                        <td className="model-tags">
                          {u.skus.slice(0, 3).map((s) => (
                            <span key={s.sku} className="dash-badge dash-badge-muted">
                              {s.sku}: ${s.amount.toFixed(2)}
                            </span>
                          ))}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <div className="chart-empty">{t("csvDash.noData")}</div>}
          </div>
        </div>
      </Section>
    </>
  );
}

/* ---------- Main CSV Dashboard ---------- */
export function CsvDashboard({ refreshKey, tab }: Props) {
  const { t } = useI18n();
  const ui = useUIState();

  const orgs = ui.csvDashOrgs;
  const setOrgs = useCallback((v: string[]) => ui.patch({ csvDashOrgs: v }), [ui.patch]);
  const costCenters = ui.csvDashCostCenters;
  const setCostCenters = useCallback((v: string[]) => ui.patch({ csvDashCostCenters: v }), [ui.patch]);
  const products = ui.csvDashProducts;
  const setProducts = useCallback((v: string[]) => ui.patch({ csvDashProducts: v }), [ui.patch]);
  const skus = ui.csvDashSkus;
  const setSkus = useCallback((v: string[]) => ui.patch({ csvDashSkus: v }), [ui.patch]);
  const dateFrom = ui.csvDashDateFrom;
  const setDateFrom = useCallback((v: string) => ui.patch({ csvDashDateFrom: v }), [ui.patch]);
  const dateTo = ui.csvDashDateTo;
  const setDateTo = useCallback((v: string) => ui.patch({ csvDashDateTo: v }), [ui.patch]);

  const params = useMemo(() => ({
    orgs, costCenters, products, skus, dateFrom, dateTo,
  }), [orgs.join(","), costCenters.join(","), products.join(","), skus.join(","), dateFrom, dateTo]); // eslint-disable-line react-hooks/exhaustive-deps

  const { data, loading } = useCsvDashboard(params);

  const hasAnyData = data && (data.premium_csv?.has_data || data.usage_report?.has_data);

  const activeDateRange = useMemo(() => {
    if (!data) return null;
    const section = tab === "premium" ? data.premium_csv : data.usage_report;
    return section?.has_data ? section.date_range : null;
  }, [data, tab]);

  return (
    <div className="dashboard" key={`${refreshKey}-${tab}`}>
      {/* Left-aligned filters */}
      <div className="dashboard-filters">
        <div className="dashboard-filter-group">
          <label>{t("csvDash.filters")}:</label>
          {data && (
            <>
              <MultiSelect
                label={t("dashboard.allOrgs")}
                options={data.filters.orgs}
                selected={orgs}
                onChange={setOrgs}
              />
              <MultiSelect
                label={t("csvDash.allCostCenters")}
                options={data.filters.cost_centers}
                selected={costCenters}
                onChange={setCostCenters}
              />
              {tab === "usage" && (
                <>
                  <MultiSelect
                    label={t("csvDash.allProducts")}
                    options={data.filters.products}
                    selected={products}
                    onChange={setProducts}
                  />
                  <MultiSelect
                    label={t("csvDash.allSkus")}
                    options={data.filters.skus}
                    selected={skus}
                    onChange={setSkus}
                  />
                </>
              )}
            </>
          )}
        </div>
        <div className="dashboard-filter-group">
          <input
            type="date"
            className="dashboard-date-input"
            value={dateFrom || activeDateRange?.start || ""}
            onChange={(e) => setDateFrom(e.target.value)}
          />
          <span className="dashboard-date-sep">—</span>
          <input
            type="date"
            className="dashboard-date-input"
            value={dateTo || activeDateRange?.end || ""}
            onChange={(e) => setDateTo(e.target.value)}
          />
        </div>
      </div>

      {loading && !data && <div className="dashboard-loading">{t("loading")}</div>}
      {!loading && !hasAnyData && <div className="dashboard-empty">{t("csvDash.noData")}</div>}

      {data && (
        tab === "premium"
          ? <PremiumContent data={data.premium_csv} />
          : <UsageContent data={data.usage_report} />
      )}
    </div>
  );
}
