import { useState } from "react";
import { useI18n } from "../contexts/I18nContext";
import { useBudgetRequests } from "../hooks/useMe";
import { statusBadgeClass } from "../utils/budgetRequests";
import type { BudgetRequest } from "../types";

const PERIODS = ["monthly", "quarterly", "yearly", "one_time"] as const;

export function BudgetRequestHistory({ requests, showOwner = false }: { requests: BudgetRequest[]; showOwner?: boolean }) {
  const { t } = useI18n();

  if (!requests.length) {
    return <div className="dashboard-empty">{t("budgetReq.empty")}</div>;
  }

  return (
    <div className="cc-table-wrap">
      <table className="cc-table">
        <thead>
          <tr>
            <th className="cc-th">{t("budgetReq.colDate")}</th>
            {showOwner && <th className="cc-th">{t("budgetReq.colUser")}</th>}
            <th className="cc-th cc-th-num">{t("budgetReq.colRequested")}</th>
            <th className="cc-th cc-th-num">{t("budgetReq.colApproved")}</th>
            <th className="cc-th">{t("budgetReq.colPeriod")}</th>
            <th className="cc-th">{t("budgetReq.colScopeInfo")}</th>
            <th className="cc-th">{t("budgetReq.colReason")}</th>
            <th className="cc-th">{t("budgetReq.colStatus")}</th>
            <th className="cc-th">{t("budgetReq.githubStatus")}</th>
            <th className="cc-th">{t("budgetReq.colReviewer")}</th>
          </tr>
        </thead>
        <tbody>
          {requests.map((r) => (
            <tr key={r.id} className="cc-table-row">
              <td className="cc-td">{r.created_at.slice(0, 10)}</td>
              {showOwner && <td className="cc-td"><strong>{r.user_login}</strong></td>}
              <td className="cc-td cc-td-num">${r.requested_amount.toLocaleString()}</td>
              <td className="cc-td cc-td-num">
                {r.approved_amount != null ? `$${r.approved_amount.toLocaleString()}` : "—"}
              </td>
              <td className="cc-td">{t(`budgetReq.period.${r.period}` as Parameters<typeof t>[0])}</td>
              <td className="cc-td">{[r.org, r.cost_center].filter(Boolean).join(" / ") || "—"}</td>
              <td className="cc-td" title={r.reason}>
                {r.reason ? (r.reason.length > 60 ? `${r.reason.slice(0, 60)}…` : r.reason) : "—"}
              </td>
              <td className="cc-td">
                <span className={statusBadgeClass(r.status)}>
                  {t(`budgetReq.status.${r.status}` as Parameters<typeof t>[0])}
                </span>
              </td>
              <td className="cc-td">
                {r.github_budget ? (
                  <span
                    className={
                      r.github_budget.status === "failed"
                        ? "dash-badge dash-badge-danger"
                        : r.github_budget.status === "skipped"
                          ? "dash-badge dash-badge-muted"
                          : "dash-badge dash-badge-success"
                    }
                    title={r.github_budget.error}
                  >
                    {t(`budgetReq.gh.${r.github_budget.status}` as Parameters<typeof t>[0])}
                  </span>
                ) : (
                  <span className="dash-badge dash-badge-muted">{t("budgetReq.gh.none")}</span>
                )}
              </td>
              <td className="cc-td" title={r.review_comment}>
                {r.reviewed_by || "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Budget request form + personal history for regular (non-admin) users. */
export function BudgetRequestPanel() {
  const { t } = useI18n();
  const { data, loading, create, remove } = useBudgetRequests();
  const [amount, setAmount] = useState("");
  const [period, setPeriod] = useState<string>("monthly");
  const [org, setOrg] = useState("");
  const [costCenter, setCostCenter] = useState("");
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setMessage("");
    const value = parseFloat(amount);
    if (!Number.isFinite(value) || value <= 0) {
      setError(t("budgetReq.invalidAmount"));
      return;
    }
    setSubmitting(true);
    try {
      const res = await create({
        amount: value,
        period,
        org: org.trim(),
        cost_center: costCenter.trim(),
        reason: reason.trim(),
      });
      if (res.error) {
        setError(res.error);
      } else {
        setMessage(t("budgetReq.submitted"));
        setAmount("");
        setReason("");
        setTimeout(() => setMessage(""), 6000);
      }
    } catch {
      setError("Network error");
    } finally {
      setSubmitting(false);
    }
  };

  const requests = data?.requests ?? [];
  const summary = data?.summary;

  return (
    <div className="csv-dashboard">
      <div className="dash-section">
        <div className="dash-section-header">
          <span className="dash-section-chevron">▼</span>
          <h3 className="dash-section-title">{t("budgetReq.newTitle")}</h3>
        </div>
        <div className="dash-section-body">
          <form className="budget-req-form" onSubmit={handleSubmit}>
            <div className="budget-req-row">
              <label className="budget-req-field">
                <span>{t("budgetReq.amount")} (USD)</span>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  placeholder="100"
                />
              </label>
              <label className="budget-req-field">
                <span>{t("budgetReq.colPeriod")}</span>
                <select className="cc-native-select" value={period} onChange={(e) => setPeriod(e.target.value)}>
                  {PERIODS.map((p) => (
                    <option key={p} value={p}>
                      {t(`budgetReq.period.${p}` as Parameters<typeof t>[0])}
                    </option>
                  ))}
                </select>
              </label>
              <label className="budget-req-field">
                <span>{t("budgetReq.org")}</span>
                <input value={org} onChange={(e) => setOrg(e.target.value)} placeholder={t("budgetReq.optional")} />
              </label>
              <label className="budget-req-field">
                <span>{t("budgetReq.costCenter")}</span>
                <input
                  value={costCenter}
                  onChange={(e) => setCostCenter(e.target.value)}
                  placeholder={t("budgetReq.optional")}
                />
              </label>
            </div>
            <label className="budget-req-field budget-req-field-wide">
              <span>{t("budgetReq.colReason")}</span>
              <textarea
                rows={3}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder={t("budgetReq.reasonPlaceholder")}
              />
            </label>
            {error && <div className="login-error">{error}</div>}
            {message && <div className="budget-req-success">{message}</div>}
            <button type="submit" className="btn btn-primary" disabled={submitting}>
              {submitting ? "..." : t("budgetReq.submit")}
            </button>
          </form>
        </div>
      </div>

      {summary && (
        <div className="dashboard-kpi">
          <div className="stat-card">
            <div className="stat-value">{summary.total}</div>
            <div className="stat-label">{t("budgetReq.kpiTotal")}</div>
          </div>
          <div className="stat-card warning">
            <div className="stat-value warning">{summary.pending}</div>
            <div className="stat-label">{t("budgetReq.kpiPending")}</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{summary.approved}</div>
            <div className="stat-label">{t("budgetReq.kpiApproved")}</div>
          </div>
          <div className="stat-card cost">
            <div className="stat-value cost">${summary.approved_amount.toLocaleString()}</div>
            <div className="stat-label">{t("budgetReq.kpiApprovedAmount")}</div>
          </div>
        </div>
      )}

      <div className="dash-section">
        <div className="dash-section-header">
          <span className="dash-section-chevron">▼</span>
          <h3 className="dash-section-title">{t("budgetReq.historyTitle")}</h3>
        </div>
        <div className="dash-section-body">
          {loading && !data ? (
            <div className="dashboard-loading">{t("loading")}</div>
          ) : (
            <>
              <BudgetRequestHistory requests={requests} />
              {requests.some((r) => r.status === "pending") && (
                <div className="budget-req-withdraw-row">
                  {requests
                    .filter((r) => r.status === "pending")
                    .map((r) => (
                      <button
                        key={r.id}
                        className="btn btn-small btn-ghost"
                        onClick={() => remove(r.id)}
                        title={`${r.created_at.slice(0, 10)} · $${r.requested_amount}`}
                      >
                        {t("budgetReq.withdraw")} ${r.requested_amount}
                      </button>
                    ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
