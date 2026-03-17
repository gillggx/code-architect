/**
 * ChatBar — fixed bottom input bar.
 * Chat messages are displayed in the center panel (Chat tab).
 */

import React, { useState, useRef } from 'react';
import { useChat, useUI, useJob, useAppStore, ChatMessage } from '../store/app';

const ChatBar: React.FC = () => {
  const { addChatMessage, updateLastAssistantMessage, isChatStreaming, setChatStreaming } = useChat();
  const { selectedProject } = useUI();
  const { currentJob } = useJob();
  const setCenterTab = useAppStore(s => s.setCenterTab);
  const isAnalyzing = currentJob?.status === 'running';

  const [inputValue, setInputValue] = useState('');
  const abortRef = useRef<AbortController | null>(null);
  const sessionIdRef = useRef<string>(crypto.randomUUID());

  const projectName = selectedProject
    ? selectedProject.path.split('/').filter(Boolean).pop() ?? selectedProject.path
    : null;

  const handleSend = async () => {
    const text = inputValue.trim();
    if (!text || isChatStreaming) return;

    addChatMessage({ id: crypto.randomUUID(), role: 'user', content: text });
    setInputValue('');
    setCenterTab('chat');   // switch center panel to Chat tab
    setChatStreaming(true);
    addChatMessage({ id: crypto.randomUUID(), role: 'assistant', content: '', streaming: true });

    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          project_id: selectedProject?.id ?? null,
          session_id: sessionIdRef.current,
        }),
        signal: ctrl.signal,
      });

      if (!res.ok) { updateLastAssistantMessage(`[Error ${res.status}]`); return; }

      const reader = res.body?.getReader();
      if (!reader) { updateLastAssistantMessage('[No response body]'); return; }

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';
        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith('data:')) continue;
          const raw = trimmed.slice(5).trim();
          if (raw === '[DONE]') break;
          try {
            const parsed = JSON.parse(raw) as { type?: string; data?: string; delta?: string; text?: string; content?: string };
            if (parsed.type === 'done') break;
            const chunk = parsed.data ?? parsed.delta ?? parsed.text ?? parsed.content ?? '';
            if (chunk) updateLastAssistantMessage(chunk);
          } catch {
            if (raw) updateLastAssistantMessage(raw);
          }
        }
      }
    } catch (err) {
      if ((err as Error).name !== 'AbortError') updateLastAssistantMessage('[Connection error]');
    } finally {
      setChatStreaming(false);
      abortRef.current = null;
    }
  };

  const handleStop = () => { abortRef.current?.abort(); setChatStreaming(false); };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };

  return (
    <div className="chatbar">
      <span className="chatbar-context">
        {projectName ? `Context: ${projectName}` : 'No project'}
      </span>

      <input
        className="chatbar-input"
        type="text"
        placeholder={isAnalyzing ? '⏳ Analysis in progress…' : 'Ask about the project…'}
        value={inputValue}
        onChange={e => setInputValue(e.target.value)}
        onKeyDown={handleKeyDown}
        disabled={isChatStreaming || isAnalyzing}
        title={isAnalyzing ? 'Please wait for analysis to complete' : undefined}
      />

      {isChatStreaming ? (
        <button className="chatbar-btn stop" onClick={handleStop}>Stop</button>
      ) : (
        <button className="chatbar-btn" onClick={handleSend} disabled={!inputValue.trim() || isAnalyzing}>
          Send
        </button>
      )}
    </div>
  );
};

export default ChatBar;
