import { useState, useCallback, useRef, useEffect, type ReactNode } from "react";
import { ThemeProvider } from "./contexts/ThemeContext";
import { I18nProvider, useI18n } from "./contexts/I18nContext";
import { useChat } from "./hooks/useChat";
import { useSessions } from "./hooks/useSessions";
import { useSyncStream } from "./hooks/useSyncStream";
import { ChatInterface } from "./components/ChatInterface";
import { ConsolePanel } from "./components/ConsolePanel";
import { SessionSelector } from "./components/SessionSelector";
import { OverviewPanel } from "./components/OverviewPanel";
import { OrgSelector } from "./components/OrgSelector";
import { ActionPanel } from "./components/ActionPanel";
import { StatusBar } from "./components/StatusBar";
import type { Recommendation } from "./types";
import "./styles/index.css";

const MIN_SIDEBAR = 240;
const MAX_SIDEBAR = 600;
const DEFAULT_SIDEBAR = 320;

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

function AppLayout() {
  const { t } = useI18n();
  const [sidebarWidth, setSidebarWidth] = useState(DEFAULT_SIDEBAR);
  const [consoleOpen, setConsoleOpen] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [collapsed, setCollapsed] = useState({
    overview: false,
    organizations: false,
    sessions: false,
    actions: true,
  });
  const isDragging = useRef(false);
  const startX = useRef(0);
  const startWidth = useRef(0);

  const chat = useChat();
  const sessions = useSessions();

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

  const togglePanel = useCallback((key: keyof typeof collapsed) => {
    setCollapsed((prev) => ({ ...prev, [key]: !prev[key] }));
  }, []);

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
    setCollapsed((prev) => ({ ...prev, actions: false }));

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
  }, [sessions.createSession, sessions.switchSession, chat.clearMessages, chat.clearConsole, handleSendMessage]);

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

  const toggleConsole = useCallback(() => setConsoleOpen((v) => !v), []);

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
          <ChatInterface
            messages={chat.messages}
            isLoading={chat.isLoading}
            sendMessage={handleSendMessage}
            abort={chat.abort}
            clearMessages={chat.clearMessages}
          />
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

function App() {
  return (
    <ThemeProvider>
      <I18nProvider>
        <AppLayout />
      </I18nProvider>
    </ThemeProvider>
  );
}

export default App;
