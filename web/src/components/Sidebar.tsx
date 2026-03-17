/**
 * Sidebar component
 * 
 * Displays project list and quick navigation
 */

import React from 'react';
import { useProjects, useUI } from '../store/app';

interface SidebarProps {}

/**
 * Sidebar component
 */
const Sidebar: React.FC<SidebarProps> = () => {
  const { projects, selected, setSelected } = useProjects();
  const { sidebarOpen, setSidebarOpen, setDarkMode, darkMode } = useUI();

  if (!sidebarOpen) {
    return null;
  }

  return (
    <aside className="app-sidebar">
      {/* Header */}
      <div className="sidebar-header">
        <h2>Recent Projects</h2>
        <button
          className="close-btn"
          onClick={() => setSidebarOpen(false)}
        >
          ✕
        </button>
      </div>

      {/* Projects list */}
      <div className="projects-list">
        {projects.length === 0 ? (
          <p className="empty-state">No projects yet</p>
        ) : (
          projects.map((project) => (
            <div
              key={project.project_id}
              className={`project-item ${
                selected?.project_id === project.project_id ? 'active' : ''
              }`}
              onClick={() => setSelected(project)}
            >
              <div className="project-name">{project.project_id}</div>
              <div className="project-meta">
                <span className="badge">{project.file_count} files</span>
                <span className="badge">{project.pattern_count} patterns</span>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Settings */}
      <div className="sidebar-footer">
        <label className="toggle-theme">
          <input
            type="checkbox"
            checked={darkMode}
            onChange={(e) => setDarkMode(e.target.checked)}
          />
          <span>Dark mode</span>
        </label>
      </div>
    </aside>
  );
};

export default Sidebar;
