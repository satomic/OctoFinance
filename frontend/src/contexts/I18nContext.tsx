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
    "settings.patEnterprise": "Enterprise Slug",
    "settings.patEnterpriseHint": "Optional. Required for Cost Center management. Find it in your enterprise URL: github.com/enterprises/YOUR-SLUG",
    "settings.patHint": "Adding a PAT will auto-discover orgs and sync data.",
    "settings.patError": "Error",
    "settings.syncSettings": "Sync Settings",
    "settings.autoSync": "Auto sync on startup",
    "settings.syncCron": "Scheduled sync",
    "settings.cronHint": "Use cron syntax: */30 * * * * (every 30min), 0 */6 * * * (every 6h), 0 0 * * * (daily). Leave empty to disable.",

    // Navigation
    "nav.chat": "Chat",
    "nav.dashboard": "Dashboard",
    "nav.dashMetrics": "Usage Metrics",

    // Cost Center Dashboard
    "ccDash.tab": "Cost Centers",
    "ccDash.title": "Cost Center Dashboard",
    "ccDash.allEnterprises": "All Enterprises",
    "ccDash.allCostCenters": "All Cost Centers",
    "ccDash.stateActive": "Active",
    "ccDash.stateArchived": "Archived",
    "ccDash.stateAll": "All States",
    "ccDash.search": "Search user...",
    "ccDash.noData": "No cost center data. Run Sync Data to fetch enterprise cost centers.",
    "ccDash.totalCostCenters": "Cost Centers",
    "ccDash.totalMembers": "Unique Members",
    "ccDash.sectionCostCenters": "Cost Centers & Members",
    "ccDash.sectionUserMap": "User → Cost Center Mapping",
    "ccDash.colCostCenter": "Cost Center",
    "ccDash.colMembers": "Members",
    "ccDash.colResources": "Resources",
    "ccDash.colUser": "User",
    "ccDash.colSource": "Source",
    "ccDash.colCostCenters": "Cost Centers",
    "ccDash.expandMembers": "Show members",
    "ccDash.colState": "State",

    // Dashboard
    "dashboard.title": "Copilot Usage Dashboard",
    "dashboard.filters": "Filters",
    "dashboard.allOrgs": "All Organizations",
    "dashboard.dailyTrend": "Daily Active Trend",
    "dashboard.featureUsage": "Feature Usage",
    "dashboard.modelUsage": "Model Usage",
    "dashboard.ideUsage": "IDE Distribution",
    "dashboard.topUsers": "Top Active Users",
    "dashboard.noData": "No data available. Please sync data first.",
    "dashboard.noSelection": "No org selected",
    "dashboard.totalChats": "Total Chats",
    "dashboard.prSummaries": "PR Summaries",
    "dashboard.activeUserTrends": "Active User Trends",
    "dashboard.codeProductivity": "Code Productivity",
    "dashboard.locTrend": "LOC Trend",
    "dashboard.acceptRate": "Acceptance Rate",
    "dashboard.langDist": "Language Distribution",
    "dashboard.langCodeGen": "Code Generation by Language",
    "dashboard.codeCompletions": "Code Completions",
    "dashboard.modelPremium": "Model & Premium Requests",
    "dashboard.premiumDetail": "Premium Request Detail",
    "dashboard.ideChart": "IDE Interactions",
    "dashboard.ideDetail": "IDE Detail",
    "dashboard.seatMgmt": "Seat Management",
    "dashboard.userPremium": "Per-User Premium Requests",
    "dashboard.userPremiumTrend": "Daily Premium Requests",
    "dashboard.userPremiumModel": "Model Breakdown",
    "dashboard.userPremiumTable": "User Details",
    "dashboard.uploadCsv": "Upload CSV",
    "dashboard.uploadCsvHint": "Upload premium request usage CSV exported from GitHub",
    "dashboard.csvLatestDate": "Data up to",
    "dashboard.csvNoData": "No CSV data uploaded yet",
    "dashboard.csvUploading": "Uploading...",
    "dashboard.csvUploadSuccess": "Upload successful",
    "dashboard.csvNoDuplicate": "No new data (all records already exist)",
    "dashboard.quotaUsage": "Quota Usage",
    "dashboard.costCenterBreakdown": "Cost Center Breakdown",
    "dashboard.costCenter": "Cost Center",

    // CSV Dashboard
    "csvDash.title": "CSV Report Dashboard",
    "csvDash.tabs.premium": "Premium Requests",
    "csvDash.tabs.usage": "Usage Report",
    "csvDash.filters": "Filters",
    "csvDash.allOrgs": "All Orgs",
    "csvDash.allCostCenters": "All Cost Centers",
    "csvDash.allProducts": "All Products",
    "csvDash.allSkus": "All SKUs",
    "csvDash.noData": "No CSV data. Upload a CSV file to get started.",
    "csvDash.noDataType": "No data for this CSV type yet.",
    "csvDash.dateFrom": "From",
    "csvDash.dateTo": "To",
    "csvDash.totalRequests": "Total Requests",
    "csvDash.totalCost": "Total Cost",
    "csvDash.uniqueUsers": "Unique Users",
    "csvDash.uniqueOrgs": "Unique Orgs",
    "csvDash.totalGross": "Total Gross",
    "csvDash.totalNet": "Total Net",
    "csvDash.totalDiscount": "Total Discount",
    "csvDash.dateRange": "Date Range",
    "csvDash.dailyTrend": "Daily Trend",
    "csvDash.modelBreakdown": "Model Breakdown",
    "csvDash.productBreakdown": "Product Breakdown",
    "csvDash.skuBreakdown": "SKU Breakdown",
    "csvDash.orgBreakdown": "Org Breakdown",
    "csvDash.userTable": "Per-User Details",
    "csvDash.user": "User",
    "csvDash.org": "Org",
    "csvDash.costCenter": "Cost Center",
    "csvDash.requests": "Requests",
    "csvDash.cost": "Cost",
    "csvDash.quota": "Quota",
    "csvDash.quotaUsage": "Quota Usage",
    "csvDash.daysActive": "Days",
    "csvDash.models": "Top Models",
    "csvDash.skus": "SKUs",
    "csvDash.grossAmount": "Gross",
    "csvDash.netAmount": "Net",
    "csvDash.quantity": "Quantity",
    "csvDash.csvType.premium_request": "Premium Request CSV",
    "csvDash.csvType.usage_report": "Usage Report CSV",
    "csvDash.uploadedInfo": "Uploaded",

    // Auth
    "auth.welcome": "Login to OctoFinance",
    "auth.createAccount": "Create your account to get started",
    "auth.username": "Username",
    "auth.password": "Password",
    "auth.confirmPassword": "Confirm Password",
    "auth.passwordMismatch": "Passwords do not match",
    "auth.setup": "Create Account",
    "auth.loginBtn": "Login",
    "auth.logout": "Logout",
    "auth.error": "Username and password are required",

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
    "settings.patEnterprise": "Enterprise Slug",
    "settings.patEnterpriseHint": "\u53ef\u9009\u3002Cost Center \u7ba1\u7406\u6240\u9700\u3002\u5728\u4f01\u4e1a URL \u4e2d\u67e5\u627e\uff1a github.com/enterprises/YOUR-SLUG",
    "settings.patHint": "\u6dfb\u52a0\u4ee4\u724c\u540e\u5c06\u81ea\u52a8\u53d1\u73b0\u7ec4\u7ec7\u5e76\u540c\u6b65\u6570\u636e\u3002",
    "settings.patError": "\u9519\u8bef",
    "settings.syncSettings": "\u540c\u6b65\u8bbe\u7f6e",
    "settings.autoSync": "\u542f\u52a8\u65f6\u81ea\u52a8\u540c\u6b65",
    "settings.syncCron": "\u5b9a\u65f6\u540c\u6b65",
    "settings.cronHint": "Cron \u8bed\u6cd5\uff1a*/30 * * * *\uff08\u6bcf30\u5206\u949f\uff09\u3001 0 */6 * * *\uff08\u6bcf6\u5c0f\u65f6\uff09\u3001 0 0 * * *\uff08\u6bcf\u5929\uff09\u3002\u7559\u7a7a\u5219\u7981\u7528\u3002",

    // Navigation
    "nav.chat": "\u5bf9\u8bdd",
    "nav.dashboard": "\u6570\u636e\u9762\u677f",
    "nav.dashMetrics": "Usage Metrics",

    // Cost Center Dashboard
    "ccDash.tab": "\u6210\u672c\u4e2d\u5fc3",
    "ccDash.title": "\u6210\u672c\u4e2d\u5fc3\u9762\u677f",
    "ccDash.allEnterprises": "\u5168\u90e8\u4f01\u4e1a",
    "ccDash.allCostCenters": "\u5168\u90e8\u6210\u672c\u4e2d\u5fc3",
    "ccDash.stateActive": "\u6d3b\u8dc3",
    "ccDash.stateArchived": "\u5df2\u5f52\u6863",
    "ccDash.stateAll": "\u5168\u90e8\u72b6\u6001",
    "ccDash.search": "\u641c\u7d22\u7528\u6237...",
    "ccDash.noData": "\u6682\u65e0\u6210\u672c\u4e2d\u5fc3\u6570\u636e\uff0c\u8bf7\u6267\u884c\u540c\u6b65\u6570\u636e\u3002",
    "ccDash.totalCostCenters": "\u6210\u672c\u4e2d\u5fc3",
    "ccDash.totalMembers": "\u6d89\u53ca\u7528\u6237",
    "ccDash.sectionCostCenters": "\u6210\u672c\u4e2d\u5fc3\u4e0e\u6210\u5458",
    "ccDash.sectionUserMap": "\u7528\u6237 \u2192 \u6210\u672c\u4e2d\u5fc3\u6620\u5c04",
    "ccDash.colCostCenter": "\u6210\u672c\u4e2d\u5fc3",
    "ccDash.colMembers": "\u6210\u5458\u6570",
    "ccDash.colResources": "\u5173\u8054\u8d44\u6e90",
    "ccDash.colUser": "\u7528\u6237",
    "ccDash.colSource": "\u6765\u6e90",
    "ccDash.colCostCenters": "\u6240\u5c5e\u6210\u672c\u4e2d\u5fc3",
    "ccDash.expandMembers": "\u67e5\u770b\u6210\u5458",
    "ccDash.colState": "\u72b6\u6001",

    // Dashboard
    "dashboard.title": "Copilot \u4f7f\u7528\u6982\u89c8",
    "dashboard.filters": "\u7b5b\u9009",
    "dashboard.allOrgs": "\u5168\u90e8\u7ec4\u7ec7",
    "dashboard.dailyTrend": "\u6bcf\u65e5\u6d3b\u8dc3\u8d8b\u52bf",
    "dashboard.featureUsage": "\u529f\u80fd\u4f7f\u7528\u5206\u5e03",
    "dashboard.modelUsage": "\u6a21\u578b\u4f7f\u7528\u5206\u5e03",
    "dashboard.ideUsage": "IDE \u5206\u5e03",
    "dashboard.topUsers": "\u6d3b\u8dc3\u7528\u6237\u6392\u540d",
    "dashboard.noData": "\u6682\u65e0\u6570\u636e\uff0c\u8bf7\u5148\u540c\u6b65\u6570\u636e\u3002",
    "dashboard.noSelection": "\u672a\u9009\u62e9\u7ec4\u7ec7",
    "dashboard.totalChats": "\u804a\u5929\u603b\u6570",
    "dashboard.prSummaries": "PR \u6458\u8981",
    "dashboard.activeUserTrends": "\u6d3b\u8dc3\u7528\u6237\u8d8b\u52bf",
    "dashboard.codeProductivity": "\u4ee3\u7801\u751f\u4ea7\u529b",
    "dashboard.locTrend": "\u4ee3\u7801\u884c\u6570\u8d8b\u52bf",
    "dashboard.acceptRate": "\u63a5\u53d7\u7387",
    "dashboard.langDist": "\u8bed\u8a00\u5206\u5e03",
    "dashboard.langCodeGen": "\u6309\u8bed\u8a00\u4ee3\u7801\u751f\u6210",
    "dashboard.codeCompletions": "\u4ee3\u7801\u8865\u5168",
    "dashboard.modelPremium": "\u6a21\u578b\u4e0e\u9ad8\u7ea7\u8bf7\u6c42",
    "dashboard.premiumDetail": "\u9ad8\u7ea7\u8bf7\u6c42\u660e\u7ec6",
    "dashboard.ideChart": "IDE \u4ea4\u4e92",
    "dashboard.ideDetail": "IDE \u660e\u7ec6",
    "dashboard.seatMgmt": "\u5e2d\u4f4d\u7ba1\u7406",
    "dashboard.userPremium": "\u7528\u6237\u9ad8\u7ea7\u8bf7\u6c42\u660e\u7ec6",
    "dashboard.userPremiumTrend": "\u6bcf\u65e5\u9ad8\u7ea7\u8bf7\u6c42",
    "dashboard.userPremiumModel": "\u6a21\u578b\u5206\u5e03",
    "dashboard.userPremiumTable": "\u7528\u6237\u660e\u7ec6",
    "dashboard.uploadCsv": "\u4e0a\u4f20 CSV",
    "dashboard.uploadCsvHint": "\u4e0a\u4f20\u4ece GitHub \u5bfc\u51fa\u7684\u9ad8\u7ea7\u8bf7\u6c42\u4f7f\u7528 CSV",
    "dashboard.csvLatestDate": "\u6570\u636e\u622a\u6b62",
    "dashboard.csvNoData": "\u5c1a\u672a\u4e0a\u4f20 CSV \u6570\u636e",
    "dashboard.csvUploading": "\u4e0a\u4f20\u4e2d...",
    "dashboard.csvUploadSuccess": "\u4e0a\u4f20\u6210\u529f",
    "dashboard.csvNoDuplicate": "\u65e0\u65b0\u6570\u636e\uff08\u6240\u6709\u8bb0\u5f55\u5df2\u5b58\u5728\uff09",
    "dashboard.quotaUsage": "\u914d\u989d\u4f7f\u7528",
    "dashboard.costCenterBreakdown": "\u6210\u672c\u4e2d\u5fc3\u5206\u5e03",
    "dashboard.costCenter": "\u6210\u672c\u4e2d\u5fc3",

    // CSV Dashboard
    "csvDash.title": "CSV \u62a5\u8868\u9762\u677f",
    "csvDash.tabs.premium": "\u9ad8\u7ea7\u8bf7\u6c42",
    "csvDash.tabs.usage": "\u4f7f\u7528\u62a5\u8868",
    "csvDash.filters": "\u7b5b\u9009",
    "csvDash.allOrgs": "\u5168\u90e8\u7ec4\u7ec7",
    "csvDash.allCostCenters": "\u5168\u90e8\u6210\u672c\u4e2d\u5fc3",
    "csvDash.allProducts": "\u5168\u90e8\u4ea7\u54c1",
    "csvDash.allSkus": "\u5168\u90e8 SKU",
    "csvDash.noData": "\u6682\u65e0 CSV \u6570\u636e\uff0c\u8bf7\u4e0a\u4f20 CSV \u6587\u4ef6\u3002",
    "csvDash.noDataType": "\u6b64\u7c7b\u578b\u7684 CSV \u6570\u636e\u5c1a\u672a\u4e0a\u4f20\u3002",
    "csvDash.dateFrom": "\u5f00\u59cb",
    "csvDash.dateTo": "\u7ed3\u675f",
    "csvDash.totalRequests": "\u8bf7\u6c42\u603b\u6570",
    "csvDash.totalCost": "\u603b\u6210\u672c",
    "csvDash.uniqueUsers": "\u7528\u6237\u6570",
    "csvDash.uniqueOrgs": "\u7ec4\u7ec7\u6570",
    "csvDash.totalGross": "\u603b\u6bdb\u989d",
    "csvDash.totalNet": "\u603b\u51c0\u989d",
    "csvDash.totalDiscount": "\u603b\u6298\u6263",
    "csvDash.dateRange": "\u65e5\u671f\u8303\u56f4",
    "csvDash.dailyTrend": "\u6bcf\u65e5\u8d8b\u52bf",
    "csvDash.modelBreakdown": "\u6a21\u578b\u5206\u5e03",
    "csvDash.productBreakdown": "\u4ea7\u54c1\u5206\u5e03",
    "csvDash.skuBreakdown": "SKU \u5206\u5e03",
    "csvDash.orgBreakdown": "\u7ec4\u7ec7\u5206\u5e03",
    "csvDash.userTable": "\u7528\u6237\u660e\u7ec6",
    "csvDash.user": "\u7528\u6237",
    "csvDash.org": "\u7ec4\u7ec7",
    "csvDash.costCenter": "\u6210\u672c\u4e2d\u5fc3",
    "csvDash.requests": "\u8bf7\u6c42\u6570",
    "csvDash.cost": "\u6210\u672c",
    "csvDash.quota": "\u914d\u989d",
    "csvDash.quotaUsage": "\u914d\u989d\u4f7f\u7528\u7387",
    "csvDash.daysActive": "\u6d3b\u8dc3\u5929\u6570",
    "csvDash.models": "\u6a21\u578b",
    "csvDash.skus": "SKU",
    "csvDash.grossAmount": "\u6bdb\u989d",
    "csvDash.netAmount": "\u51c0\u989d",
    "csvDash.quantity": "\u6570\u91cf",
    "csvDash.csvType.premium_request": "\u9ad8\u7ea7\u8bf7\u6c42 CSV",
    "csvDash.csvType.usage_report": "\u4f7f\u7528\u62a5\u8868 CSV",
    "csvDash.uploadedInfo": "\u5df2\u4e0a\u4f20",

    // Auth
    "auth.welcome": "\u767b\u5f55 OctoFinance",
    "auth.createAccount": "\u521b\u5efa\u8d26\u6237\u4ee5\u5f00\u59cb\u4f7f\u7528",
    "auth.username": "\u7528\u6237\u540d",
    "auth.password": "\u5bc6\u7801",
    "auth.confirmPassword": "\u786e\u8ba4\u5bc6\u7801",
    "auth.passwordMismatch": "\u4e24\u6b21\u5bc6\u7801\u4e0d\u4e00\u81f4",
    "auth.setup": "\u521b\u5efa\u8d26\u6237",
    "auth.loginBtn": "\u767b\u5f55",
    "auth.logout": "\u9000\u51fa",
    "auth.error": "\u7528\u6237\u540d\u548c\u5bc6\u7801\u4e0d\u80fd\u4e3a\u7a7a",

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
      return (translations[lang] as Record<string, string>)[key] || key;
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
