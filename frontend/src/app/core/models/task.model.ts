export interface TaskCluster {
  id: string;
  name: string;
  color: string;
}

export interface Task {
  task_gid: string;
  name: string;
  section_name: string;
  completed: boolean;
  scope_score: number;
  cluster: TaskCluster | null;
  tipo: string | null;
  canal: string | null;
  notes?: string;
  notes_preview?: string;
  ai_summary?: string | null;
  ai_reasoning?: string | null;
  classification_source?: string | null;
  priority: number;
  area: string | null;
  projects?: string[];
  desarrollador?: string;
  due_on?: string;
  rank?: number;
}

export interface LogEntry {
  timestamp: string;
  level: 'debug' | 'info' | 'warning' | 'error';
  message: string;
}

export interface QAQuestion {
  text: string;
  type: string;
  options: string[];
  asked_at: string;
  answer: string | null;
  plan?: string;
}

export interface ConversationMessage {
  role: 'user' | 'agent';
  text: string;
  timestamp: string;
}

export interface RepoEntry {
  id: string;
  worktree_path?: string;
  default_branch?: string;
}

export interface AgentRun {
  task_gid: string;
  phase: AgentPhase;
  is_active: boolean;
  logs: LogEntry[];
  question?: QAQuestion | null;
  plan?: string;
  qa_report?: string;
  repos: RepoEntry[];
  conversation?: ConversationMessage[];
  started_at?: string;
  updated_at?: string;
  error?: string;
  cost_usd?: number;
}

export type AgentPhase =
  | 'queued'
  | 'init'
  | 'investigating'
  | 'planning'
  | 'awaiting_approval'
  | 'coding'
  | 'testing'
  | 'qa_review'
  | 'done'
  | 'error'
  | 'paused'
  | 'cancelled';

// Keep for fallback lookups by id
export const CLUSTER_COLORS: Record<string, string> = {
  ebitda: '#e74c3c', trazabilidad: '#9b59b6', turnos: '#3498db',
  pedidos: '#f39c12', almacen: '#1abc9c', sentry: '#95a5a6',
  integracion: '#e67e22', standalone: '#7f8c8d',
};

export const PHASE_COLORS: Record<AgentPhase, string> = {
  queued: '#6b7280',
  init: '#8b5cf6',
  investigating: '#0ea5e9',
  planning: '#d97706',
  awaiting_approval: '#eab308',
  coding: '#3b82f6',
  testing: '#22c55e',
  qa_review: '#a855f7',
  done: '#10b981',
  error: '#ef4444',
  paused: '#eab308',
  cancelled: '#4b5563',
};

export const PHASE_LABELS: Record<AgentPhase, string> = {
  queued: 'Queued',
  init: 'Init',
  investigating: 'Investigating',
  planning: 'Planning',
  awaiting_approval: 'Awaiting Approval',
  coding: 'Coding',
  testing: 'Testing',
  qa_review: 'QA Review',
  done: 'Done',
  error: 'Error',
  paused: 'Paused',
  cancelled: 'Cancelled',
};

export const CLUSTERS_META: Record<string, { name: string; color: string }> = {
  ebitda:      { name: 'EBITDA Reports',        color: '#e74c3c' },
  trazabilidad: { name: 'Trazabilidad',          color: '#9b59b6' },
  turnos:      { name: 'Planificacion Turnos',   color: '#3498db' },
  pedidos:     { name: 'Pedidos / Albaranes',    color: '#f39c12' },
  almacen:     { name: 'Almacen',                color: '#1abc9c' },
  sentry:      { name: 'Sentry',                 color: '#95a5a6' },
  integracion: { name: 'Integraciones',          color: '#e67e22' },
  standalone:  { name: 'Standalone',             color: '#7f8c8d' },
};
