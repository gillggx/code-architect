/**
 * ProjectManagerPanel — slide-in panel showing past analyzed projects.
 * Fetches /api/projects on mount, supports re-analyze and delete.
 */

import React, { useEffect, useState } from 'react';
import { useAppStore, ProjectRecord } from '../store/app';

interface Props {
  onClose: () => void;
}

const ProjectManagerPanel: React.FC<Props> = ({ onClose }) => {
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const setProjectsList = useAppStore(s => s.setProjectsList);
  const setSelectedProject = useAppStore(s => s.setSelectedProject);
  const setPendingAnalyzePath = useAppStore(s => s.setPendingAnalyzePath);

  const fetchProjects = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch('/api/projects');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json() as { projects: ProjectRecord[] };
      setProjects(data.projects ?? []);
      setProjectsList(data.projects ?? []);
    } catch (err) {
      setError((err as Error).message || 'Failed to load projects');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchProjects(); }, []);

  const handleDelete = async (project: ProjectRecord) => {
    const confirmed = window.confirm(
      `確定要刪除「${project.project_name}」的分析記憶嗎？\n路徑: ${project.project_path}`
    );
    if (!confirmed) return;

    setDeletingId(project.project_id);
    try {
      const res = await fetch(`/api/projects/${encodeURIComponent(project.project_id)}`, {
        method: 'DELETE',
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await fetchProjects();
    } catch (err) {
      alert(`刪除失敗: ${(err as Error).message}`);
    } finally {
      setDeletingId(null);
    }
  };

  const handleReanalyze = (project: ProjectRecord) => {
    // Switch to workspace and trigger analysis via pendingAnalyzePath
    setSelectedProject({ path: project.project_path, id: project.project_id });
    setPendingAnalyzePath(project.project_path);
    onClose();
  };

  const formatDate = (iso: string | null): string => {
    if (!iso) return '未分析';
    try {
      return new Date(iso).toLocaleString('zh-TW', {
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit',
      });
    } catch {
      return iso;
    }
  };

  return (
    <>
      <div className="project-manager-overlay" onClick={onClose} />
      <div className="project-manager-panel">
        <div className="project-manager-header">
          <span className="project-manager-title">🗂 專案管理</span>
          <button className="project-manager-close" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <div className="project-manager-body">
          {loading && (
            <div className="project-manager-loading">載入中…</div>
          )}

          {!loading && error && (
            <div className="project-manager-error">
              ⚠ {error}
              <button className="modal-btn" onClick={fetchProjects} style={{ marginLeft: '0.5rem' }}>
                重試
              </button>
            </div>
          )}

          {!loading && !error && projects.length === 0 && (
            <div className="project-manager-empty">
              <p>尚無分析過的專案。</p>
              <p style={{ fontSize: '0.82rem', color: '#aaa' }}>點擊「解析專案」來開始分析。</p>
            </div>
          )}

          {!loading && !error && projects.map(project => (
            <div key={project.project_id} className="project-card">
              <div className="project-card-info">
                <div className="project-card-name">
                  📁 {project.project_name}
                </div>
                <div className="project-card-path" title={project.project_path}>
                  {project.project_path}
                </div>
                <div className="project-card-meta">
                  <span>分析時間: {formatDate(project.last_analyzed)}</span>
                  <span>{project.module_count} 個模組</span>
                </div>
              </div>
              <div className="project-card-actions">
                <button
                  className="project-card-btn reanalyze"
                  onClick={() => handleReanalyze(project)}
                >
                  重新分析
                </button>
                <button
                  className="project-card-btn delete"
                  onClick={() => handleDelete(project)}
                  disabled={deletingId === project.project_id}
                >
                  {deletingId === project.project_id ? '刪除中…' : '刪除'}
                </button>
              </div>
            </div>
          ))}
        </div>

        <div className="project-manager-footer">
          <button className="modal-btn" onClick={fetchProjects}>重新整理</button>
          <button className="modal-btn primary" onClick={onClose}>關閉</button>
        </div>
      </div>
    </>
  );
};

export default ProjectManagerPanel;
