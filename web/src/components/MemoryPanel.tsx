/**
 * MemoryPanel — right panel showing learned modules and detected patterns.
 *
 * When a file is open in the editor (centerTab === 'file'), automatically
 * focuses on that file's memory module in an expanded detail view.
 * A toggle lets the user switch back to the full module list.
 */

import React, { useState, useEffect } from 'react';
import { useMemory, useAppStore, MemoryModule, MemorySymbol } from '../store/app';

// ---------------------------------------------------------------------------
// Symbol type icons
// ---------------------------------------------------------------------------
const SYMBOL_ICON: Record<string, string> = {
  function: 'ƒ',
  method: 'ƒ',
  class: 'C',
  interface: 'I',
  variable: 'v',
};

function symbolIcon(type: string): string {
  return SYMBOL_ICON[type.toLowerCase()] ?? '·';
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function isErrorPurpose(purpose: string): boolean {
  return purpose.startsWith('[LLM Error') || purpose.startsWith('Error code:');
}

function findModuleForFile(modules: MemoryModule[], filePath: string): MemoryModule | null {
  if (!filePath) return null;
  const fileName = filePath.split('/').pop() ?? '';
  return modules.find(
    m => m.path === filePath
      || filePath.endsWith(m.path)
      || m.path.endsWith(fileName)
      || m.name === fileName,
  ) ?? null;
}

// ---------------------------------------------------------------------------
// Compact card (used in full-list mode)
// ---------------------------------------------------------------------------
const ModuleCard: React.FC<{ mod: MemoryModule }> = ({ mod }) => {
  const [expanded, setExpanded] = useState(false);
  const shortPath = mod.path.length > 42 ? '…' + mod.path.slice(-42) : mod.path;
  const hasError = isErrorPurpose(mod.purpose);
  const hasSymbols = (mod.symbols?.length ?? 0) > 0;
  const usedByCount = mod.imported_by?.length ?? 0;

  const setOpenedFile = useAppStore(s => s.setOpenedFile);
  const setCenterTab = useAppStore(s => s.setCenterTab);
  const selectedProject = useAppStore(s => s.selectedProject);

  const handleSymbolClick = (sym: MemorySymbol) => {
    if (!selectedProject) return;
    setOpenedFile({ path: mod.path, projectId: selectedProject.id, line: sym.line_start });
    setCenterTab('file');
  };

  return (
    <div className={`memory-module-card${hasError ? ' memory-module-card-error' : ''}`}>
      <div className="memory-module-header" onClick={() => hasSymbols && setExpanded(v => !v)} style={{ cursor: hasSymbols ? 'pointer' : 'default' }}>
        <span className="memory-module-name">{mod.name}</span>
        <span className="memory-module-path" title={mod.path}>{shortPath}</span>
        {usedByCount > 0 && (
          <span
            className={`memory-usedby-badge${usedByCount >= 5 ? ' hot' : ''}`}
            title={`Used by ${usedByCount} module${usedByCount !== 1 ? 's' : ''}: ${mod.imported_by!.join(', ')}`}
          >
            ↑{usedByCount}
          </span>
        )}
        {hasSymbols && (
          <span className="memory-module-expand" title={expanded ? 'Collapse symbols' : 'Expand symbols'}>
            {expanded ? '▲' : '▼'}
          </span>
        )}
      </div>
      <div
        className={`memory-module-purpose${!hasSymbols && !hasError ? ' clickable' : ''}`}
        onClick={() => !hasSymbols && setExpanded(v => !v)}
        title={expanded ? 'Click to collapse' : 'Click to expand'}
      >
        {hasError
          ? <em style={{ color: '#c0392b', fontSize: '0.78rem' }}>⚠ 分析失敗（需重新分析）</em>
          : (mod.purpose || <em>No description</em>)
        }
      </div>
      {mod.patterns.length > 0 && (
        <div className="memory-module-patterns">
          {mod.patterns.map(p => <span key={p} className="badge pattern">{p}</span>)}
        </div>
      )}
      {expanded && hasSymbols && (
        <ul className="memory-symbols-list">
          {mod.symbols!.slice(0, 20).map((sym, i) => (
            <li
              key={i}
              className="memory-symbol-row"
              onClick={() => handleSymbolClick(sym)}
              title={`Go to line ${sym.line_start}: ${sym.signature}`}
            >
              <span className="symbol-type-icon">{symbolIcon(sym.type)}</span>
              <span className="symbol-name">{sym.name}</span>
              <span className="symbol-line">:{sym.line_start}</span>
              <span className="symbol-sig" title={sym.signature}>{sym.signature.slice(0, 40)}</span>
            </li>
          ))}
        </ul>
      )}
      {expanded && !hasSymbols && mod.key_components.length > 0 && (
        <ul className="memory-key-components">
          {mod.key_components.map(c => <li key={c}>{c}</li>)}
        </ul>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Expanded file detail view (used in file-context mode)
// ---------------------------------------------------------------------------
const FileMemoryDetail: React.FC<{ mod: MemoryModule }> = ({ mod }) => {
  const hasError = isErrorPurpose(mod.purpose);
  const shortPath = mod.path.length > 50 ? '…' + mod.path.slice(-50) : mod.path;
  const hasSymbols = (mod.symbols?.length ?? 0) > 0;
  const usedByCount = mod.imported_by?.length ?? 0;

  const setOpenedFile = useAppStore(s => s.setOpenedFile);
  const setCenterTab = useAppStore(s => s.setCenterTab);
  const selectedProject = useAppStore(s => s.selectedProject);

  const handleSymbolClick = (sym: MemorySymbol) => {
    if (!selectedProject) return;
    setOpenedFile({ path: mod.path, projectId: selectedProject.id, line: sym.line_start });
    setCenterTab('file');
  };

  return (
    <div className="file-memory-detail">
      <div className="file-memory-header-row">
        <div className="file-memory-filename">{mod.name}</div>
        {usedByCount > 0 && (
          <span
            className={`memory-usedby-badge${usedByCount >= 5 ? ' hot' : ''}`}
            title={`Used by: ${mod.imported_by!.join(', ')}`}
          >
            ↑{usedByCount} users
          </span>
        )}
      </div>
      <div className="file-memory-path" title={mod.path}>{shortPath}</div>

      <div className="file-memory-section-label">📌 Purpose</div>
      <div className={`file-memory-purpose${hasError ? ' file-memory-purpose-error' : ''}`}>
        {hasError
          ? '⚠ 分析失敗（需重新分析）'
          : (mod.purpose || '（無描述）')
        }
      </div>

      {!hasError && mod.edit_hints && (
        <>
          <div className="file-memory-section-label">✏️ Edit Hints</div>
          <div className="file-memory-edit-hints">{mod.edit_hints}</div>
        </>
      )}

      {!hasError && hasSymbols && (
        <>
          <div className="file-memory-section-label">🔤 Symbols</div>
          <ul className="memory-symbols-list">
            {mod.symbols!.slice(0, 20).map((sym, i) => (
              <li
                key={i}
                className="memory-symbol-row"
                onClick={() => handleSymbolClick(sym)}
                title={`Go to line ${sym.line_start}: ${sym.signature}`}
              >
                <span className="symbol-type-icon">{symbolIcon(sym.type)}</span>
                <span className="symbol-name">{sym.name}</span>
                <span className="symbol-line">:{sym.line_start}</span>
                <span className="symbol-sig" title={sym.signature}>{sym.signature.slice(0, 40)}</span>
              </li>
            ))}
          </ul>
        </>
      )}

      {!hasError && mod.patterns.length > 0 && (
        <>
          <div className="file-memory-section-label">🏷 Patterns</div>
          <div className="file-memory-badges">
            {mod.patterns.map(p => <span key={p} className="badge pattern">{p}</span>)}
          </div>
        </>
      )}

      {!hasError && mod.key_components.length > 0 && (
        <>
          <div className="file-memory-section-label">🔑 Key Components</div>
          <ul className="file-memory-components">
            {mod.key_components.map(c => <li key={c}>{c}</li>)}
          </ul>
        </>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// MemoryPanel
// ---------------------------------------------------------------------------
const MemoryPanel: React.FC = () => {
  const { memoryModules, allPatterns, clearModules } = useMemory();
  const centerTab = useAppStore(s => s.centerTab);
  const openedFile = useAppStore(s => s.openedFile);

  const [showAll, setShowAll] = useState(false);

  // Auto-reset "show all" when the opened file changes
  useEffect(() => {
    setShowAll(false);
  }, [openedFile?.path]);

  const moduleCount = memoryModules.length;
  const errorCount = memoryModules.filter(m => isErrorPurpose(m.purpose)).length;

  // Determine if we should show file-context mode
  const fileContextMode = centerTab === 'file' && !!openedFile && !showAll;
  const focusedMod = fileContextMode
    ? findModuleForFile(memoryModules, openedFile!.path)
    : null;

  const fileName = openedFile?.path.split('/').pop() ?? '';

  return (
    <div className="panel-right">
      {/* Header */}
      <div className="panel-header">
        <span>🧠 Memory</span>
        {!fileContextMode && moduleCount > 0 && (
          <span style={{ fontWeight: 400, fontSize: '0.72rem' }}>
            ({moduleCount} module{moduleCount !== 1 ? 's' : ''})
          </span>
        )}
        {!fileContextMode && errorCount > 0 && (
          <span style={{ color: '#c0392b', fontSize: '0.68rem', marginLeft: 4 }} title="部分模組分析失敗，建議重新分析">
            ⚠ {errorCount} 失敗
          </span>
        )}
        <div style={{ display: 'flex', gap: '0.3rem', marginLeft: 'auto' }}>
          {/* Toggle between file-focus and all-modules */}
          {centerTab === 'file' && openedFile && moduleCount > 0 && (
            <button
              className="panel-header-btn"
              onClick={() => setShowAll(v => !v)}
              title={showAll ? `聚焦 ${fileName}` : '顯示所有模組'}
            >
              {showAll ? `← ${fileName}` : '↕ 全部'}
            </button>
          )}
          {moduleCount > 0 && (
            <button className="panel-header-btn" onClick={clearModules} title="清空 Memory">
              Clear
            </button>
          )}
        </div>
      </div>

      {/* Body */}
      {moduleCount === 0 && allPatterns.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">🧠</div>
          <div className="empty-state-text">No memory yet</div>
        </div>
      ) : fileContextMode ? (
        /* ── File-context mode ── */
        <div className="memory-content">
          {focusedMod ? (
            <FileMemoryDetail mod={focusedMod} />
          ) : (
            <div className="file-memory-no-record">
              <div className="empty-state-icon" style={{ fontSize: '1.5rem' }}>📄</div>
              <div style={{ fontSize: '0.82rem', color: '#888', textAlign: 'center', padding: '0 1rem' }}>
                「{fileName}」尚無記憶記錄
              </div>
              <button
                className="panel-header-btn"
                style={{ marginTop: '0.5rem' }}
                onClick={() => setShowAll(true)}
              >
                顯示所有模組
              </button>
            </div>
          )}
        </div>
      ) : (
        /* ── Full-list mode ── */
        <div className="memory-content">
          {moduleCount > 0 && (
            <section className="memory-section">
              <div className="memory-section-title">Modules</div>
              {memoryModules.map(m => <ModuleCard key={m.path} mod={m} />)}
            </section>
          )}
          {allPatterns.length > 0 && (
            <section className="memory-section">
              <div className="memory-section-title">Patterns Detected</div>
              <div className="memory-patterns-list">
                {allPatterns.map(p => <span key={p} className="badge pattern">{p}</span>)}
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
};

export default MemoryPanel;
