import { useEffect, useRef, useState, type ReactNode } from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useI18n } from "../contexts/I18nContext";
import { SortTh } from "./SortTh";
import { useSortableRows } from "../hooks/useSortableRows";
import type { OwnedCostCenter, OwnerDashboardData } from "../types";

interface Props {
  center: OwnedCostCenter;
  period: "all" | "current_month";
}

type ConsumptionMetric = "credits" | "aiCost" | "billed";

interface ConsumptionRow {
  label: string;
  credits: number;
  aiCost: number;
  billed?: number;
}

const BREAKDOWN_COLORS = ["#58a6ff", "#3fb950", "#39c5cf", "#d29922", "#f778ba", "#f85149"];

function ConsumptionChart({ title, rows, metrics }: {
  title: string;
  rows: ConsumptionRow[];
  metrics: { key: ConsumptionMetric; label: string; currency?: boolean }[];
}) {
  const { t, lang } = useI18n();
  const [selectedMetric, setSelectedMetric] = useState<ConsumptionMetric>("credits");
  const [chartWidth, setChartWidth] = useState(0);
  const metric = metrics.find((option) => option.key === selectedMetric) ?? metrics[0];
  if (!metric) return null;

  const ranked = rows
    .map((row, index) => ({ ...row, value: row[metric.key] ?? 0, color: BREAKDOWN_COLORS[index % BREAKDOWN_COLORS.length] }))
    .filter((row) => Number.isFinite(row.value) && row.value !== 0)
    .sort((first, second) => second.value - first.value || first.label.localeCompare(second.label));
  const chartRows = ranked.slice(0, 10);
  const height = Math.max(180, chartRows.length * 32 + 36);
  const formatValue = (value: number) => metric.currency
    ? new Intl.NumberFormat(lang, { style: "currency", currency: "USD" }).format(value)
    : value.toLocaleString(lang, { maximumFractionDigits: 2 });

  return (
    <div className="cc-owner-breakdown" role="group" aria-label={title}>
      <div className="cc-owner-breakdown-controls">
        <div className="view-toggle" role="group" aria-label={title}>
          {metrics.map((option) => <button
            key={option.key}
            type="button"
            className={`btn btn-small btn-toggle ${metric.key === option.key ? "btn-toggle-active" : ""}`}
            aria-pressed={metric.key === option.key}
            onClick={() => setSelectedMetric(option.key)}
          >{option.label}</button>)}
        </div>
        {ranked.length > 10 && <span className="dash-badge dash-badge-muted">{t("ccOwner.chartTopTen")} · 10 / {ranked.length}</span>}
      </div>
      {chartRows.length ? <div className="cc-owner-ranking-chart" style={{ height }}>
        <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 300, height }} onResize={(width) => setChartWidth(width)}>
          <BarChart data={chartRows} layout="vertical" margin={{ top: 8, right: 16, bottom: 0, left: 0 }} accessibilityLayer>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={false} />
            <XAxis
              type="number"
              domain={[(minimum: number) => Math.min(0, minimum), (maximum: number) => Math.max(0, maximum)]}
              tick={{ fontSize: 11, fill: "var(--text-muted)" }}
              tickFormatter={(value: number) => `${metric.currency ? "$" : ""}${value.toLocaleString(lang, { notation: "compact", maximumFractionDigits: 1 })}`}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              dataKey="label"
              type="category"
              width={128}
              interval={0}
              tick={{ fontSize: 11, fill: "var(--text-secondary)" }}
              tickFormatter={(value: string) => value.length > 19 ? `${value.slice(0, 17)}...` : value}
              axisLine={false}
              tickLine={false}
            />
            <ReferenceLine x={0} stroke="var(--border)" />
            <Tooltip
              cursor={{ fill: "var(--bg-tertiary)", opacity: 0.5 }}
              position={chartWidth > 0 && chartWidth < 400 ? { x: 0 } : undefined}
              wrapperStyle={{ maxWidth: "calc(100% - 16px)" }}
              contentStyle={{ background: "var(--bg-secondary)", borderColor: "var(--border)", borderRadius: 6, color: "var(--text-primary)", fontSize: 12, maxWidth: 240, whiteSpace: "normal", overflowWrap: "anywhere" }}
              itemStyle={{ color: "var(--text-primary)", whiteSpace: "normal" }}
              formatter={(value) => formatValue(Number(value))}
            />
            <Bar dataKey="value" name={metric.label} maxBarSize={18} radius={[0, 4, 4, 0]} isAnimationActive={false}>
              {chartRows.map((row) => <Cell key={row.label} fill={row.color} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div> : <div className="cc-owner-chart-empty">{t("ccOwner.chartEmpty")}</div>}
    </div>
  );
}

function OwnerSection({ title, extra, children }: { title: string; extra?: ReactNode; children: ReactNode }) {
  return (
    <details className="dash-section cc-owner-section" open>
      <summary className="dash-section-header">
        <span className="dash-section-chevron" aria-hidden="true">&#9660;</span>
        <h3 className="dash-section-title">{title}</h3>
        {extra && <span className="dash-section-extra">{extra}</span>}
      </summary>
      <div className="dash-section-body">{children}</div>
    </details>
  );
}

export function OwnerCostCenterDashboard({ center, period }: Props) {
  const { t } = useI18n();
  const [data, setData] = useState<OwnerDashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [tab, setTab] = useState<"usage" | "settings">("usage");
  const [editingUser, setEditingUser] = useState<string | null>(null);
  const [budgetAmount, setBudgetAmount] = useState("");
  const [hardLimit, setHardLimit] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [saved, setSaved] = useState(false);
  const budgetTriggerRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (editingUser === null) return;
    return () => { budgetTriggerRef.current?.focus(); };
  }, [editingUser]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    const params = new URLSearchParams({ enterprise: center.enterprise, cost_center_id: center.id, period });
    fetch(`/api/me/owned-cost-center?${params}`, { signal: controller.signal })
      .then(async (response) => {
        const result = await response.json();
        if (!response.ok) throw new Error(response.status === 403 ? t("ccOwner.accessDenied") : result.detail || t("ccOwner.loadFailed"));
        setData(result);
        setError("");
      })
      .catch((failure) => {
        if (!controller.signal.aborted) {
          setData(null);
          setError(String(failure));
        }
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [center.enterprise, center.id, period, refresh, t]);

  const members = new Map((data?.cost_center.members ?? []).map((member) => [member.login.toLowerCase(), member]));
  const aiUsers = new Map((data?.ai_usage.users ?? []).map((user) => [user.user.toLowerCase(), user]));
  const spendUsers = new Map((data?.usage.users ?? []).map((user) => [user.user.toLowerCase(), user]));
  const userRows = [...new Set([...members.keys(), ...aiUsers.keys(), ...spendUsers.keys()])].map((login) => ({
    login,
    avatar: members.get(login)?.avatar_url,
    credits: aiUsers.get(login)?.requests ?? 0,
    aiCost: aiUsers.get(login)?.gross_amount ?? 0,
    billed: spendUsers.get(login)?.net_amount ?? 0,
    source: members.get(login)?.source_name ?? "",
  }));
  const sorter = useSortableRows(userRows);

  const budgetMessages = {
    cap_admin_only: "ccOwner.capAdminOnly",
    cap_off: "ccOwner.capOffReadOnly",
    cap_unknown: "ccOwner.capUnknownReadOnly",
    budgets_unavailable: "ccOwner.budgetsUnavailable",
    budget_member_only: "ccOwner.budgetMemberOnly",
    budget_member_unverified: "ccOwner.budgetMemberUnverified",
    budget_ambiguous: "ccOwner.budgetAmbiguous",
    budget_write_failed: "ccOwner.budgetWriteFailed",
  } as const;
  const budgetReason = data?.budget_read_only_reason;
  const canEditBudgets = data?.cap_verified === true && data.cost_center.ai_credit_pool_enabled === true && data.budget_status === "live" && !budgetReason;
  const editingEntry = data?.user_budgets?.find((entry) => entry.login === editingUser);
  const canSaveBudget = canEditBudgets && editingEntry?.can_edit === true && !loading;

  const saveBudget = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!editingUser || !canSaveBudget || saving) return;
    const amount = Number(budgetAmount);
    if (!Number.isFinite(amount) || amount <= 0 || Math.abs(amount * 100 - Math.round(amount * 100)) > 0.000001) {
      setSaveError(t("budgetReq.invalidAmount"));
      return;
    }
    setSaving(true);
    setSaveError("");
    setSaved(false);
    try {
      const response = await fetch("/api/me/owned-cost-center/user-budget", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enterprise: center.enterprise, cost_center_id: center.id, login: editingUser, amount, prevent_further_usage: hardLimit }),
      });
      const result = await response.json();
      if (!response.ok) {
        const code = result.detail?.code as keyof typeof budgetMessages | undefined;
        throw new Error(code && code in budgetMessages ? t(budgetMessages[code]) : t(response.status === 403 ? "ccOwner.accessDenied" : "ccOwner.budgetWriteFailed"));
      }
      setEditingUser(null);
      setSaved(true);
      setRefresh((value) => value + 1);
    } catch (failure) {
      setSaveError(failure instanceof Error ? failure.message : t("ccOwner.budgetWriteFailed"));
      setRefresh((value) => value + 1);
    } finally {
      setSaving(false);
    }
  };

  if (!data) return (
    <div className="dashboard-empty">
      {loading ? t("loading") : <><p role="alert">{error}</p><button className="btn btn-small" onClick={() => setRefresh((value) => value + 1)}>{t("ccOwner.refresh")}</button></>}
    </div>
  );

  const pool = data.cost_center.ai_credit_pool_state;
  const consumed = pool?.current_amount;
  const allowance = pool?.target_amount;
  const remaining = consumed != null && allowance != null ? Math.max(0, allowance - consumed) : null;
  const capEnabled = data.cost_center.ai_credit_pool_enabled;
  const money = (value: number | null | undefined) => value == null ? t("ccOwner.unknown") : `$${value.toFixed(2)}`;
  const number = (value: number | null | undefined) => value == null ? t("ccOwner.unknown") : value.toLocaleString();

  return (
    <div className="csv-dashboard cc-owner-dashboard">
      <div className="csv-filters cc-owner-toolbar">
        <div className="cc-owner-heading"><h2>{center.name}</h2><span className="cc-user-muted">{center.enterprise} · {t("ccOwner.owner")}</span></div>
        <div className="cc-owner-toolbar-actions">
          <div className="view-toggle">
            <button className={`btn btn-small btn-toggle ${tab === "usage" ? "btn-toggle-active" : ""}`} onClick={() => setTab("usage")}>{t("ccOwner.usage")}</button>
            <button className={`btn btn-small btn-toggle ${tab === "settings" ? "btn-toggle-active" : ""}`} onClick={() => setTab("settings")}>{t("settings.title")}</button>
          </div>
          <button className="btn btn-small" disabled={loading} onClick={() => setRefresh((value) => value + 1)}>{loading ? t("loading") : t("ccOwner.refresh")}</button>
        </div>
      </div>
      <OwnerSection title={t("ccOwner.currentCredits")} extra={
        <span className={`dash-badge ${data.credit_status === "live" ? "dash-badge-success" : "dash-badge-muted"}`} title={data.credit_checked_at ? new Date(data.credit_checked_at).toLocaleString() : undefined}>
          {t(data.credit_status === "live" ? "ccOwner.live" : "ccOwner.cached")}
        </span>
      }>
        <div className="cc-owner-cap">
          <label className="cc-owner-toggle">
            <span className="toggle-switch">
              <input type="checkbox" role="switch" aria-label={t("ccOwner.capLabel")} checked={capEnabled === true} disabled readOnly />
              <span className="toggle-slider" />
            </span>
            <strong>{t("ccOwner.capLabel")}: {typeof capEnabled === "boolean" ? t(capEnabled ? "ccOwner.enabled" : "ccOwner.disabled") : t("ccOwner.unknown")}</strong>
          </label>
          <span className="cc-owner-setting-description">{t("ccOwner.capAdminOnly")}</span>
        </div>
        {data.credit_status === "unavailable" && <p className="settings-error" role="status">{t("ccOwner.liveFailed")}</p>}
        <div className="dashboard-kpi cc-owner-credit-kpi">
          <div className="stat-card"><div className="stat-value">{number(consumed)}</div><div className="stat-label">{t("ccOwner.consumed")}</div></div>
          <div className="stat-card"><div className="stat-value">{number(allowance)}</div><div className="stat-label">{t("ccOwner.allowance")}</div></div>
          <div className="stat-card"><div className={`stat-value ${remaining === 0 ? "warning" : "success"}`}>{number(remaining)}</div><div className="stat-label">{t("ccOwner.remaining")}</div></div>
        </div>
        {consumed != null && allowance != null && allowance > 0 && <div className="me-quota-bar" role="progressbar" aria-label={t("ccOwner.consumed")} aria-valuemin={0} aria-valuemax={allowance} aria-valuenow={Math.min(allowance, Math.max(0, consumed))} aria-valuetext={`${number(consumed)} / ${number(allowance)}`}>
          <div className="me-quota-fill" style={{ width: `${Math.min(100, Math.max(0, consumed / allowance * 100))}%`, background: consumed >= allowance ? "var(--warning, #d29922)" : "var(--accent)" }} />
        </div>}
      </OwnerSection>
      {tab === "usage" ? (
        <>
          {data.ambiguous_billing_scope && <p className="settings-error" role="status">{t("ccOwner.ambiguous")}</p>}
          <OwnerSection title={t("ccOwner.billedUsage")} extra={
            (data.ai_usage.date_range || data.usage.date_range) && <span className="cc-user-muted">{data.ai_usage.date_range?.start || data.usage.date_range?.start} / {data.ai_usage.date_range?.end || data.usage.date_range?.end}</span>
          }>
            <div className="dashboard-kpi">
              <div className="stat-card"><div className="stat-value">{number(data.ai_usage.kpi?.total_requests)}</div><div className="stat-label">{t("ccOwner.credits")}</div></div>
              <div className="stat-card cost"><div className="stat-value cost">{money(data.ai_usage.kpi?.total_cost)}</div><div className="stat-label">{t("ccOwner.aiCost")}</div></div>
              <div className="stat-card cost"><div className="stat-value cost">{money(data.usage.kpi?.total_net)}</div><div className="stat-label">{t("ccOwner.billedCost")}</div></div>
              <div className="stat-card"><div className="stat-value">{data.cost_center.member_count}</div><div className="stat-label">{t("ccDash.colMembers")}</div></div>
            </div>
            {!data.ai_usage.has_data && !data.usage.has_data && <div className="dashboard-empty">{t("ccOwner.noUsage")}</div>}
            {!!data.ai_usage.daily_trend?.length && <div className="cc-owner-chart">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={data.ai_usage.daily_trend}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="day" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip contentStyle={{ background: "var(--bg-secondary)", borderColor: "var(--border)", color: "var(--text-primary)" }} />
                  <Area dataKey="requests" name={t("ccOwner.credits")} stroke="var(--accent)" fill="var(--accent)" fillOpacity={0.15} />
                </AreaChart>
              </ResponsiveContainer>
            </div>}
          </OwnerSection>
          {!!data.ai_usage.model_breakdown?.length && <OwnerSection title={t("ccOwner.models")}>
            <ConsumptionChart
              title={t("ccOwner.models")}
              rows={data.ai_usage.model_breakdown.map((model) => ({ label: model.model, credits: model.requests, aiCost: model.amount }))}
              metrics={[{ key: "credits", label: t("ccOwner.credits") }, { key: "aiCost", label: t("ccOwner.aiCost"), currency: true }]}
            />
            <div className="cc-table-wrap"><table className="cc-table"><thead><tr><th className="cc-th">{t("ccOwner.model")}</th><th className="cc-th cc-th-num">{t("ccOwner.credits")}</th><th className="cc-th cc-th-num">{t("ccOwner.aiCost")}</th></tr></thead>
              <tbody>{data.ai_usage.model_breakdown.map((model) => <tr key={model.model} className="cc-table-row"><td className="cc-td">{model.model}</td><td className="cc-td cc-td-num">{number(model.requests)}</td><td className="cc-td cc-td-num">{money(model.amount)}</td></tr>)}</tbody>
            </table></div>
          </OwnerSection>}
          <OwnerSection title={t("ccOwner.members")}>
            <ConsumptionChart
              title={t("ccOwner.members")}
              rows={userRows.map((user) => ({ ...user, label: user.login }))}
              metrics={[
                ...(data.ai_usage.has_data ? [{ key: "credits" as const, label: t("ccOwner.credits") }, { key: "aiCost" as const, label: t("ccOwner.aiCost"), currency: true }] : []),
                ...(data.usage.has_data ? [{ key: "billed" as const, label: t("ccOwner.billedCost"), currency: true }] : []),
              ]}
            />
            <div className="cc-table-wrap"><table className="cc-table"><thead><tr>
              <SortTh label={t("ccDash.colUser")} sortKey="login" sorter={sorter} className="cc-th" />
              <SortTh label={t("ccOwner.credits")} sortKey="credits" sorter={sorter} className="cc-th cc-th-num" />
              <SortTh label={t("ccOwner.aiCost")} sortKey="aiCost" sorter={sorter} className="cc-th cc-th-num" />
              <SortTh label={t("ccOwner.billedCost")} sortKey="billed" sorter={sorter} className="cc-th cc-th-num" />
            </tr></thead><tbody>{sorter.rows.map((user) => <tr key={user.login} className="cc-table-row">
              <td className="cc-td"><div className="cc-member-info">{user.avatar && <img src={user.avatar} alt="" className="cc-member-avatar" />}<span>{user.login}</span></div></td>
              <td className="cc-td cc-td-num">{data.ai_usage.has_data ? number(user.credits) : t("ccOwner.unknown")}</td>
              <td className="cc-td cc-td-num">{data.ai_usage.has_data ? money(user.aiCost) : t("ccOwner.unknown")}</td>
              <td className="cc-td cc-td-num">{data.usage.has_data ? money(user.billed) : t("ccOwner.unknown")}</td>
            </tr>)}</tbody></table></div>
          </OwnerSection>
        </>
      ) : (
        <>
        <OwnerSection title={t("ccOwner.individualBudgets")}>
          <p className="cc-owner-setting-description">{t("budgetReq.budgetCycleHint")}</p>
          {budgetReason && <p className="cc-owner-budget-notice" role="status">{t(budgetMessages[budgetReason])}</p>}
          {data.budget_status !== "live" && budgetReason !== "budgets_unavailable" && <p className="cc-owner-budget-notice" role="status">{t("ccOwner.budgetsUnavailable")}</p>}
          {saved && <p className="budget-req-success" role="status">{t("ccOwner.budgetSaved")}</p>}
          <div className="cc-table-wrap"><table className="cc-table cc-owner-budget-table">
            <thead><tr>
              <th className="cc-th">{t("ccDash.colUser")}</th>
              <th className="cc-th cc-th-num">{t("budgetsDash.colAmount")} (USD)</th>
              <th className="cc-th cc-th-num">{t("budgetsDash.colConsumed")} (USD)</th>
              <th className="cc-th cc-th-num">{t("budgetsDash.colRemaining")} (USD)</th>
              <th className="cc-th">{t("budgetsDash.colHardLimit")}</th>
              <th className="cc-th">{t("ccOwner.editBudget")}</th>
            </tr></thead>
            <tbody>{(data.user_budgets ?? []).map((entry) => <tr key={entry.login} className="cc-table-row">
              <td className="cc-td"><div className="cc-member-info">{members.get(entry.login.toLowerCase())?.avatar_url && <img className="cc-member-avatar" src={members.get(entry.login.toLowerCase())?.avatar_url} alt="" />}<strong>{entry.login}</strong></div></td>
              <td className="cc-td cc-td-num">{entry.budgets.length ? entry.budgets.map((budget) => <div key={budget.id}>{money(budget.amount)}</div>) : t(data.budget_status === "live" ? "ccOwner.noBudget" : "ccOwner.unknown")}</td>
              <td className="cc-td cc-td-num">{entry.budgets.length ? entry.budgets.map((budget) => <div key={budget.id}>{money(budget.consumed_amount)}</div>) : t("ccOwner.unknown")}</td>
              <td className="cc-td cc-td-num">{entry.budgets.length ? entry.budgets.map((budget) => <div key={budget.id}>{money(budget.remaining_amount)}</div>) : t("ccOwner.unknown")}</td>
              <td className="cc-td">{entry.budgets.map((budget) => <div key={budget.id}><span className={`dash-badge ${budget.prevent_further_usage ? "dash-badge-success" : "dash-badge-muted"}`}>{t(budget.prevent_further_usage ? "budgetsDash.hardLimit" : "budgetsDash.softLimit")}</span></div>)}</td>
              <td className="cc-td"><button className="btn btn-small" disabled={!canEditBudgets || !entry.can_edit || loading || saving} onClick={(event) => {
                budgetTriggerRef.current = event.currentTarget;
                setEditingUser(entry.login);
                setBudgetAmount(entry.budgets[0]?.amount.toString() ?? "");
                setHardLimit(entry.budgets[0]?.prevent_further_usage ?? true);
                setSaveError("");
                setSaved(false);
              }}>{t(entry.budgets.length ? "ccOwner.editBudget" : "ccOwner.setBudget")}</button>
              {entry.budgets.length > 1 && <p className="cc-user-muted">{t("ccOwner.budgetAmbiguous")}</p>}</td>
            </tr>)}</tbody>
          </table></div>
        </OwnerSection>
        <OwnerSection title={t("ccDash.colResources")}>
          <div className="cc-resource-tags">{data.cost_center.resources.map((resource) => <span className="cc-resource-tag" key={`${resource.type}:${resource.name}`}>{resource.type}: {resource.name}</span>)}</div>
        </OwnerSection>
        </>
      )}
      {editingUser !== null && <div className="settings-modal-overlay" onClick={(event) => { if (event.target === event.currentTarget && !saving) setEditingUser(null); }}>
        <div className="settings-modal cc-owner-budget-modal" role="dialog" aria-modal="true" aria-labelledby="cc-owner-confirm-title" aria-describedby="cc-owner-budget-hint" onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.stopPropagation();
            if (!saving) setEditingUser(null);
          }
          if (event.key === "Tab") {
            const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), [tabindex="0"]'));
            const first = controls[0];
            const last = controls[controls.length - 1];
            if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
            if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
          }
        }}>
          <div className="settings-modal-header">
            <h2 id="cc-owner-confirm-title">{t("ccOwner.budgetConfirmTitle")}</h2>
            <button type="button" className="settings-close-btn" aria-label={t("ccUnassigned.cancel")} disabled={saving} onClick={() => setEditingUser(null)}>&times;</button>
          </div>
          <form className="cc-owner-budget-form" onSubmit={saveBudget}>
            <div className="settings-modal-body">
              <div className="cc-owner-budget-identity">
                {members.get(editingUser.toLowerCase())?.avatar_url
                  ? <img className="cc-owner-budget-avatar" src={members.get(editingUser.toLowerCase())?.avatar_url} alt="" />
                  : <span className="cc-owner-budget-avatar" aria-hidden="true">{editingUser.slice(0, 2).toUpperCase()}</span>}
                <div><strong>{editingUser}</strong><span>{center.name} · {center.enterprise}</span></div>
              </div>
              <dl className="cc-owner-budget-summary">
                <div><dt>{t("budgetsDash.colAmount")}</dt><dd>{editingEntry?.budgets.length ? money(editingEntry.budgets[0].amount) : t("ccOwner.noBudget")}</dd></div>
                <div><dt>{t("budgetsDash.colConsumed")}</dt><dd>{money(editingEntry?.budgets[0]?.consumed_amount)}</dd></div>
              </dl>
              <label className="budget-req-field">
                <span>{t("budgetReq.amount")} (USD / {t("budgetReq.perMonth")})</span>
                <input type="number" min="0.01" step="0.01" required value={budgetAmount} disabled={saving || !canSaveBudget} onChange={(event) => setBudgetAmount(event.target.value)} autoFocus />
              </label>
              <label className="cc-owner-hard-limit">
                <input type="checkbox" checked={hardLimit} disabled={saving || !canSaveBudget} onChange={(event) => setHardLimit(event.target.checked)} />
                <span>{t("budgetReq.hardLimit")}</span>
              </label>
              <p className="pat-form-hint" id="cc-owner-budget-hint">{t("ccOwner.budgetConfirmHint")}</p>
              {budgetReason && <p className="cc-owner-budget-notice" role="status">{t(budgetMessages[budgetReason])}</p>}
              {saveError && <p className="settings-error" role="alert">{saveError}</p>}
            </div>
            <div className="cc-owner-budget-footer">
              <button type="button" className="btn" disabled={saving} onClick={() => setEditingUser(null)}>{t("ccUnassigned.cancel")}</button>
              <button type="submit" className="btn btn-primary" disabled={saving || !canSaveBudget}>{saving ? t("loading") : t("ccOwner.confirmSave")}</button>
            </div>
          </form>
        </div>
      </div>}
    </div>
  );
}