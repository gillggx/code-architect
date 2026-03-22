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

export interface PendingApproval {
  sessionId: string;
  tool: string;
  args: Record<string, unknown>;
  diff?: string;
}

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
    | 'error'
    | 'tool_call'
    | 'tool_output'
    | 'approval_required'
    | 'message'
    | 'plan'
    | 'escalation'
    | 'session';
  message: string;
  file?: string;
  summary?: string;
  data?: Record<string, unknown>;
  timestamp: Date;
  // Edit agent fields
  tool?: string;
  args?: Record<string, unknown>;
  result?: string;
  diff?: string;
  content?: string;
  approval_required?: boolean;
  changes?: Array<{
    file: string;
    action: string;
    content?: string;
    diff?: string;
    applied: boolean;
  }>;
}

export interface PlanStep {
  index: number;
  description: string;
  files_affected: string[];
}

export interface ExecutionPlan {
  variant: string;
  steps: PlanStep[];
  confidence: number;
  rationale: string;
  risk_level: 'low' | 'medium' | 'high';
}

export interface PlanInfo {
  planA: ExecutionPlan;
  planB?: ExecutionPlan;
  needsConfirmation: boolean;
  confidenceGap: number;
  sessionId: string;
}

export interface EscalationInfo {
  sessionId: string;
  failedTool: string;
  errorMessage: string;
  planBAttempted: boolean;
  suggestedOptions: string[];
  iteration: number;
}

export interface FileNode {
  path: string;
  name: string;
  status: 'pending' | 'analyzing' | 'done' | 'skipped';
  summary?: string;
  isDir: boolean;
  children?: FileNode[];
}

export interface MemorySymbol {
  name: string;
  type: string;       // "function" | "class" | "method" | "interface" | "variable"
  line_start: number;
  line_end: number;
  signature: string;
}

export interface MemoryModule {
  name: string;
  path: string;
  purpose: string;
  patterns: string[];
  key_components: string[];
  symbols?: MemorySymbol[];
  edit_hints?: string;
  imported_by?: string[];
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

export interface ProjectRecord {
  project_id: string;
  project_path: string;
  project_name: string;
  last_analyzed: string | null;
  module_count: number;
}

export interface FreshnessStatus {
  isStale: boolean;
  changedCount: number;  // changed + new files
  lastAnalyzedAt: string | null;
  checkedAt: number;  // Date.now()
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
  setFilesAnalyzed: (n: number) => void;
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
  centerTab: 'activity' | 'chat' | 'file' | 'graph';
  setCenterTab: (tab: 'activity' | 'chat' | 'file' | 'graph') => void;

  // Opened file in editor tab
  openedFile: { path: string; projectId: string; line?: number } | null;
  setOpenedFile: (f: { path: string; projectId: string; line?: number } | null) => void;

  // Edit agent state
  editMode: boolean;
  setEditMode: (v: boolean) => void;
  agentSession: string | null;
  setAgentSession: (id: string | null) => void;
  pendingApproval: PendingApproval | null;
  setPendingApproval: (a: PendingApproval | null) => void;
  modifiedFiles: Set<string>;
  addModifiedFile: (f: string) => void;
  clearModifiedFiles: () => void;

  // Plan / escalation state
  currentPlan: PlanInfo | null;
  setCurrentPlan: (plan: PlanInfo | null) => void;
  escalation: EscalationInfo | null;
  setEscalation: (e: EscalationInfo | null) => void;

  // App view (home vs workspace)
  appView: 'home' | 'workspace';
  setAppView: (v: 'home' | 'workspace') => void;

  // New project flow
  newProjectStep: 'idle' | 'chatting' | 'spec_ready' | 'building';
  setNewProjectStep: (s: 'idle' | 'chatting' | 'spec_ready' | 'building') => void;
  newProjectSpec: string | null;
  setNewProjectSpec: (s: string | null) => void;
  newProjectMessages: ChatMessage[];
  addNewProjectMessage: (m: ChatMessage) => void;
  updateLastNewProjectMessage: (chunk: string) => void;
  clearNewProjectMessages: () => void;

  // Project list
  projectsList: ProjectRecord[];
  setProjectsList: (p: ProjectRecord[]) => void;

  // Pending analyze path (from ProjectManager -> TopBar)
  pendingAnalyzePath: string | null;
  setPendingAnalyzePath: (p: string | null) => void;

  // Freshness status
  freshnessStatus: FreshnessStatus | null;
  setFreshnessStatus: (s: FreshnessStatus | null) => void;
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
  setFilesAnalyzed: (n) => set({ filesAnalyzed: n }),
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

  // Selected project — automatically switches appView
  selectedProject: null,
  setSelectedProject: (p) =>
    set({
      selectedProject: p,
      appView: p ? 'workspace' : 'home',
      ...(p ? {} : { newProjectStep: 'idle' }),
    }),

  // UI
  darkMode: false,
  setDarkMode: (v) => set({ darkMode: v }),

  // Center panel tab
  centerTab: 'activity' as 'activity' | 'chat' | 'file' | 'graph',
  setCenterTab: (tab) => set({ centerTab: tab }),

  // Opened file
  openedFile: null,
  setOpenedFile: (f) => set({ openedFile: f }),

  // Edit agent state
  editMode: false,
  setEditMode: (v) => set({ editMode: v }),
  agentSession: null,
  setAgentSession: (id) => set({ agentSession: id }),
  pendingApproval: null,
  setPendingApproval: (a) => set({ pendingApproval: a }),
  modifiedFiles: new Set<string>(),
  addModifiedFile: (f) =>
    set((s) => ({ modifiedFiles: new Set([...s.modifiedFiles, f]) })),
  clearModifiedFiles: () => set({ modifiedFiles: new Set<string>() }),

  // Plan / escalation state
  currentPlan: null,
  setCurrentPlan: (plan) => set({ currentPlan: plan }),
  escalation: null,
  setEscalation: (e) => set({ escalation: e }),

  // App view
  appView: 'home',
  setAppView: (v) => set({ appView: v }),

  // New project flow
  newProjectStep: 'idle',
  setNewProjectStep: (s) => set({ newProjectStep: s }),
  newProjectSpec: null,
  setNewProjectSpec: (s) => set({ newProjectSpec: s }),
  newProjectMessages: [],
  addNewProjectMessage: (m) =>
    set((s) => ({ newProjectMessages: [...s.newProjectMessages, m] })),
  updateLastNewProjectMessage: (chunk) =>
    set((s) => {
      const msgs = [...s.newProjectMessages];
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
      return { newProjectMessages: msgs };
    }),
  clearNewProjectMessages: () => set({ newProjectMessages: [] }),

  // Project list
  projectsList: [],
  setProjectsList: (p) => set({ projectsList: p }),

  // Pending analyze path
  pendingAnalyzePath: null,
  setPendingAnalyzePath: (p) => set({ pendingAnalyzePath: p }),

  // Freshness status
  freshnessStatus: null,
  setFreshnessStatus: (s) => set({ freshnessStatus: s }),
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
  const setFilesAnalyzed = useAppStore((s) => s.setFilesAnalyzed);
  const incrementFilesAnalyzed = useAppStore((s) => s.incrementFilesAnalyzed);
  const resetProgress = useAppStore((s) => s.resetProgress);
  return { currentJob, setCurrentJob, filesTotal, filesAnalyzed, setFilesTotal, setFilesAnalyzed, incrementFilesAnalyzed, resetProgress };
};

export const useUI = () => {
  const darkMode = useAppStore((s) => s.darkMode);
  const setDarkMode = useAppStore((s) => s.setDarkMode);
  const selectedProject = useAppStore((s) => s.selectedProject);
  const setSelectedProject = useAppStore((s) => s.setSelectedProject);
  return { darkMode, setDarkMode, selectedProject, setSelectedProject };
};
