/**
 * FileEditor — CodeMirror 6 embedded editor for the center panel file tab.
 *
 * Features:
 * - Full file content, syntax highlighting, editable with Save
 * - Memory annotation injected as block comment at top
 * - Async file load with AbortController (StrictMode safe)
 * - 💬 Explain Selection: select code → ask LLM with file + project context
 */

import React, { useEffect, useRef, useState, useCallback } from 'react';

import { EditorState } from '@codemirror/state';
import { EditorView, keymap, lineNumbers, highlightActiveLineGutter, highlightActiveLine } from '@codemirror/view';
import { defaultKeymap, history, historyKeymap } from '@codemirror/commands';
import { foldGutter, indentOnInput, bracketMatching, syntaxHighlighting, defaultHighlightStyle } from '@codemirror/language';
import { javascript } from '@codemirror/lang-javascript';
import { python } from '@codemirror/lang-python';
import { json } from '@codemirror/lang-json';
import { css } from '@codemirror/lang-css';
import { html } from '@codemirror/lang-html';
import { markdown } from '@codemirror/lang-markdown';
import { oneDark } from '@codemirror/theme-one-dark';

import { useAppStore } from '../store/app';

// ---------------------------------------------------------------------------
// Language detection
// ---------------------------------------------------------------------------
function getLanguageExtension(path: string) {
  const ext = path.split('.').pop()?.toLowerCase() ?? '';
  switch (ext) {
    case 'js': case 'jsx': case 'mjs': case 'cjs':
      return javascript({ jsx: true });
    case 'ts': case 'tsx':
      return javascript({ jsx: true, typescript: true });
    case 'py':
      return python();
    case 'json': case 'jsonl': case 'jsonc':
      return json();
    case 'css': case 'scss': case 'less':
      return css();
    case 'html': case 'htm': case 'svg':
      return html();
    case 'md': case 'mdx':
      return markdown();
    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Build memory annotation block comment
// ---------------------------------------------------------------------------
function buildAnnotation(
  memoryModules: { path: string; purpose: string; patterns: string[]; key_components: string[] }[],
  filePath: string,
): string | null {
  const fileName = filePath.split('/').pop() ?? '';
  const mod = memoryModules.find(
    m => m.path === filePath || filePath.endsWith(m.path) || m.path.endsWith(fileName),
  );
  if (!mod) return null;

  const lines = [
    '/*',
    ` * 📝 Code Architect Memory — ${mod.path}`,
    ` * Purpose : ${mod.purpose}`,
  ];
  if (mod.patterns.length > 0) lines.push(` * Patterns: ${mod.patterns.join(', ')}`);
  if (mod.key_components.length > 0) lines.push(` * Key     : ${mod.key_components.join(', ')}`);
  lines.push(' */');
  lines.push('');
  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// Extract surrounding context lines (±N lines around the selection)
// ---------------------------------------------------------------------------
function surroundingContext(fullContent: string, selectedText: string, windowLines = 80): string {
  const lines = fullContent.split('\n');
  const selStart = fullContent.indexOf(selectedText);
  if (selStart === -1) return fullContent.slice(0, 6000); // fallback
  const linesBefore = fullContent.slice(0, selStart).split('\n').length - 1;
  const start = Math.max(0, linesBefore - windowLines);
  const end = Math.min(lines.length, linesBefore + selectedText.split('\n').length + windowLines);
  const ctx = lines.slice(start, end).join('\n');
  return start > 0 ? `…(line ${start + 1})\n${ctx}` : ctx;
}

// ---------------------------------------------------------------------------
// ExplainPanel — streaming result
// ---------------------------------------------------------------------------
const ExplainPanel: React.FC<{
  text: string;
  streaming: boolean;
  onClose: () => void;
}> = ({ text, streaming, onClose }) => (
  <div className="explain-panel">
    <div className="explain-panel-header">
      <span className="explain-panel-title">💬 Explanation</span>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        {streaming && <span className="explain-streaming-indicator">● streaming</span>}
        <button className="explain-panel-close" onClick={onClose}>✕</button>
      </div>
    </div>
    <div className="explain-panel-body">
      <pre className="explain-panel-text">
        {text}
        {streaming && <span className="chat-cursor">▍</span>}
      </pre>
    </div>
  </div>
);

// ---------------------------------------------------------------------------
// FileEditor component
// ---------------------------------------------------------------------------
const FileEditor: React.FC = () => {
  const openedFile = useAppStore(s => s.openedFile);
  const memoryModules = useAppStore(s => s.memoryModules);
  const selectedProject = useAppStore(s => s.selectedProject);
  const darkMode = useAppStore(s => s.darkMode);

  const editorContainerRef = useRef<HTMLDivElement>(null);
  const editorViewRef = useRef<EditorView | null>(null);
  const explainAbortRef = useRef<AbortController | null>(null);

  const [loadState, setLoadState] = useState<'idle' | 'loading' | 'loaded' | 'error'>('idle');
  const [errorMsg, setErrorMsg] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState('');
  const [isDirty, setIsDirty] = useState(false);
  const [selectedText, setSelectedText] = useState('');
  const [explainPanel, setExplainPanel] = useState<{ text: string; streaming: boolean } | null>(null);
  const [explaining, setExplaining] = useState(false);

  const abortRef = useRef<AbortController | null>(null);

  const createEditor = useCallback((content: string, path: string) => {
    if (!editorContainerRef.current) return;

    if (editorViewRef.current) {
      editorViewRef.current.destroy();
      editorViewRef.current = null;
    }

    const langExt = getLanguageExtension(path);

    const extensions = [
      lineNumbers(),
      highlightActiveLineGutter(),
      highlightActiveLine(),
      history(),
      foldGutter(),
      indentOnInput(),
      bracketMatching(),
      syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
      keymap.of([...defaultKeymap, ...historyKeymap]),
      EditorView.updateListener.of((update) => {
        if (update.docChanged) setIsDirty(true);
        // Track selection for Explain button
        if (update.selectionSet || update.docChanged) {
          const { state } = update;
          const sel = state.selection.main;
          const text = sel.empty ? '' : state.sliceDoc(sel.from, sel.to);
          setSelectedText(text.trim());
        }
      }),
      EditorView.theme({
        '&': { height: '100%', fontSize: '13px' },
        '.cm-scroller': { overflow: 'auto', fontFamily: '"Fira Code", "JetBrains Mono", monospace' },
      }),
    ];

    if (langExt) extensions.push(langExt);
    if (darkMode) extensions.push(oneDark);

    const state = EditorState.create({ doc: content, extensions });
    const view = new EditorView({ state, parent: editorContainerRef.current });
    editorViewRef.current = view;
    setIsDirty(false);
    setSelectedText('');
  }, [darkMode]);

  // Load file when openedFile changes (StrictMode safe)
  useEffect(() => {
    if (!openedFile) return;
    const { path, projectId } = openedFile;

    const controller = new AbortController();
    abortRef.current = controller;

    setIsDirty(false);
    setSaveMsg('');
    setErrorMsg('');
    setLoadState('loading');
    setSelectedText('');
    setExplainPanel(null);

    const annotation = buildAnnotation(memoryModules, path);
    const placeholder = annotation
      ? `${annotation}// Loading file content…`
      : '// Loading file content…';
    createEditor(placeholder, path);

    fetch(`/api/file?path=${encodeURIComponent(path)}&project_id=${encodeURIComponent(projectId)}`, {
      signal: controller.signal,
    })
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail ?? `HTTP ${res.status}`);
        }
        return res.json();
      })
      .then((data: { content: string }) => {
        const fullContent = annotation ? `${annotation}${data.content}` : data.content;
        createEditor(fullContent, path);
        setLoadState('loaded');
      })
      .catch((err) => {
        if (err.name === 'AbortError') return;
        setErrorMsg(err.message);
        setLoadState('error');
      });

    return () => { controller.abort(); };
  }, [openedFile?.path, openedFile?.projectId]);

  // Destroy editor on unmount
  useEffect(() => {
    return () => {
      if (editorViewRef.current) {
        editorViewRef.current.destroy();
        editorViewRef.current = null;
      }
      explainAbortRef.current?.abort();
    };
  }, []);

  // ── Save ────────────────────────────────────────────────────────────────
  const handleSave = async () => {
    if (!openedFile || !editorViewRef.current) return;
    const content = editorViewRef.current.state.doc.toString();
    setSaving(true);
    setSaveMsg('');
    try {
      const res = await fetch('/api/file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: openedFile.path, content, project_id: openedFile.projectId }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? `HTTP ${res.status}`);
      }
      setSaveMsg('Saved ✓');
      setIsDirty(false);
      setTimeout(() => setSaveMsg(''), 2000);
    } catch (err) {
      setSaveMsg(`Save failed: ${(err as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  // ── Explain Selection ───────────────────────────────────────────────────
  const handleExplain = async () => {
    if (!openedFile || !selectedText || !editorViewRef.current) return;

    // Abort any previous explain stream
    explainAbortRef.current?.abort();
    const controller = new AbortController();
    explainAbortRef.current = controller;

    setExplaining(true);
    setExplainPanel({ text: '', streaming: true });

    // Build context
    const fileContent = editorViewRef.current.state.doc.toString();
    const fileName = openedFile.path.split('/').pop() ?? openedFile.path;
    const memMod = memoryModules.find(
      m => m.path === openedFile.path
        || openedFile.path.endsWith(m.path)
        || m.path.endsWith(fileName),
    );
    const ctx = surroundingContext(fileContent, selectedText);

    const systemPrompt = [
      'You are a senior software engineer reviewing code. Answer in the same language as the user.',
      '',
      '## Project Memory',
      memMod
        ? `File: ${memMod.path}\nPurpose: ${memMod.purpose}\nPatterns: ${memMod.patterns.join(', ')}\nKey components: ${memMod.key_components.join(', ')}`
        : `(No memory recorded for ${fileName})`,
      '',
      `## File: ${openedFile.path}`,
      '```',
      ctx,
      '```',
    ].join('\n');

    const userMsg = `請解釋以下選取的程式碼片段。說明它的功能、設計意圖，以及在整個檔案/專案中的角色：\n\n\`\`\`\n${selectedText}\n\`\`\``;

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal,
        body: JSON.stringify({
          message: userMsg,
          project_id: selectedProject?.id ?? openedFile.projectId,
          session_id: crypto.randomUUID(),
          system_override: systemPrompt,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      let fullText = '';

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
            const p = JSON.parse(raw) as { type?: string; data?: string };
            if (p.type === 'done') break;
            if (p.type === 'error') { fullText += `\n⚠ ${p.data}`; break; }
            const chunk = p.data ?? '';
            if (chunk) {
              fullText += chunk;
              setExplainPanel({ text: fullText, streaming: true });
            }
          } catch { if (raw) { fullText += raw; setExplainPanel({ text: fullText, streaming: true }); } }
        }
      }
      setExplainPanel({ text: fullText, streaming: false });
    } catch (err) {
      if ((err as Error).name === 'AbortError') return;
      setExplainPanel({ text: `⚠ ${(err as Error).message}`, streaming: false });
    } finally {
      setExplaining(false);
    }
  };

  // ── Render ──────────────────────────────────────────────────────────────
  if (!openedFile) {
    return (
      <div className="file-editor-empty">
        <div className="empty-state-icon">✎</div>
        <div className="empty-state-text">Click a file in the tree to open it</div>
      </div>
    );
  }

  const fileName = openedFile.path.split('/').pop() ?? openedFile.path;

  return (
    <div className="file-editor">
      {/* Toolbar */}
      <div className="file-editor-toolbar">
        <span className="file-editor-filename" title={openedFile.path}>{fileName}</span>
        <span className="file-editor-path" title={openedFile.path}>{openedFile.path}</span>
        <div className="file-editor-toolbar-right">
          {loadState === 'loading' && <span className="file-editor-status loading">Loading…</span>}
          {loadState === 'error' && <span className="file-editor-status error">⚠ {errorMsg}</span>}
          {saveMsg && <span className={`file-editor-status ${saveMsg.startsWith('Save failed') ? 'error' : 'saved'}`}>{saveMsg}</span>}
          {isDirty && <span className="file-editor-dirty">● unsaved</span>}
          <button
            className="file-editor-explain-btn"
            onClick={handleExplain}
            disabled={!selectedText || explaining}
            title={selectedText ? '解釋選取的程式碼' : '先選取一段程式碼'}
          >
            {explaining ? '⏳ 解釋中…' : '💬 Explain'}
          </button>
          <button
            className="file-editor-save-btn"
            onClick={handleSave}
            disabled={saving || !isDirty}
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>

      {/* Editor + Explain panel */}
      <div className="file-editor-main">
        <div className="file-editor-body" ref={editorContainerRef} />
        {explainPanel && (
          <ExplainPanel
            text={explainPanel.text}
            streaming={explainPanel.streaming}
            onClose={() => { explainAbortRef.current?.abort(); setExplainPanel(null); }}
          />
        )}
      </div>
    </div>
  );
};

export default FileEditor;
