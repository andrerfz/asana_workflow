import { Task, AgentRun } from '../../core/models/task.model';

export const WF_PHASES = [
  { id: 'queued',            label: 'Queued',        color: '#6b7280' },
  { id: 'investigating',     label: 'Investigating', color: '#38bdf8' },
  { id: 'planning',          label: 'Planning',      color: '#f59e0b' },
  { id: 'awaiting_approval', label: 'Awaiting you',  color: '#fbbf24' },
  { id: 'coding',            label: 'Coding',        color: '#5b8cff' },
  { id: 'testing',           label: 'Testing',       color: '#34d399' },
  { id: 'qa_review',         label: 'QA Review',     color: '#c084fc' },
  { id: 'done',              label: 'Shipped',       color: '#10b981' },
];

export const WF_PHASE_BY_ID: Record<string, { id: string; label: string; color: string }> =
  Object.fromEntries(WF_PHASES.map(p => [p.id, p]));

export const LIVE_PHASES = ['investigating', 'planning', 'coding', 'testing'];

/** Friendly label for a raw model id, e.g. "claude-sonnet-4-6" → "Sonnet 4.6". */
export function modelLabel(model?: string | null): string | null {
  if (!model) return null;
  const m = model.toLowerCase();
  const tier = m.includes('opus') ? 'Opus'
    : m.includes('sonnet') ? 'Sonnet'
    : m.includes('haiku') ? 'Haiku'
    : m.includes('fable') ? 'Fable'
    : null;
  if (!tier) return model;
  const ver = m.match(/(\d+)-(\d+)/);  // 4-6 → 4.6
  return ver ? `${tier} ${ver[1]}.${ver[2]}` : tier;
}

export interface WfTask {
  gid: string;
  name: string;
  section: string;
  cluster: { id: string; name: string; color: string } | null;
  tipo: string | null;
  canal: string | null;
  area: string | null;
  ai_summary: string | null;
  ai_reasoning: string | null;
  scope: number;
  priority: number;
  notes: string;
  projects: string[];
  // From AgentRun (may be undefined if no run):
  phase: string;            // 'queued' if no run
  is_active: boolean;
  plan?: string;
  qa_report?: string;
  cost: number;
  model: string | null;  // model that executed the run (badge)
  branch: string;       // worktree_path of the first repo
  branch_slug: string;  // last segment of the git branch name
  repo: string;         // first repo id (back-compat)
  repos: string[];      // ALL repo ids in the run (cross-repo tasks have >1)
  mr_url: string | null;   // first repo's MR (back-compat)
  mrUrls: string[];        // MR links for ALL repos that have one
  log: [string, string, string][];  // [time, level, message]
  progress: number;
}

export function toWfTask(task: Task, run?: AgentRun): WfTask {
  const firstRepo = run?.repos?.[0];
  return {
    gid: task.task_gid,
    name: task.name,
    section: task.section_name,
    cluster: task.cluster ? { id: task.cluster.id, name: task.cluster.name, color: task.cluster.color } : null,
    tipo: task.tipo,
    canal: task.canal ?? null,
    area: task.area ?? null,
    ai_summary: task.ai_summary ?? null,
    ai_reasoning: task.ai_reasoning ?? null,
    scope: task.scope_score,
    priority: task.priority,
    notes: task.notes ?? '',
    projects: task.projects ?? [],
    phase: run?.phase ?? 'queued',
    is_active: run?.is_active ?? false,
    plan: run?.plan,
    qa_report: run?.qa_report,
    cost: run?.cost_usd ?? 0,
    model: run?.model ?? null,
    branch: firstRepo?.worktree_path ?? '—',
    branch_slug: (firstRepo?.branch ?? '').split('/').pop() ?? '',
    repo: firstRepo?.id ?? '—',
    repos: (run?.repos ?? []).map(r => r.id),
    mr_url: firstRepo?.mr_url ?? null,
    mrUrls: (run?.repos ?? []).map(r => r.mr_url).filter((u): u is string => !!u),
    log: (run?.logs ?? []).map(l => [
      new Date(l.timestamp).toLocaleTimeString('en-GB', { hour12: false }).slice(0, 8),
      l.level.toUpperCase(),
      l.message,
    ] as [string, string, string]),
    progress: !run ? 0 : (run.is_active ? 0.5 : (run.phase === 'done' ? 1 : 0.3)),
  };
}
