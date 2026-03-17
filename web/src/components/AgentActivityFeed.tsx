/**
 * AgentActivityFeed — center panel showing agent events in real time.
 */

import React, { useEffect, useRef, useState } from 'react';
import { useAgentEvents, AgentEvent } from '../store/app';

// ---------------------------------------------------------------------------
// Event metadata
// ---------------------------------------------------------------------------
interface EventMeta {
  icon: string;
  label: string;
  color: string;
  bold?: boolean;
}

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

// ---------------------------------------------------------------------------
// Format HH:MM:SS
// ---------------------------------------------------------------------------
function fmtTime(d: Date): string {
  return d.toTimeString().slice(0, 8);
}

// ---------------------------------------------------------------------------
// Single event row
// ---------------------------------------------------------------------------
const EventRow: React.FC<{ event: AgentEvent }> = ({ event }) => {
  const [expanded, setExpanded] = useState(false);
  const meta = EVENT_META[event.type] ?? { icon: '•', label: event.type, color: '#888' };

  // Build display message
  let displayMsg = event.message;
  if (event.type === 'llm_start' && event.file) {
    displayMsg = `Reading ${event.file}…`;
  }
  if (event.type === 'llm_done' && event.file) {
    const preview = event.summary
      ? event.summary.slice(0, 80) + (event.summary.length > 80 ? '…' : '')
      : '';
    displayMsg = `${event.file}${preview ? ': ' + preview : ''}`;
  }

  const hasSummary =
    event.type === 'llm_done' && event.summary && event.summary.length > 80;

  return (
    <div
      className={`event-row event-row-${event.type}`}
      style={{ fontWeight: meta.bold ? 700 : 400 }}
    >
      <span className="event-time">{fmtTime(event.timestamp)}</span>
      <span className="event-icon">{meta.icon}</span>
      <span className="event-label" style={{ color: meta.color }}>
        {meta.label}
      </span>
      <span className="event-msg">{displayMsg}</span>
      {hasSummary && (
        <button
          className="event-expand-btn"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? 'less' : 'more'}
        </button>
      )}
      {expanded && event.summary && (
        <div className="event-summary">{event.summary}</div>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// AgentActivityFeed
// ---------------------------------------------------------------------------
const AgentActivityFeed: React.FC = () => {
  const { events, clearEvents } = useAgentEvents();
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new events arrive
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [events.length]);

  return (
    <div className="panel-center">
      <div className="panel-header">
        <span>🤖 Agent Activity</span>
        {events.length > 0 && (
          <div className="panel-header-actions">
            <button className="panel-header-btn" onClick={clearEvents}>
              Clear
            </button>
          </div>
        )}
      </div>

      {events.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">🤖</div>
          <div className="empty-state-text">
            Analyze a project to see the agent at work
          </div>
        </div>
      ) : (
        <div className="event-feed">
          {events.filter((e) => e.type !== 'pattern').map((e) => (
            <EventRow key={e.id} event={e} />
          ))}
          <div ref={bottomRef} />
        </div>
      )}
    </div>
  );
};

export default AgentActivityFeed;
