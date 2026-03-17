/**
 * Zustand store for Code Architect Agent
 *
 * Manages agent events, file tree, memory modules,
 * chat messages, and UI state for the new 3-panel layout.
 *
 * Version: 2.0
 */

import { create } from 'zustand';

// ---------------------------------------------------------------------------
// Domain types
// ---------------------------------------------------------------------------

export interface AgentEvent {
  id: string;
  type:
    | 'scan'
    | 'ast'
    | 'llm_start'
    | 'llm_done'
    | 'memory'
    | 'pattern'
    | 'skip'
    | 'done'
    | 'error';
  message: string;
  file?: string;
  summary?: string;
  data?: Record<string, unknown>;
  timestamp: Date;
}

export interface FileNode {
  path: string;
  name: string;
  status: 'pending' | 'analyzing' | 'done' | 'skipped';
  summary?: string;
  isDir: boolean;
  children?: FileNode[];
}

export interface MemoryModule {
  name: string;
  path: string;
  purpose: string;
  patterns: string[];
  key_components: string[];
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  streaming?: boolean;
}

export interface AnalysisJob {
  jobId: string;
  projectId: string;
  projectPath: string;
  status: 'queued' | 'running' | 'complete' | 'error';
  ws?: WebSocket;
}

// ---------------------------------------------------------------------------
// Store interface
// ---------------------------------------------------------------------------

interface AppStore {
  // Agent events
  events: AgentEvent[];
  addEvent: (e: AgentEvent) => void;
  clearEvents: () => void;

  // File tree
  fileTree: FileNode[];
  setFileTree: (tree: FileNode[]) => void;
  updateFileStatus: (
    path: string,
    status: FileNode['status'],
    summary?: string
  ) => void;

  // Memory
  memoryModules: MemoryModule[];
  addModule: (m: MemoryModule) => void;
  clearModules: () => void;

  // Patterns
  allPatterns: string[];
  setPatterns: (patterns: string[]) => void;

  // Current job
  currentJob: AnalysisJob | null;
  setCurrentJob: (job: AnalysisJob | null) => void;

  // Progress tracking
  filesTotal: number;
  filesAnalyzed: number;
  setFilesTotal: (n: number) => void;
  incrementFilesAnalyzed: () => void;
  resetProgress: () => void;

  // Chat
  chatMessages: ChatMessage[];
  addChatMessage: (m: ChatMessage) => void;
  updateLastAssistantMessage: (chunk: string) => void;
  clearChat: () => void;

  // Chat streaming flag
  isChatStreaming: boolean;
  setChatStreaming: (v: boolean) => void;

  // Selected project
  selectedProject: { path: string; id: string } | null;
  setSelectedProject: (p: { path: string; id: string } | null) => void;

  // UI
  darkMode: boolean;
  setDarkMode: (v: boolean) => void;

  // Center panel tab
  centerTab: 'activity' | 'chat';
  setCenterTab: (tab: 'activity' | 'chat') => void;
}

// ---------------------------------------------------------------------------
// Store implementation
// ---------------------------------------------------------------------------

export const useAppStore = create<AppStore>((set) => ({
  // Agent events
  events: [],
  addEvent: (e) => set((s) => ({ events: [...s.events, e] })),
  clearEvents: () => set({ events: [] }),

  // File tree
  fileTree: [],
  setFileTree: (tree) => set({ fileTree: tree }),
  updateFileStatus: (path, status, summary) =>
    set((s) => ({
      fileTree: updateNodeStatus(s.fileTree, path, status, summary),
    })),

  // Memory
  memoryModules: [],
  addModule: (m) =>
    set((s) => ({
      memoryModules: [
        ...s.memoryModules.filter((x) => x.path !== m.path),
        m,
      ],
    })),
  clearModules: () => set({ memoryModules: [], allPatterns: [] }),

  // Patterns
  allPatterns: [],
  setPatterns: (patterns) => set({ allPatterns: patterns }),

  // Current job
  currentJob: null,
  setCurrentJob: (job) => set({ currentJob: job }),

  // Progress
  filesTotal: 0,
  filesAnalyzed: 0,
  setFilesTotal: (n) => set({ filesTotal: n }),
  incrementFilesAnalyzed: () => set((s) => ({ filesAnalyzed: s.filesAnalyzed + 1 })),
  resetProgress: () => set({ filesTotal: 0, filesAnalyzed: 0 }),

  // Chat
  chatMessages: [],
  addChatMessage: (m) => set((s) => ({ chatMessages: [...s.chatMessages, m] })),
  updateLastAssistantMessage: (chunk) =>
    set((s) => {
      const msgs = [...s.chatMessages];
      const lastIdx = msgs.length - 1;
      if (lastIdx >= 0 && msgs[lastIdx].role === 'assistant') {
        msgs[lastIdx] = {
          ...msgs[lastIdx],
          content: msgs[lastIdx].content + chunk,
        };
      } else {
        msgs.push({
          id: crypto.randomUUID(),
          role: 'assistant',
          content: chunk,
          streaming: true,
        });
      }
      return { chatMessages: msgs };
    }),
  clearChat: () => set({ chatMessages: [] }),

  // Chat streaming
  isChatStreaming: false,
  setChatStreaming: (v) => set({ isChatStreaming: v }),

  // Selected project
  selectedProject: null,
  setSelectedProject: (p) => set({ selectedProject: p }),

  // UI
  darkMode: false,
  setDarkMode: (v) => set({ darkMode: v }),

  // Center panel tab
  centerTab: 'activity',
  setCenterTab: (tab) => set({ centerTab: tab }),
}));

// ---------------------------------------------------------------------------
// Helper: recursively update a node's status
// ---------------------------------------------------------------------------

function updateNodeStatus(
  nodes: FileNode[],
  path: string,
  status: FileNode['status'],
  summary?: string
): FileNode[] {
  return nodes.map((n) => {
    if (n.path === path) {
      return { ...n, status, ...(summary !== undefined ? { summary } : {}) };
    }
    if (n.children) {
      return { ...n, children: updateNodeStatus(n.children, path, status, summary) };
    }
    return n;
  });
}

// ---------------------------------------------------------------------------
// Selector hooks
// ---------------------------------------------------------------------------

export const useAgentEvents = () => {
  const events = useAppStore((s) => s.events);
  const addEvent = useAppStore((s) => s.addEvent);
  const clearEvents = useAppStore((s) => s.clearEvents);
  return { events, addEvent, clearEvents };
};

export const useFileTree = () => {
  const fileTree = useAppStore((s) => s.fileTree);
  const setFileTree = useAppStore((s) => s.setFileTree);
  const updateFileStatus = useAppStore((s) => s.updateFileStatus);
  return { fileTree, setFileTree, updateFileStatus };
};

export const useMemory = () => {
  const memoryModules = useAppStore((s) => s.memoryModules);
  const addModule = useAppStore((s) => s.addModule);
  const clearModules = useAppStore((s) => s.clearModules);
  const allPatterns = useAppStore((s) => s.allPatterns);
  const setPatterns = useAppStore((s) => s.setPatterns);
  return { memoryModules, addModule, clearModules, allPatterns, setPatterns };
};

export const useChat = () => {
  const chatMessages = useAppStore((s) => s.chatMessages);
  const addChatMessage = useAppStore((s) => s.addChatMessage);
  const updateLastAssistantMessage = useAppStore((s) => s.updateLastAssistantMessage);
  const clearChat = useAppStore((s) => s.clearChat);
  const isChatStreaming = useAppStore((s) => s.isChatStreaming);
  const setChatStreaming = useAppStore((s) => s.setChatStreaming);
  return {
    chatMessages,
    addChatMessage,
    updateLastAssistantMessage,
    clearChat,
    isChatStreaming,
    setChatStreaming,
  };
};

export const useJob = () => {
  const currentJob = useAppStore((s) => s.currentJob);
  const setCurrentJob = useAppStore((s) => s.setCurrentJob);
  const filesTotal = useAppStore((s) => s.filesTotal);
  const filesAnalyzed = useAppStore((s) => s.filesAnalyzed);
  const setFilesTotal = useAppStore((s) => s.setFilesTotal);
  const incrementFilesAnalyzed = useAppStore((s) => s.incrementFilesAnalyzed);
  const resetProgress = useAppStore((s) => s.resetProgress);
  return { currentJob, setCurrentJob, filesTotal, filesAnalyzed, setFilesTotal, incrementFilesAnalyzed, resetProgress };
};

export const useUI = () => {
  const darkMode = useAppStore((s) => s.darkMode);
  const setDarkMode = useAppStore((s) => s.setDarkMode);
  const selectedProject = useAppStore((s) => s.selectedProject);
  const setSelectedProject = useAppStore((s) => s.setSelectedProject);
  return { darkMode, setDarkMode, selectedProject, setSelectedProject };
};
