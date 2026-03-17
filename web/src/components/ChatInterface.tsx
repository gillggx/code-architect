/**
 * ChatInterface — streaming chat UI for Code Architect Agent.
 *
 * Connects to POST /api/chat via SSE (text/event-stream) so the LLM
 * response streams in token-by-token.
 *
 * Uses the project selected in the global store as RAG context.
 */

import React, { useState, useRef, useEffect, useCallback } from 'react';
import { useProjects } from '../store/app';

// ─── Types ───────────────────────────────────────────────────────────────────

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  streaming?: boolean;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function uid(): string {
  return Math.random().toString(36).slice(2);
}

/** Generate a stable session ID for this browser tab */
const SESSION_ID: string = (() => {
  const key = 'ca_session_id';
  let id = sessionStorage.getItem(key);
  if (!id) { id = uid(); sessionStorage.setItem(key, id); }
  return id;
})();

// ─── Component ───────────────────────────────────────────────────────────────

const ChatInterface: React.FC = () => {
  const { selected: selectedProject } = useProjects();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Auto-scroll to latest message
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text || isStreaming) return;

    // Append user message
    const userMsg: Message = { id: uid(), role: 'user', content: text };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setIsStreaming(true);

    // Placeholder for streaming assistant reply
    const assistantId = uid();
    setMessages(prev => [
      ...prev,
      { id: assistantId, role: 'assistant', content: '', streaming: true },
    ]);

    abortRef.current = new AbortController();

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          project_id: selectedProject?.project_id ?? null,
          session_id: SESSION_ID,
        }),
        signal: abortRef.current.signal,
      });

      if (!res.ok || !res.body) {
        throw new Error(`HTTP ${res.status}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // Parse SSE lines
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';   // keep incomplete line

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const raw = line.slice(6).trim();
          if (!raw) continue;

          try {
            const event = JSON.parse(raw);
            if (event.type === 'chunk') {
              setMessages(prev =>
                prev.map(m =>
                  m.id === assistantId
                    ? { ...m, content: m.content + event.data }
                    : m,
                ),
              );
            } else if (event.type === 'done' || event.type === 'error') {
              break;
            }
          } catch {
            // ignore malformed SSE lines
          }
        }
      }
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        setMessages(prev =>
          prev.map(m =>
            m.id === assistantId
              ? { ...m, content: `[Error: ${err.message}]` }
              : m,
          ),
        );
      }
    } finally {
      setMessages(prev =>
        prev.map(m =>
          m.id === assistantId ? { ...m, streaming: false } : m,
        ),
      );
      setIsStreaming(false);
    }
  }, [input, isStreaming, selectedProject]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const stopStreaming = () => {
    abortRef.current?.abort();
  };

  const clearChat = () => {
    if (!isStreaming) setMessages([]);
  };

  // ─── Render ──────────────────────────────────────────────────────────────

  return (
    <div className="chat-interface">
      {/* Header */}
      <div className="chat-header">
        <span className="chat-title">Chat with Code Architect</span>
        {selectedProject && (
          <span className="chat-project-badge">
            📁 {selectedProject.project_path.split('/').pop()}
          </span>
        )}
        {!selectedProject && (
          <span className="chat-project-badge chat-project-none">
            No project selected — using general knowledge
          </span>
        )}
        <button className="chat-clear-btn" onClick={clearChat} disabled={isStreaming}>
          Clear
        </button>
      </div>

      {/* Messages */}
      <div className="chat-messages">
        {messages.length === 0 && (
          <div className="chat-empty">
            <p>Ask anything about your codebase architecture, patterns, or feasibility.</p>
            <p className="chat-hint">
              {selectedProject
                ? 'Context loaded from analyzed project memory.'
                : 'Select and analyze a project first for code-grounded answers.'}
            </p>
          </div>
        )}

        {messages.map(msg => (
          <div key={msg.id} className={`chat-message chat-message-${msg.role}`}>
            <div className="chat-bubble">
              <MessageContent content={msg.content} streaming={msg.streaming} />
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="chat-input-row">
        <textarea
          className="chat-input"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about architecture, patterns, feasibility… (Enter to send)"
          rows={2}
          disabled={isStreaming}
        />
        {isStreaming ? (
          <button className="chat-send-btn chat-stop-btn" onClick={stopStreaming}>
            ■ Stop
          </button>
        ) : (
          <button
            className="chat-send-btn"
            onClick={sendMessage}
            disabled={!input.trim()}
          >
            Send
          </button>
        )}
      </div>
    </div>
  );
};

// ─── MessageContent — renders markdown-ish text with code blocks ─────────────

const MessageContent: React.FC<{ content: string; streaming?: boolean }> = ({
  content,
  streaming,
}) => {
  // Split on fenced code blocks
  const parts = content.split(/(```[\s\S]*?```)/g);

  return (
    <span>
      {parts.map((part, i) => {
        if (part.startsWith('```')) {
          const body = part.replace(/^```[^\n]*\n?/, '').replace(/```$/, '');
          return (
            <pre key={i} className="chat-code-block">
              <code>{body}</code>
            </pre>
          );
        }
        return <span key={i} style={{ whiteSpace: 'pre-wrap' }}>{part}</span>;
      })}
      {streaming && <span className="chat-cursor">▌</span>}
    </span>
  );
};

export default ChatInterface;
