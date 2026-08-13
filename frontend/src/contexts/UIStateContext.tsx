import { createContext, useContext, useState, useCallback, useEffect, type ReactNode } from "react";

const STORAGE_KEY = "octofinance-ui-state";

export interface UIState {
  currentView: "chat" | "dashboard";
  periodMode: "all" | "current_month";
  dashboardTab: "metrics" | "ai" | "usage" | "costcenter" | "unassigned" | "budgets" | "requests" | "entteams";
  consoleOpen: boolean;
  sidebarWidth: number;
  sidebarCollapsed: Record<string, boolean>;
  currentSessionId: string | null;
  dashboardSections: Record<string, boolean>;
  dashboardSelectedOrgs: string[] | null;
  dashboardDateFrom: string;
  dashboardDateTo: string;
  dashboardEnterpriseTeam: string;
  // Chat
  chatModel: string;
  // CSV dashboard filters
  csvDashOrgs: string[];
  csvDashCostCenters: string[];
  csvDashProducts: string[];
  csvDashSkus: string[];
  csvDashDateFrom: string;
  csvDashDateTo: string;
  csvDashEnterpriseTeam: string;
  // Cost Center dashboard filters
  ccDashEnterprise: string;
  ccDashCostCenters: string[];
  ccDashState: string;
  ccDashSearch: string;
  ccUnassignedSearch: string;
  // Budgets dashboard filters
  budgetsDashEnterprise: string;
  budgetsDashScope: string;
  budgetsDashSearch: string;
  // Enterprise teams dashboard filters
  etDashEnterprise: string;
  etDashTeams: string[];
  etDashSearch: string;
}


const DEFAULTS: UIState = {
  currentView: "chat",
  periodMode: "all",
  dashboardTab: "metrics",
  consoleOpen: false,
  sidebarWidth: 320,
  sidebarCollapsed: {
    overview: false,
    organizations: false,
    sessions: false,
    actions: true,
  },
  currentSessionId: null,
  dashboardSections: {},
  dashboardSelectedOrgs: null,
  dashboardDateFrom: "",
  dashboardDateTo: "",
  dashboardEnterpriseTeam: "",
  chatModel: "",
  csvDashOrgs: [],
  csvDashCostCenters: [],
  csvDashProducts: [],
  csvDashSkus: [],
  csvDashDateFrom: "",
  csvDashDateTo: "",
  csvDashEnterpriseTeam: "",
  ccDashEnterprise: "",
  ccDashCostCenters: [],
  ccDashState: "active",
  ccDashSearch: "",
  ccUnassignedSearch: "",
  budgetsDashEnterprise: "",
  budgetsDashScope: "all",
  budgetsDashSearch: "",
  etDashEnterprise: "",
  etDashTeams: [],
  etDashSearch: "",
};

interface UIStateContextValue extends UIState {
  patch: (partial: Partial<UIState>) => void;
}

const UIStateContext = createContext<UIStateContextValue>({
  ...DEFAULTS,
  patch: () => {},
});

export function UIStateProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<UIState>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved);
        return { ...DEFAULTS, ...parsed };
      }
    } catch {
      // ignore
    }
    return DEFAULTS;
  });

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }, [state]);

  const patch = useCallback((partial: Partial<UIState>) => {
    setState((prev) => ({ ...prev, ...partial }));
  }, []);

  return (
    <UIStateContext.Provider value={{ ...state, patch }}>
      {children}
    </UIStateContext.Provider>
  );
}

export function useUIState() {
  return useContext(UIStateContext);
}
