import { Component, computed, signal } from '@angular/core';
import { Router } from '@angular/router';
import { AgentStateService } from '../../core/services/agent-state.service';
import { Task, AgentPhase, CLUSTERS_META } from '../../core/models/task.model';

type SortField = 'priority' | 'name' | 'scope';

@Component({
  selector: 'app-dashboard',
  templateUrl: './dashboard.page.html',
  styleUrls: ['./dashboard.page.scss'],
  standalone: false,
})
export class DashboardPage {
  readonly filterCluster = signal<string | null>(null);
  readonly filterPhase = signal<AgentPhase | 'all' | null>(null);
  readonly searchQuery = signal('');
  readonly sortField = signal<SortField>('priority');

  readonly clusters = Object.entries(CLUSTERS_META).map(([id, meta]) => ({ id, ...meta }));

  readonly phaseOptions: Array<{ value: AgentPhase | 'all'; label: string }> = [
    { value: 'all', label: 'All active' },
    { value: 'awaiting_approval', label: 'Needs approval' },
    { value: 'error', label: 'Error' },
    { value: 'coding', label: 'Coding' },
    { value: 'testing', label: 'Testing' },
    { value: 'done', label: 'Done' },
  ];

  readonly filteredTasks = computed(() => {
    let tasks = [...this.state.tasks()];
    const cluster = this.filterCluster();
    const phase = this.filterPhase();
    const q = this.searchQuery().toLowerCase().trim();

    if (cluster) tasks = tasks.filter(t => t.cluster === cluster);
    if (q) tasks = tasks.filter(t => t.name.toLowerCase().includes(q));

    if (phase === 'all') {
      tasks = tasks.filter(t => !!this.state.agentRuns()[t.task_gid]);
    } else if (phase) {
      tasks = tasks.filter(t => this.state.agentRuns()[t.task_gid]?.phase === phase);
    }

    const sf = this.sortField();
    tasks.sort((a, b) => {
      if (sf === 'priority') return (b.priority ?? 0) - (a.priority ?? 0);
      if (sf === 'scope') return (b.scope_score ?? 0) - (a.scope_score ?? 0);
      return a.name.localeCompare(b.name);
    });

    return tasks;
  });

  readonly stats = computed(() => {
    const runs = Object.values(this.state.agentRuns());
    return {
      total: this.state.tasks().length,
      active: runs.filter(r => r.is_active).length,
      needsApproval: runs.filter(r => r.phase === 'awaiting_approval').length,
      errors: runs.filter(r => r.phase === 'error').length,
    };
  });

  constructor(public state: AgentStateService, private router: Router) {}

  openTask(gid: string): void {
    this.router.navigate(['/task', gid]);
  }

  async startAgent(gid: string): Promise<void> {
    await this.state.startAgent(gid);
  }

  async stopAgent(gid: string): Promise<void> {
    await this.state.stopAgent(gid);
  }

  async refresh(): Promise<void> {
    await this.state.refreshTasks();
  }

  setCluster(id: string | null): void { this.filterCluster.set(id); }
  setPhase(p: AgentPhase | 'all' | null): void { this.filterPhase.set(p); }
  setSort(f: SortField): void { this.sortField.set(f); }
  onSearch(e: CustomEvent): void { this.searchQuery.set((e.detail.value ?? '').toLowerCase()); }

  trackByGid(_: number, t: Task): string { return t.task_gid; }
}
