import React, { useState } from 'react';
import { useAppStore } from '../store/app';

interface PlanCardProps {
  event: any;
}

const confidenceColor = (c: number) =>
  c >= 0.7 ? '#27ae60' : c >= 0.5 ? '#f39c12' : '#e74c3c';

const riskBadge: Record<string, string> = {
  low: '#27ae60',
  medium: '#f39c12',
  high: '#e74c3c',
};

export const PlanCard: React.FC<PlanCardProps> = ({ event }) => {
  const { setCurrentPlan, agentSession } = useAppStore();
  const [showPlanB, setShowPlanB] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [resolved, setResolved] = useState(false);

  let planData: any = null;
  try {
    planData = event.content ? JSON.parse(event.content) : null;
  } catch {
    return null;
  }
  if (!planData?.plan_a) return null;

  const planA = planData.plan_a;
  const planB = planData.plan_b;
  const needsConfirmation = planData.needs_confirmation;
  const sessionId = planData.session_id || agentSession;

  const handleAction = async (action: string, chosenPlan?: string) => {
    if (!sessionId || submitting) return;
    setSubmitting(true);
    try {
      await fetch('/api/agent/approve-plan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, action, chosen_plan: chosenPlan }),
      });
      setResolved(true);
      setCurrentPlan(null);
    } catch (e) {
      console.error('approve-plan failed', e);
    } finally {
      setSubmitting(false);
    }
  };

  if (resolved) {
    return (
      <div className="plan-card plan-card--resolved">
        ✅ Plan approved — executing...
      </div>
    );
  }

  const renderPlan = (plan: any, label: string) => (
    <div className="plan-variant">
      <div className="plan-variant-header">
        <span className="plan-label">Plan {label}</span>
        <span className="plan-confidence" style={{ color: confidenceColor(plan.confidence) }}>
          {Math.round(plan.confidence * 100)}% confidence
        </span>
        <span className="plan-risk" style={{ background: riskBadge[plan.risk_level] || '#888' }}>
          {plan.risk_level} risk
        </span>
      </div>
      <p className="plan-rationale">{plan.rationale}</p>
      <ol className="plan-steps">
        {plan.steps.map((s: any) => (
          <li key={s.index}>
            {s.description}
            {s.files_affected?.length > 0 && (
              <span className="plan-files"> [{s.files_affected.join(', ')}]</span>
            )}
          </li>
        ))}
      </ol>
    </div>
  );

  return (
    <div className={`plan-card ${needsConfirmation ? 'plan-card--confirm' : ''}`}>
      <div className="plan-card-header">
        <span>📋 Execution Plan</span>
        {needsConfirmation && (
          <span className="plan-confirm-badge">Confirmation Required</span>
        )}
      </div>

      {renderPlan(planA, 'A')}

      {planB && (
        <div className="plan-b-section">
          <button className="plan-toggle" onClick={() => setShowPlanB(!showPlanB)}>
            {showPlanB ? '▲ Hide' : '▼ Show'} Plan B (fallback)
          </button>
          {showPlanB && renderPlan(planB, 'B')}
        </div>
      )}

      {needsConfirmation && (
        <div className="plan-actions">
          <button
            className="plan-btn plan-btn--approve"
            onClick={() => handleAction('approve', 'A')}
            disabled={submitting}
          >
            ✅ Approve Plan A
          </button>
          {planB && (
            <button
              className="plan-btn plan-btn--planb"
              onClick={() => handleAction('approve', 'B')}
              disabled={submitting}
            >
              🔄 Use Plan B
            </button>
          )}
          <button
            className="plan-btn plan-btn--stop"
            onClick={() => handleAction('stop')}
            disabled={submitting}
          >
            ⛔ Stop
          </button>
        </div>
      )}
    </div>
  );
};
