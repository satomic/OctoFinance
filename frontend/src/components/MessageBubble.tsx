import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessage } from "../types";
import { useI18n } from "../contexts/I18nContext";

interface Props {
  message: ChatMessage;
}

export function MessageBubble({ message }: Props) {
  const { t } = useI18n();
  const isUser = message.role === "user";

  return (
    <div className={`message ${isUser ? "message-user" : "message-assistant"}`}>
      <div className="message-header">
        <span className="message-role">{isUser ? t("chat.you") : t("chat.ai")}</span>
        <span className="message-time">
          {new Date(message.timestamp).toLocaleTimeString()}
        </span>
      </div>
      {message.toolCalls && message.toolCalls.length > 0 && (
        <div className="tool-calls">
          {message.toolCalls.map((tool) => (
            <span key={tool.id} className={`tool-badge ${tool.status}`}>
              {tool.status === "running" ? "\u23F3" : "\u2705"} {tool.name}
            </span>
          ))}
        </div>
      )}
      <div className="message-content">
        {message.content ? (
          isUser ? (
            message.content
          ) : (
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {message.content}
            </ReactMarkdown>
          )
        ) : (
          <span className="typing-indicator">
            <span></span><span></span><span></span>
          </span>
        )}
      </div>
    </div>
  );
}
