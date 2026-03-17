/**
 * Dependency Visualizer component
 * 
 * Visual representation of project dependencies
 * and architecture patterns
 */

import React from 'react';
import { useAnalysis } from '../store/app';

/**
 * Dependency Visualizer component
 */
const DependencyVisualizer: React.FC = () => {
  const { currentAnalysis, selectedPattern } = useAnalysis();

  if (!currentAnalysis) {
    return (
      <div className="visualizer-empty">
        <p>
          📊 Analyze a project first to see dependency visualizations
        </p>
        <p className="help-text">
          Go to the Analyze tab, enter a project path, and run an analysis
        </p>
      </div>
    );
  }

  return (
    <div className="dependency-visualizer">
      <h2>Project Architecture</h2>

      {/* Pattern distribution chart */}
      <div className="chart-container card">
        <h3>Pattern Distribution</h3>
        <div className="pattern-chart">
          {currentAnalysis.patterns_detected.length === 0 ? (
            <p>No patterns detected</p>
          ) : (
            <div className="pattern-bars">
              {currentAnalysis.patterns_detected.map((pattern, idx) => (
                <div
                  key={idx}
                  className={`pattern-bar ${
                    selectedPattern?.name === pattern.name ? 'active' : ''
                  }`}
                >
                  <div
                    className="bar-fill"
                    style={{
                      width: `${pattern.confidence * 100}%`,
                      backgroundColor: getPatternColor(pattern.category),
                    }}
                  ></div>
                  <span className="bar-label">
                    {pattern.name} ({(pattern.confidence * 100).toFixed(0)}%)
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Statistics */}
      <div className="stats-grid">
        <div className="stat-card card">
          <h4>📁 Files</h4>
          <p className="stat-value">{currentAnalysis.total_files}</p>
        </div>
        <div className="stat-card card">
          <h4>🎯 Patterns</h4>
          <p className="stat-value">
            {currentAnalysis.patterns_detected.length}
          </p>
        </div>
        <div className="stat-card card">
          <h4>🌐 Languages</h4>
          <p className="stat-value">
            {currentAnalysis.supported_languages.length}
          </p>
        </div>
        <div className="stat-card card">
          <h4>⏱️ Analysis</h4>
          <p className="stat-value">
            {currentAnalysis.analysis_time_seconds.toFixed(2)}s
          </p>
        </div>
      </div>

      {/* Language breakdown */}
      {currentAnalysis.supported_languages.length > 0 && (
        <div className="languages-breakdown card">
          <h3>Languages Used</h3>
          <div className="languages-grid">
            {currentAnalysis.supported_languages.map((lang) => (
              <div key={lang} className="language-item">
                <span className="lang-icon">
                  {getLanguageIcon(lang)}
                </span>
                <span className="lang-name">{lang}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Pattern details */}
      {selectedPattern && (
        <div className="pattern-details card">
          <h3>Pattern Details: {selectedPattern.name}</h3>
          <div className="detail-grid">
            <div>
              <strong>Category:</strong> {selectedPattern.category}
            </div>
            <div>
              <strong>Confidence:</strong>{' '}
              {(selectedPattern.confidence * 100).toFixed(0)}%
            </div>
            <div>
              <strong>Evidence Count:</strong> {selectedPattern.evidence_count}
            </div>
          </div>

          {selectedPattern.locations.length > 0 && (
            <div className="locations-list">
              <strong>Locations:</strong>
              <ul>
                {selectedPattern.locations.map((loc, idx) => (
                  <li key={idx}>
                    {loc.file}:{loc.start_line}-{loc.end_line}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

/**
 * Get color for pattern category
 */
function getPatternColor(category: string): string {
  const colors: Record<string, string> = {
    oop: '#3b82f6',
    behavioral: '#8b5cf6',
    structural: '#ec4899',
    architectural: '#f59e0b',
    async_concurrency: '#10b981',
    error_handling: '#ef4444',
    data_persistence: '#06b6d4',
  };
  return colors[category] || '#6b7280';
}

/**
 * Get icon for programming language
 */
function getLanguageIcon(lang: string): string {
  const icons: Record<string, string> = {
    python: '🐍',
    javascript: '📜',
    typescript: '🔷',
    java: '☕',
    cpp: '⚙️',
    csharp: '🔶',
    go: '🐹',
    rust: '🦀',
    sql: '🗄️',
    html: '🌐',
  };
  return icons[lang] || '📄';
}

export default DependencyVisualizer;
