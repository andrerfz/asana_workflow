import { Component, OnInit, OnDestroy, computed, signal, effect, AfterViewInit, ElementRef, ViewChild, ChangeDetectorRef } from '@angular/core';
import { Router } from '@angular/router';
import { Chart, registerables } from 'chart.js';
import { AgentStateService } from '../../core/services/agent-state.service';
import { ApiService } from '../../core/services/api.service';
import { Task, AgentPhase, CLUSTERS_META, CLUSTER_COLORS } from '../../core/models/task.model';
import { firstValueFrom } from 'rxjs';

Chart.register(...registerables);

type SortField = 'priority' | 'name' | 'scope';
type ViewMode = 'cards' | 'table' | 'cluster' | 'history' | 'agents';

@Component({
  selector: 'app-dashboard',
  templateUrl: './dashboard.page.html',
  styleUrls: ['./dashboard.page.scss'],
  standalone: false,
})
export class DashboardPage implements OnInit, OnDestroy, AfterViewInit {
  @ViewChild('clusterChartCanvas') clusterChartCanvas!: ElementRef<HTMLCanvasElement>;

  readonly viewMode = signal<ViewMode>('cards');
  readonly filterCluster = signal<string | null>(null);
  readonly filterSection = signal<string | null>(null);
  readonly filterPhase = signal<AgentPhase | 'all' | null>(null);
  readonly filterType = signal<string | null>(null);
  readonly searchQuery = signal('');
  readonly sortField = signal<SortField>('priority');
  readonly historyItems = signal<unknown[]>([]);
  readonly syncing = signal(false);
  readonly classifying = signal(false);

  readonly clusters = Object.entries(CLUSTERS_META).map(([id, meta]) => ({ id, ...meta }));

  readonly sections = computed(() => {
    const seen = new Set<string>();
    const result: Array<{ name: string; count: number }> = [];
    for (const t of this.state.tasks()) {
      if (t.section_name && !seen.has(t.section_name)) {
        seen.add(t.section_name);
        result.push({ name: t.section_name, count: 0 });
      }
    }
    for (const s of result) {
      s.count = this.state.tasks().filter(t => t.section_name === s.name).length;
    }
    return result;
  });

  readonly typeOptions = ['Error', 'Funcionalidad', 'Mejora', 'Otros'];

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
    const section = this.filterSection();
    const phase = this.filterPhase();
    const type = this.filterType();
    const q = this.searchQuery().toLowerCase().trim();

    if (cluster) tasks = tasks.filter(t => t.cluster?.id === cluster);
    if (section) tasks = tasks.filter(t => t.section_name === section);
    if (type) tasks = tasks.filter(t => (t.tipo ?? '').toLowerCase() === type.toLowerCase());
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

  readonly agentTasks = computed(() => {
    const runs = this.state.agentRuns();
    return this.state.tasks()
      .filter(t => !!runs[t.task_gid])
      .sort((a, b) => {
        const pa = runs[a.task_gid]?.phase ?? '';
        const pb = runs[b.task_gid]?.phase ?? '';
        return pa.localeCompare(pb);
      });
  });

  readonly clusteredTasks = computed(() => {
    const tasks = this.filteredTasks();
    const map = new Map<string, { label: string; color: string; items: Task[] }>();
    for (const task of tasks) {
      const key = task.cluster?.id ?? 'other';
      if (!map.has(key)) {
        map.set(key, {
          label: task.cluster?.name ?? 'Uncategorized',
          color: task.cluster?.color ?? '#888',
          items: [],
        });
      }
      map.get(key)!.items.push(task);
    }
    return Array.from(map.entries()).map(([id, val]) => ({ id, ...val }));
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

  readonly darkMode = signal(false);

  private chart: Chart | null = null;

  constructor(public state: AgentStateService, private router: Router, private api: ApiService, private cdr: ChangeDetectorRef) {
    const saved = localStorage.getItem('darkMode');
    const dark = saved !== null ? saved === 'true' : window.matchMedia('(prefers-color-scheme: dark)').matches;
    this.darkMode.set(dark);
    this._applyTheme(dark);

    // Auto-init chart whenever tasks load and view is cards
    effect(() => {
      const tasks = this.state.tasks();
      if (tasks.length > 0 && this.viewMode() === 'cards') {
        setTimeout(() => this.initChart(), 50);
      }
    });
  }

  ngOnInit(): void {}

  ngAfterViewInit(): void {
    // Chart init deferred to when view mode changes to 'cards'
  }

  ngOnDestroy(): void {
    this.chart?.destroy();
  }

  initChart(): void {
    if (!this.clusterChartCanvas?.nativeElement) return;
    if (this.chart) { this.chart.destroy(); this.chart = null; }

    const tasks = this.state.tasks();
    const clusterMap = new Map<string, { label: string; color: string; count: number }>();
    for (const t of tasks) {
      const key = t.cluster?.id ?? 'other';
      if (!clusterMap.has(key)) {
        clusterMap.set(key, { label: t.cluster?.name ?? 'Other', color: t.cluster?.color ?? CLUSTER_COLORS[key] ?? '#888', count: 0 });
      }
      clusterMap.get(key)!.count++;
    }

    const labels = Array.from(clusterMap.values()).map(v => v.label);
    const data = Array.from(clusterMap.values()).map(v => v.count);
    const colors = Array.from(clusterMap.values()).map(v => v.color);

    this.chart = new Chart(this.clusterChartCanvas.nativeElement, {
      type: 'doughnut',
      data: {
        labels,
        datasets: [{ data, backgroundColor: colors, borderWidth: 1 }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: 'right', labels: { font: { size: 11 }, boxWidth: 12 } },
        },
      },
    });
  }

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
    if (this.viewMode() === 'cards') {
      setTimeout(() => this.initChart(), 50);
    }
  }

  async sync(): Promise<void> {
    this.syncing.set(true);
    try {
      await firstValueFrom(this.api.syncTasks());
      await this.state.refreshTasks();
    } catch (e) {
      console.error('[Dashboard] sync failed', e);
    } finally {
      this.syncing.set(false);
    }
  }

  async classifyAll(): Promise<void> {
    this.classifying.set(true);
    try {
      await firstValueFrom(this.api.classifyAll());
    } catch (e) {
      console.error('[Dashboard] classifyAll failed', e);
    } finally {
      this.classifying.set(false);
    }
  }

  async loadHistory(): Promise<void> {
    try {
      const items = await firstValueFrom(this.api.getAgentHistory());
      this.historyItems.set(items ?? []);
    } catch (e) {
      console.error('[Dashboard] loadHistory failed', e);
    }
  }

  setViewMode(mode: ViewMode): void {
    this.viewMode.set(mode);
    if (mode === 'history') {
      this.loadHistory();
    } else if (mode === 'cards') {
      setTimeout(() => this.initChart(), 100);
    }
  }

  setCluster(id: string | null): void { this.filterCluster.set(id); }
  setSection(name: string | null): void {
    this.filterSection.set(this.filterSection() === name ? null : name);
  }
  setPhase(p: AgentPhase | 'all' | null): void { this.filterPhase.set(p); }
  setSort(f: SortField): void { this.sortField.set(f); }
  setType(t: string | null): void { this.filterType.set(t === this.filterType() ? null : t); }
  onSearch(e: CustomEvent): void { this.searchQuery.set((e.detail.value ?? '').toLowerCase()); }

  historyAsRecord(item: unknown): Record<string, unknown> {
    return item as Record<string, unknown>;
  }

  toggleDarkMode(): void {
    const next = !this.darkMode();
    this.darkMode.set(next);
    this._applyTheme(next);
    localStorage.setItem('darkMode', String(next));
  }

  private _applyTheme(dark: boolean): void {
    document.documentElement.classList.toggle('ion-palette-dark', dark);
  }

  trackByGid(_: number, t: Task): string { return t.task_gid; }
  trackByCluster(_: number, c: { id: string }): string { return c.id; }
  trackByIdx(i: number): number { return i; }
}
