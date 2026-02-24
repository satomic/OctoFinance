import { useState } from "react";
import { useI18n } from "../contexts/I18nContext";
import type { SessionInfo } from "../types";

interface Props {
  sessions: SessionInfo[];
  currentSessionId: string | null;
  onSwitch: (sessionId: string) => void;
  onCreate: () => void;
  onDelete: (sessionId: string) => void;
  onRename: (sessionId: string, title: string) => void;
}

function formatDate(iso: string) {
  const d = new Date(iso);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  if (diffDay < 7) return `${diffDay}d ago`;
  return d.toLocaleDateString();
}

export function SessionSelector({ sessions, currentSessionId, onSwitch, onCreate, onDelete, onRename }: Props) {
  const { t } = useI18n();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");

  const startEdit = (session: SessionInfo) => {
    setEditingId(session.session_id);
    setEditTitle(session.title);
  };

  const commitEdit = () => {
    if (editingId && editTitle.trim()) {
      onRename(editingId, editTitle.trim());
    }
    setEditingId(null);
    setEditTitle("");
  };

  const handleEditKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      commitEdit();
    } else if (e.key === "Escape") {
      setEditingId(null);
      setEditTitle("");
    }
  };

  return (
    <div className="session-selector">
      <div className="session-list">
        {sessions.length === 0 && (
          <div className="session-empty">{t("sessions.empty")}</div>
        )}
        {sessions.map((s) => (
          <div
            key={s.session_id}
            className={`session-item ${s.session_id === currentSessionId ? "session-item-active" : ""}`}
            onClick={() => onSwitch(s.session_id)}
          >
            {editingId === s.session_id ? (
              <input
                className="session-edit-input"
                value={editTitle}
                onChange={(e) => setEditTitle(e.target.value)}
                onBlur={commitEdit}
                onKeyDown={handleEditKeyDown}
                autoFocus
                onClick={(e) => e.stopPropagation()}
              />
            ) : (
              <>
                <div className="session-item-main">
                  <span
                    className="session-item-title"
                    onDoubleClick={(e) => {
                      e.stopPropagation();
                      startEdit(s);
                    }}
                  >
                    {s.title}
                  </span>
                  <span className="session-item-meta">
                    {s.message_count > 0 && <span>{s.message_count} msgs</span>}
                    <span>{formatDate(s.updated_at)}</span>
                  </span>
                </div>
                <div className="session-actions">
                  <button
                    className="session-delete-btn"
                    onClick={(e) => {
                      e.stopPropagation();
                      onDelete(s.session_id);
                    }}
                    title={t("sessions.delete")}
                  >
                    &times;
                  </button>
                </div>
              </>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
