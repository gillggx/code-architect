/**
 * FileTree — left panel showing analyzed project files with status icons.
 *
 * Modified files (touched by the edit agent) are marked with ●.
 */

import React, { useState } from 'react';
import { Clock, RefreshCw, CheckCircle, Minus, FolderOpen, Folder, ChevronUp, ChevronDown, Pencil, type LucideIcon } from 'lucide-react';
import { useFileTree, useJob, useAppStore, FileNode } from '../store/app';

// ---------------------------------------------------------------------------
// Status icon + color
// ---------------------------------------------------------------------------
const STATUS_ICON: Record<FileNode['status'], LucideIcon> = {
  pending:   Clock,
  analyzing: RefreshCw,
  done:      CheckCircle,
  skipped:   Minus,
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
interface FileRowProps {
  node: FileNode;
  modified: boolean;
  editMode: boolean;
  projectId: string;
  onOpenFile: (path: string) => void;
}

const FileRow: React.FC<FileRowProps> = ({ node, modified, editMode, onOpenFile }) => {
  const [expanded, setExpanded] = useState(false);

  const handleClick = () => {
    if (editMode && !node.isDir) {
      onOpenFile(node.path);
    } else if (node.summary) {
      setExpanded((v) => !v);
    }
  };

  const isClickable = (editMode && !node.isDir) || !!node.summary;

  return (
    <div className="file-row-wrapper">
      <div
        className={`file-row${isClickable ? ' clickable' : ''}${editMode && !node.isDir ? ' editable' : ''}`}
        onClick={handleClick}
        title={editMode && !node.isDir ? `Open ${node.path}` : node.path}
      >
        <span
          className="file-status-icon"
          style={{ color: STATUS_COLOR[node.status] }}
        >
          {React.createElement(STATUS_ICON[node.status], { size: 12 })}
        </span>
        <span className="file-name">{node.name}</span>
        {modified && (
          <span
            className="file-modified-dot"
            title="Modified by edit agent"
            style={{ color: '#e67e22', marginLeft: 4, fontSize: '0.7rem' }}
          >
            &#x25CF;
          </span>
        )}
        {!editMode && node.summary && (
          <span className="file-expand-toggle">
            {expanded ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
          </span>
        )}
        {editMode && !node.isDir && (
          <span className="file-open-hint" style={{ color: '#888', marginLeft: 4 }}>
            <Pencil size={10} />
          </span>
        )}
      </div>
      {!editMode && expanded && node.summary && (
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
  const modifiedFiles = useAppStore(s => s.modifiedFiles);
  const editMode = useAppStore(s => s.editMode);
  const selectedProject = useAppStore(s => s.selectedProject);
  const setOpenedFile = useAppStore(s => s.setOpenedFile);
  const setCenterTab = useAppStore(s => s.setCenterTab);

  const handleOpenFile = (path: string) => {
    if (!selectedProject) return;
    setOpenedFile({ path, projectId: selectedProject.id });
    setCenterTab('file');
  };

  const total = fileTree.length;
  const pct = filesTotal > 0 ? Math.round((filesAnalyzed / filesTotal) * 100) : 0;
  const showProgress = filesTotal > 0;

  return (
    <div className="panel-left">
      <div className="panel-header">
        <span><Folder size={13} style={{ marginRight: 5 }} />Files</span>
        {total > 0 && (
          <span style={{ fontWeight: 400, fontSize: '0.72rem' }}>({total})</span>
        )}
        {modifiedFiles.size > 0 && (
          <span
            className="file-modified-badge"
            title={`${modifiedFiles.size} file(s) modified by edit agent`}
            style={{ color: '#e67e22', fontSize: '0.72rem', marginLeft: 4 }}
          >
            &#x25CF; {modifiedFiles.size} edited
          </span>
        )}
      </div>

      {total === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon"><FolderOpen size={32} strokeWidth={1.5} /></div>
          <div className="empty-state-text">
            Analyze a project to see files
          </div>
        </div>
      ) : (
        <>
          <div className="file-list">
            {fileTree.map((node) => {
              // Check if this file (or any child) is in modifiedFiles
              const isModified = modifiedFiles.has(node.path) ||
                modifiedFiles.has(node.name) ||
                [...modifiedFiles].some(f => node.path.endsWith(f) || f.endsWith(node.name));
              return (
                <FileRow
                  key={node.path}
                  node={node}
                  modified={isModified}
                  editMode={editMode}
                  projectId={selectedProject?.id ?? ''}
                  onOpenFile={handleOpenFile}
                />
              );
            })}
          </div>
          <div className="file-list-footer">
            {showProgress ? (
              <>
                <div className="progress-bar-track">
                  <div className="progress-bar-fill" style={{ width: `${pct}%` }} />
                </div>
                <div className="progress-bar-label">
                  {filesAnalyzed} / {filesTotal} processed ({pct}%)
                </div>
              </>
            ) : (
              <span>{fileTree.filter(f => f.status === 'done' || f.status === 'skipped').length} / {total} processed</span>
            )}
          </div>
        </>
      )}
    </div>
  );
};

export default FileTree;
