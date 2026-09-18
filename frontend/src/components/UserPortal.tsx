import { useEffect, useState } from "react";
import { useI18n } from "../contexts/I18nContext";
import { useUIState } from "../contexts/UIStateContext";
import { MyDashboard } from "./MyDashboard";
import { BudgetRequestPanel } from "./BudgetRequestPanel";
import { PeriodToggle } from "./PeriodToggle";
import { SourceCodeLink } from "./SourceCodeLink";
import { UserMenu } from "./UserMenu";
import { OwnerCostCenterDashboard } from "./OwnerCostCenterDashboard";
import type { AuthUser, OwnedCostCenter, UpdateInfo } from "../types";

interface Props {
  user: AuthUser;
  version?: string;
  update?: UpdateInfo;
  onLogout: () => void;
}

/**
 * Layout shown to regular (non-admin) GitHub SSO users.
 * Scoped strictly to the signed-in user's own data plus the budget request flow.
 */
export function UserPortal({ user, version, update, onLogout }: Props) {
  const { t } = useI18n();
  const ui = useUIState();
  const period = ui.periodMode ?? "all";
  const [tab, setTab] = useState<"usage" | "budget">("usage");
  const [ownedCenters, setOwnedCenters] = useState<OwnedCostCenter[]>([]);
  const [selectedRole, setSelectedRole] = useState("");
  const [rolesError, setRolesError] = useState(false);

  useEffect(() => {
    let disposed = false;
    const loadRoles = async () => {
      try {
        const response = await fetch("/api/me/owned-cost-centers");
        if (!response.ok) throw new Error("Unable to load roles");
        const result = await response.json();
        if (!disposed) { setOwnedCenters(result.cost_centers); setRolesError(false); }
      } catch {
        if (!disposed) { setOwnedCenters([]); setRolesError(true); }
      }
    };
    loadRoles();
    window.addEventListener("focus", loadRoles);
    const timer = window.setInterval(loadRoles, 60000);
    return () => { disposed = true; window.removeEventListener("focus", loadRoles); window.clearInterval(timer); };
  }, [user.login]);

  const selectedCenter = ownedCenters.find((center) => JSON.stringify([center.enterprise, center.id]) === selectedRole);

  return (
    <div className="app">
      <div className="status-bar">
        <div className="status-left">
          <span className="app-title">OctoFinance</span>
          {version && <span className="app-version">v{version}</span>}
          <span className="status-dot green" />
          <span className="status-text">{t("me.portalTitle")}</span>
        </div>
        <div className="status-right">
          {ownedCenters.length > 0 && <select
            className="cc-native-select cc-role-select"
            aria-label={t("ccOwner.switchRole")}
            value={selectedCenter ? selectedRole : ""}
            onChange={(event) => setSelectedRole(event.target.value)}
          >
            <option value="">{t("ccOwner.personal")}</option>
            {ownedCenters.map((center) => <option key={JSON.stringify([center.enterprise, center.id])} value={JSON.stringify([center.enterprise, center.id])}>{t("ccOwner.owner")}: {center.name} ({center.enterprise})</option>)}
          </select>}
          <PeriodToggle value={period} onChange={(v) => ui.patch({ periodMode: v })} />
          {!selectedCenter && <div className="view-toggle">
            <button
              className={`btn btn-small btn-toggle ${tab === "usage" ? "btn-toggle-active" : ""}`}
              onClick={() => setTab("usage")}
            >
              {t("me.tabUsage")}
            </button>
            <button
              className={`btn btn-small btn-toggle ${tab === "budget" ? "btn-toggle-active" : ""}`}
              onClick={() => setTab("budget")}
            >
              {t("me.tabBudget")}
            </button>
          </div>}
          <SourceCodeLink update={update} />
          <a
            className="btn btn-small btn-link-icon"
            href="https://github.com/satomic/OctoFinance/issues/new"
            target="_blank"
            rel="noopener noreferrer"
            title={t("nav.feedback")}
            aria-label={t("nav.feedback")}
          >
            <svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true">
              <path d="M8 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13ZM0 8a8 8 0 1 1 16 0A8 8 0 0 1 0 8Zm9 3a1 1 0 1 1-2 0 1 1 0 0 1 2 0ZM6.92 6.085h.001a.749.749 0 1 1-1.342-.67c.169-.339.436-.701.849-.977C6.845 4.16 7.369 4 8 4a2.756 2.756 0 0 1 1.637.525c.503.377.863.965.863 1.725 0 .448-.115.83-.329 1.15-.205.307-.47.513-.692.662-.109.072-.22.138-.313.195l-.006.004a6.24 6.24 0 0 0-.26.16.952.952 0 0 0-.276.245.75.75 0 0 1-1.248-.832c.184-.264.42-.489.692-.661.103-.067.207-.132.313-.195l.007-.004c.1-.061.182-.11.258-.161a.969.969 0 0 0 .277-.245C8.96 6.514 9 6.427 9 6.25a.612.612 0 0 0-.262-.525A1.27 1.27 0 0 0 8 5.5c-.369 0-.595.09-.74.187a1.01 1.01 0 0 0-.34.398Z" />
            </svg>
            {t("nav.feedback")}
          </a>
          <UserMenu user={user} onLogout={onLogout} />
        </div>
      </div>
      <div className="app-body">
        <main className="main-content">
          <div className="unified-dashboard">
            {rolesError && <p className="settings-error" role="alert">{t("ccOwner.loadFailed")}</p>}
            {selectedCenter ? <OwnerCostCenterDashboard key={`${selectedRole}:${period}`} center={selectedCenter} period={period} /> : tab === "usage" ? <MyDashboard period={period} /> : <BudgetRequestPanel />}
          </div>
        </main>
      </div>
    </div>
  );
}
