import { useState, useCallback, useEffect } from "react";
import type { SavedPrompt } from "../types";

export interface PromptDraft {
  title: string;
  prompt: string;
  shared: boolean;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(json.detail || json.error || `HTTP ${res.status}`);
  return json as T;
}

/** The admin's saved chat prompts plus the ones other admins shared. */
export function usePrompts() {
  const [prompts, setPrompts] = useState<SavedPrompt[]>([]);

  const reload = useCallback(async () => {
    try {
      const data = await request<{ prompts: SavedPrompt[] }>("/api/prompts");
      setPrompts(data.prompts);
    } catch {
      setPrompts([]);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    request<{ prompts: SavedPrompt[] }>("/api/prompts")
      .then((data) => !cancelled && setPrompts(data.prompts))
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  const create = useCallback(async (draft: PromptDraft) => {
    const saved = await request<SavedPrompt>("/api/prompts", {
      method: "POST",
      body: JSON.stringify(draft),
    });
    setPrompts((prev) => [saved, ...prev]);
    return saved;
  }, []);

  const update = useCallback(async (id: string, draft: PromptDraft) => {
    const saved = await request<SavedPrompt>(`/api/prompts/${id}`, {
      method: "PUT",
      body: JSON.stringify(draft),
    });
    setPrompts((prev) => prev.map((p) => (p.id === id ? saved : p)));
    return saved;
  }, []);

  const remove = useCallback(async (id: string) => {
    await request(`/api/prompts/${id}`, { method: "DELETE" });
    setPrompts((prev) => prev.filter((p) => p.id !== id));
  }, []);

  // Usage stats only reorder the list; a failure here must not block sending.
  const markUsed = useCallback(async (id: string) => {
    try {
      const saved = await request<SavedPrompt>(`/api/prompts/${id}/use`, { method: "POST" });
      setPrompts((prev) => [saved, ...prev.filter((p) => p.id !== id)]);
    } catch {
      // ignore
    }
  }, []);

  return { prompts, reload, create, update, remove, markUsed };
}
