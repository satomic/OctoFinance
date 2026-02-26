import { useState, useCallback, useRef, useEffect, type ReactNode } from "react";
import { ThemeProvider } from "./contexts/ThemeContext";
import { I18nProvider, useI18n } from "./contexts/I18nContext";
import { UIStateProvider, useUIState } from "./contexts/UIStateContext";
import { useChat } from "./hooks/useChat";
import { useSessions } from "./hooks/useSessions";
import { useSyncStream } from "./hooks/useSyncStream";
import { ChatInterface } from "./components/ChatInterface";
import { Dashboard } from "./components/Dashboard";
import { ConsolePanel } from "./components/ConsolePanel";
import { SessionSelector } from "./components/SessionSelector";
import { OverviewPanel } from "./components/OverviewPanel";
import { OrgSelector } from "./components/OrgSelector";
import { ActionPanel } from "./components/ActionPanel";
import { StatusBar } from "./components/StatusBar";
import { LoginPage } from "./components/LoginPage";
import type { Recommendation } from "./types";
import "./styles/index.css";

const MIN_SIDEBAR = 240;
const MAX_SIDEBAR = 600;

interface SidebarPanelProps {
  title: string;
  collapsed: boolean;
  onToggle: () => void;
  extra?: ReactNode;
  children: ReactNode;
}

function SidebarPanel({ title, collapsed, onToggle, extra, children }: SidebarPanelProps) {
  return (
    <div className={`sidebar-panel ${collapsed ? "sidebar-panel-collapsed" : "sidebar-panel-expanded"}`}>
      <div className="sidebar-panel-header" onClick={onToggle}>
        <span className="sidebar-panel-chevron">{collapsed ? "\u25B6" : "\u25BC"}</span>
        <span className="sidebar-panel-title">{title}</span>
        {extra && (
          <span className="sidebar-panel-extra" onClick={(e) => e.stopPropagation()}>
            {extra}
          </span>
        )}
      </div>
      {!collapsed && (
        <div className="sidebar-panel-body">
          {children}
        </div>
      )}
    </div>
  );
}

function AppLayout({ onLogout }: { onLogout: () => void }) {
  const { t } = useI18n();
  const ui = useUIState();
  const sidebarWidth = ui.sidebarWidth;
  const setSidebarWidth = useCallback((w: number) => ui.patch({ sidebarWidth: w }), [ui.patch]);
  const consoleOpen = ui.consoleOpen;
  const setConsoleOpen = useCallback((v: boolean) => ui.patch({ consoleOpen: v }), [ui.patch]);
  const currentView = ui.currentView;
  const setCurrentView = useCallback((v: "chat" | "dashboard") => ui.patch({ currentView: v }), [ui.patch]);
  const [refreshKey, setRefreshKey] = useState(0);
  const collapsed = ui.sidebarCollapsed;
  const isDragging = useRef(false);
  const startX = useRef(0);
  const startWidth = useRef(0);

  const chat = useChat();
  const sessions = useSessions();
  const initialLoadRef = useRef(false);

  // On mount, load messages for persisted session
  useEffect(() => {
    if (!initialLoadRef.current && sessions.currentSessionId && sessions.sessions.length > 0) {
      initialLoadRef.current = true;
      const exists = sessions.sessions.some((s) => s.session_id === sessions.currentSessionId);
      if (exists) {
        chat.loadMessages(sessions.currentSessionId);
      }
    }
  }, [sessions.currentSessionId, sessions.sessions]); // eslint-disable-line react-hooks/exhaustive-deps

  // Connect to sync SSE stream — push sync logs into console, track syncing state
  const { syncing, setOnSyncComplete } = useSyncStream(chat.addConsoleLog);

  // When sync completes, refresh sidebar data
  useEffect(() => {
    setOnSyncComplete(() => {
      setRefreshKey((k) => k + 1);
    });
  }, [setOnSyncComplete]);

  // Auto-open console when sync starts
  useEffect(() => {
    if (syncing) {
      setConsoleOpen(true);
    }
  }, [syncing]);

  const togglePanel = useCallback((key: string) => {
    ui.patch({ sidebarCollapsed: { ...ui.sidebarCollapsed, [key]: !ui.sidebarCollapsed[key] } });
  }, [ui.patch, ui.sidebarCollapsed]);

  // Wrap sendMessage to pass current session id and refresh session list after
  const handleSendMessage = useCallback(async (content: string) => {
    const sid = sessions.currentSessionId || "default";
    await chat.sendMessage(content, sid);
    sessions.loadSessions();
    setRefreshKey((k) => k + 1);
  }, [chat.sendMessage, sessions.currentSessionId, sessions.loadSessions]);

  // Switch session: load messages from backend, clear console
  const handleSwitchSession = useCallback(async (sessionId: string) => {
    sessions.switchSession(sessionId);
    await chat.loadMessages(sessionId);
    chat.clearConsole();
  }, [sessions.switchSession, chat.loadMessages, chat.clearConsole]);

  // Create new session: create on backend, switch to it, clear messages
  const handleCreateSession = useCallback(async () => {
    const session = await sessions.createSession();
    if (session) {
      sessions.switchSession(session.session_id);
      chat.clearMessages();
      chat.clearConsole();
    }
  }, [sessions.createSession, sessions.switchSession, chat.clearMessages, chat.clearConsole]);

  // Delete session
  const handleDeleteSession = useCallback(async (sessionId: string) => {
    await sessions.deleteSession(sessionId);
    // If we deleted the current session, clear the chat
    if (sessions.currentSessionId === sessionId) {
      chat.clearMessages();
      chat.clearConsole();
    }
  }, [sessions.deleteSession, sessions.currentSessionId, chat.clearMessages, chat.clearConsole]);

  // Rename session
  const handleRenameSession = useCallback(async (sessionId: string, title: string) => {
    await sessions.updateSessionTitle(sessionId, title);
  }, [sessions.updateSessionTitle]);

  // Execute action via Copilot session: approve → create session → send prompt → SSE streaming
  const handleExecuteAction = useCallback(async (rec: Recommendation) => {
    // 1. Approve the recommendation on backend (mark as approved)
    try {
      const res = await fetch("/api/actions/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ recommendation_id: rec.id }),
      });
      const data = await res.json();
      if (data.error) {
        console.error("Failed to approve:", data.error);
        return;
      }
    } catch (err) {
      console.error("Failed to approve recommendation:", err);
      return;
    }

    // 2. Create a new session for executing this action
    const session = await sessions.createSession(`Action: ${rec.type.replace(/_/g, " ")}`);
    if (!session) return;

    // 3. Switch to the new session
    sessions.switchSession(session.session_id);
    chat.clearMessages();
    chat.clearConsole();

    // 4. Expand actions panel to collapsed=false so user sees update
    ui.patch({ sidebarCollapsed: { ...ui.sidebarCollapsed, actions: false } });

    // 5. Build execution prompt
    let prompt = "";
    if (rec.type === "remove_seats") {
      prompt = `Please execute the following approved admin action directly without asking for confirmation:\n- Action: Remove Copilot seats\n- Organization: ${rec.org}\n- Users: ${rec.affected_users.join(", ")}\n- Reason: ${rec.description}\nExecute now using the remove_user_seat or batch_remove_seats tool.`;
    } else {
      prompt = `Please execute the following approved admin action directly without asking for confirmation:\n- Action: ${rec.type}\n- Organization: ${rec.org}\n- Users: ${rec.affected_users.join(", ")}\n- Description: ${rec.description}\nExecute now.`;
    }

    // 6. Send the prompt (reuse existing SSE chat mechanism)
    await handleSendMessage(prompt);

    // 7. Refresh actions panel
    setRefreshKey((k) => k + 1);
  }, [sessions.createSession, sessions.switchSession, chat.clearMessages, chat.clearConsole, handleSendMessage, ui.patch, ui.sidebarCollapsed]);

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    isDragging.current = true;
    startX.current = e.clientX;
    startWidth.current = sidebarWidth;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }, [sidebarWidth]);

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (!isDragging.current) return;
      const delta = e.clientX - startX.current;
      const newWidth = Math.min(MAX_SIDEBAR, Math.max(MIN_SIDEBAR, startWidth.current + delta));
      setSidebarWidth(newWidth);
    };

    const onMouseUp = () => {
      if (!isDragging.current) return;
      isDragging.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };

    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
    return () => {
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
    };
  }, []);

  const toggleConsole = useCallback(() => ui.patch({ consoleOpen: !ui.consoleOpen }), [ui.patch, ui.consoleOpen]);

  const handlePATChange = useCallback(() => {
    setRefreshKey((k) => k + 1);
  }, []);

  return (
    <div className="app">
      <StatusBar
        consoleOpen={consoleOpen}
        onToggleConsole={toggleConsole}
        onPATChange={handlePATChange}
        syncing={syncing}
        currentView={currentView}
        onViewChange={setCurrentView}
        onLogout={onLogout}
      />
      <div className="app-body">
        <aside className="sidebar" style={{ width: sidebarWidth }}>
          <SidebarPanel
            title={t("sidebar.overview")}
            collapsed={collapsed.overview}
            onToggle={() => togglePanel("overview")}
          >
            <OverviewPanel key={refreshKey} />
          </SidebarPanel>
          <SidebarPanel
            title={t("sidebar.organizations")}
            collapsed={collapsed.organizations}
            onToggle={() => togglePanel("organizations")}
          >
            <OrgSelector key={refreshKey} />
          </SidebarPanel>
          <SidebarPanel
            title={t("sessions.title")}
            collapsed={collapsed.sessions}
            onToggle={() => togglePanel("sessions")}
            extra={
              <button className="session-new-btn" onClick={handleCreateSession} title={t("sessions.new")}>
                +
              </button>
            }
          >
            <SessionSelector
              sessions={sessions.sessions}
              currentSessionId={sessions.currentSessionId}
              onSwitch={handleSwitchSession}
              onCreate={handleCreateSession}
              onDelete={handleDeleteSession}
              onRename={handleRenameSession}
            />
          </SidebarPanel>
          <SidebarPanel
            title={t("actions.title")}
            collapsed={collapsed.actions}
            onToggle={() => togglePanel("actions")}
          >
            <ActionPanel key={refreshKey} onExecute={handleExecuteAction} />
          </SidebarPanel>
        </aside>
        <div className="resizer" onMouseDown={onMouseDown} />
        <main className="main-content">
          {currentView === "chat" ? (
            <ChatInterface
              messages={chat.messages}
              isLoading={chat.isLoading}
              sendMessage={handleSendMessage}
              abort={chat.abort}
              clearMessages={chat.clearMessages}
            />
          ) : (
            <Dashboard refreshKey={refreshKey} />
          )}
          {consoleOpen && (
            <ConsolePanel
              entries={chat.consoleLogs}
              onClose={() => setConsoleOpen(false)}
              onClear={chat.clearConsole}
            />
          )}
        </main>
      </div>
    </div>
  );
}

function AuthGate() {
  const [authStatus, setAuthStatus] = useState<{
    setup_required: boolean;
    authenticated: boolean;
  } | null>(null);

  const checkAuth = useCallback(() => {
    fetch("/api/auth/status")
      .then((r) => r.json())
      .then(setAuthStatus)
      .catch(() => setAuthStatus({ setup_required: false, authenticated: false }));
  }, []);

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  if (!authStatus) {
    return null; // loading
  }

  if (!authStatus.authenticated) {
    return <LoginPage setupRequired={authStatus.setup_required} onLogin={checkAuth} />;
  }

  return <AppLayout onLogout={checkAuth} />;
}

function App() {
  return (
    <ThemeProvider>
      <I18nProvider>
        <UIStateProvider>
          <AuthGate />
        </UIStateProvider>
      </I18nProvider>
    </ThemeProvider>
  );
}

export default App;
