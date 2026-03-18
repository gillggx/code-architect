/**
 * AgentActivityFeed — center panel with Activity / Chat tabs.
 *
 * Handles both analysis events and code-edit agent events (tool_call,
 * tool_output, approval_required, message, plan, done, error).
 */

import React, { useEffect, useRef, useState } from 'react';
import { useAgentEvents, useChat, useAppStore, AgentEvent, ChatMessage } from '../store/app';
import { PlanCard } from './PlanCard';
import { EscalationCard } from './EscalationCard';

// ---------------------------------------------------------------------------
// Event metadata
// ---------------------------------------------------------------------------
interface EventMeta { icon: string; label: string; color: string; bold?: boolean; }

const EVENT_META: Partial<Record<AgentEvent['type'], EventMeta>> = {
  scan:              { icon: '📂', label: 'Scan',       color: '#888' },
  ast:               { icon: '🔍', label: 'AST',        color: '#2980b9' },
  llm_start:         { icon: '🤖', label: 'Reading',    color: '#e67e22' },
  llm_done:          { icon: '✅', label: 'Done',       color: '#27ae60' },
  memory:            { icon: '💾', label: 'Memory',     color: '#8e44ad' },
  pattern:           { icon: '🏷',  label: 'Pattern',   color: '#16a085' },
  skip:              { icon: '➖', label: 'Skip',        color: '#aaa' },
  done:              { icon: '🎉', label: 'Complete',   color: '#27ae60', bold: true },
  error:             { icon: '❌', label: 'Error',      color: '#c0392b' },
  tool_call:         { icon: '🔧', label: 'Tool',       color: '#2980b9' },
  tool_output:       { icon: '📤', label: 'Output',     color: '#27ae60' },
  approval_required: { icon: '⏳', label: 'Approval',  color: '#e67e22', bold: true },
  message:           { icon: '💬', label: 'Message',   color: '#555' },
  plan:              { icon: '📋', label: 'Plan',       color: '#8e44ad', bold: true },
  escalation:        { icon: '🚨', label: 'Escalation', color: '#c0392b', bold: true },
  session:           { icon: '🔑', label: 'Session',   color: '#888' },
};

function fmtTime(d: Date): string { return d.toTimeString().slice(0, 8); }

// ---------------------------------------------------------------------------
// Diff viewer
// ---------------------------------------------------------------------------
const DiffViewer: React.FC<{ diff: string }> = ({ diff }) => {
  if (!diff) return null;
  return (
    <pre className="diff-viewer">
      {diff.split('\n').map((line, i) => {
        let cls = 'diff-line';
        if (line.startsWith('+') && !line.startsWith('+++')) cls += ' diff-add';
        else if (line.startsWith('-') && !line.startsWith('---')) cls += ' diff-remove';
        else if (line.startsWith('@@')) cls += ' diff-hunk';
        return <span key={i} className={cls}>{line}{'\n'}</span>;
      })}
    </pre>
  );
};

// ---------------------------------------------------------------------------
// Approval card
// ---------------------------------------------------------------------------
const ApprovalCard: React.FC<{ event: AgentEvent }> = ({ event }) => {
  const agentSession = useAppStore(s => s.agentSession);
  const setPendingApproval = useAppStore(s => s.setPendingApproval);
  const addModifiedFile = useAppStore(s => s.addModifiedFile);
  const [resolved, setResolved] = useState(false);
  const [editContent, setEditContent] = useState('');
  const [showEdit, setShowEdit] = useState(false);

  const sessionId = agentSession ?? '';
  const tool = event.tool ?? '';
  const diff = event.diff ?? '';
  const isFileOp = tool === 'write_file' || tool === 'edit_file';
  const isCmd = tool === 'run_command';

  const sendApproval = async (action: string, editedContent?: string) => {
    if (!sessionId) return;
    try {
      await fetch('/api/agent/approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          action,
          edited_content: editedContent ?? null,
        }),
      });
      if (action === 'apply' && event.args?.path) {
        addModifiedFile(event.args.path as string);
      }
      setResolved(true);
      setPendingApproval(null);
    } catch (err) {
      console.error('Approval failed:', err);
    }
  };

  if (resolved) {
    return (
      <div className="approval-card resolved">
        <span className="approval-resolved-label">Resolved</span>
      </div>
    );
  }

  return (
    <div className="approval-card">
      <div className="approval-card-header">
        <span className="approval-tool-name">{tool}</span>
        {event.args?.path != null && (
          <span className="approval-file-path">{String(event.args.path)}</span>
        )}
        {isCmd && event.args?.cmd != null && (
          <code className="approval-cmd">{String(event.args.cmd)}</code>
        )}
      </div>

      {isFileOp && diff && (
        <div className="approval-diff">
          <DiffViewer diff={diff} />
        </div>
      )}

      {showEdit && (
        <div className="approval-edit-section">
          <textarea
            className="approval-edit-textarea"
            value={editContent}
            onChange={e => setEditContent(e.target.value)}
            placeholder="Paste edited content here…"
            rows={10}
          />
        </div>
      )}

      <div className="approval-actions">
        <button
          className="approval-btn approval-btn-apply"
          onClick={() => sendApproval('apply')}
        >
          Apply
        </button>
        {isFileOp && (
          <button
            className="approval-btn approval-btn-edit"
            onClick={() => setShowEdit(v => !v)}
          >
            {showEdit ? 'Cancel edit' : 'Edit first'}
          </button>
        )}
        {showEdit && editContent && (
          <button
            className="approval-btn approval-btn-edit"
            onClick={() => sendApproval('edit', editContent)}
          >
            Apply edited
          </button>
        )}
        <button
          className="approval-btn approval-btn-skip"
          onClick={() => sendApproval('skip')}
        >
          Skip
        </button>
        <button
          className="approval-btn approval-btn-stop"
          onClick={() => sendApproval('stop')}
        >
          Stop
        </button>
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Activity event row
// ---------------------------------------------------------------------------
const EventRow: React.FC<{ event: AgentEvent }> = ({ event }) => {
  const [expanded, setExpanded] = useState(false);
  const meta = EVENT_META[event.type] ?? { icon: '•', label: event.type, color: '#888' };

  // Special rendering for approval_required
  if (event.type === 'approval_required') {
    return (
      <div className={`event-row event-row-approval_required`}>
        <span className="event-time">{fmtTime(event.timestamp)}</span>
        <span className="event-icon">{meta.icon}</span>
        <span className="event-label" style={{ color: meta.color, fontWeight: 700 }}>
          {meta.label} required — {event.tool}
        </span>
        <ApprovalCard event={event} />
      </div>
    );
  }

  // Special rendering for plan events
  if (event.type === 'plan') {
    return (
      <div className="event-row event-row-plan">
        <span className="event-time">{fmtTime(event.timestamp)}</span>
        <span className="event-icon">{meta.icon}</span>
        <span className="event-label" style={{ color: meta.color, fontWeight: 700 }}>
          {meta.label}
        </span>
        <PlanCard event={event} />
      </div>
    );
  }

  // Special rendering for escalation events
  if (event.type === 'escalation') {
    return (
      <div className="event-row event-row-escalation">
        <span className="event-time">{fmtTime(event.timestamp)}</span>
        <span className="event-icon">{meta.icon}</span>
        <span className="event-label" style={{ color: meta.color, fontWeight: 700 }}>
          {meta.label}
        </span>
        <EscalationCard event={event} />
      </div>
    );
  }

  // Tool call row: show tool name + args summary
  if (event.type === 'tool_call') {
    const argsStr = event.args
      ? Object.entries(event.args)
          .map(([k, v]) => `${k}=${String(v).slice(0, 60)}`)
          .join(', ')
      : '';
    return (
      <div className="event-row event-row-tool_call">
        <span className="event-time">{fmtTime(event.timestamp)}</span>
        <span className="event-icon">{meta.icon}</span>
        <span className="event-label" style={{ color: meta.color }}>{event.tool}</span>
        <span className="event-msg">{argsStr}</span>
      </div>
    );
  }

  // Tool output row: show result + optional diff
  if (event.type === 'tool_output') {
    const hasDiff = !!event.diff;
    return (
      <div className="event-row event-row-tool_output">
        <span className="event-time">{fmtTime(event.timestamp)}</span>
        <span className="event-icon">{meta.icon}</span>
        <span className="event-label" style={{ color: meta.color }}>{event.tool}</span>
        <span className="event-msg">{(event.result ?? '').slice(0, 120)}</span>
        {hasDiff && (
          <button className="event-expand-btn" onClick={() => setExpanded(v => !v)}>
            {expanded ? 'hide diff' : 'show diff'}
          </button>
        )}
        {expanded && event.diff && (
          <div className="event-summary">
            <DiffViewer diff={event.diff} />
          </div>
        )}
      </div>
    );
  }

  // Default row (all other event types including analysis events)
  let displayMsg = event.message;
  if (event.type === 'llm_start' && event.file) displayMsg = `Reading ${event.file}…`;
  if (event.type === 'llm_done' && event.file) {
    const preview = event.summary
      ? event.summary.slice(0, 80) + (event.summary.length > 80 ? '…' : '')
      : '';
    displayMsg = `${event.file}${preview ? ': ' + preview : ''}`;
  }
  if (event.type === 'message' && event.content) displayMsg = event.content;

  const hasSummary = event.type === 'llm_done' && event.summary && event.summary.length > 80;

  return (
    <div className={`event-row event-row-${event.type}`} style={{ fontWeight: meta.bold ? 700 : 400 }}>
      <span className="event-time">{fmtTime(event.timestamp)}</span>
      <span className="event-icon">{meta.icon}</span>
      <span className="event-label" style={{ color: meta.color }}>{meta.label}</span>
      <span className="event-msg">{displayMsg}</span>
      {hasSummary && (
        <button className="event-expand-btn" onClick={() => setExpanded(v => !v)}>
          {expanded ? 'less' : 'more'}
        </button>
      )}
      {expanded && event.summary && <div className="event-summary">{event.summary}</div>}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Chat message bubble
// ---------------------------------------------------------------------------
export const MessageBubble: React.FC<{ msg: ChatMessage }> = ({ msg }) => (
  <div className={`chat-bubble chat-bubble-${msg.role}`}>
    <div className="chat-bubble-role">{msg.role === 'user' ? 'You' : 'Assistant'}</div>
    <div className="chat-bubble-content">
      {msg.content}
      {msg.streaming && <span className="chat-cursor">▍</span>}
    </div>
  </div>
);

// ---------------------------------------------------------------------------
// AgentActivityFeed (tabbed center panel)
// ---------------------------------------------------------------------------
const AgentActivityFeed: React.FC = () => {
  const { events, clearEvents } = useAgentEvents();
  const { chatMessages, clearChat } = useChat();
  const centerTab = useAppStore(s => s.centerTab);
  const setCenterTab = useAppStore(s => s.setCenterTab);

  const activityBottomRef = useRef<HTMLDivElement>(null);
  const chatBottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll activity feed
  useEffect(() => {
    if (centerTab === 'activity') {
      activityBottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [events.length, centerTab]);

  // Auto-scroll chat
  useEffect(() => {
    if (centerTab === 'chat') {
      chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [chatMessages.length, chatMessages[chatMessages.length - 1]?.content, centerTab]);

  // Switch to chat tab when new chat messages arrive (from auto-summary)
  const prevChatLenRef = useRef(chatMessages.length);
  useEffect(() => {
    if (chatMessages.length > prevChatLenRef.current && centerTab === 'activity') {
      setCenterTab('chat');
    }
    prevChatLenRef.current = chatMessages.length;
  }, [chatMessages.length]);

  // Count visible events (exclude pattern + session events from badge)
  const visibleCount = events.filter(e => e.type !== 'pattern' && e.type !== 'session').length;

  return (
    <div className="panel-center">
      {/* Tab bar */}
      <div className="panel-header panel-tabs">
        <div className="tab-group">
          <button
            className={`panel-tab${centerTab === 'activity' ? ' active' : ''}`}
            onClick={() => setCenterTab('activity')}
          >
            🤖 Activity
            {visibleCount > 0 && <span className="tab-badge">{visibleCount}</span>}
          </button>
          <button
            className={`panel-tab${centerTab === 'chat' ? ' active' : ''}`}
            onClick={() => setCenterTab('chat')}
          >
            💬 Chat
            {chatMessages.length > 0 && <span className="tab-badge">{chatMessages.length}</span>}
          </button>
        </div>
        <div className="panel-header-actions">
          {centerTab === 'activity' && events.length > 0 && (
            <button className="panel-header-btn" onClick={clearEvents}>Clear</button>
          )}
          {centerTab === 'chat' && chatMessages.length > 0 && (
            <button className="panel-header-btn" onClick={clearChat}>Clear</button>
          )}
        </div>
      </div>

      {/* Activity tab */}
      {centerTab === 'activity' && (
        events.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">🤖</div>
            <div className="empty-state-text">Analyze a project to see the agent at work</div>
          </div>
        ) : (
          <div className="event-feed">
            {events
              .filter(e => e.type !== 'pattern' && e.type !== 'session')
              .map(e => (
                <EventRow key={e.id} event={e} />
              ))}
            <div ref={activityBottomRef} />
          </div>
        )
      )}

      {/* Chat tab */}
      {centerTab === 'chat' && (
        chatMessages.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">💬</div>
            <div className="empty-state-text">Ask anything about the project…</div>
          </div>
        ) : (
          <div className="chat-messages">
            {chatMessages.map(m => <MessageBubble key={m.id} msg={m} />)}
            <div ref={chatBottomRef} />
          </div>
        )
      )}
    </div>
  );
};

export default AgentActivityFeed;
