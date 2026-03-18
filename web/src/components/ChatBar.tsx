/**
 * ChatBar — fixed bottom input bar.
 *
 * In Chat mode: sends to /api/chat (SSE), shows in Chat tab.
 * In Edit mode: sends to /api/a2a/generate (SSE), shows in Activity tab.
 */

import React, { useState, useRef } from 'react';
import { useChat, useUI, useJob, useAppStore } from '../store/app';

const ChatBar: React.FC = () => {
  const { addChatMessage, updateLastAssistantMessage, isChatStreaming, setChatStreaming, chatMessages } = useChat();
  const { selectedProject } = useUI();
  const { currentJob } = useJob();
  const setCenterTab = useAppStore(s => s.setCenterTab);
  const addEvent = useAppStore(s => s.addEvent);

  // Edit agent state
  const editMode = useAppStore(s => s.editMode);
  const setEditMode = useAppStore(s => s.setEditMode);
  const agentSession = useAppStore(s => s.agentSession);
  const setAgentSession = useAppStore(s => s.setAgentSession);
  const setPendingApproval = useAppStore(s => s.setPendingApproval);
  const addModifiedFile = useAppStore(s => s.addModifiedFile);

  const isAnalyzing = currentJob?.status === 'running';

  const [inputValue, setInputValue] = useState('');
  const abortRef = useRef<AbortController | null>(null);
  const sessionIdRef = useRef<string>(crypto.randomUUID());
  const [isAgentRunning, setIsAgentRunning] = useState(false);

  const projectName = selectedProject
    ? selectedProject.path.split('/').filter(Boolean).pop() ?? selectedProject.path
    : null;

  // ------------------------------------------------------------------
  // Chat send (existing behaviour)
  // ------------------------------------------------------------------
  const handleChatSend = async () => {
    const text = inputValue.trim();
    if (!text || isChatStreaming) return;

    addChatMessage({ id: crypto.randomUUID(), role: 'user', content: text });
    setInputValue('');
    setCenterTab('chat');
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

  // ------------------------------------------------------------------
  // Edit agent send
  // ------------------------------------------------------------------
  const handleEditSend = async () => {
    const text = inputValue.trim();
    if (!text || isAgentRunning) return;
    if (!selectedProject) {
      addEvent({
        id: crypto.randomUUID(),
        type: 'error',
        message: 'No project selected. Analyze a project first.',
        timestamp: new Date(),
      });
      return;
    }

    setInputValue('');
    setCenterTab('activity');
    setIsAgentRunning(true);

    addEvent({
      id: crypto.randomUUID(),
      type: 'llm_start',
      message: `Edit task: ${text}`,
      timestamp: new Date(),
    });

    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      // Send last 10 completed chat messages as context (skip streaming ones)
      const historyToSend = chatMessages
        .filter(m => !m.streaming && m.content)
        .slice(-10)
        .map(m => ({ role: m.role, content: m.content }));

      const res = await fetch('/api/a2a/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task: text,
          project_id: selectedProject.id,
          mode: 'interactive',
          chat_history: historyToSend,
        }),
        signal: ctrl.signal,
      });

      if (!res.ok) {
        addEvent({
          id: crypto.randomUUID(),
          type: 'error',
          message: `Agent error: HTTP ${res.status}`,
          timestamp: new Date(),
        });
        return;
      }

      const reader = res.body?.getReader();
      if (!reader) return;

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
          if (!raw) continue;

          try {
            const evt = JSON.parse(raw) as {
              type: string;
              session_id?: string;
              tool?: string;
              args?: Record<string, unknown>;
              result?: string;
              diff?: string;
              content?: string;
              summary?: string;
              error?: string;
              changes?: Array<{ file: string; action: string; diff?: string; applied: boolean }>;
            };

            if (evt.type === 'session' && evt.session_id) {
              setAgentSession(evt.session_id);
              continue;
            }

            if (evt.type === 'approval_required' && evt.tool) {
              // Store pending approval so the UI can render the card
              setPendingApproval({
                sessionId: '', // will be set from agentSession store value
                tool: evt.tool,
                args: evt.args ?? {},
                diff: evt.diff,
              });
            }

            if (evt.type === 'plan' && evt.content) {
              try {
                const planData = JSON.parse(evt.content);
                useAppStore.getState().setCurrentPlan({
                  planA: planData.plan_a,
                  planB: planData.plan_b || undefined,
                  needsConfirmation: planData.needs_confirmation,
                  confidenceGap: planData.confidence_gap,
                  sessionId: planData.session_id || agentSession || '',
                });
              } catch (e) {
                console.warn('Failed to parse plan event', e);
              }
            }

            if (evt.type === 'escalation' && evt.content) {
              try {
                const esc = JSON.parse(evt.content);
                useAppStore.getState().setEscalation({
                  sessionId: esc.session_id || agentSession || '',
                  failedTool: esc.failed_tool,
                  errorMessage: esc.error_message,
                  planBAttempted: esc.plan_b_attempted,
                  suggestedOptions: esc.suggested_options,
                  iteration: esc.iteration,
                });
              } catch (e) {
                console.warn('Failed to parse escalation event', e);
              }
            }

            if (evt.type === 'done' && evt.changes) {
              for (const c of evt.changes) {
                if (c.applied) addModifiedFile(c.file);
              }
            }

            // Add to activity feed
            addEvent({
              id: crypto.randomUUID(),
              type: evt.type as any,
              message: evt.content ?? evt.result ?? evt.summary ?? evt.error ?? evt.tool ?? evt.type,
              tool: evt.tool,
              args: evt.args,
              result: evt.result,
              diff: evt.diff,
              content: evt.content,
              approval_required: evt.type === 'approval_required',
              summary: evt.summary,
              timestamp: new Date(),
            });
          } catch {
            // ignore parse errors
          }
        }
      }
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        addEvent({
          id: crypto.randomUUID(),
          type: 'error',
          message: '[Connection error]',
          timestamp: new Date(),
        });
      }
    } finally {
      setIsAgentRunning(false);
      abortRef.current = null;
    }
  };

  const handleSend = editMode ? handleEditSend : handleChatSend;

  const handleStop = () => {
    abortRef.current?.abort();
    setChatStreaming(false);
    setIsAgentRunning(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };

  const isBusy = editMode ? isAgentRunning : isChatStreaming;

  return (
    <div className="chatbar">
      {/* Mode toggle */}
      <div className="chatbar-mode-toggle">
        <button
          className={`chatbar-mode-btn${!editMode ? ' active' : ''}`}
          onClick={() => setEditMode(false)}
          title="Chat mode"
        >
          Chat
        </button>
        <button
          className={`chatbar-mode-btn${editMode ? ' active' : ''}`}
          onClick={() => setEditMode(true)}
          title="Edit mode"
        >
          Edit
        </button>
      </div>

      <span className="chatbar-context">
        {projectName ? `Context: ${projectName}` : 'No project'}
      </span>

      <input
        className="chatbar-input"
        type="text"
        placeholder={
          isAnalyzing
            ? '⏳ Analysis in progress…'
            : editMode
            ? 'Describe what to change…'
            : 'Ask about the project…'
        }
        value={inputValue}
        onChange={e => setInputValue(e.target.value)}
        onKeyDown={handleKeyDown}
        disabled={isBusy || isAnalyzing}
        title={isAnalyzing ? 'Please wait for analysis to complete' : undefined}
      />

      {isBusy ? (
        <button className="chatbar-btn stop" onClick={handleStop}>Stop</button>
      ) : (
        <button
          className="chatbar-btn"
          onClick={handleSend}
          disabled={!inputValue.trim() || isAnalyzing}
        >
          {editMode ? 'Run' : 'Send'}
        </button>
      )}
    </div>
  );
};

export default ChatBar;
