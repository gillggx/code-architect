/**
 * TopBar — header with folder browser, pre-scan, analyze, dark mode.
 */

import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
  useAppStore,
  AgentEvent,
  FileNode,
  MemoryModule,
  AnalysisJob,
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
          <button className="folder-browser-up" onClick={() => navigate(parent)}>← Up</button>
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
              📁 {e.name}
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
  const setFilesAnalyzed = useAppStore((s) => s.setFilesAnalyzed);
  const incrementFilesAnalyzed = useAppStore((s) => s.incrementFilesAnalyzed);
  const resetProgress = useAppStore((s) => s.resetProgress);
  const { addChatMessage, updateLastAssistantMessage, setChatStreaming } = useChat();
  const chatSessionIdRef = useRef<string>(crypto.randomUUID());

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
  useAppStore.subscribe((state) => {
    fileListRef.current = state.fileTree;
    allPatternsRef.current = state.allPatterns;
  });

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

      // Load existing memory from disk so user sees past analysis immediately
      fetch(`/api/memory/${projectId}`)
        .then(r => r.json())
        .then(data => {
          if (data.modules?.length > 0) {
            data.modules.forEach((m: any) => addModule({
              name: m.name ?? m.path?.split('/').pop() ?? 'module',
              path: m.path ?? '',
              purpose: m.purpose ?? '',
              patterns: m.patterns ?? [],
              key_components: m.key_components ?? [],
            }));
            // Reflect loaded modules in progress bar
            setFilesAnalyzed(data.modules.length);
            if (data.modules.length > (scanInfo?.analyzable ?? 0)) {
              setFilesTotal(data.modules.length);
            }
          }
          if (data.patterns?.length > 0) setPatterns(data.patterns);
        })
        .catch(() => {/* no memory yet */});

      setShowModal(false);
      setInputPath('');
      setScanInfo(null);

      const wsProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
      const ws = new WebSocket(`${wsProtocol}://${window.location.host}/ws/analyze/${jobId}`);
      const job: AnalysisJob = { jobId, projectId, projectPath, status: 'running', ws };
      setCurrentJob(job);

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
          // Auto-post summary to chat
          const filesAnalyzed = (event.data?.files_analyzed as number) ?? 0;
          const patternsFound = (event.data?.patterns_found as number) ?? 0;
          const duration = (event.data?.duration_seconds as number) ?? 0;
          const projectName = projectPath.split('/').filter(Boolean).pop() ?? projectPath;
          addChatMessage({
            id: crypto.randomUUID(),
            role: 'assistant',
            content: `✅ **Analysis complete** — ${projectName}\n${filesAnalyzed} files analyzed · ${patternsFound} patterns detected · ${duration.toFixed(1)}s\n\nAsk me anything about the architecture.`,
          });
          // Trigger LLM summary
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
        // If job never reached 'complete', mark as error so UI unblocks
        const latestJob = useAppStore.getState().currentJob;
        if (latestJob?.status === 'running') {
          addEvent({ id: crypto.randomUUID(), type: 'error', message: `Connection closed${ev.reason ? ': ' + ev.reason : ''}`, timestamp: new Date() });
          setCurrentJob({ ...job, status: 'error' });
        }
      };
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
        <span className="topbar-logo">🏗</span>
        <span className="topbar-title">Code Architect</span>
        {projectLabel && (
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
          <button className="topbar-btn analyze" onClick={() => { setModalError(''); setShowModal(true); }} disabled={isRunning}>
            Analyze
          </button>
          <button className="topbar-btn" onClick={() => setDarkMode(!darkMode)} title="Toggle dark mode">
            {darkMode ? '☀️' : '🌙'}
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
                {picking ? '…' : '📁 Choose Folder'}
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
