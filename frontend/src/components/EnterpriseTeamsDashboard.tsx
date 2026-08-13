import { useCallback, useState } from "react";
import { useI18n } from "../contexts/I18nContext";
import { useUIState } from "../contexts/UIStateContext";
import { useEnterpriseTeamsDashboard, useDatasetSync } from "../hooks/useData";
import type { EnterpriseTeam, EnterpriseTeamMember } from "../types";

interface Props {
  refreshKey: number;
}

function formatDate(value: string): string {
  if (!value) return "—";
  return value.slice(0, 10);
}

function MemberRow({ member }: { member: EnterpriseTeamMember }) {
  const { t } = useI18n();
  return (
    <tr className="cc-member-row">
      <td className="cc-td cc-td-member">
        <div className="cc-member-info">
          {member.avatar_url
            ? <img src={member.avatar_url} alt={member.login} className="cc-member-avatar" />
            : <div className="cc-member-avatar cc-member-avatar-placeholder" />}
          <a href={member.html_url} target="_blank" rel="noopener noreferrer" className="cc-member-login">
            {member.login}
          </a>
        </div>
      </td>
      <td className="cc-td">
        {member.has_seat
          ? <span className="cc-state-badge cc-state-active">{t("etDash.hasSeat")}</span>
          : <span className="cc-state-badge cc-state-archived">{t("etDash.noSeat")}</span>}
      </td>
      <td className="cc-td">
        <div className="cc-resource-tags">
          {member.orgs.length
            ? member.orgs.map((o) => <span key={o} className="cc-cc-tag">{o}</span>)
            : <span className="cc-muted">{t("etDash.unaffiliated")}</span>}
        </div>
      </td>
      <td className="cc-td cc-td-num">{member.interactions.toLocaleString()}</td>
      <td className="cc-td cc-td-num">{member.active_days}</td>
      <td className="cc-td cc-td-num">${member.ai_net_amount.toFixed(2)}</td>
      <td className="cc-td">{formatDate(member.last_activity_at)}</td>
    </tr>
  );
}

/* Members render in their own table so their columns never have to line up with
   the outer teams table. */
function MemberTable({ members }: { members: EnterpriseTeamMember[] }) {
  const { t } = useI18n();
  return (
    <table className="cc-table">
      <thead>
        <tr>
          <th className="cc-th">{t("etDash.colMember")}</th>
          <th className="cc-th">{t("etDash.colSeat")}</th>
          <th className="cc-th">{t("etDash.colOrgs")}</th>
          <th className="cc-th cc-th-num">{t("etDash.colInteractions")}</th>
          <th className="cc-th cc-th-num">{t("etDash.colActiveDays")}</th>
          <th className="cc-th cc-th-num">{t("etDash.colAiCost")}</th>
          <th className="cc-th">{t("etDash.colLastActivity")}</th>
        </tr>
      </thead>
      <tbody>
        {members.map((m) => <MemberRow key={m.login} member={m} />)}
      </tbody>
    </table>
  );
}

function TeamRow({ team }: { team: EnterpriseTeam }) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(false);

  return (
    <>
      <tr className="cc-table-row" onClick={() => setExpanded((v) => !v)} style={{ cursor: "pointer" }}>
        <td className="cc-td">
          <span className="cc-expand-icon">{expanded ? "▼" : "▶"}</span>
          <strong>{team.name}</strong>
          <div className="cc-muted">{team.slug}</div>
        </td>
        <td className="cc-td">
          <div className="cc-resource-tags">
            {team.organizations.length
              ? team.organizations.map((o) => <span key={o} className="cc-cc-tag">{o}</span>)
              : <span className="cc-muted">{t("etDash.noOrgAssignment")}</span>}
          </div>
        </td>
        <td className="cc-td cc-td-num"><strong>{team.member_count}</strong></td>
        <td className="cc-td cc-td-num">{team.seat_count}</td>
        <td className="cc-td cc-td-num">
          {team.no_seat_count > 0
            ? <span className="cc-state-badge cc-state-archived">{team.no_seat_count}</span>
            : 0}
        </td>
        <td className="cc-td cc-td-num">{team.active_member_count}</td>
        <td className="cc-td cc-td-num">{team.interactions.toLocaleString()}</td>
        <td className="cc-td cc-td-num">${team.ai_net_amount.toFixed(2)}</td>
        <td className="cc-td cc-td-num">${team.seat_cost.toFixed(2)}</td>
      </tr>
      {expanded && (
        <tr className="et-detail-row">
          <td className="et-detail-cell" colSpan={9}>
            {team.members.length
              ? <MemberTable members={team.members} />
              : <div className="et-detail-empty">{t("etDash.emptyTeam")}</div>}
          </td>
        </tr>
      )}
    </>
  );
}

export function EnterpriseTeamsDashboard({ refreshKey }: Props) {
  const { t } = useI18n();
  const ui = useUIState();
  const { patch } = ui;

  const enterprise = ui.etDashEnterprise;
  const teams = ui.etDashTeams;
  const [searchInput, setSearchInput] = useState(ui.etDashSearch);
  const commitSearch = useCallback((v: string) => patch({ etDashSearch: v }), [patch]);

  const { data, loading, refetch } = useEnterpriseTeamsDashboard({
    enterprise, teams, search: ui.etDashSearch,
  });
  const { syncing, runSync } = useDatasetSync();
  const handleSync = useCallback(() => runSync("enterprise_teams", refetch), [runSync, refetch]);

  const setEnterprise = useCallback((v: string) => patch({ etDashEnterprise: v, etDashTeams: [] }), [patch]);
  const setTeams = useCallback((v: string[]) => patch({ etDashTeams: v }), [patch]);

  const [showUnassigned, setShowUnassigned] = useState(false);

  if (loading && !data) return <div className="dashboard-loading">{t("loading")}</div>;

  const syncButton = (
    <button
      className="btn btn-small"
      style={{ marginLeft: "auto" }}
      onClick={handleSync}
      disabled={syncing}
      title={t("etDash.syncHint")}
    >
      {syncing ? t("status.syncing") : `⟳ ${t("etDash.sync")}`}
    </button>
  );

  if (!data || data.no_data) {
    return (
      <div className="csv-dashboard">
        <div className="csv-filters">{syncButton}</div>
        <div className="dashboard-empty">{t("etDash.noData")}</div>
      </div>
    );
  }

  const { totals } = data;
  const enterpriseOptions = data.enterprises.map((e) => e.slug);

  return (
    <div className="csv-dashboard" key={refreshKey}>
      {/* Filters */}
      <div className="csv-filters">
        {enterpriseOptions.length > 1 && (
          <div className="org-dropdown" style={{ minWidth: 160 }}>
            <select
              className="cc-native-select"
              value={enterprise || data.selected_enterprise}
              onChange={(e) => setEnterprise(e.target.value)}
            >
              {enterpriseOptions.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
        )}

        <div className="org-dropdown" style={{ minWidth: 200 }}>
          <select
            className="cc-native-select"
            value={teams[0] ?? ""}
            onChange={(e) => setTeams(e.target.value ? [e.target.value] : [])}
          >
            <option value="">{t("etDash.allTeams")}</option>
            {data.all_teams.map((tm) => (
              <option key={tm.slug} value={tm.slug}>{tm.name}</option>
            ))}
          </select>
        </div>

        <input
          type="text"
          className="cc-search-input"
          placeholder={t("etDash.search")}
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          onBlur={() => commitSearch(searchInput)}
          onKeyDown={(e) => { if (e.key === "Enter") commitSearch(searchInput); }}
        />

        {syncButton}
      </div>

      {/* KPI cards */}
      <div className="dashboard-kpi">
        <div className="stat-card">
          <div className="stat-value">{totals.total_teams}</div>
          <div className="stat-label">{t("etDash.kpiTeams")}</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{totals.total_unique_members}</div>
          <div className="stat-label">{t("etDash.kpiMembers")}</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{totals.members_with_seat}</div>
          <div className="stat-label">{t("etDash.kpiWithSeat")}</div>
        </div>
        <div className="stat-card warning">
          <div className="stat-value warning">{totals.members_without_seat}</div>
          <div className="stat-label">{t("etDash.kpiWithoutSeat")}</div>
        </div>
        <div className="stat-card warning">
          <div className="stat-value warning">{totals.unassigned_seat_users}</div>
          <div className="stat-label">{t("etDash.kpiUncovered")}</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{totals.coverage_pct}%</div>
          <div className="stat-label">{t("etDash.kpiCoverage")}</div>
        </div>
        <div className="stat-card cost">
          <div className="stat-value cost">${totals.seat_cost.toLocaleString()}</div>
          <div className="stat-label">{t("etDash.kpiSeatCost")}</div>
        </div>
        <div className="stat-card cost">
          <div className="stat-value cost">${totals.ai_net_amount.toFixed(2)}</div>
          <div className="stat-label">{t("etDash.kpiAiCost")}</div>
        </div>
      </div>

      {!data.ai_usage_available && (
        <div className="dash-note">{t("etDash.noAiCsv")}</div>
      )}

      {/* Teams table */}
      <div className="dash-section">
        <div className="dash-section-header">
          <h3 className="dash-section-title">{t("etDash.teamsTitle")}</h3>
        </div>
        <div className="dash-section-body">
          <div className="cc-table-wrap">
            <table className="cc-table">
              <thead>
                <tr>
                  <th className="cc-th">{t("etDash.colTeam")}</th>
                  <th className="cc-th">{t("etDash.colTeamOrgs")}</th>
                  <th className="cc-th cc-th-num">{t("etDash.colMembers")}</th>
                  <th className="cc-th cc-th-num">{t("etDash.colSeats")}</th>
                  <th className="cc-th cc-th-num">{t("etDash.colNoSeat")}</th>
                  <th className="cc-th cc-th-num">{t("etDash.colActive")}</th>
                  <th className="cc-th cc-th-num">{t("etDash.colInteractions")}</th>
                  <th className="cc-th cc-th-num">{t("etDash.colAiCost")}</th>
                  <th className="cc-th cc-th-num">{t("etDash.colSeatCost")}</th>
                </tr>
              </thead>
              <tbody>
                {data.teams.length
                  ? data.teams.map((tm) => <TeamRow key={tm.slug} team={tm} />)
                  : <tr><td className="cc-td" colSpan={9}>{t("etDash.noMatch")}</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Seat holders not covered by any enterprise team */}
      <div className="dash-section">
        <div className="dash-section-header" onClick={() => setShowUnassigned((v) => !v)}>
          <span className="dash-section-chevron">{showUnassigned ? "▼" : "▶"}</span>
          <h3 className="dash-section-title">
            {t("etDash.uncoveredTitle")} ({data.unassigned_seat_users.length})
          </h3>
        </div>
        {showUnassigned && (
          <div className="dash-section-body">
            <div className="dash-note">{t("etDash.uncoveredHint")}</div>
            <div className="cc-table-wrap">
              <MemberTable members={data.unassigned_seat_users} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
