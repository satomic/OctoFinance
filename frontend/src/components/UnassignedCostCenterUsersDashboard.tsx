import { useCallback, useMemo, useState } from "react";
import { useI18n } from "../contexts/I18nContext";
import { useUIState } from "../contexts/UIStateContext";
import { useDatasetSync, useUnassignedCostCenterUsers } from "../hooks/useData";
import type { CostCenterOption, UnassignedCostCenterUser } from "../types";

interface Props {
  refreshKey: number;
}

interface PendingAssignment {
  users: string[];
  costCenter: CostCenterOption;
}

function formatDate(value: string) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString();
}

function UserCell({ user }: { user: UnassignedCostCenterUser }) {
  return (
    <div className="cc-member-info">
      {user.avatar_url
        ? <img src={user.avatar_url} alt={user.login} className="cc-member-avatar" />
        : <div className="cc-member-avatar cc-member-avatar-placeholder" />}
      <div className="cc-user-stack">
        <a href={user.html_url} target="_blank" rel="noopener noreferrer" className="cc-member-login">
          {user.login}
        </a>
        <span className="cc-user-muted">{user.seat_count} seat{user.seat_count === 1 ? "" : "s"}</span>
      </div>
    </div>
  );
}

function TagList({ values, empty = "-" }: { values: string[]; empty?: string }) {
  if (!values.length) return <span className="cc-user-muted">{empty}</span>;
  return (
    <div className="cc-resource-tags">
      {values.map((value) => <span key={value} className="cc-cc-tag">{value}</span>)}
    </div>
  );
}

export function UnassignedCostCenterUsersDashboard(_props: Props) {
  const { t } = useI18n();
  const ui = useUIState();
  const enterprise = ui.ccDashEnterprise;
  const search = ui.ccUnassignedSearch;

  const [searchInput, setSearchInput] = useState(search);
  const [selectedUsers, setSelectedUsers] = useState<Set<string>>(new Set());
  const [batchCostCenterId, setBatchCostCenterId] = useState("");
  const [rowCostCenters, setRowCostCenters] = useState<Record<string, string>>({});
  const [pending, setPending] = useState<PendingAssignment | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  const { data, loading, refetch, assignUsers } = useUnassignedCostCenterUsers({ enterprise, search });
  const { syncing, runSync } = useDatasetSync();

  const commitSearch = useCallback((value: string) => {
    ui.patch({ ccUnassignedSearch: value });
  }, [ui]);

  const setEnterprise = useCallback((slug: string) => {
    ui.patch({ ccDashEnterprise: slug, ccUnassignedSearch: "" });
    setSearchInput("");
    setSelectedUsers(new Set());
    setBatchCostCenterId("");
  }, [ui]);

  const users = useMemo(() => data?.unassigned_users ?? [], [data?.unassigned_users]);
  const costCenters = useMemo(() => data?.cost_centers ?? [], [data?.cost_centers]);
  const selectedList = useMemo(
    () => users.filter((user) => selectedUsers.has(user.login)).map((user) => user.login),
    [users, selectedUsers],
  );

  const allVisibleSelected = users.length > 0 && users.every((user) => selectedUsers.has(user.login));
  const selectedCostCenter = costCenters.find((cc) => cc.id === batchCostCenterId);

  const toggleUser = useCallback((login: string) => {
    setSelectedUsers((prev) => {
      const next = new Set(prev);
      if (next.has(login)) next.delete(login);
      else next.add(login);
      return next;
    });
  }, []);

  const toggleAllVisible = useCallback(() => {
    setSelectedUsers((prev) => {
      const next = new Set(prev);
      if (users.every((user) => next.has(user.login))) {
        users.forEach((user) => next.delete(user.login));
      } else {
        users.forEach((user) => next.add(user.login));
      }
      return next;
    });
  }, [users]);

  const openConfirmation = useCallback((logins: string[], costCenterId: string) => {
    const costCenter = costCenters.find((cc) => cc.id === costCenterId);
    if (!costCenter) {
      setMessage(t("ccUnassigned.noCostCenter"));
      return;
    }
    setPending({ users: logins, costCenter });
    setMessage("");
  }, [costCenters, t]);

  const executeAssignment = useCallback(async () => {
    if (!pending || !data) return;
    setSaving(true);
    const result = await assignUsers(data.selected_enterprise, pending.costCenter.id, pending.users);
    setSaving(false);
    if (result.error) {
      setMessage(result.error);
      return;
    }
    setSelectedUsers((prev) => {
      const next = new Set(prev);
      pending.users.forEach((login) => next.delete(login));
      return next;
    });
    setRowCostCenters((prev) => {
      const next = { ...prev };
      pending.users.forEach((login) => delete next[login]);
      return next;
    });
    setBatchCostCenterId("");
    setMessage(`${t("ccUnassigned.success")} ${pending.users.length}`);
    setPending(null);
  }, [assignUsers, data, pending, t]);

  const handleSync = useCallback(() => {
    runSync("cost_centers", refetch);
  }, [runSync, refetch]);

  if (loading) return <div className="dashboard-loading">{t("loading")}</div>;

  if (!data || data.no_data) {
    return <div className="dashboard-empty">{t("ccUnassigned.noData")}</div>;
  }

  const enterpriseOptions = data.enterprises.map((item) => item.slug);

  return (
    <div className="csv-dashboard">
      <div className="csv-filters">
        {enterpriseOptions.length > 1 && (
          <div className="org-dropdown" style={{ minWidth: 160 }}>
            <select
              className="cc-native-select"
              value={enterprise || data.selected_enterprise}
              onChange={(event) => setEnterprise(event.target.value)}
            >
              {enterpriseOptions.map((slug) => <option key={slug} value={slug}>{slug}</option>)}
            </select>
          </div>
        )}

        <input
          type="text"
          className="cc-search-input"
          placeholder={t("ccUnassigned.search")}
          value={searchInput}
          onChange={(event) => setSearchInput(event.target.value)}
          onBlur={() => commitSearch(searchInput)}
          onKeyDown={(event) => { if (event.key === "Enter") commitSearch(searchInput); }}
        />

        <button
          className="btn btn-small"
          style={{ marginLeft: "auto" }}
          onClick={handleSync}
          disabled={syncing}
          title={t("ccUnassigned.syncHint")}
        >
          {syncing ? t("status.syncing") : t("ccDash.sync")}
        </button>
      </div>

      <div className="dashboard-kpi">
        <div className="stat-card">
          <div className="stat-value">{data.total_unassigned}</div>
          <div className="stat-label">{t("ccUnassigned.totalUnassigned")}</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{data.total_copilot_users}</div>
          <div className="stat-label">{t("ccUnassigned.totalCopilotUsers")}</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{data.assigned_user_count}</div>
          <div className="stat-label">{t("ccUnassigned.assignedUsers")}</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{data.orgs.length}</div>
          <div className="stat-label">{t("ccUnassigned.enterpriseOrgs")}</div>
        </div>
      </div>

      <div className="cc-batch-bar">
        <span className="cc-user-muted">{selectedList.length} {t("ccUnassigned.selected")}</span>
        <select
          className="cc-native-select cc-batch-select"
          value={batchCostCenterId}
          onChange={(event) => setBatchCostCenterId(event.target.value)}
        >
          <option value="">{t("ccUnassigned.selectCostCenter")}</option>
          {costCenters.map((cc) => <option key={cc.id} value={cc.id}>{cc.name}</option>)}
        </select>
        <button
          className="btn btn-small btn-primary"
          disabled={!selectedList.length || !selectedCostCenter}
          onClick={() => openConfirmation(selectedList, batchCostCenterId)}
        >
          {t("ccUnassigned.assignSelected")}
        </button>
        {message && <span className={`cc-inline-message ${message.includes("failed") || message.includes("Error") ? "cc-inline-error" : ""}`}>{message}</span>}
      </div>

      {!users.length ? (
        <div className="dashboard-empty">{t("ccUnassigned.noUsers")}</div>
      ) : (
        <div className="cc-table-wrap">
          <table className="cc-table cc-unassigned-table">
            <thead>
              <tr>
                <th className="cc-th cc-checkbox-cell">
                  <input type="checkbox" checked={allVisibleSelected} onChange={toggleAllVisible} />
                </th>
                <th className="cc-th">{t("ccDash.colUser")}</th>
                <th className="cc-th">{t("ccUnassigned.colOrganizations")}</th>
                <th className="cc-th">{t("ccUnassigned.colTeams")}</th>
                <th className="cc-th">{t("ccUnassigned.plan")}</th>
                <th className="cc-th">{t("ccUnassigned.colLastActivity")}</th>
                <th className="cc-th">{t("ccUnassigned.colAssign")}</th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => {
                const rowCostCenterId = rowCostCenters[user.login] || "";
                return (
                  <tr key={user.login} className="cc-table-row">
                    <td className="cc-td cc-checkbox-cell">
                      <input
                        type="checkbox"
                        checked={selectedUsers.has(user.login)}
                        onChange={() => toggleUser(user.login)}
                      />
                    </td>
                    <td className="cc-td"><UserCell user={user} /></td>
                    <td className="cc-td"><TagList values={user.orgs} /></td>
                    <td className="cc-td"><TagList values={user.teams} /></td>
                    <td className="cc-td"><TagList values={user.plan_types} /></td>
                    <td className="cc-td">
                      <div className="cc-user-stack">
                        <span>{formatDate(user.last_activity_at)}</span>
                        {user.last_activity_editor && <span className="cc-user-muted">{user.last_activity_editor}</span>}
                      </div>
                    </td>
                    <td className="cc-td">
                      <div className="cc-row-actions">
                        <select
                          className="cc-native-select cc-row-select"
                          value={rowCostCenterId}
                          onChange={(event) => setRowCostCenters((prev) => ({ ...prev, [user.login]: event.target.value }))}
                        >
                          <option value="">{t("ccUnassigned.selectCostCenter")}</option>
                          {costCenters.map((cc) => <option key={cc.id} value={cc.id}>{cc.name}</option>)}
                        </select>
                        <button
                          className="btn btn-small"
                          disabled={!rowCostCenterId}
                          onClick={() => openConfirmation([user.login], rowCostCenterId)}
                        >
                          {t("ccUnassigned.colAssign")}
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {pending && (
        <div className="settings-modal-overlay" onClick={() => !saving && setPending(null)}>
          <div className="settings-modal cc-confirm-modal" onClick={(event) => event.stopPropagation()}>
            <div className="settings-modal-header">
              <h2>{t("ccUnassigned.confirmTitle")}</h2>
              <button className="settings-close-btn" onClick={() => setPending(null)} disabled={saving}>x</button>
            </div>
            <div className="settings-modal-body">
              <p className="cc-confirm-text">{t("ccUnassigned.confirmIntro")}</p>
              <div className="cc-confirm-summary">
                <div>
                  <span className="cc-user-muted">{t("ccUnassigned.confirmCostCenter")}</span>
                  <strong>{pending.costCenter.name}</strong>
                </div>
                <div>
                  <span className="cc-user-muted">{t("ccUnassigned.confirmUsers")}</span>
                  <strong>{pending.users.length}</strong>
                </div>
              </div>
              <div className="cc-confirm-users">
                {pending.users.map((login) => <span key={login} className="cc-cc-tag">{login}</span>)}
              </div>
              <div className="cc-confirm-actions">
                <button className="btn btn-small btn-ghost" onClick={() => setPending(null)} disabled={saving}>
                  {t("ccUnassigned.cancel")}
                </button>
                <button className="btn btn-small btn-primary" onClick={executeAssignment} disabled={saving}>
                  {saving ? t("ccUnassigned.saving") : t("ccUnassigned.confirmExecute")}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}