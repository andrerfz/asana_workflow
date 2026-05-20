import {
  Component,
  ChangeDetectionStrategy,
  ViewEncapsulation,
  signal,
  computed,
  inject,
  HostListener,
} from '@angular/core';
import { AgentStateService } from '../../core/services/agent-state.service';
import { ApiService } from '../../core/services/api.service';
import { toWfTask, WfTask, LIVE_PHASES } from './wf-task.model';
import { WfStats, WfHeaderComponent } from './wf-header/wf-header.component';
import { WfSidebarComponent } from './wf-sidebar/wf-sidebar.component';
import { WfStatsBarComponent } from './wf-stats-bar/wf-stats-bar.component';
import { WfToolbarComponent } from './wf-toolbar/wf-toolbar.component';
import { WfListComponent } from './wf-list/wf-list.component';
import { WfCardsComponent } from './wf-cards/wf-cards.component';
import { WfDrawerComponent } from './wf-drawer/wf-drawer.component';
import { WfAction } from './wf-list/wf-list.component';

@Component({
  selector: 'app-wf-dashboard',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  imports: [
    WfHeaderComponent,
    WfSidebarComponent,
    WfStatsBarComponent,
    WfToolbarComponent,
    WfListComponent,
    WfCardsComponent,
    WfDrawerComponent,
  ],
  template: `
    <div class="wf-root" [class.wf-theme-light]="darkMode()">
      <app-wf-header
        [stats]="stats()"
        [search]="search()"
        [mode]="mode()"
        [connected]="stateService.connected()"
        [darkMode]="darkMode()"
        (searchChange)="search.set($event)"
        (modeChange)="mode.set($event)"
        (darkModeToggle)="toggleDarkMode()"
        (classify)="onClassify()"
        (sync)="onSync()"
      />

      @if (mode() === 'tasks') {
        <app-wf-sidebar
          [tasks]="allWfTasks()"
          [workspace]="workspace()"
          [section]="section()"
          [selected]="selected()"
          [stats]="stats()"
          (workspaceChange)="onWorkspaceChange($event)"
          (sectionChange)="section.set($event)"
          (selectedChange)="selected.set($event)"
        />

        <main class="wf-main">
          <app-wf-stats-bar
            [stats]="stats()"
            [statFilter]="statFilter()"
            (statFilterChange)="onStatFilterChange($event)"
          />
          <app-wf-toolbar
            [view]="view()"
            [typeFilter]="typeFilter()"
            [cluster]="cluster()"
            [filteredCount]="filteredTasks().length"
            [tasks]="allWfTasks()"
            [filtersActive]="filtersActive()"
            (viewChange)="view.set($event)"
            (typeFilterChange)="typeFilter.set($event)"
            (clusterChange)="cluster.set($event)"
            (resetFilters)="resetFilters()"
          />

          @if (view() === 'list') {
            <app-wf-list
              [tasks]="filteredTasks()"
              [selected]="selected()"
              (selectedChange)="selected.set($event)"
              (action)="onAction($event)"
            />
          } @else {
            <app-wf-cards
              [tasks]="filteredTasks()"
              [selected]="selected()"
              (selectedChange)="selected.set($event)"
              (action)="onAction($event)"
            />
          }
        </main>

        <app-wf-drawer
          [task]="selectedTask()"
          (action)="onDrawerAction($event)"
        />
      }

      @if (mode() === 'history') {
        <main class="wf-main" style="grid-column:1 / -1; display:flex; flex-direction:column; min-height:0">
          <div style="padding:24px; color:var(--wf-text-mute)">History view coming soon…</div>
        </main>
      }

      @if (mode() === 'settings') {
        <main class="wf-main" style="grid-column:1 / -1; display:flex; flex-direction:column; min-height:0">
          <div style="padding:24px; color:var(--wf-text-mute)">Settings view coming soon…</div>
        </main>
      }
    </div>
  `,
})
export class WfDashboardPage {
  protected stateService = inject(AgentStateService);
  private api = inject(ApiService);

  // UI state signals
  mode = signal<string>('tasks');
  selected = signal<string | null>(null);
  workspace = signal<string>('inbox');
  section = signal<string | null>(null);
  cluster = signal<string | null>(null);
  typeFilter = signal<string | null>(null);
  statFilter = signal<string | null>(null);
  view = signal<string>('list');
  search = signal('');
  darkMode = signal(false);

  // All tasks merged with run data
  allWfTasks = computed<WfTask[]>(() => {
    const tasks = this.stateService.tasks();
    const runs = this.stateService.agentRuns();
    return tasks.map(t => toWfTask(t, runs[t.task_gid]));
  });

  // Workspace filter
  private workspaceFilter = computed(() => {
    const ws = this.workspace();
    return (task: WfTask): boolean => {
      switch (ws) {
        case 'inbox':    return task.phase !== 'done';
        case 'awaiting': return task.phase === 'awaiting_approval';
        case 'flight':   return LIVE_PHASES.includes(task.phase);
        case 'queued':   return task.phase === 'queued';
        case 'shipped':  return task.phase === 'done';
        default: return true;
      }
    };
  });

  filteredTasks = computed<WfTask[]>(() => {
    const wsFilter = this.workspaceFilter();
    const q = this.search().toLowerCase();
    const sec = this.section();
    const clus = this.cluster();
    const tipo = this.typeFilter();
    const stat = this.statFilter();

    let list = this.allWfTasks().filter(wsFilter);

    if (q) {
      list = list.filter(t =>
        t.name.toLowerCase().includes(q) ||
        t.gid.includes(q) ||
        (t.branch !== '—' && t.branch.toLowerCase().includes(q)) ||
        (t.cluster?.name.toLowerCase().includes(q) ?? false)
      );
    }
    if (sec) list = list.filter(t => t.section === sec);
    if (clus) list = list.filter(t => t.cluster?.id === clus);
    if (tipo) list = list.filter(t => t.tipo === tipo);
    if (stat === 'awaiting') list = list.filter(t => t.phase === 'awaiting_approval');
    if (stat === 'flight')   list = list.filter(t => LIVE_PHASES.includes(t.phase));
    if (stat === 'shipped')  list = list.filter(t => t.phase === 'done');

    return list;
  });

  stats = computed<WfStats>(() => {
    const all = this.allWfTasks();
    return {
      total: all.length,
      awaiting: all.filter(t => t.phase === 'awaiting_approval').length,
      running: all.filter(t => LIVE_PHASES.includes(t.phase)).length,
      shipped: all.filter(t => t.phase === 'done').length,
      cost: all.reduce((sum, t) => sum + t.cost, 0),
    };
  });

  selectedTask = computed<WfTask | null>(() => {
    const id = this.selected();
    if (!id) return null;
    return this.allWfTasks().find(t => t.gid === id) ?? null;
  });

  filtersActive = computed(() =>
    this.workspace() !== 'inbox' ||
    !!this.section() ||
    !!this.cluster() ||
    !!this.typeFilter() ||
    !!this.statFilter() ||
    !!this.search()
  );

  onWorkspaceChange(ws: string): void {
    this.workspace.set(ws);
    this.statFilter.set(null);
  }

  onStatFilterChange(v: string | null): void {
    this.statFilter.set(v);
    if (v) this.workspace.set('inbox');
  }

  resetFilters(): void {
    this.workspace.set('inbox');
    this.section.set(null);
    this.cluster.set(null);
    this.typeFilter.set(null);
    this.statFilter.set(null);
    this.search.set('');
  }

  onAction(event: WfAction): void {
    this.handleAction(event.gid, event.act);
  }

  onDrawerAction(act: string): void {
    const id = this.selected();
    if (id) this.handleAction(id, act);
  }

  private handleAction(gid: string, act: string): void {
    switch (act) {
      case 'approve':
        this.stateService.answerQuestion(gid, 'Approve');
        break;
      case 'reject':
        this.stateService.answerQuestion(gid, 'Reject');
        break;
      case 'start':
        this.stateService.startAgent(gid);
        break;
      case 'stop':
        this.stateService.stopAgent(gid);
        break;
      case 'classify':
        this.api.classifyTask(gid).subscribe();
        break;
      case 'branch': {
        this.api.getBranchName(gid).subscribe(r => {
          if (r?.branch) navigator.clipboard.writeText(r.branch);
        });
        break;
      }
      case 'ide': {
        const run = this.stateService.getRunForTask(gid);
        const path = run?.repos?.[0]?.worktree_path;
        if (path) {
          this.api.openInIde(path, { cli: 'code', cliArgs: ['-r'] }).subscribe();
        }
        break;
      }
    }
  }

  toggleDarkMode(): void {
    this.darkMode.update(v => !v);
  }

  onClassify(): void {
    this.api.classifyAll().subscribe();
  }

  onSync(): void {
    this.stateService.refreshTasks();
  }

  // Keyboard navigation: j/k or arrow down/up
  @HostListener('window:keydown', ['$event'])
  onKeyDown(event: KeyboardEvent): void {
    const target = event.target as HTMLElement;
    if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') return;

    const filtered = this.filteredTasks();
    const currentId = this.selected();
    const currentIdx = filtered.findIndex(t => t.gid === currentId);

    if (event.key === 'j' || event.key === 'ArrowDown') {
      event.preventDefault();
      const next = filtered[Math.min(filtered.length - 1, currentIdx + 1)];
      if (next) this.selected.set(next.gid);
    } else if (event.key === 'k' || event.key === 'ArrowUp') {
      event.preventDefault();
      const prev = filtered[Math.max(0, currentIdx - 1)];
      if (prev) this.selected.set(prev.gid);
    }
  }
}
