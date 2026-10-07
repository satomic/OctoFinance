import { useState, useRef, useEffect, useCallback } from "react";
import { useI18n } from "../contexts/I18nContext";
import { useUIState } from "../contexts/UIStateContext";
import { useChatModels } from "../hooks/useData";
import { usePrompts, type PromptDraft } from "../hooks/usePrompts";
import { MessageBubble } from "./MessageBubble";
import { PromptEditor, PromptLibrary } from "./PromptLibrary";
import type { ChatMessage, SavedPrompt } from "../types";

interface Props {
  messages: ChatMessage[];
  isLoading: boolean;
  sendMessage: (content: string, sessionId?: string, model?: string) => Promise<void>;
  abort: () => void;
  clearMessages: () => void;
}

export function ChatInterface({ messages, isLoading, sendMessage, abort, clearMessages }: Props) {
  const { t } = useI18n();
  const ui = useUIState();
  const models = useChatModels();
  const model = ui.chatModel;
  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const library = usePrompts();
  const [libraryOpen, setLibraryOpen] = useState(false);
  // The prompt being edited (with its id), or a new draft (id null)
  const [editing, setEditing] = useState<{ id: string | null; draft: PromptDraft } | null>(null);
  const closeLibrary = useCallback(() => setLibraryOpen(false), []);

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
    sendMessage(text, undefined, model);
  };

  const insertPrompt = (p: SavedPrompt) => {
    setInput(p.prompt);
    setLibraryOpen(false);
    library.markUsed(p.id);
    inputRef.current?.focus();
  };

  const runPrompt = (p: SavedPrompt) => {
    if (isLoading) return;
    setLibraryOpen(false);
    library.markUsed(p.id);
    sendMessage(p.prompt, undefined, model);
  };

  const openEditor = (prompt: string, p?: SavedPrompt) => {
    setLibraryOpen(false);
    setEditing(p
      ? { id: p.id, draft: { title: p.title, prompt: p.prompt, shared: p.shared } }
      : { id: null, draft: { title: "", prompt, shared: false } });
  };

  const savePrompt = async (draft: PromptDraft) => {
    if (editing?.id) await library.update(editing.id, draft);
    else await library.create(draft);
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
                  onClick={() => sendMessage(qp.prompt, undefined, model)}
                  disabled={isLoading}
                >
                  {qp.label}
                </button>
              ))}
            </div>
            {library.prompts.length > 0 && (
              <div className="quick-prompts saved-quick-prompts">
                <span className="saved-quick-prompts-label">{t("prompts.title")}</span>
                {library.prompts.slice(0, 8).map((p) => (
                  <button
                    key={p.id}
                    className="quick-prompt-btn"
                    onClick={() => runPrompt(p)}
                    disabled={isLoading}
                    title={p.prompt}
                  >
                    {p.title}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        {messages.map((msg) => (
          <MessageBubble
            key={msg.id}
            message={msg}
            onSavePrompt={msg.role === "user" ? () => openEditor(msg.content) : undefined}
          />
        ))}
        <div ref={messagesEndRef} />
      </div>
      <div className="chat-input-area">
        {libraryOpen && (
          <PromptLibrary
            prompts={library.prompts}
            disabled={isLoading}
            onInsert={insertPrompt}
            onRun={runPrompt}
            onNew={() => openEditor(input.trim())}
            onEdit={(p) => openEditor(p.prompt, p)}
            onDelete={(p) => library.remove(p.id)}
            onClose={closeLibrary}
          />
        )}
        {messages.length > 0 && (
          <button className="clear-btn" onClick={clearMessages} title={t("chat.clear")}>
            {t("chat.clear")}
          </button>
        )}
        <select
          className="chat-model-select"
          value={model}
          onChange={(e) => ui.patch({ chatModel: e.target.value })}
          disabled={isLoading}
          title={t("chat.modelHint")}
        >
          <option value="">{t("chat.modelAuto")}</option>
          {models.filter((m) => m.id !== "auto").map((m) => (
            <option key={m.id} value={m.id}>{m.name}</option>
          ))}
        </select>
        <button
          className={`clear-btn prompt-library-toggle ${libraryOpen ? "active" : ""}`}
          onClick={() => {
            if (!libraryOpen) library.reload();
            setLibraryOpen((open) => !open);
          }}
          title={t("prompts.openHint")}
          aria-expanded={libraryOpen}
        >
          {t("prompts.button")}
        </button>
        <textarea
          ref={inputRef}
          className="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={t("chat.placeholder")}
          rows={1}
          disabled={isLoading}
        />
        <button
          className="clear-btn"
          onClick={() => openEditor(input.trim())}
          disabled={!input.trim()}
          title={t("prompts.saveHint")}
        >
          {t("prompts.saveShort")}
        </button>
        {isLoading ? (
          <button className="send-btn stop-btn" onClick={abort}>{t("chat.stop")}</button>
        ) : (
          <button className="send-btn" onClick={handleSend} disabled={!input.trim()}>
            {t("chat.send")}
          </button>
        )}
      </div>
      {editing && (
        <PromptEditor
          initial={editing.draft}
          isEdit={editing.id !== null}
          onSave={savePrompt}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}
