import { useEffect, useMemo, useState } from "react";
import { useI18n } from "../contexts/I18nContext";
import { useBudgetRequests, useMyCostCenters } from "../hooks/useMe";
import { statusBadgeClass } from "../utils/budgetRequests";
import type { BudgetRequest } from "../types";

/** Read-only view of a request's cost center move. */
export function CostCenterChangeCell({ request }: { request: BudgetRequest }) {
  const { t } = useI18n();
  const plan = request.cost_center_plan;
  if (!plan) return <>—</>;
  return (
    <div className="cc-change-cell">
      <span className="cc-change-leave">{plan.from?.name ?? t("budgetReq.ccUnassigned")}</span>
      <span className="cc-change-arrow">→</span>
      <span className="cc-change-join">{plan.to?.name ?? t("budgetReq.ccUnassigned")}</span>
    </div>
  );
}

export function RequestHistoryTable({ requests, showOwner = false }: { requests: BudgetRequest[]; showOwner?: boolean }) {
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
            <th className="cc-th">{t("budgetReq.colType")}</th>
            <th className="cc-th">{t("budgetReq.colDetails")}</th>
            <th className="cc-th">{t("budgetReq.colReason")}</th>
            <th className="cc-th">{t("budgetReq.colStatus")}</th>
            <th className="cc-th">{t("budgetReq.githubStatus")}</th>
            <th className="cc-th">{t("budgetReq.colReviewer")}</th>
          </tr>
        </thead>
        <tbody>
          {requests.map((r) => {
            const isCC = r.request_type === "cost_center";
            const sync = isCC ? r.cost_center_result : r.github_budget;
            const syncStatus = sync?.status;
            return (
              <tr key={r.id} className="cc-table-row">
                <td className="cc-td">{r.created_at.slice(0, 10)}</td>
                {showOwner && <td className="cc-td"><strong>{r.user_login}</strong></td>}
                <td className="cc-td">
                  <span className="dash-badge dash-badge-muted">
                    {t(isCC ? "budgetReq.typeCostCenter" : "budgetReq.typeBudget")}
                  </span>
                </td>
                <td className="cc-td">
                  {isCC ? (
                    <CostCenterChangeCell request={r} />
                  ) : (
                    <>
                      ${(r.requested_amount ?? 0).toLocaleString()}
                      {r.approved_amount != null && r.approved_amount !== r.requested_amount && (
                        <span className="cc-subtle"> → ${r.approved_amount.toLocaleString()}</span>
                      )}
                      <span className="cc-subtle"> / {t("budgetReq.perMonth")}</span>
                    </>
                  )}
                </td>
                <td className="cc-td" title={r.reason}>
                  {r.reason ? (r.reason.length > 40 ? `${r.reason.slice(0, 40)}…` : r.reason) : "—"}
                </td>
                <td className="cc-td">
                  <span className={statusBadgeClass(r.status)}>
                    {t(`budgetReq.status.${r.status}` as Parameters<typeof t>[0])}
                  </span>
                </td>
                <td className="cc-td">
                  {syncStatus ? (
                    <span
                      className={
                        syncStatus === "failed"
                          ? "dash-badge dash-badge-danger"
                          : syncStatus === "partial"
                            ? "dash-badge dash-badge-warning"
                            : syncStatus === "skipped"
                              ? "dash-badge dash-badge-muted"
                              : "dash-badge dash-badge-success"
                      }
                      title={sync?.error ?? undefined}
                    >
                      {t(`budgetReq.gh.${syncStatus}` as Parameters<typeof t>[0])}
                    </span>
                  ) : (
                    <span className="dash-badge dash-badge-muted">{t("budgetReq.gh.none")}</span>
                  )}
                </td>
                <td className="cc-td" title={r.review_comment}>{r.reviewed_by || "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** Request form + personal history for regular (non-admin) users. */
export function BudgetRequestPanel() {
  const { t } = useI18n();
  const { data, loading, create, remove } = useBudgetRequests();
  const { data: ccData, loading: ccLoading, refetch: refetchCC } = useMyCostCenters();

  const [type, setType] = useState<"budget" | "cost_center">("budget");
  const [amount, setAmount] = useState("");
  const [org, setOrg] = useState("");
  const [reason, setReason] = useState("");
  const [selected, setSelected] = useState<string>("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const costCenters = useMemo(() => ccData?.cost_centers ?? [], [ccData]);

  // GitHub allows one cost center per user, so this is a single choice
  const current = useMemo(() => costCenters.find((c) => c.is_direct) ?? null, [costCenters]);
  const inherited = useMemo(() => costCenters.filter((c) => c.locked), [costCenters]);
  const selectable = useMemo(() => costCenters.filter((c) => !c.locked), [costCenters]);

  // Preselect the cost center the user is currently assigned to
  useEffect(() => {
    setSelected(current?.id ?? "");
  }, [current]);

  const target = costCenters.find((c) => c.id === selected) ?? null;
  const ccDirty = (current?.id ?? "") !== selected;

  const resetCC = () => setSelected(current?.id ?? "");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setMessage("");

    if (type === "budget") {
      const value = parseFloat(amount);
      if (!Number.isFinite(value) || value <= 0) {
        setError(t("budgetReq.invalidAmount"));
        return;
      }
      setSubmitting(true);
      try {
        const res = await create({
          request_type: "budget",
          amount: value,
          org: org.trim(),
          reason: reason.trim(),
        });
        if (res.error) setError(res.error);
        else {
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
      return;
    }

    if (!ccDirty) {
      setError(t("budgetReq.ccNoChangeError"));
      return;
    }
    setSubmitting(true);
    try {
      const res = await create({
        request_type: "cost_center",
        cost_center_id: selected,
        reason: reason.trim(),
      });
      if (res.error) setError(res.error);
      else {
        setMessage(t("budgetReq.submitted"));
        setReason("");
        await refetchCC();
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
          <div className="view-toggle" style={{ marginBottom: 12 }}>
            <button
              className={`btn btn-small btn-toggle ${type === "budget" ? "btn-toggle-active" : ""}`}
              onClick={() => { setType("budget"); setError(""); }}
            >
              {t("budgetReq.typeBudget")}
            </button>
            <button
              className={`btn btn-small btn-toggle ${type === "cost_center" ? "btn-toggle-active" : ""}`}
              onClick={() => { setType("cost_center"); setError(""); }}
            >
              {t("budgetReq.typeCostCenter")}
            </button>
          </div>

          <form className="budget-req-form" onSubmit={handleSubmit}>
            {type === "budget" ? (
              <>
                <div className="budget-req-row">
                  <label className="budget-req-field">
                    <span>{t("budgetReq.amount")} (USD / {t("budgetReq.perMonth")})</span>
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
                    <span>{t("budgetReq.org")}</span>
                    <input value={org} onChange={(e) => setOrg(e.target.value)} placeholder={t("budgetReq.optional")} />
                  </label>
                </div>
                <p className="pat-form-hint">{t("budgetReq.budgetCycleHint")}</p>
              </>
            ) : (
              <div className="cc-picker">
                <div className="cc-picker-header">
                  <span>{t("budgetReq.ccPickerTitle")}</span>
                  {ccDirty && (
                    <button type="button" className="btn btn-small btn-ghost" onClick={resetCC}>
                      {t("budgetReq.ccReset")}
                    </button>
                  )}
                </div>
                {ccLoading && !ccData ? (
                  <div className="dashboard-loading">{t("loading")}</div>
                ) : selectable.length === 0 ? (
                  <div className="dashboard-empty">{t("budgetReq.ccNone")}</div>
                ) : (
                  <>
                    <div className="budget-req-row">
                      <label className="budget-req-field">
                        <span>{t("budgetReq.ccCurrent")}</span>
                        <input value={current?.name ?? t("budgetReq.ccUnassigned")} readOnly disabled />
                      </label>
                      <label className="budget-req-field">
                        <span>{t("budgetReq.ccTarget")}</span>
                        <select
                          className="cc-native-select"
                          value={selected}
                          onChange={(e) => setSelected(e.target.value)}
                        >
                          <option value="">{t("budgetReq.ccUnassigned")}</option>
                          {selectable.map((c) => (
                            <option key={`${c.enterprise}-${c.id}`} value={c.id}>
                              {c.name}
                              {c.enterprise_name ? ` (${c.enterprise_name})` : ""}
                              {c.is_direct ? ` — ${t("budgetReq.ccCurrentTag")}` : ""}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>
                    <p className="pat-form-hint">{t("budgetReq.ccSingleHint")}</p>
                    {inherited.length > 0 && (
                      <p className="pat-form-hint">
                        {t("budgetReq.ccInherited")}:{" "}
                        {inherited.map((c) => `${c.name}${c.source_name ? ` (${c.source_name})` : ""}`).join(", ")}
                        {" — "}
                        {t("budgetReq.ccInheritedHint")}
                      </p>
                    )}
                    {ccDirty && (
                      <div className="cc-change-preview">
                        <div className="cc-change-cell">
                          <span className="cc-change-leave">{current?.name ?? t("budgetReq.ccUnassigned")}</span>
                          <span className="cc-change-arrow">→</span>
                          <span className="cc-change-join">{target?.name ?? t("budgetReq.ccUnassigned")}</span>
                        </div>
                      </div>
                    )}
                  </>
                )}
              </div>
            )}

            <label className="budget-req-field budget-req-field-wide">
              <span>{t("budgetReq.colReason")}</span>
              <textarea
                rows={3}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder={
                  type === "budget" ? t("budgetReq.reasonPlaceholder") : t("budgetReq.ccReasonPlaceholder")
                }
              />
            </label>

            {error && <div className="login-error">{error}</div>}
            {message && <div className="budget-req-success">{message}</div>}

            <button
              type="submit"
              className="btn btn-primary"
              disabled={submitting || (type === "cost_center" && !ccDirty)}
            >
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
              <RequestHistoryTable requests={requests} />
              {requests.some((r) => r.status === "pending") && (
                <div className="budget-req-withdraw-row">
                  {requests
                    .filter((r) => r.status === "pending")
                    .map((r) => (
                      <button
                        key={r.id}
                        className="btn btn-small btn-ghost"
                        onClick={() => remove(r.id)}
                      >
                        {t("budgetReq.withdraw")}{" "}
                        {r.request_type === "cost_center"
                          ? t("budgetReq.typeCostCenter")
                          : `$${r.requested_amount}`}
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
