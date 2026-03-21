/**
 * HomeView — full-screen home with 3 mode cards (analyze / new project / manage).
 * Shown when appView === 'home'.
 */

import React, { useState, useRef, useEffect, useCallback } from 'react';
import { useAppStore, ChatMessage } from '../store/app';
import ProjectManagerPanel from './ProjectManagerPanel';

// ---------------------------------------------------------------------------
// Folder browser (inline, reused from TopBar pattern)
// ---------------------------------------------------------------------------

interface BrowseEntry { name: string; path: string; is_dir: boolean }
interface BrowseResult { path: string; parent: string | null; entries: BrowseEntry[] }

const FolderBrowser: React.FC<{
  initialPath?: string;
  onSelect: (path: string) => void;
  onCancel: () => void;
}> = ({ initialPath = '/', onSelect, onCancel }) => {
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
    <div className="folder-browser home-folder-browser">
      <div className="folder-browser-path">
        {parent && (
          <button className="folder-browser-up" onClick={() => navigate(parent)}>← Up</button>
        )}
        <span className="folder-browser-current" title={currentPath}>{currentPath}</span>
      </div>
      <div className="folder-browser-list">
        {loading && <div className="folder-browser-loading">Loading…</div>}
        {entries.filter(e => e.is_dir).map(e => (
          <div key={e.path} className="folder-browser-entry">
            <button className="folder-browser-nav" onClick={() => navigate(e.path)}>
              📁 {e.name}
            </button>
            <button className="folder-browser-select" onClick={() => onSelect(e.path)}>
              Select
            </button>
          </div>
        ))}
        {!loading && entries.filter(e => e.is_dir).length === 0 && (
          <div className="folder-browser-empty">No subdirectories</div>
        )}
      </div>
      <div className="folder-browser-footer" style={{ display: 'flex', gap: '0.5rem' }}>
        <button className="modal-btn" onClick={onCancel}>Cancel</button>
        <button className="modal-btn primary" onClick={() => onSelect(currentPath)}>
          Use this folder
        </button>
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// HomeView
// ---------------------------------------------------------------------------

const SPEC_START = '===SPEC_START===';
const SPEC_END = '===SPEC_END===';

function extractSpec(text: string): string | null {
  const start = text.indexOf(SPEC_START);
  const end = text.indexOf(SPEC_END);
  if (start === -1 || end === -1) return null;
  return text.slice(start + SPEC_START.length, end).trim();
}

const HomeView: React.FC = () => {
  const newProjectStep = useAppStore(s => s.newProjectStep);
  const setNewProjectStep = useAppStore(s => s.setNewProjectStep);
  const newProjectMessages = useAppStore(s => s.newProjectMessages);
  const addNewProjectMessage = useAppStore(s => s.addNewProjectMessage);
  const updateLastNewProjectMessage = useAppStore(s => s.updateLastNewProjectMessage);
  const clearNewProjectMessages = useAppStore(s => s.clearNewProjectMessages);
  const newProjectSpec = useAppStore(s => s.newProjectSpec);
  const setNewProjectSpec = useAppStore(s => s.setNewProjectSpec);
  const setSelectedProject = useAppStore(s => s.setSelectedProject);
  const addEvent = useAppStore(s => s.addEvent);
  const clearEvents = useAppStore(s => s.clearEvents);
  const clearModules = useAppStore(s => s.clearModules);
  const setFileTree = useAppStore(s => s.setFileTree);
  const setPatterns = useAppStore(s => s.setPatterns);
  const resetProgress = useAppStore(s => s.resetProgress);
  const setCurrentJob = useAppStore(s => s.setCurrentJob);

  // Analyze flow (inline)
  const [showAnalyzeModal, setShowAnalyzeModal] = useState(false);
  const [analyzeInputPath, setAnalyzeInputPath] = useState('');
  const [showBrowser, setShowBrowser] = useState(false);
  const [scanInfo, setScanInfo] = useState<{ total: number; analyzable: number } | null>(null);
  const [scanning, setScanning] = useState(false);
  const [analyzeError, setAnalyzeError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  // New project chat flow
  const [chatInput, setChatInput] = useState('');
  const [isChatStreaming, setIsChatStreaming] = useState(false);
  const chatSessionIdRef = useRef<string>(crypto.randomUUID());
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Project manager panel
  const [showProjectManager, setShowProjectManager] = useState(false);

  // Build output dir for spec confirmation
  const [buildDir, setBuildDir] = useState('');
  const [showBuildDirBrowser, setShowBuildDirBrowser] = useState(false);
  const [buildError, setBuildError] = useState('');
  const [isBuilding, setIsBuilding] = useState(false);

  // Scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [newProjectMessages]);

  // Pre-scan debounce
  useEffect(() => {
    if (!analyzeInputPath.trim()) { setScanInfo(null); return; }
    const t = setTimeout(async () => {
      setScanning(true);
      try {
        const res = await fetch(`/api/scan?path=${encodeURIComponent(analyzeInputPath.trim())}`);
        if (res.ok) {
          const d = await res.json();
          setScanInfo({ total: d.total_files, analyzable: d.analyzable_files });
        } else { setScanInfo(null); }
      } catch { setScanInfo(null); }
      setScanning(false);
    }, 500);
    return () => clearTimeout(t);
  }, [analyzeInputPath]);

  // ── Greet on entering chatting mode ──────────────────────────────────────

  useEffect(() => {
    if (newProjectStep === 'chatting' && newProjectMessages.length === 0) {
      addNewProjectMessage({
        id: crypto.randomUUID(),
        role: 'assistant',
        content: '你好！我來幫你規劃新專案。請描述你想建立什麼？',
      });
    }
  }, [newProjectStep, newProjectMessages.length, addNewProjectMessage]);

  // ── Send message to /api/chat/new-project ─────────────────────────────────

  const sendNewProjectMessage = async (text: string) => {
    if (!text.trim() || isChatStreaming) return;
    const userMsg: ChatMessage = { id: crypto.randomUUID(), role: 'user', content: text };
    addNewProjectMessage(userMsg);
    setChatInput('');
    setIsChatStreaming(true);

    // Seed streaming assistant bubble
    addNewProjectMessage({ id: crypto.randomUUID(), role: 'assistant', content: '', streaming: true });

    try {
      const res = await fetch('/api/chat/new-project', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          session_id: chatSessionIdRef.current,
          project_id: null,
        }),
      });
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      let fullAssistant = '';

      while (true) {
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
            const p = JSON.parse(raw) as { type?: string; data?: string };
            if (p.type === 'done') break;
            if (p.type === 'chunk' && p.data) {
              fullAssistant += p.data;
              updateLastNewProjectMessage(p.data);
            }
          } catch { /* ignore parse errors */ }
        }
      }

      // Check for spec in the full response
      const spec = extractSpec(fullAssistant);
      if (spec) {
        setNewProjectSpec(spec);
        setNewProjectStep('spec_ready');
      }
    } catch (err) {
      updateLastNewProjectMessage(`\n\n[Error: ${(err as Error).message}]`);
    } finally {
      setIsChatStreaming(false);
    }
  };

  // ── Analyze project (from inline modal) ──────────────────────────────────

  const handleAnalyze = async () => {
    const projectPath = analyzeInputPath.trim();
    if (!projectPath) { setAnalyzeError('Please enter a project path.'); return; }
    setAnalyzeError('');
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
      setFileTree([]);
      setPatterns([]);

      setSelectedProject({ path: projectPath, id: projectId });
      setShowAnalyzeModal(false);
      setAnalyzeInputPath('');
      setScanInfo(null);

      // Load existing memory
      fetch(`/api/memory/${projectId}`)
        .then(r => r.json())
        .then((memData: { modules?: unknown[]; patterns?: string[] }) => {
          if (memData.modules?.length) {
            // modules get loaded by TopBar's WS handler; just set patterns
          }
          if (memData.patterns?.length) setPatterns(memData.patterns);
        })
        .catch(() => {});

      const wsProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
      const ws = new WebSocket(`${wsProtocol}://${window.location.host}/ws/analyze/${jobId}`);
      setCurrentJob({ jobId, projectId, projectPath, status: 'running', ws });

      ws.onmessage = () => { /* handled by TopBar */ };
      ws.onerror = () => { addEvent({ id: crypto.randomUUID(), type: 'error', message: 'WebSocket error', timestamp: new Date() }); };
    } catch (err) {
      setAnalyzeError((err as Error).message || 'Failed to start analysis');
    } finally {
      setIsSubmitting(false);
    }
  };

  // ── Build new project from spec ───────────────────────────────────────────

  const handleBuildProject = async () => {
    if (!buildDir.trim()) { setBuildError('Please choose an output directory.'); return; }
    if (!newProjectSpec) return;
    setBuildError('');
    setIsBuilding(true);
    setNewProjectStep('building');
    try {
      // First analyze the output dir to get a project_id
      const analyzeRes = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_path: buildDir.trim() }),
      });
      if (!analyzeRes.ok) throw new Error(`Analyze failed: HTTP ${analyzeRes.status}`);
      const { project_id: projectId } = await analyzeRes.json() as { project_id: string; job_id: string };

      // Then call a2a/generate with the spec
      const genRes = await fetch('/api/a2a/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task: newProjectSpec,
          project_id: projectId,
          mode: 'apply',
        }),
      });
      if (!genRes.ok) throw new Error(`Generate failed: HTTP ${genRes.status}`);

      setSelectedProject({ path: buildDir.trim(), id: projectId });
      clearNewProjectMessages();
      setNewProjectSpec(null);
    } catch (err) {
      setBuildError((err as Error).message);
      setNewProjectStep('spec_ready');
    } finally {
      setIsBuilding(false);
    }
  };

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="home-view">
      {/* ── Idle: 3 mode cards ── */}
      {newProjectStep === 'idle' && (
        <>
          <div className="home-hero">
            <div className="home-hero-icon">🏗</div>
            <h1 className="home-hero-title">Code Architect</h1>
            <p className="home-hero-subtitle">你的 AI 程式碼設計夥伴</p>
          </div>

          <div className="home-cards">
            <button
              className="home-card"
              onClick={() => setShowAnalyzeModal(true)}
            >
              <span className="home-card-icon">🔍</span>
              <span className="home-card-title">解析專案</span>
              <span className="home-card-desc">分析現有程式碼庫，建立架構記憶</span>
            </button>

            <button
              className="home-card"
              onClick={() => {
                clearNewProjectMessages();
                setNewProjectSpec(null);
                chatSessionIdRef.current = crypto.randomUUID();
                setNewProjectStep('chatting');
              }}
            >
              <span className="home-card-icon">✨</span>
              <span className="home-card-title">建新專案</span>
              <span className="home-card-desc">從零開始，AI 幫你規劃並生成專案</span>
            </button>

            <button
              className="home-card"
              onClick={() => setShowProjectManager(true)}
            >
              <span className="home-card-icon">🗂</span>
              <span className="home-card-title">專案管理</span>
              <span className="home-card-desc">管理已分析的歷史專案</span>
            </button>
          </div>
        </>
      )}

      {/* ── Chatting: new project chat ── */}
      {(newProjectStep === 'chatting') && (
        <div className="home-chat-container">
          <div className="home-chat-header">
            <button
              className="home-back-btn"
              onClick={() => { setNewProjectStep('idle'); clearNewProjectMessages(); }}
            >
              ← 返回
            </button>
            <span className="home-chat-title">✨ 規劃新專案</span>
          </div>

          <div className="home-chat-area">
            {newProjectMessages.map(msg => (
              <div
                key={msg.id}
                className={`chat-bubble ${msg.role === 'user' ? 'chat-bubble-user' : 'chat-bubble-assistant'}`}
              >
                <div className="chat-bubble-role">{msg.role === 'user' ? 'You' : 'Architect AI'}</div>
                <div className="chat-bubble-content">
                  {msg.content}
                  {msg.streaming && !msg.content && <span className="chat-cursor">▋</span>}
                </div>
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>

          <div className="home-chat-input-row">
            <textarea
              className="home-chat-input"
              placeholder="描述你的專案想法…"
              value={chatInput}
              onChange={e => setChatInput(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  sendNewProjectMessage(chatInput);
                }
              }}
              disabled={isChatStreaming}
              rows={2}
            />
            <button
              className="home-chat-send-btn"
              onClick={() => sendNewProjectMessage(chatInput)}
              disabled={isChatStreaming || !chatInput.trim()}
            >
              {isChatStreaming ? '…' : '送出'}
            </button>
          </div>
        </div>
      )}

      {/* ── Spec ready: preview + confirm ── */}
      {newProjectStep === 'spec_ready' && newProjectSpec && (
        <div className="home-chat-container">
          <div className="home-chat-header">
            <button
              className="home-back-btn"
              onClick={() => setNewProjectStep('chatting')}
            >
              ← 修改 Spec
            </button>
            <span className="home-chat-title">📄 專案規格確認</span>
          </div>

          <div className="spec-preview">
            <pre className="spec-preview-content">{newProjectSpec}</pre>
          </div>

          <div className="spec-actions">
            <div className="spec-dir-row">
              <input
                className="modal-input"
                type="text"
                placeholder="/path/to/output/directory"
                value={buildDir}
                onChange={e => setBuildDir(e.target.value)}
              />
              <button
                className="modal-btn browse-btn"
                onClick={() => setShowBuildDirBrowser(!showBuildDirBrowser)}
              >
                📁 選擇
              </button>
            </div>

            {showBuildDirBrowser && (
              <FolderBrowser
                initialPath={buildDir || '/'}
                onSelect={p => { setBuildDir(p); setShowBuildDirBrowser(false); }}
                onCancel={() => setShowBuildDirBrowser(false)}
              />
            )}

            {buildError && <div className="modal-error">{buildError}</div>}

            <div className="spec-action-btns">
              <button
                className="modal-btn"
                onClick={() => {
                  setNewProjectStep('idle');
                  clearNewProjectMessages();
                  setNewProjectSpec(null);
                }}
              >
                重新來過
              </button>
              <button
                className="modal-btn"
                onClick={() => setNewProjectStep('chatting')}
              >
                繼續修改
              </button>
              <button
                className="modal-btn primary"
                onClick={handleBuildProject}
                disabled={isBuilding || !buildDir.trim()}
              >
                {isBuilding ? '建立中…' : '確認，開始建立'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Building ── */}
      {newProjectStep === 'building' && (
        <div className="home-building">
          <div className="home-building-spinner">🔨</div>
          <p>正在建立專案，請稍候…</p>
        </div>
      )}

      {/* ── Inline analyze modal ── */}
      {showAnalyzeModal && (
        <div className="modal-backdrop" onClick={() => setShowAnalyzeModal(false)}>
          <div className="modal modal-wide" onClick={e => e.stopPropagation()}>
            <h2>解析專案</h2>

            <div className="path-input-row">
              <input
                className="modal-input"
                type="text"
                placeholder="/path/to/your/project"
                value={analyzeInputPath}
                onChange={e => setAnalyzeInputPath(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter') handleAnalyze();
                  if (e.key === 'Escape') setShowAnalyzeModal(false);
                }}
                autoFocus
              />
              <button
                className="modal-btn browse-btn"
                onClick={async () => {
                  try {
                    const res = await fetch('/api/native-pick');
                    if (res.ok) {
                      const d = await res.json() as { path?: string };
                      if (d.path) setAnalyzeInputPath(d.path);
                    } else {
                      setShowBrowser(!showBrowser);
                    }
                  } catch {
                    setShowBrowser(!showBrowser);
                  }
                }}
              >
                📁 Choose Folder
              </button>
            </div>

            {showBrowser && (
              <FolderBrowser
                initialPath={analyzeInputPath || '/'}
                onSelect={p => { setAnalyzeInputPath(p); setShowBrowser(false); }}
                onCancel={() => setShowBrowser(false)}
              />
            )}

            {scanning && <div className="scan-info scanning">Scanning…</div>}
            {!scanning && scanInfo && (
              <div className="scan-info">
                Found <strong>{scanInfo.total.toLocaleString()}</strong> files — {' '}
                <strong>{scanInfo.analyzable.toLocaleString()}</strong> source files to analyze
              </div>
            )}

            {analyzeError && <div className="modal-error">{analyzeError}</div>}

            <div className="modal-actions">
              <button className="modal-btn" onClick={() => { setShowAnalyzeModal(false); setAnalyzeError(''); }}>
                Cancel
              </button>
              <button
                className="modal-btn primary"
                onClick={handleAnalyze}
                disabled={isSubmitting || !analyzeInputPath.trim()}
              >
                {isSubmitting ? 'Starting…' : 'Start Analysis'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Project Manager Panel ── */}
      {showProjectManager && (
        <ProjectManagerPanel onClose={() => setShowProjectManager(false)} />
      )}
    </div>
  );
};

export default HomeView;
