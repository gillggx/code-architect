/**
 * AgentActivityFeed — center panel with Activity / Chat tabs.
 */

import React, { useEffect, useRef, useState } from 'react';
import { useAgentEvents, useChat, useAppStore, AgentEvent, ChatMessage } from '../store/app';

// ---------------------------------------------------------------------------
// Event metadata
// ---------------------------------------------------------------------------
interface EventMeta { icon: string; label: string; color: string; bold?: boolean; }

const EVENT_META: Record<AgentEvent['type'], EventMeta> = {
  scan:      { icon: '📂', label: 'Scan',    color: '#888' },
  ast:       { icon: '🔍', label: 'AST',     color: '#2980b9' },
  llm_start: { icon: '🤖', label: 'Reading', color: '#e67e22' },
  llm_done:  { icon: '✅', label: 'Done',    color: '#27ae60' },
  memory:    { icon: '💾', label: 'Memory',  color: '#8e44ad' },
  pattern:   { icon: '🏷',  label: 'Pattern', color: '#16a085' },
  skip:      { icon: '➖', label: 'Skip',    color: '#aaa' },
  done:      { icon: '🎉', label: 'Complete',color: '#27ae60', bold: true },
  error:     { icon: '❌', label: 'Error',   color: '#c0392b' },
};

function fmtTime(d: Date): string { return d.toTimeString().slice(0, 8); }

// ---------------------------------------------------------------------------
// Activity event row
// ---------------------------------------------------------------------------
const EventRow: React.FC<{ event: AgentEvent }> = ({ event }) => {
  const [expanded, setExpanded] = useState(false);
  const meta = EVENT_META[event.type] ?? { icon: '•', label: event.type, color: '#888' };

  let displayMsg = event.message;
  if (event.type === 'llm_start' && event.file) displayMsg = `Reading ${event.file}…`;
  if (event.type === 'llm_done' && event.file) {
    const preview = event.summary
      ? event.summary.slice(0, 80) + (event.summary.length > 80 ? '…' : '')
      : '';
    displayMsg = `${event.file}${preview ? ': ' + preview : ''}`;
  }

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
            {events.length > 0 && <span className="tab-badge">{events.filter(e => e.type !== 'pattern').length}</span>}
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
            {events.filter(e => e.type !== 'pattern').map(e => (
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
