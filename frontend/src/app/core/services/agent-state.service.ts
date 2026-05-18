import { Injectable, signal, computed, effect } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { AgentRun, LogEntry, ConversationMessage, Task } from '../models/task.model';

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

  readonly activeRuns = computed(() =>
    Object.values(this.agentRuns()).filter(r => r.is_active)
  );

  readonly runningCount = computed(() =>
    this.activeRuns().filter(r => r.phase !== 'queued').length
  );

  private ws: WebSocket | null = null;
  private pingInterval: ReturnType<typeof setInterval> | null = null;

  constructor(private http: HttpClient) {
    this.loadInitialState();
    this.connect();
  }

  private async loadInitialState(): Promise<void> {
    this.loading.set(true);
    try {
      const [tasksRes, agentsRes] = await Promise.all([
        firstValueFrom(this.http.get<{ tasks: Task[] }>('/api/tasks')),
        firstValueFrom(this.http.get<AgentRun[]>('/api/agent')),
      ]);
      this.tasks.set(tasksRes.tasks ?? []);
      const runsMap: Record<string, AgentRun> = {};
      for (const run of (agentsRes ?? [])) {
        runsMap[run.task_gid] = run;
      }
      this.agentRuns.set(runsMap);
    } catch (e) {
      console.error('[AgentState] Initial load failed', e);
    } finally {
      this.loading.set(false);
    }
  }

  private connect(): void {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    this.ws = new WebSocket(`${proto}//${location.host}/ws/agent`);

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
      this.http.post(`/api/agent/guide/${taskGid}`, { message })
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

  async reloadRun(taskGid: string): Promise<void> {
    const run = await firstValueFrom(
      this.http.get<AgentRun>(`/api/agent/status/${taskGid}`)
    );
    this.agentRuns.update(runs => ({ ...runs, [taskGid]: run }));
  }
}
