import { useState, useCallback, useRef } from "react";
import type { ChatMessage, SSEEvent, ToolCallInfo, ConsoleEntry } from "../types";

let entrySeq = 0;
function nextId() {
  return `ce_${Date.now()}_${++entrySeq}`;
}

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [activeTools, setActiveTools] = useState<ToolCallInfo[]>([]);
  const [consoleLogs, setConsoleLogs] = useState<ConsoleEntry[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const thinkingRef = useRef("");
  const toolNameMap = useRef<Record<string, string>>({});

  const sendMessage = useCallback(async (content: string, sessionId = "default") => {
    const userMsg: ChatMessage = {
      id: Date.now().toString(),
      role: "user",
      content,
      timestamp: Date.now(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setIsLoading(true);
    setActiveTools([]);
    thinkingRef.current = "";

    // Log user message to console
    setConsoleLogs((prev) => [
      ...prev,
      { id: nextId(), timestamp: Date.now(), type: "user", title: `User: ${content.slice(0, 100)}${content.length > 100 ? "..." : ""}` },
    ]);

    const assistantMsg: ChatMessage = {
      id: (Date.now() + 1).toString(),
      role: "assistant",
      content: "",
      timestamp: Date.now(),
      toolCalls: [],
    };
    setMessages((prev) => [...prev, assistantMsg]);

    abortRef.current = new AbortController();

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: content, session_id: sessionId }),
        signal: abortRef.current.signal,
      });

      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      if (!response.body) throw new Error("No response body");

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let fullContent = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const event: SSEEvent = JSON.parse(line.slice(6));
              if (event.type === "delta") {
                fullContent += event.content;
                setMessages((prev) => {
                  const updated = [...prev];
                  const last = updated[updated.length - 1];
                  if (last.role === "assistant") {
                    last.content = fullContent;
                  }
                  return updated;
                });
              } else if (event.type === "message") {
                if (event.content) {
                  fullContent = event.content;
                  setMessages((prev) => {
                    const updated = [...prev];
                    const last = updated[updated.length - 1];
                    if (last.role === "assistant") {
                      last.content = fullContent;
                    }
                    return updated;
                  });
                  // Log final assistant message to console
                  setConsoleLogs((prev) => [
                    ...prev,
                    { id: nextId(), timestamp: Date.now(), type: "assistant" as const, title: `Assistant response (${fullContent.length} chars)` },
                  ]);
                }
              } else if (event.type === "thinking_delta") {
                thinkingRef.current += event.content;
                // Emit a thinking console entry (update last thinking entry or add new)
                const snapshot = thinkingRef.current;
                setConsoleLogs((prev) => {
                  const lastIdx = prev.length - 1;
                  if (lastIdx >= 0 && prev[lastIdx].type === "thinking") {
                    const updated = [...prev];
                    updated[lastIdx] = { ...updated[lastIdx], detail: snapshot };
                    return updated;
                  }
                  return [
                    ...prev,
                    { id: nextId(), timestamp: Date.now(), type: "thinking" as const, title: "Thinking...", detail: snapshot },
                  ];
                });
              } else if (event.type === "tool_start") {
                const toolId = event.tool_call_id || `${event.content}_${Date.now()}`;
                if (event.tool_call_id && event.content) {
                  toolNameMap.current[event.tool_call_id] = event.content;
                }
                const tool: ToolCallInfo = { id: toolId, name: event.content, status: "running" };
                setActiveTools((prev) => {
                  if (prev.some((t) => t.id === toolId)) return prev;
                  return [...prev, tool];
                });
                setMessages((prev) => {
                  const updated = [...prev];
                  const last = updated[updated.length - 1];
                  if (last.role === "assistant") {
                    const existing = last.toolCalls || [];
                    if (existing.some((t) => t.id === toolId)) return updated;
                    last.toolCalls = [...existing, tool];
                  }
                  return updated;
                });
                // Flush thinking if accumulated
                if (thinkingRef.current) {
                  thinkingRef.current = "";
                }
                // Console: tool start with arguments
                setConsoleLogs((prev) => [
                  ...prev,
                  { id: nextId(), timestamp: Date.now(), type: "tool_start" as const, title: `Tool: ${event.content}`, detail: event.detail || undefined },
                ]);
              } else if (event.type === "tool_complete") {
                const toolId = event.tool_call_id;
                const resolvedName = event.content || (toolId && toolNameMap.current[toolId]) || "unknown";
                setActiveTools((prev) =>
                  prev.map((t) => {
                    if (toolId && t.id === toolId) return { ...t, status: "complete" as const };
                    if (!toolId && resolvedName && t.name === resolvedName && t.status === "running")
                      return { ...t, status: "complete" as const };
                    return t;
                  })
                );
                setMessages((prev) => {
                  const updated = [...prev];
                  const last = updated[updated.length - 1];
                  if (last.role === "assistant" && last.toolCalls) {
                    last.toolCalls = last.toolCalls.map((t) => {
                      if (toolId && t.id === toolId) return { ...t, status: "complete" as const };
                      if (!toolId && resolvedName && t.name === resolvedName && t.status === "running")
                        return { ...t, status: "complete" as const };
                      return t;
                    });
                  }
                  return updated;
                });
                // Console: tool complete with result - show preview in title
                const resultPreview = event.detail
                  ? event.detail.length > 80 ? event.detail.slice(0, 80) + "..." : event.detail
                  : "(empty)";
                setConsoleLogs((prev) => [
                  ...prev,
                  { id: nextId(), timestamp: Date.now(), type: "tool_complete" as const, title: `${resolvedName}: ${resultPreview}`, detail: event.detail || undefined },
                ]);
              } else if (event.type === "usage") {
                setConsoleLogs((prev) => [
                  ...prev,
                  { id: nextId(), timestamp: Date.now(), type: "usage" as const, title: `Model: ${event.content}`, detail: event.detail || undefined },
                ]);
              } else if (event.type === "error") {
                fullContent += `\n\n[Error: ${event.content}]`;
                setMessages((prev) => {
                  const updated = [...prev];
                  const last = updated[updated.length - 1];
                  if (last.role === "assistant") {
                    last.content = fullContent;
                  }
                  return updated;
                });
                setConsoleLogs((prev) => [
                  ...prev,
                  { id: nextId(), timestamp: Date.now(), type: "error" as const, title: `Error: ${event.content}` },
                ]);
              }
            } catch {
              // Skip malformed SSE data
            }
          }
        }
      }
    } catch (err: any) {
      if (err.name !== "AbortError") {
        setMessages((prev) => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (last.role === "assistant") {
            last.content = `Error: ${err.message}`;
          }
          return updated;
        });
        setConsoleLogs((prev) => [
          ...prev,
          { id: nextId(), timestamp: Date.now(), type: "error" as const, title: `Connection error: ${err.message}` },
        ]);
      }
    } finally {
      setIsLoading(false);
      setActiveTools([]);
      abortRef.current = null;
    }
  }, []);

  const abort = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const clearMessages = useCallback(() => {
    setMessages([]);
  }, []);

  const clearConsole = useCallback(() => {
    setConsoleLogs([]);
  }, []);

  const loadMessages = useCallback(async (sessionId: string) => {
    try {
      const res = await fetch(`/api/sessions/${sessionId}/messages`);
      if (res.ok) {
        const data = await res.json();
        const loaded: ChatMessage[] = data.map((m: any) => ({
          id: m.id || String(m.timestamp),
          role: m.role,
          content: m.content,
          timestamp: m.timestamp,
        }));
        setMessages(loaded);
      }
    } catch {
      // Silently fail
    }
  }, []);

  const setMessagesDirectly = useCallback((msgs: ChatMessage[]) => {
    setMessages(msgs);
  }, []);

  return { messages, isLoading, activeTools, consoleLogs, sendMessage, abort, clearMessages, clearConsole, loadMessages, setMessagesDirectly };
}
