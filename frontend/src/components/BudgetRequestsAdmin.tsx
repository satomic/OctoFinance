import { useState } from "react";
import { useI18n } from "../contexts/I18nContext";
import { useBudgetAudit, useBudgetRequests } from "../hooks/useMe";
import { statusBadgeClass } from "../utils/budgetRequests";
import type { BudgetRequest, GithubBudgetSync } from "../types";

interface Props {
  refreshKey?: number;
}

const STATUS_FILTERS = ["all", "pending", "approved", "rejected"] as const;

const GH_BADGE: Record<string, string> = {
  created: "dash-badge dash-badge-success",
  updated: "dash-badge dash-badge-success",
  failed: "dash-badge dash-badge-danger",
  skipped: "dash-badge dash-badge-muted",
};

/** Shows whether the approved amount actually reached GitHub. */
function GithubBudgetBadge({ sync }: { sync?: GithubBudgetSync | null }) {
  const { t } = useI18n();
  if (!sync) {
    return <span className="dash-badge dash-badge-muted">{t("budgetReq.gh.none")}</span>;
  }
  const label = t(`budgetReq.gh.${sync.status}` as Parameters<typeof t>[0]);
  const title = [
    sync.error,
    sync.budget_id ? `budget_id: ${sync.budget_id}` : "",
    sync.entity_name ? `${sync.entity_type}: ${sync.entity_name}` : "",
    sync.synced_at ? sync.synced_at.slice(0, 19).replace("T", " ") : "",
  ]
    .filter(Boolean)
    .join("\n");
  return (
    <span className={GH_BADGE[sync.status] ?? "dash-badge dash-badge-muted"} title={title}>
      {label}
    </span>
  );
}

function ReviewTable() {
  const { t } = useI18n();
  const [statusFilter, setStatusFilter] = useState<string>("pending");
  const { data, loading, review, updateAmount, resync, remove } = useBudgetRequests(statusFilter);
  const [editing, setEditing] = useState<Record<string, string>>({});
  const [comments, setComments] = useState<Record<string, string>>({});
  const [applyToGithub, setApplyToGithub] = useState(true);
  const [hardLimit, setHardLimit] = useState(true);
  const [busy, setBusy] = useState<string>("");
  const [warning, setWarning] = useState<string>("");

  const amountFor = (r: BudgetRequest) =>
    editing[r.id] ?? String(r.approved_amount ?? r.requested_amount);

  const opts = { applyToGithub, preventFurtherUsage: hardLimit };

  const run = async (id: string, fn: () => Promise<{ warning?: string; error?: string }>) => {
    setBusy(id);
    setWarning("");
    const res = await fn();
    if (res?.warning || res?.error) setWarning(res.warning || res.error || "");
    setBusy("");
  };

  const handleApprove = (r: BudgetRequest) => {
    const value = parseFloat(amountFor(r));
    if (!Number.isFinite(value) || value < 0) return;
    return run(r.id, () => review(r.id, "approve", value, comments[r.id] ?? "", opts));
  };

  const requests = data?.requests ?? [];
  const summary = data?.summary;

  return (
    <>
      <div className="csv-filters">
        <div className="org-dropdown" style={{ minWidth: 160 }}>
          <select
            className="cc-native-select"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            {STATUS_FILTERS.map((s) => (
              <option key={s} value={s}>
                {s === "all"
                  ? t("budgetReq.filterAll")
                  : t(`budgetReq.status.${s}` as Parameters<typeof t>[0])}
              </option>
            ))}
          </select>
        </div>
        <label className="budget-req-inline-check">
          <input type="checkbox" checked={applyToGithub} onChange={(e) => setApplyToGithub(e.target.checked)} />
          <span>{t("budgetReq.applyToGithub")}</span>
        </label>
        <label className="budget-req-inline-check">
          <input type="checkbox" checked={hardLimit} onChange={(e) => setHardLimit(e.target.checked)} />
          <span>{t("budgetReq.hardLimit")}</span>
        </label>
      </div>

      {warning && <div className="login-error">{warning}</div>}

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
          <div className="stat-card warning">
            <div className="stat-value warning">${summary.pending_amount.toLocaleString()}</div>
            <div className="stat-label">{t("budgetReq.kpiPendingAmount")}</div>
          </div>
        </div>
      )}

      <div className="dash-section">
        <div className="dash-section-header">
          <span className="dash-section-chevron">▼</span>
          <h3 className="dash-section-title">{t("budgetReq.adminTitle")}</h3>
        </div>
        <div className="dash-section-body">
          {loading && !data ? (
            <div className="dashboard-loading">{t("loading")}</div>
          ) : requests.length === 0 ? (
            <div className="dashboard-empty">{t("budgetReq.emptyAdmin")}</div>
          ) : (
            <div className="cc-table-wrap">
              <table className="cc-table">
                <thead>
                  <tr>
                    <th className="cc-th">{t("budgetReq.colDate")}</th>
                    <th className="cc-th">{t("budgetReq.colUser")}</th>
                    <th className="cc-th cc-th-num">{t("budgetReq.colRequested")}</th>
                    <th className="cc-th">{t("budgetReq.colPeriod")}</th>
                    <th className="cc-th">{t("budgetReq.colReason")}</th>
                    <th className="cc-th">{t("budgetReq.colStatus")}</th>
                    <th className="cc-th">{t("budgetReq.githubStatus")}</th>
                    <th className="cc-th">{t("budgetReq.colDecision")}</th>
                  </tr>
                </thead>
                <tbody>
                  {requests.map((r) => (
                    <tr key={r.id} className="cc-table-row">
                      <td className="cc-td">{r.created_at.slice(0, 10)}</td>
                      <td className="cc-td">
                        <div className="budget-req-user">
                          {r.avatar_url && <img src={r.avatar_url} alt="" className="budget-req-avatar" />}
                          <strong>{r.user_login}</strong>
                        </div>
                      </td>
                      <td className="cc-td cc-td-num">${r.requested_amount.toLocaleString()}</td>
                      <td className="cc-td">
                        {t(`budgetReq.period.${r.period}` as Parameters<typeof t>[0])}
                      </td>
                      <td className="cc-td" title={r.reason}>
                        {r.reason ? (r.reason.length > 40 ? `${r.reason.slice(0, 40)}…` : r.reason) : "—"}
                      </td>
                      <td className="cc-td">
                        <span className={statusBadgeClass(r.status)}>
                          {t(`budgetReq.status.${r.status}` as Parameters<typeof t>[0])}
                        </span>
                        {r.reviewed_by && (
                          <div className="budget-req-reviewer" title={r.review_comment}>
                            {r.reviewed_by}
                            {r.approved_amount != null ? ` · $${r.approved_amount.toLocaleString()}` : ""}
                          </div>
                        )}
                      </td>
                      <td className="cc-td">
                        <GithubBudgetBadge sync={r.github_budget} />
                        {r.github_budget?.error && (
                          <div className="budget-req-gh-error" title={r.github_budget.error}>
                            {r.github_budget.error.length > 44
                              ? `${r.github_budget.error.slice(0, 44)}…`
                              : r.github_budget.error}
                          </div>
                        )}
                      </td>
                      <td className="cc-td">
                        <div className="budget-req-actions">
                          <input
                            type="number"
                            min="0"
                            step="0.01"
                            className="budget-req-amount-input"
                            value={amountFor(r)}
                            onChange={(e) => setEditing((prev) => ({ ...prev, [r.id]: e.target.value }))}
                            title={t("budgetReq.approvedAmountHint")}
                          />
                          <input
                            type="text"
                            className="budget-req-comment-input"
                            placeholder={t("budgetReq.comment")}
                            value={comments[r.id] ?? ""}
                            onChange={(e) => setComments((prev) => ({ ...prev, [r.id]: e.target.value }))}
                          />
                          {r.status === "pending" ? (
                            <>
                              <button
                                className="btn btn-small btn-primary"
                                disabled={busy === r.id}
                                onClick={() => handleApprove(r)}
                              >
                                {t("budgetReq.approve")}
                              </button>
                              <button
                                className="btn btn-small btn-ghost"
                                disabled={busy === r.id}
                                onClick={() =>
                                  run(r.id, () => review(r.id, "reject", undefined, comments[r.id] ?? "", opts))
                                }
                              >
                                {t("budgetReq.reject")}
                              </button>
                            </>
                          ) : (
                            <>
                              <button
                                className="btn btn-small"
                                disabled={busy === r.id}
                                onClick={() => {
                                  const v = parseFloat(amountFor(r));
                                  if (!Number.isFinite(v) || v < 0) return;
                                  return run(r.id, () => updateAmount(r.id, v, comments[r.id] ?? "", opts));
                                }}
                              >
                                {t("budgetReq.updateAmount")}
                              </button>
                              {r.status === "approved" && r.github_budget?.status !== "created" && (
                                <button
                                  className="btn btn-small btn-ghost"
                                  disabled={busy === r.id}
                                  onClick={() => run(r.id, () => resync(r.id, hardLimit))}
                                  title={t("budgetReq.resync")}
                                >
                                  ⟳
                                </button>
                              )}
                            </>
                          )}
                          <button
                            className="btn btn-small btn-ghost"
                            disabled={busy === r.id}
                            onClick={() => remove(r.id)}
                            title={t("budgetReq.delete")}
                          >
                            ✕
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

function AuditTable({ refreshKey }: { refreshKey: number }) {
  const { t } = useI18n();
  const { entries, loading } = useBudgetAudit(refreshKey);

  if (loading) return <div className="dashboard-loading">{t("loading")}</div>;
  if (!entries.length) return <div className="dashboard-empty">{t("budgetReq.auditEmpty")}</div>;

  return (
    <div className="dash-section">
      <div className="dash-section-header">
        <span className="dash-section-chevron">▼</span>
        <h3 className="dash-section-title">{t("budgetReq.auditTitle")}</h3>
      </div>
      <div className="dash-section-body">
        <div className="cc-table-wrap">
          <table className="cc-table">
            <thead>
              <tr>
                <th className="cc-th">{t("budgetReq.colDate")}</th>
                <th className="cc-th">{t("budgetReq.colAction")}</th>
                <th className="cc-th">{t("budgetReq.colUser")}</th>
                <th className="cc-th">{t("budgetReq.colBy")}</th>
                <th className="cc-th cc-th-num">{t("budgetReq.colRequested")}</th>
                <th className="cc-th cc-th-num">{t("budgetReq.colApproved")}</th>
                <th className="cc-th">{t("budgetReq.githubStatus")}</th>
                <th className="cc-th">{t("budgetReq.comment")}</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e, i) => (
                <tr key={`${e.request_id}-${i}`} className="cc-table-row">
                  <td className="cc-td">{e.at ? e.at.slice(0, 19).replace("T", " ") : "—"}</td>
                  <td className="cc-td">
                    <span className={statusBadgeClass(e.action)}>
                      {t(`budgetReq.action.${e.action}` as Parameters<typeof t>[0])}
                    </span>
                  </td>
                  <td className="cc-td"><strong>{e.user_login}</strong></td>
                  <td className="cc-td">{e.by || "—"}</td>
                  <td className="cc-td cc-td-num">
                    {e.requested_amount != null ? `$${e.requested_amount.toLocaleString()}` : "—"}
                  </td>
                  <td className="cc-td cc-td-num">
                    {e.amount != null ? `$${e.amount.toLocaleString()}` : "—"}
                  </td>
                  <td className="cc-td">
                    {e.github_budget_status ? (
                      <GithubBudgetBadge sync={{ status: e.github_budget_status as GithubBudgetSync["status"], error: e.github_budget_error ?? undefined }} />
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="cc-td" title={e.comment}>
                    {e.comment ? (e.comment.length > 40 ? `${e.comment.slice(0, 40)}…` : e.comment) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

/** Admin view: review requests (provisioning real GitHub budgets) + audit trail. */
export function BudgetRequestsAdmin({ refreshKey = 0 }: Props) {
  const { t } = useI18n();
  const [tab, setTab] = useState<"review" | "history">("review");

  return (
    <div className="csv-dashboard" key={refreshKey}>
      <div className="view-toggle" style={{ marginBottom: 8 }}>
        <button
          className={`btn btn-small btn-toggle ${tab === "review" ? "btn-toggle-active" : ""}`}
          onClick={() => setTab("review")}
        >
          {t("budgetReq.tabPending")}
        </button>
        <button
          className={`btn btn-small btn-toggle ${tab === "history" ? "btn-toggle-active" : ""}`}
          onClick={() => setTab("history")}
        >
          {t("budgetReq.tabHistory")}
        </button>
      </div>

      {tab === "review" ? <ReviewTable /> : <AuditTable refreshKey={refreshKey} />}
    </div>
  );
}
