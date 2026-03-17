/**
 * Project Explorer component
 * 
 * Displays list of analyzed projects with details
 */

import React from 'react';
import { useProjects } from '../store/app';

/**
 * Project Explorer component
 */
const ProjectExplorer: React.FC = () => {
  const { projects, isLoading, error } = useProjects();

  if (isLoading) {
    return (
      <div className="loading-container">
        <div className="spinner"></div>
        <p>Loading projects...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="error-container">
        <div className="error-icon">⚠️</div>
        <p>Error: {error}</p>
      </div>
    );
  }

  return (
    <div className="project-explorer">
      <h2>Your Projects</h2>
      
      {projects.length === 0 ? (
        <div className="empty-state">
          <p>No projects analyzed yet</p>
          <p className="help-text">Go to the Analyze tab to start</p>
        </div>
      ) : (
        <div className="projects-grid">
          {projects.map((project) => (
            <div key={project.project_id} className="project-card card">
              <div className="project-card-header">
                <h3>📁 {project.project_id}</h3>
              </div>

              <div className="project-card-body">
                <p className="project-path">
                  <strong>Path:</strong> {project.project_path}
                </p>

                <div className="project-stats">
                  <div className="stat">
                    <span className="stat-label">Files</span>
                    <span className="stat-value">{project.file_count}</span>
                  </div>
                  <div className="stat">
                    <span className="stat-label">Patterns</span>
                    <span className="stat-value">{project.pattern_count}</span>
                  </div>
                  <div className="stat">
                    <span className="stat-label">Languages</span>
                    <span className="stat-value">
                      {project.languages.length}
                    </span>
                  </div>
                </div>

                <div className="languages-list">
                  {project.languages.map((lang) => (
                    <span key={lang} className="lang-badge">
                      {lang}
                    </span>
                  ))}
                </div>

                <div className="project-timestamps">
                  <small>
                    Created:{' '}
                    {new Date(project.created_at).toLocaleDateString()}
                  </small>
                  {project.last_analyzed && (
                    <small>
                      Analyzed:{' '}
                      {new Date(project.last_analyzed).toLocaleDateString()}
                    </small>
                  )}
                </div>
              </div>

              <div className="project-card-footer">
                <button className="btn btn-primary btn-sm">View Details</button>
                <button className="btn btn-secondary btn-sm">Reanalyze</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default ProjectExplorer;
