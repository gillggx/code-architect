/**
 * MemoryPanel — right panel showing learned modules and detected patterns.
 */

import React, { useState } from 'react';
import { useMemory, MemoryModule } from '../store/app';

// ---------------------------------------------------------------------------
// Module card
// ---------------------------------------------------------------------------
const ModuleCard: React.FC<{ mod: MemoryModule }> = ({ mod }) => {
  const [expanded, setExpanded] = useState(false);

  const shortPath =
    mod.path.length > 42 ? '…' + mod.path.slice(-42) : mod.path;

  return (
    <div className="memory-module-card">
      <div className="memory-module-header">
        <span className="memory-module-name">{mod.name}</span>
        <span className="memory-module-path" title={mod.path}>
          {shortPath}
        </span>
      </div>

      <div
        className={`memory-module-purpose${expanded ? ' expanded' : ''}`}
        onClick={() => setExpanded((v) => !v)}
        title={expanded ? 'Click to collapse' : 'Click to expand'}
      >
        {mod.purpose || <em>No description</em>}
      </div>

      {mod.patterns.length > 0 && (
        <div className="memory-module-patterns">
          {mod.patterns.map((p) => (
            <span key={p} className="badge pattern">
              {p}
            </span>
          ))}
        </div>
      )}

      {expanded && mod.key_components.length > 0 && (
        <ul className="memory-key-components">
          {mod.key_components.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// MemoryPanel
// ---------------------------------------------------------------------------
const MemoryPanel: React.FC = () => {
  const { memoryModules, allPatterns } = useMemory();

  const moduleCount = memoryModules.length;

  return (
    <div className="panel-right">
      <div className="panel-header">
        <span>🧠 Memory</span>
        {moduleCount > 0 && (
          <span style={{ fontWeight: 400, fontSize: '0.72rem' }}>
            ({moduleCount} module{moduleCount !== 1 ? 's' : ''})
          </span>
        )}
      </div>

      {moduleCount === 0 && allPatterns.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">🧠</div>
          <div className="empty-state-text">No memory yet</div>
        </div>
      ) : (
        <div className="memory-content">
          {moduleCount > 0 && (
            <section className="memory-section">
              <div className="memory-section-title">Modules</div>
              {memoryModules.map((m) => (
                <ModuleCard key={m.path} mod={m} />
              ))}
            </section>
          )}

          {allPatterns.length > 0 && (
            <section className="memory-section">
              <div className="memory-section-title">Patterns Detected</div>
              <div className="memory-patterns-list">
                {allPatterns.map((p) => (
                  <span key={p} className="badge pattern">
                    {p}
                  </span>
                ))}
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
};

export default MemoryPanel;
