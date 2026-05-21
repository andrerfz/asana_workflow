import { Injectable, signal, computed } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { AgentRun, LogEntry, ConversationMessage, Task } from '../models/task.model';
import { ApiService } from './api.service';

interface WsEvent {
  event: string;
  data: Record<string, unknown>;
}

@Injectable({ providedIn: 'root' })
export class AgentStateService {
  readonly tasks = signal<Task[]>([]);
  readonly agentRuns = signal<Record<string, AgentRun>>({});
  readonly connected = signal(false);
  readonly loading = signal(false);
  readonly taskRepoOverrides = signal<Record<string, string[]>>({});

  readonly activeRuns = computed(() =>
    Object.values(this.agentRuns()).filter(r => r.is_active)
  );

  readonly runningCount = computed(() =>
    this.activeRuns().filter(r => r.phase !== 'queued').length
  );

  private ws: WebSocket | null = null;
  private pingInterval: ReturnType<typeof setInterval> | null = null;

  constructor(private http: HttpClient, private api: ApiService) {
    this.loadInitialState();
    this.connect();
  }

  private async loadInitialState(): Promise<void> {
    this.loading.set(true);
    try {
      const [tasksRes, agentsRes] = await Promise.all([
        firstValueFrom(this.http.get<{ tasks: Task[] }>('/api/tasks')),
        firstValueFrom(this.http.get<{ agents: AgentRun[] }>('/api/agent')),
      ]);
      this.tasks.set(tasksRes.tasks ?? []);
      const runsMap: Record<string, AgentRun> = {};
      for (const run of (agentsRes?.agents ?? [])) {
        runsMap[run.task_gid] = run;
      }
      this.agentRuns.set(runsMap);

      // Load repo overrides in background
      this.api.getTaskRepoOverrides().subscribe({
        next: (overrides) => this.taskRepoOverrides.set(overrides ?? {}),
        error: (e) => console.error('[AgentState] Failed to load repo overrides', e),
      });
    } catch (e) {
      console.error('[AgentState] Initial load failed', e);
    } finally {
      this.loading.set(false);
    }
  }

  private connect(): void {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    // Dev server (:4200) can't proxy WebSocket reliably — connect directly to FastAPI
    const host = location.port === '4200' ? `${location.hostname}:8765` : location.host;
    this.ws = new WebSocket(`${proto}//${host}/ws/agent`);

    this.ws.onopen = () => {
      this.connected.set(true);
      this.pingInterval = setInterval(() => {
        if (this.ws?.readyState === WebSocket.OPEN) {
          this.ws.send('ping');
        }
      }, 30_000);
    };

    this.ws.onmessage = (e: MessageEvent) => {
      try {
        const msg = JSON.parse(e.data as string) as WsEvent;
        this.handleEvent(msg);
      } catch { /* malformed frame */ }
    };

    this.ws.onclose = () => {
      this.connected.set(false);
      if (this.pingInterval) clearInterval(this.pingInterval);
      setTimeout(() => this.connect(), 3_000);
    };

    this.ws.onerror = () => this.ws?.close();
  }

  private handleEvent(msg: WsEvent): void {
    const { event, data } = msg;
    const gid = data['task_gid'] as string | undefined;
    if (!gid) return;

    if (event === 'agent:state') {
      const state = data['state'] as AgentRun;
      this.agentRuns.update(runs => ({ ...runs, [gid]: state }));
    } else if (event === 'agent:log') {
      const entry = data['log'] as LogEntry;
      this.agentRuns.update(runs => {
        const run = runs[gid];
        if (!run) return runs;
        return { ...runs, [gid]: { ...run, logs: [...(run.logs ?? []), entry] } };
      });
    } else if (event === 'agent:conversation') {
      const message = data['message'] as ConversationMessage;
      this.agentRuns.update(runs => {
        const run = runs[gid];
        if (!run) return runs;
        return { ...runs, [gid]: { ...run, conversation: [...(run.conversation ?? []), message] } };
      });
    }
  }

  getRunForTask(taskGid: string): AgentRun | undefined {
    return this.agentRuns()[taskGid];
  }

  async refreshTasks(): Promise<void> {
    const res = await firstValueFrom(this.http.post<{ tasks: Task[] }>('/api/tasks/refresh', {}));
    if (res?.tasks) this.tasks.set(res.tasks);
  }

  async startAgent(taskGid: string): Promise<void> {
    const run = await firstValueFrom(
      this.http.post<AgentRun>(`/api/agent/start/${taskGid}`, {})
    );
    this.agentRuns.update(runs => ({ ...runs, [taskGid]: run }));
  }

  async startAgentWithBranch(taskGid: string): Promise<{ needsModal: boolean; slug: string; suggestions: { branch: string; author: string }[] }> {
    try {
      const [branchRes, suggestionsRes] = await Promise.all([
        firstValueFrom(this.api.getBranchName(taskGid)),
        firstValueFrom(this.api.getBranchSuggestions(taskGid)),
      ]);
      // API returns full branch path (feature/{gid}/slug) — extract just the slug part
      const fullBranch = branchRes?.branch ?? '';
      const slug = fullBranch.split('/').pop() ?? fullBranch;
      const suggestions = suggestionsRes?.branches ?? [];
      const needsModal = suggestions.length > 0 || !!slug;
      return { needsModal, slug, suggestions };
    } catch (e) {
      console.error('[AgentState] startAgentWithBranch failed', e);
      return { needsModal: false, slug: '', suggestions: [] };
    }
  }

  async confirmStart(taskGid: string, slug: string, baseBranch: string | null): Promise<void> {
    const body: Record<string, unknown> = { branch_slug: slug };
    if (baseBranch) body['base_branch'] = baseBranch;
    const run = await firstValueFrom(
      this.http.post<AgentRun>(`/api/agent/start/${taskGid}`, body)
    );
    this.agentRuns.update(runs => ({ ...runs, [taskGid]: run }));
  }

  async updateTaskRepos(taskGid: string, repoIds: string[]): Promise<void> {
    try {
      await firstValueFrom(this.api.updateTaskRepos(taskGid, repoIds));
      this.taskRepoOverrides.update(o => ({ ...o, [taskGid]: repoIds }));
    } catch (e) {
      console.error('[AgentState] updateTaskRepos failed', e);
    }
  }

  async runManualQA(taskGid: string): Promise<void> {
    try {
      await firstValueFrom(this.api.runQA(taskGid));
    } catch (e) {
      console.error('[AgentState] runManualQA failed', e);
    }
  }

  async runManualTest(taskGid: string): Promise<{ all_passed: boolean }> {
    try {
      const res = await firstValueFrom(this.api.runTest(taskGid));
      return res ?? { all_passed: false };
    } catch (e) {
      console.error('[AgentState] runManualTest failed', e);
      return { all_passed: false };
    }
  }

  async revisePlan(taskGid: string, feedback: string): Promise<void> {
    try {
      await firstValueFrom(
        this.http.post(`/api/agent/answer/${taskGid}`, { answer: `revise:${feedback}` })
      );
    } catch (e) {
      console.error('[AgentState] revisePlan failed', e);
    }
  }

  async stopAgent(taskGid: string): Promise<void> {
    await firstValueFrom(this.http.post(`/api/agent/stop/${taskGid}`, {}));
    this.agentRuns.update(runs => {
      const run = runs[taskGid];
      if (!run) return runs;
      return { ...runs, [taskGid]: { ...run, is_active: false, phase: 'cancelled' } };
    });
  }

  async answerQuestion(taskGid: string, answer: string): Promise<void> {
    await firstValueFrom(
      this.http.post(`/api/agent/answer/${taskGid}`, { answer })
    );
  }

  async resumeAgent(taskGid: string, feedback?: string): Promise<void> {
    await firstValueFrom(
      this.http.post(`/api/agent/resume/${taskGid}`, { feedback: feedback ?? '' })
    );
  }

  async sendGuideMessage(taskGid: string, message: string): Promise<void> {
    await firstValueFrom(
      this.http.post(`/api/agent/guide/${taskGid}`, { feedback: message })
    );
  }

  async clearRun(taskGid: string): Promise<void> {
    await firstValueFrom(this.http.delete(`/api/agent/clear/${taskGid}`));
    this.agentRuns.update(runs => {
      const copy = { ...runs };
      delete copy[taskGid];
      return copy;
    });
  }

  async clearConversation(taskGid: string): Promise<void> {
    await firstValueFrom(this.http.delete(`/api/agent/chat/${taskGid}`));
    this.agentRuns.update(runs => {
      const run = runs[taskGid];
      if (!run) return runs;
      return { ...runs, [taskGid]: { ...run, conversation: [] } };
    });
  }

  async reloadRun(taskGid: string): Promise<void> {
    const run = await firstValueFrom(
      this.http.get<AgentRun>(`/api/agent/status/${taskGid}`)
    );
    this.agentRuns.update(runs => ({ ...runs, [taskGid]: run }));
  }
}
