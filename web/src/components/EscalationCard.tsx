import React, { useState } from 'react';
import { useAppStore } from '../store/app';

interface EscalationCardProps {
  event: any;
}

export const EscalationCard: React.FC<EscalationCardProps> = ({ event }) => {
  const { setEscalation, agentSession } = useAppStore();
  const [instruction, setInstruction] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [resolved, setResolved] = useState(false);
  const [showInput, setShowInput] = useState(false);

  let esc: any = null;
  try {
    esc = event.content ? JSON.parse(event.content) : null;
  } catch {
    return null;
  }
  if (!esc) return null;

  const sessionId = esc.session_id || agentSession;

  const handleAction = async (action: string) => {
    if (!sessionId || submitting) return;
    setSubmitting(true);
    try {
      await fetch('/api/agent/escalate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          action,
          instruction: action === 'alternative' ? instruction : undefined,
        }),
      });
      setResolved(true);
      setEscalation(null);
    } catch (e) {
      console.error('escalate failed', e);
    } finally {
      setSubmitting(false);
    }
  };

  if (resolved) {
    return (
      <div className="escalation-card escalation-card--resolved">
        🔄 Escalation resolved — continuing...
      </div>
    );
  }

  return (
    <div className="escalation-card">
      <div className="escalation-header">
        <span>🚨 Execution Halted — Human Intervention Required</span>
      </div>
      <div className="escalation-body">
        <div className="escalation-detail">
          <strong>Failed tool:</strong> <code>{esc.failed_tool}</code>
        </div>
        <div className="escalation-detail">
          <strong>Error:</strong> {esc.error_message}
        </div>
        {esc.plan_b_attempted && (
          <div className="escalation-detail escalation-warning">
            ⚠️ Plan B auto-recovery was also attempted and failed.
          </div>
        )}
      </div>
      <div className="escalation-actions">
        <button
          className="escalation-btn escalation-btn--alt"
          onClick={() => setShowInput(!showInput)}
          disabled={submitting}
        >
          💡 Try Alternative Approach
        </button>
        {showInput && (
          <div className="escalation-input-row">
            <input
              className="escalation-input"
              placeholder="Describe the alternative approach..."
              value={instruction}
              onChange={e => setInstruction(e.target.value)}
            />
            <button
              className="escalation-btn escalation-btn--submit"
              onClick={() => handleAction('alternative')}
              disabled={submitting || !instruction.trim()}
            >
              Submit
            </button>
          </div>
        )}
        <button
          className="escalation-btn escalation-btn--manual"
          onClick={() => handleAction('manual_fix')}
          disabled={submitting}
        >
          🔧 I Fixed It Manually
        </button>
        <button
          className="escalation-btn escalation-btn--stop"
          onClick={() => handleAction('stop')}
          disabled={submitting}
        >
          ⛔ Stop Execution
        </button>
      </div>
    </div>
  );
};
