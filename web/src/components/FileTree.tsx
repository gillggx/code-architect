/**
 * FileTree — left panel showing analyzed project files with status icons.
 */

import React, { useState } from 'react';
import { useFileTree, useJob, FileNode } from '../store/app';

// ---------------------------------------------------------------------------
// Status icon + color
// ---------------------------------------------------------------------------
const STATUS_ICON: Record<FileNode['status'], string> = {
  pending: '⏳',
  analyzing: '🔄',
  done: '✅',
  skipped: '➖',
};

const STATUS_COLOR: Record<FileNode['status'], string> = {
  pending: '#aaa',
  analyzing: '#e67e22',
  done: '#27ae60',
  skipped: '#bbb',
};

// ---------------------------------------------------------------------------
// Single file row
// ---------------------------------------------------------------------------
const FileRow: React.FC<{ node: FileNode }> = ({ node }) => {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="file-row-wrapper">
      <div
        className={`file-row${node.summary ? ' clickable' : ''}`}
        onClick={() => node.summary && setExpanded((v) => !v)}
        title={node.path}
      >
        <span
          className="file-status-icon"
          style={{ color: STATUS_COLOR[node.status] }}
        >
          {STATUS_ICON[node.status]}
        </span>
        <span className="file-name">{node.name}</span>
        {node.summary && (
          <span className="file-expand-toggle">{expanded ? '▲' : '▼'}</span>
        )}
      </div>
      {expanded && node.summary && (
        <div className="file-summary">{node.summary}</div>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// FileTree panel
// ---------------------------------------------------------------------------
const FileTree: React.FC = () => {
  const { fileTree } = useFileTree();
  const { filesTotal, filesAnalyzed } = useJob();

  const total = fileTree.length;
  const pct = filesTotal > 0 ? Math.round((filesAnalyzed / filesTotal) * 100) : 0;
  const showProgress = filesTotal > 0;

  return (
    <div className="panel-left">
      <div className="panel-header">
        <span>📁 Files</span>
        {total > 0 && (
          <span style={{ fontWeight: 400, fontSize: '0.72rem' }}>({total})</span>
        )}
      </div>

      {total === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">📂</div>
          <div className="empty-state-text">
            Analyze a project to see files
          </div>
        </div>
      ) : (
        <>
          <div className="file-list">
            {fileTree.map((node) => (
              <FileRow key={node.path} node={node} />
            ))}
          </div>
          <div className="file-list-footer">
            {showProgress ? (
              <>
                <div className="progress-bar-track">
                  <div className="progress-bar-fill" style={{ width: `${pct}%` }} />
                </div>
                <div className="progress-bar-label">
                  {filesAnalyzed} / {filesTotal} analyzed ({pct}%)
                </div>
              </>
            ) : (
              <span>{fileTree.filter(f => f.status === 'done' || f.status === 'skipped').length} / {total} analyzed</span>
            )}
          </div>
        </>
      )}
    </div>
  );
};

export default FileTree;
