import { useEffect, useRef, useState } from "react";
import { useI18n } from "../contexts/I18nContext";
import type { ConsoleEntry } from "../types";

interface Props {
  entries: ConsoleEntry[];
  onClose: () => void;
  onClear: () => void;
}

const TYPE_LABELS: Record<ConsoleEntry["type"], string> = {
  tool_start: "TOOL",
  tool_complete: "RESULT",
  thinking: "THINK",
  usage: "USAGE",
  error: "ERROR",
  user: "USER",
  assistant: "AI",
  sync: "SYNC",
};

const TYPE_COLORS: Record<ConsoleEntry["type"], string> = {
  tool_start: "var(--warning)",
  tool_complete: "var(--success)",
  thinking: "var(--accent)",
  usage: "var(--text-muted)",
  error: "var(--danger)",
  user: "var(--text-secondary)",
  assistant: "var(--accent)",
  sync: "var(--info, #2196f3)",
};

function formatTime(ts: number) {
  return new Date(ts).toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function tryFormatJson(s: string | undefined): string | undefined {
  if (!s) return undefined;
  try {
    const obj = JSON.parse(s);
    return JSON.stringify(obj, null, 2);
  } catch {
    return s;
  }
}

function ConsoleEntryRow({ entry }: { entry: ConsoleEntry }) {
  const [expanded, setExpanded] = useState(false);
  const hasDetail = !!entry.detail;
  const formattedDetail = tryFormatJson(entry.detail);

  return (
    <div className={`console-entry console-entry-${entry.type}`}>
      <div className="console-entry-header" onClick={() => hasDetail && setExpanded(!expanded)}>
        <span className="console-time">{formatTime(entry.timestamp)}</span>
        <span className="console-type-badge" style={{ color: TYPE_COLORS[entry.type] }}>
          [{TYPE_LABELS[entry.type]}]
        </span>
        <span className="console-title">{entry.title}</span>
        {hasDetail && (
          <span className="console-expand">{expanded ? "\u25BC" : "\u25B6"}</span>
        )}
      </div>
      {expanded && formattedDetail && (
        <pre className="console-detail">{formattedDetail}</pre>
      )}
    </div>
  );
}

export function ConsolePanel({ entries, onClose, onClear }: Props) {
  const { t } = useI18n();
  const bottomRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  useEffect(() => {
    if (autoScroll) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [entries, autoScroll]);

  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    const isAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    setAutoScroll(isAtBottom);
  };

  return (
    <div className="console-panel">
      <div className="console-header">
        <div className="console-header-left">
          <span className="console-title-text">{t("console.title")}</span>
          <span className="console-count">{entries.length}</span>
        </div>
        <div className="console-header-right">
          <button className="console-btn" onClick={onClear} title={t("console.clear")}>
            {t("console.clear")}
          </button>
          <button className="console-btn console-btn-close" onClick={onClose} title={t("console.close")}>
            &times;
          </button>
        </div>
      </div>
      <div className="console-body" onScroll={handleScroll}>
        {entries.length === 0 && (
          <div className="console-empty">{t("console.empty")}</div>
        )}
        {entries.map((entry) => (
          <ConsoleEntryRow key={entry.id} entry={entry} />
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
