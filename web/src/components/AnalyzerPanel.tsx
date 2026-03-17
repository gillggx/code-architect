/**
 * Analyzer Panel component
 * 
 * Main interface for project analysis with
 * real-time progress updates via WebSocket
 */

import React, { useState, useEffect } from 'react';
import apiClient from '../api/client';
import { useAnalysis } from '../store/app';

/**
 * Analyzer Panel component
 */
const AnalyzerPanel: React.FC = () => {
  const [projectPath, setProjectPath] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [ws, setWs] = useState<WebSocket | null>(null);

  const {
    currentAnalysis,
    isAnalyzing,
    progress,
    error,
    setCurrentAnalysis,
    setIsAnalyzing,
    setProgress,
    setError,
  } = useAnalysis();

  /**
   * Handle form submission
   */
  const handleAnalyze = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!projectPath.trim()) {
      setError('Please enter a project path');
      return;
    }

    try {
      setIsSubmitting(true);
      setError(null);
      setIsAnalyzing(true);

      const result = await apiClient.analyzeProject({
        project_path: projectPath,
        include_patterns: true,
        include_search: true,
      });

      setCurrentAnalysis(result);
      setProgress(100);

      // Connect WebSocket for real-time updates
      if (result.job_id) {
        const newWs = apiClient.connectWebSocket(result.job_id, {
          onProgress: (prog) => {
            setProgress(prog.progress_percent);
          },
          onError: (err) => {
            setError(err);
            setIsAnalyzing(false);
          },
          onComplete: (res) => {
            setIsAnalyzing(false);
          },
        });
        setWs(newWs);
      }
    } catch (err) {
      const error = err as any;
      setError(error.message || 'Analysis failed');
      setIsAnalyzing(false);
    } finally {
      setIsSubmitting(false);
    }
  };

  /**
   * Cleanup WebSocket on unmount
   */
  useEffect(() => {
    return () => {
      if (ws) {
        ws.close();
      }
    };
  }, [ws]);

  return (
    <div className="analyzer-panel">
      <h2>Analyze Project</h2>

      {/* Input form */}
      <form onSubmit={handleAnalyze} className="analysis-form card">
        <div className="input-group">
          <label htmlFor="projectPath">Project Path</label>
          <input
            id="projectPath"
            type="text"
            placeholder="Enter project directory path..."
            value={projectPath}
            onChange={(e) => setProjectPath(e.target.value)}
            disabled={isAnalyzing}
          />
          <small>
            The path to your project directory (e.g., /path/to/myapp)
          </small>
        </div>

        {error && <div className="error-message">{error}</div>}

        <button
          type="submit"
          disabled={isSubmitting || isAnalyzing}
          className="btn btn-primary"
        >
          {isSubmitting ? (
            <>
              <span className="spinner small"></span> Analyzing...
            </>
          ) : (
            <>🔍 Start Analysis</>
          )}
        </button>
      </form>

      {/* Progress display */}
      {isAnalyzing && (
        <div className="progress-container card">
          <h3>Analysis Progress</h3>
          <div className="progress-bar">
            <div
              className="progress-bar-fill"
              style={{ width: `${progress}%` }}
            ></div>
          </div>
          <p className="progress-text">{progress}% complete</p>
        </div>
      )}

      {/* Results display */}
      {currentAnalysis && (
        <div className="analysis-results card">
          <h3>Analysis Results</h3>

          <div className="results-summary">
            <div className="summary-item">
              <span className="summary-label">Total Files</span>
              <span className="summary-value">
                {currentAnalysis.total_files}
              </span>
            </div>
            <div className="summary-item">
              <span className="summary-label">Patterns Detected</span>
              <span className="summary-value">
                {currentAnalysis.patterns_detected.length}
              </span>
            </div>
            <div className="summary-item">
              <span className="summary-label">Analysis Time</span>
              <span className="summary-value">
                {currentAnalysis.analysis_time_seconds.toFixed(2)}s
              </span>
            </div>
          </div>

          {/* Patterns list */}
          {currentAnalysis.patterns_detected.length > 0 && (
            <div className="patterns-list">
              <h4>Detected Patterns</h4>
              {currentAnalysis.patterns_detected.map((pattern, idx) => (
                <div key={idx} className="pattern-item">
                  <div className="pattern-header">
                    <span className="pattern-name">{pattern.name}</span>
                    <span className="pattern-category">{pattern.category}</span>
                    <span className="pattern-confidence">
                      {(pattern.confidence * 100).toFixed(0)}%
                    </span>
                  </div>

                  {pattern.locations.length > 0 && (
                    <div className="pattern-locations">
                      <small>Found in:</small>
                      <ul>
                        {pattern.locations.map((loc, i) => (
                          <li key={i}>
                            {loc.file}:{loc.start_line}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default AnalyzerPanel;
