import { createContext, useContext, useState, useCallback, type ReactNode } from "react";

type Lang = "en" | "zh";

const translations = {
  en: {
    // StatusBar
    "status.notConnected": "Not connected",
    "status.orgs": "orgs",
    "status.aiReady": "AI Ready",
    "status.aiStarting": "AI Starting...",
    "status.syncData": "Sync Data",
    "status.syncing": "Syncing...",

    // Chat
    "chat.title": "OctoFinance AI FinOps",
    "chat.subtitle": "Ask me anything about your GitHub Copilot usage, costs, and optimization.",
    "chat.placeholder": "Ask about Copilot usage, costs, inactive users...",
    "chat.send": "Send",
    "chat.stop": "Stop",
    "chat.clear": "Clear",
    "chat.you": "You",
    "chat.ai": "OctoFinance AI",

    // Quick Prompts
    "qp.overview": "Overview",
    "qp.overviewPrompt": "Give me an overview of our Copilot usage and costs across all organizations.",
    "qp.inactive": "Inactive Users",
    "qp.inactivePrompt": "Find all users who haven't used Copilot in the last 30 days. Show the cost impact.",
    "qp.costOpt": "Cost Optimization",
    "qp.costOptPrompt": "Analyze our Copilot spending and recommend ways to reduce waste.",
    "qp.roi": "ROI Analysis",
    "qp.roiPrompt": "Calculate the ROI of our Copilot investment. Are we getting value?",

    // Sidebar
    "sidebar.overview": "Overview",
    "sidebar.totalSeats": "Total Seats",
    "sidebar.active": "Active",
    "sidebar.inactive": "Inactive",
    "sidebar.utilization": "Utilization",
    "sidebar.monthlyCost": "Monthly Cost",
    "sidebar.monthlyWaste": "Monthly Waste",
    "sidebar.organizations": "Organizations",
    "sidebar.noOrgs": "No organizations discovered",
    "sidebar.noCopilot": "No Copilot",

    // Sort
    "sort.name": "Name",
    "sort.seats": "Total Seats",
    "sort.active": "Active Seats",
    "sort.inactive": "Inactive",
    "sort.waste": "Waste",

    // Actions
    "actions.title": "Pending Actions",
    "actions.empty": "No pending recommendations. Ask the AI to analyze your Copilot usage to get optimization suggestions.",
    "actions.approve": "Approve & Execute",
    "actions.reject": "Reject",
    "actions.users": "Users",
    "actions.savings": "Estimated savings",

    // Console
    "console.title": "Console",
    "console.clear": "Clear",
    "console.close": "Close",
    "console.empty": "No logs yet. Send a message to see AI processing details.",

    // Sessions
    "sessions.title": "Sessions",
    "sessions.new": "New Session",
    "sessions.delete": "Delete",
    "sessions.empty": "No sessions yet",

    // Settings
    "settings.title": "Settings",
    "settings.pats": "GitHub Personal Access Tokens",
    "settings.addPat": "Add PAT",
    "settings.patLabel": "Label",
    "settings.patToken": "Token",
    "settings.patAdding": "Adding...",
    "settings.patDelete": "Delete",
    "settings.patDeleteConfirm": "Remove this PAT?",
    "settings.noPats": "No PATs configured. Add one to get started.",
    "settings.patHint": "Adding a PAT will auto-discover orgs and sync data.",
    "settings.patError": "Error",

    // Loading
    "loading": "Loading...",
    "loading.actions": "Loading actions...",
  },
  zh: {
    // StatusBar
    "status.notConnected": "\u672a\u8fde\u63a5",
    "status.orgs": "\u4e2a\u7ec4\u7ec7",
    "status.aiReady": "AI \u5c31\u7eea",
    "status.aiStarting": "AI \u542f\u52a8\u4e2d...",
    "status.syncData": "\u540c\u6b65\u6570\u636e",
    "status.syncing": "\u540c\u6b65\u4e2d...",

    // Chat
    "chat.title": "OctoFinance AI \u667a\u80fd\u8fd0\u7ef4",
    "chat.subtitle": "\u8be2\u95ee\u5173\u4e8e GitHub Copilot \u4f7f\u7528\u60c5\u51b5\u3001\u6210\u672c\u548c\u4f18\u5316\u7684\u4efb\u4f55\u95ee\u9898\u3002",
    "chat.placeholder": "\u8be2\u95ee Copilot \u4f7f\u7528\u60c5\u51b5\u3001\u6210\u672c\u3001\u4e0d\u6d3b\u8dc3\u7528\u6237...",
    "chat.send": "\u53d1\u9001",
    "chat.stop": "\u505c\u6b62",
    "chat.clear": "\u6e05\u7a7a",
    "chat.you": "\u4f60",
    "chat.ai": "OctoFinance AI",

    // Quick Prompts
    "qp.overview": "\u6982\u89c8",
    "qp.overviewPrompt": "\u7ed9\u6211\u4e00\u4e2a\u6240\u6709\u7ec4\u7ec7\u7684 Copilot \u4f7f\u7528\u60c5\u51b5\u548c\u6210\u672c\u6982\u89c8\u3002",
    "qp.inactive": "\u4e0d\u6d3b\u8dc3\u7528\u6237",
    "qp.inactivePrompt": "\u67e5\u627e\u6240\u6709 30 \u5929\u672a\u4f7f\u7528 Copilot \u7684\u7528\u6237\uff0c\u663e\u793a\u6210\u672c\u5f71\u54cd\u3002",
    "qp.costOpt": "\u6210\u672c\u4f18\u5316",
    "qp.costOptPrompt": "\u5206\u6790\u6211\u4eec\u7684 Copilot \u652f\u51fa\uff0c\u63a8\u8350\u51cf\u5c11\u6d6a\u8d39\u7684\u65b9\u6cd5\u3002",
    "qp.roi": "ROI \u5206\u6790",
    "qp.roiPrompt": "\u8ba1\u7b97\u6211\u4eec Copilot \u6295\u8d44\u7684 ROI\u3002\u6211\u4eec\u83b7\u5f97\u4e86\u4ef7\u503c\u5417\uff1f",

    // Sidebar
    "sidebar.overview": "\u6982\u89c8",
    "sidebar.totalSeats": "\u603b\u5e2d\u4f4d",
    "sidebar.active": "\u6d3b\u8dc3",
    "sidebar.inactive": "\u4e0d\u6d3b\u8dc3",
    "sidebar.utilization": "\u4f7f\u7528\u7387",
    "sidebar.monthlyCost": "\u6708\u5ea6\u6210\u672c",
    "sidebar.monthlyWaste": "\u6708\u5ea6\u6d6a\u8d39",
    "sidebar.organizations": "\u7ec4\u7ec7",
    "sidebar.noOrgs": "\u672a\u53d1\u73b0\u7ec4\u7ec7",
    "sidebar.noCopilot": "\u65e0 Copilot",

    // Sort
    "sort.name": "\u540d\u79f0",
    "sort.seats": "\u603b\u5e2d\u4f4d",
    "sort.active": "\u6d3b\u8dc3\u5e2d\u4f4d",
    "sort.inactive": "\u4e0d\u6d3b\u8dc3",
    "sort.waste": "\u6d6a\u8d39",

    // Actions
    "actions.title": "\u5f85\u5904\u7406\u64cd\u4f5c",
    "actions.empty": "\u6682\u65e0\u5f85\u5904\u7406\u5efa\u8bae\u3002\u8bf7\u8ba9 AI \u5206\u6790\u60a8\u7684 Copilot \u4f7f\u7528\u60c5\u51b5\u4ee5\u83b7\u53d6\u4f18\u5316\u5efa\u8bae\u3002",
    "actions.approve": "\u6279\u51c6\u5e76\u6267\u884c",
    "actions.reject": "\u62d2\u7edd",
    "actions.users": "\u7528\u6237",
    "actions.savings": "\u9884\u4f30\u8282\u7701",

    // Console
    "console.title": "\u63a7\u5236\u53f0",
    "console.clear": "\u6e05\u7a7a",
    "console.close": "\u5173\u95ed",
    "console.empty": "\u6682\u65e0\u65e5\u5fd7\u3002\u53d1\u9001\u6d88\u606f\u540e\u53ef\u67e5\u770b AI \u5904\u7406\u8be6\u60c5\u3002",

    // Sessions
    "sessions.title": "\u4f1a\u8bdd",
    "sessions.new": "\u65b0\u5efa\u4f1a\u8bdd",
    "sessions.delete": "\u5220\u9664",
    "sessions.empty": "\u6682\u65e0\u4f1a\u8bdd",

    // Settings
    "settings.title": "\u8bbe\u7f6e",
    "settings.pats": "GitHub \u4e2a\u4eba\u8bbf\u95ee\u4ee4\u724c",
    "settings.addPat": "\u6dfb\u52a0\u4ee4\u724c",
    "settings.patLabel": "\u6807\u7b7e",
    "settings.patToken": "\u4ee4\u724c",
    "settings.patAdding": "\u6dfb\u52a0\u4e2d...",
    "settings.patDelete": "\u5220\u9664",
    "settings.patDeleteConfirm": "\u786e\u8ba4\u79fb\u9664\u6b64\u4ee4\u724c\uff1f",
    "settings.noPats": "\u672a\u914d\u7f6e\u4ee4\u724c\u3002\u8bf7\u6dfb\u52a0\u4e00\u4e2a\u4ee5\u5f00\u59cb\u4f7f\u7528\u3002",
    "settings.patHint": "\u6dfb\u52a0\u4ee4\u724c\u540e\u5c06\u81ea\u52a8\u53d1\u73b0\u7ec4\u7ec7\u5e76\u540c\u6b65\u6570\u636e\u3002",
    "settings.patError": "\u9519\u8bef",

    // Loading
    "loading": "\u52a0\u8f7d\u4e2d...",
    "loading.actions": "\u52a0\u8f7d\u64cd\u4f5c\u4e2d...",
  },
} as const;

type TranslationKey = keyof typeof translations.en;

interface I18nContextValue {
  lang: Lang;
  toggleLang: () => void;
  t: (key: TranslationKey) => string;
}

const I18nContext = createContext<I18nContextValue>({
  lang: "en",
  toggleLang: () => {},
  t: (key) => key,
});

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLang] = useState<Lang>(() => {
    const saved = localStorage.getItem("octofinance-lang");
    return (saved === "en" || saved === "zh") ? saved : "en";
  });

  const toggleLang = useCallback(() => {
    setLang((l) => {
      const next = l === "en" ? "zh" : "en";
      localStorage.setItem("octofinance-lang", next);
      return next;
    });
  }, []);

  const t = useCallback(
    (key: TranslationKey): string => {
      return translations[lang][key] || key;
    },
    [lang]
  );

  return (
    <I18nContext.Provider value={{ lang, toggleLang, t }}>
      {children}
    </I18nContext.Provider>
  );
}

export function useI18n() {
  return useContext(I18nContext);
}
