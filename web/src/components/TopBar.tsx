/**
 * TopBar — header with folder browser, pre-scan, analyze, dark mode.
 */

import React, { useState, useRef, useEffect, useCallback } from 'react';
import { Folder, ArrowLeft, Wrench as BuildIcon, CheckCircle, Zap, RotateCcw, RefreshCw, Sun, Moon } from 'lucide-react';
import {
  useAppStore,
  AgentEvent,
  FileNode,
  MemoryModule,
  useChat,
} from '../store/app';

// ─── Helpers ─────────────────────────────────────────────────────────────────

function makeFileNode(path: string): FileNode {
  const parts = path.split('/');
  return { path, name: parts[parts.length - 1] || path, status: 'pending', isDir: false };
}

interface BrowseEntry { name: string; path: string; is_dir: boolean }
interface BrowseResult { path: string; parent: string | null; entries: BrowseEntry[] }

// ─── FolderBrowser sub-component ─────────────────────────────────────────────

const FolderBrowser: React.FC<{
  initialPath?: string;
  onSelect: (path: string) => void;
}> = ({ initialPath = '/', onSelect }) => {
  const [currentPath, setCurrentPath] = useState(initialPath);
  const [entries, setEntries] = useState<BrowseEntry[]>([]);
  const [parent, setParent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const navigate = useCallback(async (path: string) => {
    setLoading(true);
    try {
      const res = await fetch(`/api/browse?path=${encodeURIComponent(path)}`);
      if (!res.ok) return;
      const data: BrowseResult = await res.json();
      setCurrentPath(data.path);
      setParent(data.parent);
      setEntries(data.entries);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { navigate(initialPath); }, [initialPath, navigate]);

  return (
    <div className="folder-browser">
      <div className="folder-browser-path">
        {parent && (
          <button className="folder-browser-up" onClick={() => navigate(parent)}><ArrowLeft size={12} style={{ marginRight: 3 }} />Up</button>
        )}
        <span className="folder-browser-current" title={currentPath}>
          {currentPath}
        </span>
      </div>
      <div className="folder-browser-list">
        {loading && <div className="folder-browser-loading">Loading…</div>}
        {entries.filter(e => e.is_dir).map(e => (
          <div key={e.path} className="folder-browser-entry">
            <button
              className="folder-browser-nav"
              onClick={() => navigate(e.path)}
            >
              <Folder size={12} style={{ marginRight: 4 }} />{e.name}
            </button>
            <button
              className="folder-browser-select"
              onClick={() => onSelect(e.path)}
            >
              Select
            </button>
          </div>
        ))}
        {!loading && entries.filter(e => e.is_dir).length === 0 && (
          <div className="folder-browser-empty">No subdirectories</div>
        )}
      </div>
      <div className="folder-browser-footer">
        <button className="modal-btn primary" onClick={() => onSelect(currentPath)}>
          Use this folder
        </button>
      </div>
    </div>
  );
};

// ─── TopBar ───────────────────────────────────────────────────────────────────

const TopBar: React.FC = () => {
  const darkMode = useAppStore((s) => s.darkMode);
  const setDarkMode = useAppStore((s) => s.setDarkMode);
  const selectedProject = useAppStore((s) => s.selectedProject);
  const setSelectedProject = useAppStore((s) => s.setSelectedProject);
  const appView = useAppStore((s) => s.appView);
  const setCurrentJob = useAppStore((s) => s.setCurrentJob);
  const currentJob = useAppStore((s) => s.currentJob);
  const addEvent = useAppStore((s) => s.addEvent);
  const clearEvents = useAppStore((s) => s.clearEvents);
  const setFileTree = useAppStore((s) => s.setFileTree);
  const updateFileStatus = useAppStore((s) => s.updateFileStatus);
  const addModule = useAppStore((s) => s.addModule);
  const clearModules = useAppStore((s) => s.clearModules);
  const setPatterns = useAppStore((s) => s.setPatterns);
  const setFilesTotal = useAppStore((s) => s.setFilesTotal);
  const incrementFilesAnalyzed = useAppStore((s) => s.incrementFilesAnalyzed);
  const resetProgress = useAppStore((s) => s.resetProgress);
  const pendingAnalyzePath = useAppStore((s) => s.pendingAnalyzePath);
  const setPendingAnalyzePath = useAppStore((s) => s.setPendingAnalyzePath);
  const { addChatMessage, updateLastAssistantMessage, setChatStreaming } = useChat();
  const chatSessionIdRef = useRef<string>(crypto.randomUUID());

  const freshnessStatus = useAppStore((s) => s.freshnessStatus);
  const setFreshnessStatus = useAppStore((s) => s.setFreshnessStatus);
  const agentSession = useAppStore((s) => s.agentSession);
  const setAgentSession = useAppStore((s) => s.setAgentSession);

  const [showModal, setShowModal] = useState(false);
  const [showBrowser, setShowBrowser] = useState(false);
  const [inputPath, setInputPath] = useState('');
  const [picking, setPicking] = useState(false);
  const [scanInfo, setScanInfo] = useState<{ total: number; analyzable: number } | null>(null);
  const [scanning, setScanning] = useState(false);
  const [modalError, setModalError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const fileListRef = useRef<FileNode[]>([]);
  const allPatternsRef = useRef<string[]>([]);
  useEffect(() => {
    return useAppStore.subscribe((state) => {
      fileListRef.current = state.fileTree;
      allPatternsRef.current = state.allPatterns;
    });
  }, []);

  // Attach WebSocket event handlers whenever a new analysis job starts.
  // This covers jobs started from both TopBar (Analyze button) and HomeView (card flow).
  useEffect(() => {
    if (!currentJob || !currentJob.ws) return;
    const job = currentJob;
    const ws = currentJob.ws as WebSocket;
    const { projectId, projectPath } = job;

    ws.onmessage = (ev) => {
      let payload: Record<string, unknown>;
      try { payload = JSON.parse(ev.data as string); } catch { return; }
      if (payload.type !== 'agent_event') return;

      const raw = (
        typeof payload.data === 'object' && payload.data !== null
          ? payload.data : payload
      ) as Record<string, unknown>;

      const event: AgentEvent = {
        id: (raw.id as string) ?? crypto.randomUUID(),
        type: (raw.type as AgentEvent['type']) ?? 'scan',
        message: (raw.message as string) ?? '',
        file: raw.file as string | undefined,
        summary: raw.summary as string | undefined,
        data: raw.data as Record<string, unknown> | undefined,
        timestamp: new Date(),
      };

      addEvent(event);

      if (event.file) {
        if (event.type === 'scan') addFileIfMissing(event.file);
        else if (event.type === 'llm_start') {
          addFileIfMissing(event.file);
          updateFileStatus(event.file, 'analyzing');
        } else if (event.type === 'llm_done') {
          updateFileStatus(event.file, 'done', event.summary);
          incrementFilesAnalyzed();
        } else if (event.type === 'skip') {
          addFileIfMissing(event.file);
          updateFileStatus(event.file, 'skipped');
          incrementFilesAnalyzed();
        }
      }

      if (event.type === 'memory' && event.data) {
        const d = event.data;
        const mod: MemoryModule = {
          name: (d.name as string) ?? event.file ?? 'module',
          path: (d.path as string) ?? event.file ?? '',
          purpose: (d.purpose as string) ?? event.summary ?? '',
          patterns: Array.isArray(d.patterns) ? (d.patterns as string[]) : [],
          key_components: Array.isArray(d.key_components) ? (d.key_components as string[]) : [],
          symbols: Array.isArray(d.symbols) ? (d.symbols as any[]) : undefined,
          edit_hints: (d.edit_hints as string) || undefined,
          imported_by: Array.isArray(d.imported_by) ? (d.imported_by as string[]) : undefined,
        };
        addModule(mod);
      }

      if (event.type === 'pattern') {
        const pattern = (event.data?.pattern as string) ?? (event.data?.name as string) ?? event.message;
        if (pattern) addPatternIfMissing(pattern);
      }

      if (event.type === 'done') {
        setCurrentJob({ ...job, status: 'complete' });
        ws.close();
        // Refresh freshness status after analysis completes
        setTimeout(() => checkFreshness(projectId), 1000);
        // Reload full file tree + modules from disk so Refresh doesn't show partial tree
        (async () => {
          try {
            const r = await fetch(`/api/projects/${encodeURIComponent(projectId)}/load`);
            if (!r.ok) return;
            const d = await r.json() as {
              modules: Array<Record<string, unknown>>;
              file_tree: Array<{ path: string; name: string; status: string; isDir: boolean; summary?: string }>;
            };
            if (d.file_tree?.length) {
              fileListRef.current = d.file_tree as FileNode[];
              setFileTree(d.file_tree as FileNode[]);
            }
            if (d.modules?.length) {
              clearModules();
              for (const m of d.modules) {
                addModule({
                  name: (m.name as string) || '',
                  path: (m.path as string) || '',
                  purpose: (m.purpose as string) || '',
                  patterns: Array.isArray(m.patterns) ? (m.patterns as string[]) : [],
                  key_components: Array.isArray(m.key_components) ? (m.key_components as string[]) : [],
                  symbols: Array.isArray(m.symbols) ? (m.symbols as any[]) : undefined,
                  edit_hints: (m.edit_hints as string) || undefined,
                  imported_by: Array.isArray(m.imported_by) ? (m.imported_by as string[]) : undefined,
                });
              }
            }
          } catch { /* ignore */ }
        })();
        const filesAnalyzed = (event.data?.files_analyzed as number) ?? 0;
        const patternsFound = (event.data?.patterns_found as number) ?? 0;
        const duration = (event.data?.duration_seconds as number) ?? 0;
        const projectName = projectPath.split('/').filter(Boolean).pop() ?? projectPath;
        addChatMessage({
          id: crypto.randomUUID(),
          role: 'assistant',
          content: `**Analysis complete** — ${projectName}\n${filesAnalyzed} files analyzed · ${patternsFound} patterns detected · ${duration.toFixed(1)}s\n\nAsk me anything about the architecture.`,
        });
        const autoPrompt = `Summarize the key architectural findings from this analysis in 3-5 bullet points.`;
        addChatMessage({ id: crypto.randomUUID(), role: 'user', content: autoPrompt });
        setChatStreaming(true);
        addChatMessage({ id: crypto.randomUUID(), role: 'assistant', content: '', streaming: true });
        (async () => {
          try {
            const res = await fetch('/api/chat', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ message: autoPrompt, project_id: projectId, session_id: chatSessionIdRef.current }),
            });
            if (res.ok) {
              const reader = res.body?.getReader();
              const decoder = new TextDecoder();
              let buf = '';
              while (reader) {
                const { done, value } = await reader.read();
                if (done) break;
                buf += decoder.decode(value, { stream: true });
                const lines = buf.split('\n');
                buf = lines.pop() ?? '';
                for (const line of lines) {
                  const t = line.trim();
                  if (!t.startsWith('data:')) continue;
                  const raw = t.slice(5).trim();
                  if (raw === '[DONE]') break;
                  try {
                    const p = JSON.parse(raw) as { type?: string; data?: string; delta?: string; text?: string; content?: string };
                    if (p.type === 'done') break;
                    const chunk = p.data ?? p.delta ?? p.text ?? p.content ?? '';
                    if (chunk) updateLastAssistantMessage(chunk);
                  } catch { if (raw) updateLastAssistantMessage(raw); }
                }
              }
            }
          } finally {
            setChatStreaming(false);
          }
        })();
      } else if (event.type === 'error') {
        setCurrentJob({ ...job, status: 'error' });
        ws.close();
      }
    };

    ws.onerror = () => {
      addEvent({ id: crypto.randomUUID(), type: 'error', message: 'WebSocket connection error', timestamp: new Date() });
      setCurrentJob({ ...job, status: 'error' });
    };

    ws.onclose = (ev) => {
      const latestJob = useAppStore.getState().currentJob;
      if (latestJob?.status === 'running') {
        addEvent({ id: crypto.randomUUID(), type: 'error', message: `Connection closed${ev.reason ? ': ' + ev.reason : ''}`, timestamp: new Date() });
        setCurrentJob({ ...job, status: 'error' });
      }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentJob?.jobId]);

  // Watch pendingAnalyzePath from ProjectManager
  useEffect(() => {
    if (!pendingAnalyzePath) return;
    setInputPath(pendingAnalyzePath);
    setPendingAnalyzePath(null);
    setShowModal(true);
  }, [pendingAnalyzePath, setPendingAnalyzePath]);

  // Freshness check — runs once when project is selected, then every 30s
  const checkFreshness = useCallback(async (projectId: string) => {
    try {
      const res = await fetch(`/api/projects/${encodeURIComponent(projectId)}/freshness`);
      if (!res.ok) return;
      const data = await res.json() as {
        is_fresh: boolean;
        changed_files: Array<{ path: string; reason: string }>;
        new_files: Array<{ path: string; reason: string }>;
        last_analyzed_at: string | null;
      };
      const changedCount = data.changed_files.length + data.new_files.length;
      setFreshnessStatus({
        isStale: !data.is_fresh,
        changedCount,
        lastAnalyzedAt: data.last_analyzed_at,
        checkedAt: Date.now(),
      });
    } catch {
      // Network error — silently ignore, don't disrupt UX
    }
  }, [setFreshnessStatus]);

  useEffect(() => {
    if (!selectedProject) {
      setFreshnessStatus(null);
      return;
    }
    // Check immediately when project loads or changes
    checkFreshness(selectedProject.id);
    // Then every 30 seconds
    const interval = setInterval(() => checkFreshness(selectedProject.id), 30_000);
    return () => clearInterval(interval);
  }, [selectedProject?.id, checkFreshness, setFreshnessStatus]);

  // Pre-scan when path changes (debounced)
  useEffect(() => {
    if (!inputPath.trim()) { setScanInfo(null); return; }
    const t = setTimeout(async () => {
      setScanning(true);
      try {
        const res = await fetch(`/api/scan?path=${encodeURIComponent(inputPath.trim())}`);
        if (res.ok) {
          const d = await res.json();
          setScanInfo({ total: d.total_files, analyzable: d.analyzable_files });
        } else {
          setScanInfo(null);
        }
      } catch { setScanInfo(null); }
      setScanning(false);
    }, 500);
    return () => clearTimeout(t);
  }, [inputPath]);

  const addFileIfMissing = (filePath: string) => {
    const exists = fileListRef.current.some((n) => n.path === filePath);
    if (!exists) {
      const updated = [...fileListRef.current, makeFileNode(filePath)];
      fileListRef.current = updated;
      setFileTree(updated);
    }
  };

  const addPatternIfMissing = (pattern: string) => {
    if (!allPatternsRef.current.includes(pattern)) {
      const updated = [...allPatternsRef.current, pattern];
      allPatternsRef.current = updated;
      setPatterns(updated);
    }
  };

  const handleRollback = async () => {
    if (!agentSession || !selectedProject) return;
    if (!window.confirm('Roll back all agent changes and return to base branch?')) return;
    try {
      const res = await fetch(
        `/api/agent/rollback-session-v2?session_id=${encodeURIComponent(agentSession)}&project_path=${encodeURIComponent(selectedProject.path)}`,
        { method: 'POST' }
      );
      if (res.ok) {
        setAgentSession(null);
        clearEvents();
        addEvent({ id: crypto.randomUUID(), type: 'message' as any, message: 'Rolled back to base branch.', timestamp: new Date() });
      } else {
        const body = await res.json().catch(() => ({})) as { detail?: string };
        addEvent({ id: crypto.randomUUID(), type: 'error', message: `Rollback failed: ${body.detail ?? res.status}`, timestamp: new Date() });
      }
    } catch (err) {
      addEvent({ id: crypto.randomUUID(), type: 'error', message: `Rollback error: ${(err as Error).message}`, timestamp: new Date() });
    }
  };

  const handleRefresh = async () => {
    if (!selectedProject) return;
    setIsSubmitting(true);
    try {
      const res = await fetch('/api/analyze/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_path: selectedProject.path, project_id: selectedProject.id }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({})) as { detail?: string };
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      const data = await res.json() as { job_id: string; project_id: string };
      const { job_id: jobId, project_id: projectId } = data;

      clearEvents();
      resetProgress();
      // Don't clear file tree — Refresh only re-analyzes a subset of files.
      // After the job completes, the done handler below will reload the full tree.

      setFreshnessStatus(null);

      const wsProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
      const ws = new WebSocket(`${wsProtocol}://${window.location.host}/ws/analyze/${jobId}`);
      setCurrentJob({ jobId, projectId, projectPath: selectedProject.path, status: 'running', ws });
    } catch (err) {
      console.error('Refresh failed:', err);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleForceAnalyze = async () => {
    if (!selectedProject) return;
    if (!window.confirm('Force full re-analysis? This will re-read all files and overwrite the current memory.')) return;
    setIsSubmitting(true);
    try {
      const res = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_path: selectedProject.path }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({})) as { detail?: string };
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      const data = await res.json() as { job_id: string; project_id: string };
      const { job_id: jobId, project_id: projectId } = data;

      clearEvents();
      clearModules();
      resetProgress();
      fileListRef.current = [];
      allPatternsRef.current = [];
      setFileTree([]);
      setPatterns([]);
      setFreshnessStatus(null);

      const wsProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
      const ws = new WebSocket(`${wsProtocol}://${window.location.host}/ws/analyze/${jobId}`);
      setCurrentJob({ jobId, projectId, projectPath: selectedProject.path, status: 'running', ws });
    } catch (err) {
      console.error('Force re-analyze failed:', err);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleAnalyze = async () => {
    const projectPath = inputPath.trim();
    if (!projectPath) { setModalError('Please enter a project path.'); return; }
    setModalError('');
    setIsSubmitting(true);
    try {
      const res = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_path: projectPath }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({})) as { detail?: string };
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      const data = await res.json() as { job_id: string; project_id: string };
      const { job_id: jobId, project_id: projectId } = data;

      clearEvents();
      clearModules();
      resetProgress();
      fileListRef.current = [];
      allPatternsRef.current = [];
      setFileTree([]);
      setPatterns([]);
      if (scanInfo) setFilesTotal(scanInfo.analyzable);

      setSelectedProject({ path: projectPath, id: projectId });

      setShowModal(false);
      setInputPath('');
      setScanInfo(null);

      const wsProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
      const ws = new WebSocket(`${wsProtocol}://${window.location.host}/ws/analyze/${jobId}`);
      setCurrentJob({ jobId, projectId, projectPath, status: 'running', ws });
      // Handlers are attached by the useEffect below that watches currentJob.jobId
    } catch (err) {
      setModalError((err as Error).message || 'Failed to start analysis');
    } finally {
      setIsSubmitting(false);
    }
  };

  const isRunning = currentJob?.status === 'running';
  const projectLabel = selectedProject?.path ?? null;

  return (
    <>
      <header className="topbar">
        {appView === 'workspace' ? (
          <button
            className="topbar-btn topbar-home-btn"
            onClick={() => setSelectedProject(null)}
            title="Return to Home"
          >
            <ArrowLeft size={13} style={{ marginRight: 4 }} />首頁
          </button>
        ) : (
          <>
            <span className="topbar-logo"><BuildIcon size={16} /></span>
            <span className="topbar-title">Code Architect</span>
          </>
        )}
        {projectLabel && appView === 'workspace' && (
          <span className="topbar-project" title={projectLabel}>
            {projectLabel.split('/').slice(-2).join('/')}
          </span>
        )}
        <div className="topbar-actions">
          {isRunning && (
            <span className="topbar-analyzing">
              <span className="spinner" /> Analyzing…
              <button
                className="topbar-cancel-btn"
                title="Cancel / clear stuck state"
                onClick={() => {
                  currentJob?.ws?.close();
                  setCurrentJob(null);
                }}
              >✕</button>
            </span>
          )}
          {!isRunning && freshnessStatus?.isStale && appView === 'workspace' && (
            <button
              className="topbar-freshness-stale topbar-freshness-btn"
              title={`${freshnessStatus.changedCount} 個檔案已變動，點擊執行增量刷新`}
              onClick={handleRefresh}
              disabled={isSubmitting}
            >
              <Zap size={12} style={{ marginRight: 3 }} />{freshnessStatus.changedCount} 變動
            </button>
          )}
          {!isRunning && freshnessStatus && !freshnessStatus.isStale && appView === 'workspace' && (
            <span className="topbar-freshness-fresh" title="所有追蹤檔案均為最新">
              <CheckCircle size={12} style={{ marginRight: 3 }} />最新
            </span>
          )}
          {appView === 'workspace' && agentSession && (
            <button
              className="topbar-btn topbar-rollback-btn"
              onClick={handleRollback}
              title="Roll back all agent changes (git checkout base branch)"
            >
              <RotateCcw size={12} style={{ marginRight: 4 }} />Rollback
            </button>
          )}
          {appView === 'workspace' && selectedProject && (
            <button
              className="topbar-btn"
              onClick={handleRefresh}
              disabled={isRunning || isSubmitting}
              title="只重新分析新增或變動的檔案"
            >
              <Zap size={12} style={{ marginRight: 3 }} />Refresh
            </button>
          )}
          {appView === 'workspace' && selectedProject && (
            <button
              className="topbar-btn"
              onClick={handleForceAnalyze}
              disabled={isRunning || isSubmitting}
              title="強制重新分析所有檔案（清除快取）"
            >
              <RefreshCw size={12} style={{ marginRight: 3 }} />Re-analyze
            </button>
          )}
          {appView === 'workspace' && (
            <button className="topbar-btn analyze" onClick={() => { setModalError(''); setShowModal(true); }} disabled={isRunning}>
              Analyze
            </button>
          )}
          <button className="topbar-btn" onClick={() => setDarkMode(!darkMode)} title="Toggle dark mode">
            {darkMode ? <Sun size={13} /> : <Moon size={13} />}
          </button>
        </div>
      </header>

      {showModal && (
        <div className="modal-backdrop" onClick={() => setShowModal(false)}>
          <div className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
            <h2>Analyze a Project</h2>

            <div className="path-input-row">
              <input
                className="modal-input"
                type="text"
                placeholder="/path/to/your/project"
                value={inputPath}
                onChange={(e) => setInputPath(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') handleAnalyze(); if (e.key === 'Escape') setShowModal(false); }}
                autoFocus
              />
              <button
                className="modal-btn browse-btn"
                disabled={picking}
                onClick={async () => {
                  setPicking(true);
                  try {
                    const res = await fetch('/api/native-pick');
                    if (res.ok) {
                      const d = await res.json();
                      if (d.path) setInputPath(d.path);
                    } else {
                      // fallback to web browser
                      setShowBrowser(!showBrowser);
                    }
                  } catch {
                    setShowBrowser(!showBrowser);
                  } finally {
                    setPicking(false);
                  }
                }}
              >
                {picking ? '…' : <><Folder size={12} style={{ marginRight: 4 }} />Choose Folder</>}
              </button>
            </div>

            {showBrowser && (
              <FolderBrowser
                initialPath={inputPath || '/'}
                onSelect={(p) => { setInputPath(p); setShowBrowser(false); }}
              />
            )}

            {scanning && <div className="scan-info scanning">Scanning…</div>}
            {!scanning && scanInfo && (
              <div className="scan-info">
                Found <strong>{scanInfo.total.toLocaleString()}</strong> files total —{' '}
                <strong>{scanInfo.analyzable.toLocaleString()}</strong> source files to analyze
              </div>
            )}

            {modalError && <div className="modal-error">{modalError}</div>}

            <div className="modal-actions">
              <button className="modal-btn" onClick={() => { setShowModal(false); setModalError(''); }}>Cancel</button>
              <button className="modal-btn primary" onClick={handleAnalyze} disabled={isSubmitting || !inputPath.trim()}>
                {isSubmitting ? 'Starting…' : 'Start Analysis'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};

export default TopBar;
