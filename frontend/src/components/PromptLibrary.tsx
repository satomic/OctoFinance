import { useState, useEffect, useRef } from "react";
import { useI18n } from "../contexts/I18nContext";
import type { SavedPrompt } from "../types";
import type { PromptDraft } from "../hooks/usePrompts";

interface LibraryProps {
  prompts: SavedPrompt[];
  disabled: boolean;
  onInsert: (prompt: SavedPrompt) => void;
  onRun: (prompt: SavedPrompt) => void;
  onNew: () => void;
  onEdit: (prompt: SavedPrompt) => void;
  onDelete: (prompt: SavedPrompt) => Promise<void>;
  onClose: () => void;
}

/** Popover above the chat input listing the saved prompts. */
export function PromptLibrary({ prompts, disabled, onInsert, onRun, onNew, onEdit, onDelete, onClose }: LibraryProps) {
  const { t } = useI18n();
  const [query, setQuery] = useState("");
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onPointerDown = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (panelRef.current?.contains(target) || target.closest(".prompt-library-toggle")) return;
      onClose();
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  const needle = query.trim().toLowerCase();
  const visible = needle
    ? prompts.filter((p) => p.title.toLowerCase().includes(needle) || p.prompt.toLowerCase().includes(needle))
    : prompts;

  const handleDelete = async (p: SavedPrompt) => {
    if (confirmingId !== p.id) {
      setConfirmingId(p.id);
      return;
    }
    setError("");
    try {
      await onDelete(p);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    setConfirmingId(null);
  };

  return (
    <div className="prompt-library" ref={panelRef} role="dialog" aria-label={t("prompts.title")}>
      <div className="prompt-library-header">
        <strong>{t("prompts.title")}</strong>
        <button className="btn btn-small" onClick={onNew}>+ {t("prompts.new")}</button>
      </div>
      {prompts.length > 0 && (
        <input
          className="prompt-library-search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("prompts.search")}
          autoFocus
        />
      )}
      {error && <p className="settings-error">{error}</p>}
      <ul className="prompt-library-list">
        {prompts.length === 0 && <li className="prompt-library-empty">{t("prompts.empty")}</li>}
        {prompts.length > 0 && visible.length === 0 && <li className="prompt-library-empty">{t("prompts.noMatch")}</li>}
        {visible.map((p) => (
          <li key={p.id} className="prompt-library-item">
            <button
              className="prompt-library-main"
              onClick={() => onInsert(p)}
              title={t("prompts.insertHint")}
            >
              <span className="prompt-library-title">
                {p.title}
                {p.shared && (
                  <span className="prompt-badge">
                    {p.is_owner ? t("prompts.shared") : `${t("prompts.sharedBy")} ${p.owner}`}
                  </span>
                )}
              </span>
              <span className="prompt-library-preview">{p.prompt}</span>
            </button>
            <div className="prompt-library-actions">
              <button className="btn btn-small btn-approve" onClick={() => onRun(p)} disabled={disabled}>
                {t("prompts.run")}
              </button>
              {p.is_owner && (
                <>
                  <button className="btn btn-small" onClick={() => onEdit(p)}>{t("prompts.edit")}</button>
                  <button
                    className="btn btn-small btn-reject"
                    onClick={() => handleDelete(p)}
                    onBlur={() => setConfirmingId((id) => (id === p.id ? null : id))}
                  >
                    {confirmingId === p.id ? t("prompts.confirmDelete") : t("prompts.delete")}
                  </button>
                </>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

interface EditorProps {
  initial: PromptDraft;
  isEdit: boolean;
  onSave: (draft: PromptDraft) => Promise<void>;
  onClose: () => void;
}

/** Modal for saving a new prompt or editing one the admin owns. */
export function PromptEditor({ initial, isEdit, onSave, onClose }: EditorProps) {
  const { t } = useI18n();
  const [draft, setDraft] = useState(initial);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      await onSave(draft);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="settings-modal-overlay" onClick={(e) => e.target === e.currentTarget && !saving && onClose()}>
      <div
        className="settings-modal prompt-editor"
        role="dialog"
        aria-modal="true"
        aria-labelledby="prompt-editor-title"
        onKeyDown={(e) => e.key === "Escape" && !saving && onClose()}
      >
        <div className="settings-modal-header">
          <h2 id="prompt-editor-title">{isEdit ? t("prompts.editTitle") : t("prompts.saveTitle")}</h2>
          <button type="button" className="settings-close-btn" aria-label={t("prompts.cancel")} disabled={saving} onClick={onClose}>&times;</button>
        </div>
        <form onSubmit={submit}>
          <div className="settings-modal-body">
            <label className="budget-req-field">
              <span>{t("prompts.fieldTitle")}</span>
              <input
                value={draft.title}
                maxLength={80}
                placeholder={t("prompts.fieldTitleHint")}
                onChange={(e) => setDraft({ ...draft, title: e.target.value })}
                autoFocus
              />
            </label>
            <label className="budget-req-field">
              <span>{t("prompts.fieldPrompt")}</span>
              <textarea
                value={draft.prompt}
                rows={7}
                maxLength={8000}
                required
                onChange={(e) => setDraft({ ...draft, prompt: e.target.value })}
              />
            </label>
            <label className="cc-owner-hard-limit">
              <input
                type="checkbox"
                checked={draft.shared}
                onChange={(e) => setDraft({ ...draft, shared: e.target.checked })}
              />
              <span>{t("prompts.fieldShared")}</span>
            </label>
            {error && <p className="settings-error" role="alert">{error}</p>}
          </div>
          <div className="cc-owner-budget-footer">
            <button type="button" className="btn" disabled={saving} onClick={onClose}>{t("prompts.cancel")}</button>
            <button type="submit" className="btn btn-approve" disabled={saving || !draft.prompt.trim()}>
              {saving ? t("prompts.saving") : t("prompts.save")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
