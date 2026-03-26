/**
 * ChatBar — fixed bottom input bar.
 *
 * In Chat mode: sends to /api/chat (SSE), shows in Chat tab.
 * In Edit mode: sends to /api/a2a/generate (SSE), shows in Activity tab.
 */

import React, { useState, useRef } from 'react';
import { useChat, useUI, useJob, useAppStore } from '../store/app';

// ---------------------------------------------------------------------------
// Benchmark model list — driven by VITE_BENCHMARK_MODELS env var.
// Format: "model-id:Label,model-id:Label"
// Empty or unset → dropdown hidden entirely.
// ---------------------------------------------------------------------------
const BENCHMARK_MODELS: { id: string; label: string }[] = (() => {
  const raw = import.meta.env.VITE_BENCHMARK_MODELS ?? '';
  if (!raw.trim()) return [];
  return raw.split(',').flatMap((entry: string) => {
    const [id, ...rest] = entry.trim().split(':');
    if (!id) return [];
    return [{ id: id.trim(), label: rest.join(':').trim() || id.trim() }];
  });
})();

// ---------------------------------------------------------------------------
// Impact Preview Modal (Sprint 4.1)
// ---------------------------------------------------------------------------
interface ImpactFile {
  path: string;
  confidence: number;
  reason: string;
}

interface ImpactPreviewModalProps {
  files: ImpactFile[];
  loading: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

const ImpactPreviewModal: React.FC<ImpactPreviewModalProps> = ({ files, loading, onConfirm, onCancel }) => (
  <div className="modal-backdrop" onClick={onCancel}>
    <div className="modal" onClick={e => e.stopPropagation()}>
      <h2>Predicted Impact</h2>
      {loading ? (
        <div className="impact-loading">Analyzing impact…</div>
      ) : files.length === 0 ? (
        <div className="impact-empty">No predicted file changes found.</div>
      ) : (
        <div className="impact-list">
          {files.map((f, i) => (
            <div key={i} className="impact-row">
              <div className="impact-confidence-track">
                <div className="impact-confidence-bar" style={{ width: `${Math.round(f.confidence * 100)}%` }} />
              </div>
              <span className="impact-path" title={f.path}>{f.path}</span>
              <span className="impact-badge">{f.reason}</span>
            </div>
          ))}
        </div>
      )}
      <div className="modal-actions">
        <button className="modal-btn" onClick={onCancel}>Cancel</button>
        <button className="modal-btn primary" onClick={onConfirm} disabled={loading}>
          Confirm &amp; Run
        </button>
      </div>
    </div>
  </div>
);

// ---------------------------------------------------------------------------
// Tool event helpers
// ---------------------------------------------------------------------------

function toolThinkingLabel(tool: string, args: Record<string, unknown>): string {
  switch (tool) {
    case 'read_file':    return `Reading \`${args.path ?? ''}\``;
    case 'search_files': return `Searching \`${args.query ?? ''}\``;
    case 'edit_file':    return `Editing \`${args.path ?? ''}\``;
    default: return tool;
  }
}

const ChatBar: React.FC = () => {
  const { addChatMessage, updateLastAssistantMessage, isChatStreaming, setChatStreaming, chatMessages } = useChat();
  const { selectedProject } = useUI();
  const { currentJob } = useJob();
  const setCenterTab = useAppStore(s => s.setCenterTab);
  const addEvent = useAppStore(s => s.addEvent);

  // Edit agent state
  const editMode = useAppStore(s => s.editMode);
  const setEditMode = useAppStore(s => s.setEditMode);

  // Chat mode: agent vs direct
  const chatMode = useAppStore(s => s.chatMode);
  const setChatMode = useAppStore(s => s.setChatMode);
  const agentSession = useAppStore(s => s.agentSession);
  const setAgentSession = useAppStore(s => s.setAgentSession);
  const setPendingApproval = useAppStore(s => s.setPendingApproval);
  const addModifiedFile = useAppStore(s => s.addModifiedFile);

  const isAnalyzing = currentJob?.status === 'running';

  const [inputValue, setInputValue] = useState('');
  const [shellUnrestricted, setShellUnrestricted] = useState(false);
  const [autoApprove, setAutoApprove] = useState(false);
  const [selectedModel, setSelectedModel] = useState('');
  const abortRef = useRef<AbortController | null>(null);
  const sessionIdRef = useRef<string>(crypto.randomUUID());
  const [isAgentRunning, setIsAgentRunning] = useState(false);

  // Impact preview state (Sprint 4.1)
  const [showImpactModal, setShowImpactModal] = useState(false);
  const [impactLoading, setImpactLoading] = useState(false);
  const [impactFiles, setImpactFiles] = useState<ImpactFile[]>([]);
  const pendingTaskRef = useRef<string>('');

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

    let escalationTask: string | null = null;

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          project_id: selectedProject?.id ?? null,
          session_id: sessionIdRef.current,
          chat_mode: chatMode,
          ...(selectedModel ? { model: selectedModel } : {}),
        }),
        signal: ctrl.signal,
      });

      if (!res.ok) { updateLastAssistantMessage(`[Error ${res.status}]`); return; }

      const reader = res.body?.getReader();
      if (!reader) { updateLastAssistantMessage('[No response body]'); return; }

      const decoder = new TextDecoder();
      let buffer = '';

      outer: while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';
        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith('data:')) continue;
          const raw = trimmed.slice(5).trim();
          if (raw === '[DONE]') break outer;
          try {
            const parsed = JSON.parse(raw) as {
              type?: string;
              data?: string;
              delta?: string;
              text?: string;
              content?: string;
              tool?: string;
              args?: Record<string, unknown>;
              result?: string;
              path?: string;
              diff?: string;
              task?: string;
              reason?: string;
            };

            if (parsed.type === 'done') break outer;

            if (parsed.type === 'chunk') {
              const chunk = parsed.data ?? parsed.delta ?? parsed.text ?? parsed.content ?? '';
              if (chunk) updateLastAssistantMessage(chunk);
              continue;
            }

            if (parsed.type === 'mode_note' && parsed.data) {
              updateLastAssistantMessage(`\n\n> ⚡ *${parsed.data}*\n\n`);
              continue;
            }

            if (parsed.type === 'tool_thinking' && parsed.tool) {
              const label = toolThinkingLabel(parsed.tool, parsed.args ?? {});
              updateLastAssistantMessage(`\n\n> *${label}...*\n\n`);
              continue;
            }

            if (parsed.type === 'tool_edit' && parsed.path) {
              updateLastAssistantMessage(`\n\n> *Edited \`${parsed.path}\`*\n\n`);
              continue;
            }

            if (parsed.type === 'tool_result' && parsed.tool) {
              const res = parsed.result ?? '';
              let summary = '';
              if (res.startsWith('[Error:') || res.startsWith('Error:')) {
                summary = `> ⚠️ *${parsed.tool} failed: ${res.slice(0, 120)}*\n\n`;
              } else if (res.includes('is a directory')) {
                summary = `> ⚠️ *Path is a directory — picking a file from listing...*\n\n`;
              } else if (res === '' || res.startsWith('No matches found')) {
                summary = `> ⚠️ *${parsed.tool}: no results*\n\n`;
              } else {
                const chars = res.length;
                const matchCount = parsed.tool === 'search_files'
                  ? (res.match(/\n/g)?.length ?? 0) + 1
                  : null;
                summary = matchCount !== null
                  ? `> ✅ *Found ${matchCount} match${matchCount !== 1 ? 'es' : ''}*\n\n`
                  : `> ✅ *Read ${chars.toLocaleString()} chars*\n\n`;
              }
              if (summary) updateLastAssistantMessage(summary);
              continue;
            }

            if (parsed.type === 'escalate' && parsed.task) {
              updateLastAssistantMessage(
                `\n\n---\n*This task requires multi-file changes. Escalating to Edit Agent...*\n`
              );
              escalationTask = parsed.task;
              break outer;
            }

            if (parsed.type === 'error') {
              updateLastAssistantMessage(`\n\n[Error: ${parsed.data ?? 'unknown'}]`);
              break outer;
            }

            // Fallback: legacy plain chunk
            const chunk = parsed.data ?? parsed.delta ?? parsed.text ?? parsed.content ?? '';
            if (chunk) updateLastAssistantMessage(chunk);
          } catch {
            if (raw) updateLastAssistantMessage(raw);
          }
        }
      }
    } catch (err) {
      if ((err as Error).name !== 'AbortError') updateLastAssistantMessage('[Connection error]');
      escalationTask = null; // Don't escalate on error
    } finally {
      setChatStreaming(false);
      abortRef.current = null;
    }

    // Auto-escalate: hand off to Edit Agent after chat mode escalation
    if (escalationTask) {
      runEditAgent(escalationTask);
    }
  };

  // ------------------------------------------------------------------
  // Edit agent send — shows impact preview first (Sprint 4.1)
  // ------------------------------------------------------------------
  const handleEditSend = async () => {
    const text = inputValue.trim();
    if (!text || isAgentRunning) return;
    if (!selectedProject) {
      addEvent({ id: crypto.randomUUID(), type: 'error', message: 'No project selected. Analyze a project first.', timestamp: new Date() });
      return;
    }
    setInputValue('');
    pendingTaskRef.current = text;

    // Call impact API and show preview modal
    setImpactLoading(true);
    setImpactFiles([]);
    setShowImpactModal(true);

    // Send recent chat history so impact API understands context references
    const historyForImpact = chatMessages
      .filter(m => !m.streaming && m.content)
      .slice(-8)
      .map(m => ({ role: m.role, content: m.content }));

    try {
      const res = await fetch('/api/a2a/impact', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: selectedProject.id,
          files: [],
          change_description: text,
          chat_history: historyForImpact,
        }),
      });
      if (res.ok) {
        const data = await res.json() as { affected_files?: ImpactFile[] };
        setImpactFiles(data.affected_files ?? []);
      }
      // On error: stay in modal with empty list, user can still confirm
    } catch {
      // Network error — keep modal open, allow proceeding
    } finally {
      setImpactLoading(false);
    }
  };

  const handleImpactConfirm = () => {
    setShowImpactModal(false);
    const task = pendingTaskRef.current;
    if (task) runEditAgent(task);
  };

  const handleImpactCancel = () => {
    setShowImpactModal(false);
    setImpactFiles([]);
  };

  // ------------------------------------------------------------------
  // Actual agent execution (after impact confirmed)
  // ------------------------------------------------------------------
  const runEditAgent = async (text: string) => {
    if (!selectedProject) return;
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
          shell_unrestricted: shellUnrestricted,
          auto_approve: autoApprove,
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
    <>
    {showImpactModal && (
      <ImpactPreviewModal
        files={impactFiles}
        loading={impactLoading}
        onConfirm={handleImpactConfirm}
        onCancel={handleImpactCancel}
      />
    )}
    <div className="chatbar">
      {/* Mode toggle: Chat / Edit */}
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

      {/* Chat sub-mode: Agent / Direct (only visible in Chat mode) */}
      {!editMode && (
        <div className="chatbar-submode-toggle" title={chatMode === 'agent' ? 'Agent mode: LLM decides which files to read (better for smart models)' : 'Direct mode: Python pre-reads files, single LLM call (better for weaker models, faster)'}>
          <button
            className={`chatbar-submode-btn${chatMode === 'agent' ? ' active' : ''}`}
            onClick={() => setChatMode('agent')}
          >
            Agent
          </button>
          <button
            className={`chatbar-submode-btn${chatMode === 'direct' ? ' active' : ''}`}
            onClick={() => setChatMode('direct')}
          >
            Direct
          </button>
        </div>
      )}

      {/* Model selector — only shown when VITE_BENCHMARK_MODELS is configured */}
      {!editMode && BENCHMARK_MODELS.length > 0 && (
        <select
          className="chatbar-model-select"
          value={selectedModel}
          onChange={e => setSelectedModel(e.target.value)}
          title="Override LLM model (empty = server default)"
        >
          <option value="">Default</option>
          {BENCHMARK_MODELS.map(({ id, label }) => (
            <option key={id} value={id}>{label}</option>
          ))}
        </select>
      )}

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

      {editMode && (
        <>
          <button
            className={`chatbar-unrestricted-btn${autoApprove ? ' active' : ''}`}
            onClick={() => setAutoApprove(v => !v)}
            title={autoApprove ? 'Auto-approve ON — all file changes applied without asking (click to disable)' : 'Auto-approve OFF — will ask before each file change'}
          >
            {autoApprove ? '✅' : '👁'}
          </button>
          <button
            className={`chatbar-unrestricted-btn${shellUnrestricted ? ' active' : ''}`}
            onClick={() => setShellUnrestricted(v => !v)}
            title={shellUnrestricted ? 'Shell unrestricted (click to restrict)' : 'Shell restricted — click to allow all commands'}
          >
            {shellUnrestricted ? '🔓' : '🔒'}
          </button>
        </>
      )}

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
    </>
  );
};

export default ChatBar;
