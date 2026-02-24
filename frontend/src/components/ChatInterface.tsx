import { useState, useRef, useEffect } from "react";
import { useI18n } from "../contexts/I18nContext";
import { MessageBubble } from "./MessageBubble";
import type { ChatMessage } from "../types";

interface Props {
  messages: ChatMessage[];
  isLoading: boolean;
  sendMessage: (content: string, sessionId?: string) => Promise<void>;
  abort: () => void;
  clearMessages: () => void;
}

export function ChatInterface({ messages, isLoading, sendMessage, abort, clearMessages }: Props) {
  const { t } = useI18n();
  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const quickPrompts = [
    { label: t("qp.overview"), prompt: t("qp.overviewPrompt") },
    { label: t("qp.inactive"), prompt: t("qp.inactivePrompt") },
    { label: t("qp.costOpt"), prompt: t("qp.costOptPrompt") },
    { label: t("qp.roi"), prompt: t("qp.roiPrompt") },
  ];

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = () => {
    const text = input.trim();
    if (!text || isLoading) return;
    setInput("");
    sendMessage(text);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="chat-interface">
      <div className="chat-messages">
        {messages.length === 0 && (
          <div className="chat-welcome">
            <h2>{t("chat.title")}</h2>
            <p>{t("chat.subtitle")}</p>
            <div className="quick-prompts">
              {quickPrompts.map((qp) => (
                <button
                  key={qp.label}
                  className="quick-prompt-btn"
                  onClick={() => sendMessage(qp.prompt)}
                  disabled={isLoading}
                >
                  {qp.label}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}
        <div ref={messagesEndRef} />
      </div>
      <div className="chat-input-area">
        {messages.length > 0 && (
          <button className="clear-btn" onClick={clearMessages} title={t("chat.clear")}>
            {t("chat.clear")}
          </button>
        )}
        <textarea
          className="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={t("chat.placeholder")}
          rows={1}
          disabled={isLoading}
        />
        {isLoading ? (
          <button className="send-btn stop-btn" onClick={abort}>{t("chat.stop")}</button>
        ) : (
          <button className="send-btn" onClick={handleSend} disabled={!input.trim()}>
            {t("chat.send")}
          </button>
        )}
      </div>
    </div>
  );
}
