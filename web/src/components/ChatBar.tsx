/**
 * ChatBar — fixed bottom bar with a chat input and floating overlay.
 *
 * - POST /api/chat with SSE streaming
 * - Overlay shows conversation history (position: absolute, bottom of chatbar)
 * - Toggle overlay with chat icon button
 */

import React, { useState, useRef, useEffect } from 'react';
import { useChat, useUI, useJob, ChatMessage } from '../store/app';

// ---------------------------------------------------------------------------
// Single message bubble
// ---------------------------------------------------------------------------
const MessageBubble: React.FC<{ msg: ChatMessage }> = ({ msg }) => (
  <div className={`chat-bubble chat-bubble-${msg.role}`}>
    <div className="chat-bubble-role">
      {msg.role === 'user' ? 'You' : 'Assistant'}
    </div>
    <div className="chat-bubble-content">
      {msg.content}
      {msg.streaming && <span className="chat-cursor">▍</span>}
    </div>
  </div>
);

// ---------------------------------------------------------------------------
// Chat overlay
// ---------------------------------------------------------------------------
const ChatOverlay: React.FC<{ onClose: () => void }> = ({ onClose }) => {
  const { chatMessages, clearChat } = useChat();
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMessages.length, chatMessages[chatMessages.length - 1]?.content]);

  return (
    <div className="chat-overlay">
      <div className="chat-overlay-header">
        <span>💬 Chat</span>
        <div style={{ display: 'flex', gap: '0.4rem' }}>
          {chatMessages.length > 0 && (
            <button className="panel-header-btn" onClick={clearChat}>
              Clear
            </button>
          )}
          <button className="panel-header-btn" onClick={onClose}>
            ✕
          </button>
        </div>
      </div>
      <div className="chat-messages">
        {chatMessages.length === 0 ? (
          <div className="chat-empty">Ask anything about the project…</div>
        ) : (
          chatMessages.map((m) => <MessageBubble key={m.id} msg={m} />)
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// ChatBar
// ---------------------------------------------------------------------------
const ChatBar: React.FC = () => {
  const {
    addChatMessage,
    updateLastAssistantMessage,
    isChatStreaming,
    setChatStreaming,
  } = useChat();
  const { selectedProject } = useUI();
  const { currentJob } = useJob();
  const isAnalyzing = currentJob?.status === 'running';

  const [inputValue, setInputValue] = useState('');
  const [overlayOpen, setOverlayOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const projectName = selectedProject
    ? selectedProject.path.split('/').filter(Boolean).pop() ?? selectedProject.path
    : null;

  // ---- send message -------------------------------------------------------
  const handleSend = async () => {
    const text = inputValue.trim();
    if (!text || isChatStreaming) return;

    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content: text,
    };
    addChatMessage(userMsg);
    setInputValue('');
    setOverlayOpen(true);
    setChatStreaming(true);

    // Seed assistant placeholder
    const assistantId = crypto.randomUUID();
    addChatMessage({ id: assistantId, role: 'assistant', content: '', streaming: true });

    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          project_id: selectedProject?.id ?? null,
          stream: true,
        }),
        signal: ctrl.signal,
      });

      if (!res.ok) {
        updateLastAssistantMessage(`[Error ${res.status}]`);
        return;
      }

      const reader = res.body?.getReader();
      if (!reader) {
        updateLastAssistantMessage('[No response body]');
        return;
      }

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // SSE lines: "data: <json>\n\n"
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith('data:')) continue;
          const raw = trimmed.slice(5).trim();
          if (raw === '[DONE]') break;
          try {
            const parsed = JSON.parse(raw) as {
              delta?: string;
              text?: string;
              content?: string;
            };
            const chunk =
              parsed.delta ?? parsed.text ?? parsed.content ?? '';
            if (chunk) updateLastAssistantMessage(chunk);
          } catch {
            // Non-JSON SSE line — treat as raw text
            if (raw) updateLastAssistantMessage(raw);
          }
        }
      }
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        updateLastAssistantMessage('[Connection error]');
      }
    } finally {
      setChatStreaming(false);
      abortRef.current = null;
    }
  };

  const handleStop = () => {
    abortRef.current?.abort();
    setChatStreaming(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="chatbar" style={{ position: 'relative' }}>
      {overlayOpen && (
        <ChatOverlay onClose={() => setOverlayOpen(false)} />
      )}

      <span className="chatbar-context">
        {projectName ? `Context: ${projectName}` : 'No project'}
      </span>

      <input
        ref={inputRef}
        className="chatbar-input"
        type="text"
        placeholder={isAnalyzing ? '⏳ Please wait for analysis to complete…' : 'Ask about the project…'}
        value={inputValue}
        onChange={(e) => setInputValue(e.target.value)}
        onKeyDown={handleKeyDown}
        disabled={isChatStreaming || isAnalyzing}
        title={isAnalyzing ? 'Please wait for analysis to complete' : undefined}
      />

      <button
        className="chatbar-icon-btn"
        onClick={() => setOverlayOpen((v) => !v)}
        title="Toggle chat history"
      >
        💬
      </button>

      {isChatStreaming ? (
        <button className="chatbar-btn stop" onClick={handleStop}>
          Stop
        </button>
      ) : (
        <button
          className="chatbar-btn"
          onClick={handleSend}
          disabled={!inputValue.trim() || isAnalyzing}
        >
          Send
        </button>
      )}
    </div>
  );
};

export default ChatBar;
